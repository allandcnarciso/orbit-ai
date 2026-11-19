"""Provider-agnostic conversation engine.

Owns generation lifecycle: model resolution, context construction, persistence
of the turn, provider invocation, terminal outcome and lock release. Database
transactions are never held across provider calls.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orbit.chat.context import DEFAULT_MAX_OUTPUT, build_context
from orbit.chat.events import (
    ContentDelta,
    GenerationEvent,
    Heartbeat,
    MessageCancelled,
    MessageCompleted,
    MessageFailed,
    MessageStarted,
)
from orbit.conversations.enums import MessageStatus
from orbit.conversations.errors import (
    ContextTooLarge,
    ConversationNotFound,
    GenerationInProgress,
    InvalidGenerationParameters,
    InvalidSelection,
    ModelNotAvailable,
    NoModelSelected,
    ServerShuttingDown,
)
from orbit.conversations.repository import ConversationRepository, StartedTurn
from orbit.providers.base import ChatMessage, CompletionRequest, ModelProvider, TokenUsage
from orbit.providers.errors import (
    ProviderError,
    ProviderInvalidResponseError,
    ProviderTimeoutError,
)
from orbit.providers.registry import ProviderRegistry
from orbit.storage.models import Conversation, Message
from orbit.storage.system_state import SystemStateStore

_logger = logging.getLogger("orbit.chat.engine")

DEFAULT_SELECTION_KEY = "default_model"
PARTIAL_FLUSH_INTERVAL_SECONDS = 1.0
STREAM_QUEUE_MAXSIZE = 128
# Idle comment frames keep proxies from closing a healthy but silent generation.
SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0
TERMINAL_STATUSES = {
    MessageStatus.COMPLETED.value,
    MessageStatus.FAILED.value,
    MessageStatus.CANCELLED.value,
}


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    provider: ModelProvider
    provider_id: str
    model: str
    context_length: int | None
    max_output_tokens: int | None


@dataclass(frozen=True, slots=True)
class GenerationOutcome:
    conversation_id: str
    user_message: Message
    assistant_message: Message
    replayed: bool


@dataclass
class GenerationHandle:
    conversation_id: str
    message_id: str
    task: asyncio.Task[None] | None = None
    cancel_requested: bool = False
    shutdown_requested: bool = False


class GenerationRegistry:
    """In-process registry of active generations (one per conversation)."""

    def __init__(self) -> None:
        self._active: dict[str, GenerationHandle] = {}

    def register(self, handle: GenerationHandle) -> None:
        self._active[handle.conversation_id] = handle

    def unregister(self, handle: GenerationHandle) -> None:
        if self._active.get(handle.conversation_id) is handle:
            del self._active[handle.conversation_id]

    def get(self, conversation_id: str) -> GenerationHandle | None:
        return self._active.get(conversation_id)

    def request_cancel(self, conversation_id: str) -> GenerationHandle | None:
        handle = self._active.get(conversation_id)
        if handle is None or (handle.task is not None and handle.task.done()):
            return None
        handle.cancel_requested = True
        if handle.task is not None:
            handle.task.cancel()
        return handle

    def cancel_all(self, *, shutdown: bool = False) -> list[GenerationHandle]:
        """Request cancellation of every active generation (app shutdown)."""
        handles = list(self._active.values())
        for handle in handles:
            handle.cancel_requested = True
            handle.shutdown_requested = shutdown
            if handle.task is not None and not handle.task.done():
                handle.task.cancel()
        return handles


class ModelResolver:
    """Resolve request > conversation > persisted default, then validate discovery."""

    def __init__(
        self,
        registry: ProviderRegistry,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._registry = registry
        self._session_factory = session_factory

    async def resolve(
        self,
        conversation: Conversation,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> ResolvedModel:
        default = await self._default_selection()
        requested_provider = provider or conversation.provider
        provider_id: str | None
        model_id: str | None

        if requested_provider is not None:
            provider_id = requested_provider
            if model is not None:
                model_id = model
            elif conversation.model is not None and (
                conversation.provider is None or conversation.provider == provider_id
            ):
                model_id = conversation.model
            else:
                default_provider = default.get("provider")
                default_model = default.get("model")
                if default_provider != provider_id or not default_model:
                    raise NoModelSelected(
                        f"No default model is configured for provider {provider_id}.",
                        conversation_id=conversation.id,
                    )
                model_id = default_model
        else:
            provider_id = default.get("provider")
            model_id = model or conversation.model or default.get("model")

        if not provider_id or not model_id:
            raise NoModelSelected(
                "No model selected: set one on the conversation, the request, or as default.",
                conversation_id=conversation.id,
            )

        selected = self._registry.get(provider_id)
        if selected is None:
            raise InvalidSelection(
                f"Unknown provider: {provider_id}", conversation_id=conversation.id
            )
        if not selected.configured:
            from orbit.providers.errors import ProviderNotConfigured

            raise ProviderNotConfigured(
                f"Provider {provider_id} is not configured.", provider=provider_id
            )

        models = await self._registry.discover_models(selected)
        info = next((item for item in models if item.id == model_id), None)
        if info is None:
            raise ModelNotAvailable(
                f"Model {model_id} is not available for provider {provider_id}.",
                conversation_id=conversation.id,
            )
        return ResolvedModel(
            provider=selected,
            provider_id=provider_id,
            model=model_id,
            context_length=info.context_length,
            max_output_tokens=info.max_output_tokens,
        )

    async def _default_selection(self) -> dict[str, str]:
        raw = await SystemStateStore(self._session_factory).get(DEFAULT_SELECTION_KEY)
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        provider = payload.get("provider")
        model = payload.get("model")
        if isinstance(provider, str) and isinstance(model, str):
            return {"provider": provider, "model": model}
        return {}


class ConversationEngine:
    """Coordinates one generation from request to persisted terminal outcome."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        registry: ProviderRegistry,
        *,
        generations: GenerationRegistry | None = None,
        generation_timeout_seconds: float | None = 300.0,
        max_output_tokens: int = 8192,
    ) -> None:
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        self._sessions = session_factory
        self._registry = registry
        self._resolver = ModelResolver(registry, session_factory)
        self.generations = generations or GenerationRegistry()
        self._generation_timeout = generation_timeout_seconds
        self._max_output_tokens = max_output_tokens
        # Serialises turn persistence + registry registration with cancellation.
        # Held only across the short DB transaction, never across provider I/O.
        self._start_lock = asyncio.Lock()
        # Shutdown barrier and the starts still in their pre-registration phase.
        # Both are needed to guarantee that no provider call survives shutdown.
        self._shutting_down = False
        self._in_flight_starts: set[asyncio.Task[Any]] = set()
        # Terminal writes are shielded from cancellation; `shutdown` drains them.
        self._finalizations: set[asyncio.Task[Message | None]] = set()

    @property
    def shutting_down(self) -> bool:
        """True once ``shutdown()`` started; new generations are rejected."""
        return self._shutting_down

    async def cancel(self, conversation_id: str) -> str | None:
        async with self._start_lock:
            handle = self.generations.request_cancel(conversation_id)
            return handle.message_id if handle is not None else None

    async def shutdown(self, *, timeout_seconds: float = 10.0) -> None:
        """Cancel active generations and wait for durable terminal states.

        The barrier is raised before the registry is touched and ``_start_lock``
        is held across the cancellation sweep, so a concurrent ``start_stream``
        either registered its handle before the sweep (and is cancelled here) or
        observes the barrier and aborts before persisting a turn. Waits are
        bounded with ``asyncio.wait`` (which does not await cancellation), so a
        provider that ignores cancellation cannot block process exit.
        """
        self._shutting_down = True
        pending_starts = [task for task in self._in_flight_starts if not task.done()]

        async with self._start_lock:
            handles = self.generations.cancel_all(shutdown=True)
            tasks = [handle.task for handle in handles if handle.task is not None]
            if tasks:
                await self._wait_bounded(tasks, timeout_seconds, "generation")

        if pending_starts:
            await self._wait_bounded(pending_starts, timeout_seconds, "in-flight start")

        pending_finalizations = [task for task in self._finalizations if not task.done()]
        if pending_finalizations:
            await self._wait_bounded(pending_finalizations, timeout_seconds, "terminal write")

    async def _wait_bounded(
        self, tasks: list[asyncio.Task[Any]], timeout_seconds: float, label: str
    ) -> None:
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=timeout_seconds)
        if pending:
            _logger.warning(
                "Timed out waiting for %s %s task(s) during shutdown",
                len(pending),
                label,
            )

    def _reject_if_shutting_down(self) -> None:
        if self._shutting_down:
            raise ServerShuttingDown("The server is shutting down; no new generation can start.")

    # ------------------------------------------------------------------
    # Shared lifecycle helpers
    # ------------------------------------------------------------------
    async def _load_conversation(self, conversation_id: str) -> Conversation:
        async with self._sessions() as session:
            conversation = await ConversationRepository(session).get_conversation(conversation_id)
        if conversation is None:
            raise ConversationNotFound("Conversation not found.", conversation_id=conversation_id)
        return conversation

    async def _begin_turn(
        self,
        conversation_id: str,
        *,
        content: str,
        resolved: ResolvedModel,
        client_message_id: str | None,
    ) -> StartedTurn:
        async with self._sessions() as session:
            repo = ConversationRepository(session)
            turn = await repo.start_turn(
                conversation_id,
                content=content,
                provider=resolved.provider_id,
                model=resolved.model,
                client_message_id=client_message_id,
            )
            await session.commit()
            return turn

    async def _context_messages(
        self,
        conversation_id: str,
        assistant_sequence: int,
        resolved: ResolvedModel,
        max_tokens: int | None,
    ) -> list[ChatMessage]:
        async with self._sessions() as session:
            history = await ConversationRepository(session).list_completed_dialogue(
                conversation_id, before_sequence=assistant_sequence
            )
        return build_context(
            history,
            context_length=resolved.context_length,
            max_output_tokens=max_tokens,
        )

    async def _finish(
        self,
        conversation_id: str,
        message_id: str,
        *,
        status: MessageStatus,
        content: str | None = None,
        finish_reason: str | None = None,
        usage: TokenUsage | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> Message | None:
        """Persist a terminal outcome, surviving cancellation of the caller.

        The write runs in its own task and is awaited through ``shield``. A
        cancelled producer (transport disconnect, server shutdown) must not
        abort the terminal transition or leave the generation lock held, so the
        caller may observe ``CancelledError`` while the write still completes.
        """
        persistence = asyncio.ensure_future(
            self._persist_terminal(
                conversation_id,
                message_id,
                status=status,
                content=content,
                finish_reason=finish_reason,
                usage=usage,
                error_code=error_code,
                error_message=error_message,
            )
        )
        self._finalizations.add(persistence)
        persistence.add_done_callback(self._finalizations.discard)
        try:
            return await asyncio.shield(persistence)
        except asyncio.CancelledError:
            _logger.info("Terminal write continues after cancellation (message_id=%s)", message_id)
            raise

    async def _persist_terminal(
        self,
        conversation_id: str,
        message_id: str,
        *,
        status: MessageStatus,
        content: str | None = None,
        finish_reason: str | None = None,
        usage: TokenUsage | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> Message | None:
        """Write the terminal state and release the lock (see ``_finish``).

        Returns ``None`` when the assistant message no longer exists, which only
        happens when the conversation was deleted while the generation was in
        flight. Deletion is an accepted outcome: the caller must not promise a
        terminal state for a row that is gone, and must not raise out of the
        generation lifecycle.
        """
        async with self._sessions() as session:
            repo = ConversationRepository(session)
            message = await repo.finalize_message(
                message_id,
                status=status,
                content=content,
                finish_reason=finish_reason,
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
                total_tokens=usage.total_tokens if usage else None,
                error_code=error_code,
                error_message=error_message,
            )
            await repo.release_generation_lock(conversation_id, message_id)
            await session.commit()
            if message is None:
                _logger.warning(
                    "Generation outcome discarded: message %s no longer exists "
                    "(conversation_id=%s, conversation deleted)",
                    message_id,
                    conversation_id,
                )
            return message

    def _validate_temperature(self, temperature: float | None) -> None:
        if temperature is not None and not 0 <= temperature <= 2:
            raise InvalidGenerationParameters(
                "temperature must be between 0 and 2.",
                conversation_id=None,
            )

    def _effective_max_tokens(self, requested: int | None, resolved: ResolvedModel) -> int:
        """Resolve the output budget before any turn is persisted or sent."""
        if requested is not None and requested < 1:
            raise InvalidGenerationParameters(
                "max_tokens must be at least 1.",
                conversation_id=None,
            )
        if requested is None:
            effective = min(DEFAULT_MAX_OUTPUT, self._max_output_tokens)
            if resolved.max_output_tokens is not None:
                effective = min(effective, resolved.max_output_tokens)
        else:
            if requested > self._max_output_tokens:
                raise InvalidGenerationParameters(
                    f"max_tokens exceeds the local limit of {self._max_output_tokens}.",
                    conversation_id=None,
                )
            if resolved.max_output_tokens is not None and requested > resolved.max_output_tokens:
                raise InvalidGenerationParameters(
                    f"max_tokens exceeds the model limit of {resolved.max_output_tokens}.",
                    conversation_id=None,
                )
            effective = requested

        if resolved.context_length is not None and effective >= resolved.context_length:
            raise InvalidGenerationParameters(
                "max_tokens leaves no room for the prompt in the model context window.",
                conversation_id=None,
            )
        return effective

    # ------------------------------------------------------------------
    # Non-streaming generation
    # ------------------------------------------------------------------
    async def generate(
        self,
        conversation_id: str,
        *,
        content: str,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        client_message_id: str | None = None,
    ) -> GenerationOutcome:
        """Run a non-streaming generation, rejecting starts during shutdown."""
        self._reject_if_shutting_down()
        current = asyncio.current_task()
        if current is not None:
            self._in_flight_starts.add(current)
        try:
            return await self._generate(
                conversation_id,
                content=content,
                provider=provider,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                client_message_id=client_message_id,
            )
        finally:
            if current is not None:
                self._in_flight_starts.discard(current)

    async def _generate(
        self,
        conversation_id: str,
        *,
        content: str,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        client_message_id: str | None = None,
    ) -> GenerationOutcome:
        conversation = await self._load_conversation(conversation_id)
        self._validate_temperature(temperature)
        resolved = await self._resolver.resolve(conversation, provider=provider, model=model)
        max_tokens = self._effective_max_tokens(max_tokens, resolved)
        async with self._start_lock:
            self._reject_if_shutting_down()
            turn = await self._begin_turn(
                conversation_id,
                content=content,
                resolved=resolved,
                client_message_id=client_message_id,
            )
            if turn.replayed:
                if turn.assistant_message.status in TERMINAL_STATUSES:
                    return GenerationOutcome(
                        conversation_id,
                        turn.user_message,
                        turn.assistant_message,
                        replayed=True,
                    )
                raise GenerationInProgress(
                    "The idempotent request is still generating.",
                    conversation_id=conversation_id,
                )

            assistant_id = turn.assistant_message.id
            handle = GenerationHandle(
                conversation_id,
                assistant_id,
                task=cast("asyncio.Task[None] | None", asyncio.current_task()),
            )
            self.generations.register(handle)
        try:
            try:
                messages = await self._context_messages(
                    conversation_id,
                    turn.assistant_message.sequence,
                    resolved,
                    max_tokens,
                )
            except ContextTooLarge as exc:
                await self._finish(
                    conversation_id,
                    assistant_id,
                    status=MessageStatus.FAILED,
                    error_code=exc.code,
                    error_message=exc.message,
                )
                raise

            request = CompletionRequest(
                model=resolved.model,
                messages=tuple(messages),
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if self._generation_timeout:
                try:
                    async with asyncio.timeout(self._generation_timeout):
                        result = await resolved.provider.complete(request)
                except TimeoutError:
                    await self._finish(
                        conversation_id,
                        assistant_id,
                        status=MessageStatus.FAILED,
                        error_code="provider_timeout",
                        error_message="Generation timed out.",
                    )
                    raise ProviderTimeoutError(
                        "Generation timed out.", provider=resolved.provider_id
                    ) from None
            else:
                result = await resolved.provider.complete(request)

            if not result.content.strip():
                await self._finish(
                    conversation_id,
                    assistant_id,
                    status=MessageStatus.FAILED,
                    error_code="provider_invalid_response",
                    error_message="Provider returned an empty response.",
                )
                raise ProviderInvalidResponseError(
                    "Provider returned an empty response.", provider=resolved.provider_id
                )

            assistant = await self._finish(
                conversation_id,
                assistant_id,
                status=MessageStatus.COMPLETED,
                content=result.content,
                finish_reason=result.finish_reason,
                usage=result.usage,
            )
            if assistant is None:
                # The conversation was deleted while the provider was running.
                raise ConversationNotFound(
                    "Conversation was deleted during generation.",
                    conversation_id=conversation_id,
                )
            return GenerationOutcome(conversation_id, turn.user_message, assistant, replayed=False)
        except asyncio.CancelledError:
            reason = _cancellation_reason(handle)
            await self._finish(
                conversation_id,
                assistant_id,
                status=MessageStatus.CANCELLED,
                error_code=reason,
                error_message="Generation cancelled.",
            )
            raise
        except ProviderError as exc:
            await self._finish(
                conversation_id,
                assistant_id,
                status=MessageStatus.FAILED,
                error_code=exc.code,
                error_message=exc.message,
            )
            raise
        except Exception:
            _logger.exception("Unexpected generation failure")
            await self._finish(
                conversation_id,
                assistant_id,
                status=MessageStatus.FAILED,
                error_code="internal_error",
                error_message="Generation failed.",
            )
            raise
        finally:
            self.generations.unregister(handle)

    async def _abort_start(
        self,
        conversation_id: str,
        handle: GenerationHandle,
        task: asyncio.Task[None] | None,
        exc: BaseException,
    ) -> None:
        """Clean up a stream that failed before handing control to its caller.

        ``_run_stream`` owns the normal terminal path; this method is
        idempotent with that path because finalization is conditional and
        lock release is scoped to the assistant message.
        """
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        self.generations.unregister(handle)

        if isinstance(exc, asyncio.CancelledError):
            status = MessageStatus.CANCELLED
            error_code = "client_disconnect"
            error_message = "Generation cancelled."
        elif isinstance(exc, TimeoutError):
            status = MessageStatus.FAILED
            error_code = "generation_start_timeout"
            error_message = "Generation failed to start."
        else:
            status = MessageStatus.FAILED
            error_code = "internal_error"
            error_message = "Generation failed to start."

        try:
            await asyncio.shield(
                self._finish(
                    conversation_id,
                    handle.message_id,
                    status=status,
                    error_code=error_code,
                    error_message=error_message,
                )
            )
        except (asyncio.CancelledError, Exception):
            _logger.exception("Failed to finalize aborted stream startup")

    async def start_stream(
        self,
        conversation_id: str,
        *,
        content: str,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        client_message_id: str | None = None,
    ) -> GenerationStream:
        """Start a streaming generation, rejecting starts during shutdown.

        The task is tracked until its turn is persisted so ``shutdown()`` can
        wait for starts that are still resolving their model.
        """
        self._reject_if_shutting_down()
        current = asyncio.current_task()
        if current is not None:
            self._in_flight_starts.add(current)
        try:
            return await self._start_stream(
                conversation_id,
                content=content,
                provider=provider,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                client_message_id=client_message_id,
            )
        finally:
            if current is not None:
                self._in_flight_starts.discard(current)

    async def _start_stream(
        self,
        conversation_id: str,
        *,
        content: str,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        client_message_id: str | None = None,
    ) -> GenerationStream:
        """Validate, persist the turn, then start streaming in a background task."""
        conversation = await self._load_conversation(conversation_id)
        self._validate_temperature(temperature)
        resolved = await self._resolver.resolve(conversation, provider=provider, model=model)
        max_tokens = self._effective_max_tokens(max_tokens, resolved)

        queue: asyncio.Queue[GenerationEvent | None] = asyncio.Queue(maxsize=STREAM_QUEUE_MAXSIZE)
        done = asyncio.Event()

        async with self._start_lock:
            self._reject_if_shutting_down()
            turn = await self._begin_turn(
                conversation_id,
                content=content,
                resolved=resolved,
                client_message_id=client_message_id,
            )

            started = MessageStarted(
                conversation_id=conversation_id,
                message_id=turn.assistant_message.id,
                user_message_id=turn.user_message.id,
                provider=resolved.provider_id,
                model=resolved.model,
                sequence=turn.assistant_message.sequence,
            )

            if turn.replayed:
                if turn.assistant_message.status not in TERMINAL_STATUSES:
                    raise GenerationInProgress(
                        "The idempotent request is still generating.",
                        conversation_id=conversation_id,
                    )
                queue.put_nowait(started)
                queue.put_nowait(_terminal_event(turn.assistant_message, resolved))
                queue.put_nowait(None)
                done.set()
                return GenerationStream(
                    queue,
                    None,
                    done=done,
                    conversation_id=conversation_id,
                    message_id=turn.assistant_message.id,
                )

            handle = GenerationHandle(conversation_id, turn.assistant_message.id)
            self.generations.register(handle)
            queue.put_nowait(started)
            ready = asyncio.Event()
            task: asyncio.Task[None] | None = None
            try:
                task = asyncio.create_task(
                    _run_stream(
                        self,
                        queue,
                        handle,
                        resolved,
                        turn,
                        done,
                        ready=ready,
                        generation_timeout=self._generation_timeout,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                )
                handle.task = task
                # Wait for the producer to enter its coroutine while still holding
                # the registration lock, so cancel cannot hit a task that has not
                # started yet.
                await asyncio.wait_for(ready.wait(), timeout=5)
            except BaseException as exc:
                await self._abort_start(conversation_id, handle, task, exc)
                raise
        return GenerationStream(
            queue,
            task,
            done=done,
            conversation_id=conversation_id,
            message_id=turn.assistant_message.id,
        )


class GenerationStream:
    """Events produced by a background generation task (SSE-friendly)."""

    def __init__(
        self,
        queue: asyncio.Queue[GenerationEvent | None],
        task: asyncio.Task[None] | None,
        *,
        done: asyncio.Event | None = None,
        conversation_id: str,
        message_id: str,
    ) -> None:
        self._queue = queue
        self._task = task
        self._done = done or asyncio.Event()
        self._close_started = False
        self.conversation_id = conversation_id
        self.message_id = message_id

    async def __aiter__(self) -> AsyncIterator[GenerationEvent]:
        try:
            while True:
                if self._done.is_set() and self._queue.empty():
                    return
                try:
                    event = await asyncio.wait_for(
                        self._queue.get(), timeout=SSE_HEARTBEAT_INTERVAL_SECONDS
                    )
                except TimeoutError:
                    # Silence while the producer waits on the provider: emit a
                    # comment frame. Cancelling `Queue.get()` is safe (the item,
                    # if any, stays queued for the next read).
                    if self._done.is_set():
                        return
                    yield Heartbeat()
                    continue
                if event is None:
                    return
                yield event
        finally:
            await self.close()

    async def close(self) -> None:
        """Cancel the producer at most once.

        ``close`` is reachable twice on a transport disconnect: once from the
        route's serialiser and again when the nested iterator is finalised. A
        second ``task.cancel()`` would interrupt the producer's own terminal
        persistence and leave the row non-terminal, so the first call wins and
        later calls are no-ops.
        """
        if self._close_started:
            return
        self._close_started = True
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def _persist_partial(
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: str,
    message_id: str,
    content: str,
) -> None:
    async with session_factory() as session:
        await ConversationRepository(session).update_message(
            message_id, status=MessageStatus.STREAMING, content=content
        )
        await session.commit()


def _enqueue_delta(queue: asyncio.Queue[GenerationEvent | None], event: ContentDelta) -> None:
    """Queue a delta without blocking generation on a slow consumer.

    When the bounded queue is full, evict the oldest *delta* and retry once.
    Terminal events and the sentinel are never evicted here; if the queue has
    no delta to evict, the incoming delta is dropped instead. ``parts`` is
    maintained independently by the caller, so dropped deltas never change
    the content that will be persisted.
    """
    try:
        queue.put_nowait(event)
        return
    except asyncio.QueueFull:
        pass

    buffered: list[GenerationEvent | None] = []
    while True:
        try:
            buffered.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break

    drop_index = next(
        (index for index, item in enumerate(buffered) if isinstance(item, ContentDelta)),
        None,
    )
    if drop_index is None:
        for item in buffered:
            queue.put_nowait(item)
        _logger.warning(
            "Stream queue full with no delta to evict; dropped %s (message_id=%s)",
            type(event).__name__,
            event.message_id,
        )
        return

    dropped = buffered.pop(drop_index)
    for item in buffered:
        queue.put_nowait(item)
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        _logger.warning(
            "Unable to deliver %s after evicting %s (message_id=%s)",
            type(event).__name__,
            type(dropped).__name__,
            event.message_id,
        )
        return
    _logger.warning(
        "Stream queue full; dropped %s to deliver %s (message_id=%s)",
        type(dropped).__name__,
        type(event).__name__,
        event.message_id,
    )


async def _deliver(
    queue: asyncio.Queue[GenerationEvent | None],
    event: GenerationEvent | None,
) -> None:
    """Place a terminal event without blocking generation finalization.

    Terminal events take priority: if the bounded queue is full, the oldest
    queued event is discarded to make room for the terminal. The sentinel is
    best-effort when the queue is full; GenerationStream uses its ``done``
    event to terminate after draining, so dropping the sentinel cannot lose a
    terminal event. The persisted message remains the source of truth.
    """
    if event is None and queue.full():
        _logger.warning("Stream queue full; sentinel not queued")
        return
    try:
        queue.put_nowait(event)
        return
    except asyncio.QueueFull:
        try:
            dropped = queue.get_nowait()
        except asyncio.QueueEmpty:
            dropped = None
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            _logger.warning(
                "Unable to deliver %s; queue remains full (message_id=%s)",
                type(event).__name__,
                getattr(event, "message_id", None),
            )
            return
        _logger.warning(
            "Stream queue full; dropped %s to deliver %s (message_id=%s)",
            type(dropped).__name__,
            type(event).__name__,
            getattr(event, "message_id", None),
        )


async def _deliver_conversation_deleted(
    queue: asyncio.Queue[GenerationEvent | None], message_id: str
) -> None:
    """Terminal event for a generation whose conversation was deleted mid-flight.

    Nothing can be persisted (the row is gone), but the stream must still end
    with exactly one terminal event so clients never wait on a connection that
    can no longer complete. The persisted resource is authoritative: a follow-up
    request for the conversation returns 404.
    """
    _logger.warning(
        "Generation discarded: message %s no longer exists (conversation deleted)",
        message_id,
    )
    await _deliver(
        queue,
        MessageFailed(
            message_id,
            "conversation_deleted",
            "Conversation was deleted during generation.",
            False,
        ),
    )


def _cancellation_reason(handle: GenerationHandle) -> str:
    if handle.shutdown_requested:
        return "server_shutdown"
    if handle.cancel_requested:
        return "cancelled"
    return "client_disconnect"


async def _run_stream(
    engine: ConversationEngine,
    queue: asyncio.Queue[GenerationEvent | None],
    handle: GenerationHandle,
    resolved: ResolvedModel,
    turn: StartedTurn,
    done: asyncio.Event,
    *,
    ready: asyncio.Event,
    generation_timeout: float | None,
    temperature: float | None,
    max_tokens: int | None,
) -> None:
    conversation_id = handle.conversation_id
    message_id = handle.message_id
    parts: list[str] = []
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    last_flush = time.monotonic()
    ready.set()

    try:
        try:
            messages = await engine._context_messages(
                conversation_id, turn.assistant_message.sequence, resolved, max_tokens
            )
        except ContextTooLarge as exc:
            message = await engine._finish(
                conversation_id,
                message_id,
                status=MessageStatus.FAILED,
                error_code=exc.code,
                error_message=exc.message,
            )
            if message is None:
                await _deliver_conversation_deleted(queue, message_id)
            else:
                await _deliver(
                    queue, MessageFailed(message_id, exc.code, exc.message, retryable=False)
                )
            return

        request = CompletionRequest(
            model=resolved.model,
            messages=tuple(messages),
            temperature=temperature,
            max_tokens=max_tokens,
        )

        async def consume() -> None:
            nonlocal finish_reason, usage, last_flush
            async for chunk in resolved.provider.stream(request):
                if chunk.delta:
                    parts.append(chunk.delta)
                    # Never block generation on a slow consumer; the full
                    # content stays in ``parts`` for the final persistence.
                    _enqueue_delta(queue, ContentDelta(message_id, chunk.delta))
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
                if chunk.usage is not None:
                    usage = chunk.usage
                now = time.monotonic()
                if parts and now - last_flush >= PARTIAL_FLUSH_INTERVAL_SECONDS:
                    await _persist_partial(
                        engine._sessions, conversation_id, message_id, "".join(parts)
                    )
                    last_flush = now

        try:
            if generation_timeout:
                async with asyncio.timeout(generation_timeout):
                    await consume()
            else:
                await consume()
        except TimeoutError:
            message = await engine._finish(
                conversation_id,
                message_id,
                status=MessageStatus.FAILED,
                content="".join(parts),
                error_code="provider_timeout",
                error_message="Generation timed out.",
            )
            if message is None:
                await _deliver_conversation_deleted(queue, message_id)
            else:
                await _deliver(
                    queue,
                    MessageFailed(message_id, "provider_timeout", "Generation timed out.", True),
                )
            return

        content = "".join(parts)
        if not content.strip():
            message = await engine._finish(
                conversation_id,
                message_id,
                status=MessageStatus.FAILED,
                error_code="provider_invalid_response",
                error_message="Provider returned an empty response.",
            )
            if message is None:
                await _deliver_conversation_deleted(queue, message_id)
            else:
                await _deliver(
                    queue,
                    MessageFailed(
                        message_id,
                        "provider_invalid_response",
                        "Provider returned an empty response.",
                        False,
                    ),
                )
            return

        message = await engine._finish(
            conversation_id,
            message_id,
            status=MessageStatus.COMPLETED,
            content=content,
            finish_reason=finish_reason,
            usage=usage,
        )
        if message is None:
            await _deliver_conversation_deleted(queue, message_id)
            return
        if message.status != MessageStatus.COMPLETED.value:
            await _deliver(queue, _terminal_event(message, resolved))
            return
        await _deliver(
            queue,
            MessageCompleted(
                message_id,
                content,
                resolved.provider_id,
                resolved.model,
                finish_reason,
                usage,
            ),
        )
    except asyncio.CancelledError:
        partial = "".join(parts)
        reason = _cancellation_reason(handle)
        message = await engine._finish(
            conversation_id,
            message_id,
            status=MessageStatus.CANCELLED,
            content=partial,
            error_code=reason,
            error_message="Generation cancelled.",
        )
        if message is None:
            await _deliver_conversation_deleted(queue, message_id)
        elif message.status != MessageStatus.CANCELLED.value:
            await _deliver(queue, _terminal_event(message, resolved))
        else:
            await _deliver(queue, MessageCancelled(message_id, message.content, reason))
    except ProviderError as exc:
        partial = "".join(parts)
        message = await engine._finish(
            conversation_id,
            message_id,
            status=MessageStatus.FAILED,
            content=partial,
            error_code=exc.code,
            error_message=exc.message,
        )
        if message is None:
            await _deliver_conversation_deleted(queue, message_id)
        elif message.status == MessageStatus.COMPLETED.value:
            await _deliver(queue, _terminal_event(message, resolved))
        else:
            await _deliver(
                queue,
                MessageFailed(message_id, exc.code, exc.message, retryable=exc.retryable),
            )
    except Exception:
        _logger.exception("Unexpected streaming generation failure")
        partial = "".join(parts)
        message = await engine._finish(
            conversation_id,
            message_id,
            status=MessageStatus.FAILED,
            content=partial,
            error_code="internal_error",
            error_message="Generation failed.",
        )
        if message is None:
            await _deliver_conversation_deleted(queue, message_id)
        else:
            await _deliver(
                queue,
                MessageFailed(message_id, "internal_error", "Generation failed.", False),
            )
    finally:
        engine.generations.unregister(handle)
        await _deliver(queue, None)
        done.set()


def _terminal_event(message: Message, resolved: ResolvedModel) -> GenerationEvent:
    """Build the terminal event for an already persisted turn.

    Provider and model come from the persisted message, not from the resolved
    selection: a replay must report the model that produced the reply even if
    the conversation has been re-pointed since then.
    """
    provider = message.provider or resolved.provider_id
    model = message.model or resolved.model
    if message.status == MessageStatus.CANCELLED.value:
        return MessageCancelled(message.id, message.content, message.error_code or "cancelled")
    if message.status == MessageStatus.COMPLETED.value:
        usage: TokenUsage | None = None
        if message.total_tokens is not None:
            usage = TokenUsage(
                prompt_tokens=message.prompt_tokens or 0,
                completion_tokens=message.completion_tokens or 0,
                total_tokens=message.total_tokens,
            )
        return MessageCompleted(
            message.id,
            message.content,
            provider,
            model,
            message.finish_reason,
            usage,
        )
    return MessageFailed(
        message.id,
        message.error_code or "generation_failed",
        message.error_message or "Generation failed.",
        retryable=False,
    )
