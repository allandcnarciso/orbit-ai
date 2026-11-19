"""SSE lifecycle, cancellation, shutdown and persistence hardening tests."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest

import orbit.chat.engine as engine_module
from orbit.chat.engine import ConversationEngine, GenerationStream, _deliver
from orbit.chat.events import ContentDelta, GenerationEvent, MessageCompleted
from orbit.conversations.enums import MessageStatus
from orbit.conversations.errors import ServerShuttingDown
from orbit.conversations.repository import ConversationRepository
from orbit.providers.base import (
    CompletionChunk,
    CompletionRequest,
    CompletionResult,
    ModelInfo,
)
from orbit.providers.errors import ProviderUnavailableError
from orbit.providers.registry import ProviderRegistry
from orbit.storage.models import Conversation, Message
from orbit.storage.system_state import SystemStateStore
from tests.fakes import FakeProvider

BASE = "/api/v1/conversations"


def _install(app, provider: FakeProvider) -> ConversationEngine:
    registry = ProviderRegistry([provider])
    app.state.providers = registry
    engine = ConversationEngine(app.state.db.session_factory, registry)
    app.state.engine = engine
    return engine


async def _create(client, **payload: object) -> str:
    response = await client.post(BASE, json=payload)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _message(app, message_id: str) -> Message | None:
    async with app.state.db.session_factory() as session:
        return await session.get(Message, message_id)


async def _conversation(app, conversation_id: str) -> Conversation | None:
    async with app.state.db.session_factory() as session:
        return await session.get(Conversation, conversation_id)


async def _consume(stream: GenerationStream) -> list[GenerationEvent]:
    return [event async for event in stream]


class TimeoutAfterFirstChunkProvider(FakeProvider):
    async def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]:
        self.stream_calls += 1
        yield CompletionChunk(delta="partial", model=request.model)
        await asyncio.Event().wait()


async def test_total_stream_timeout_preserves_partial_content(client, app) -> None:
    provider = TimeoutAfterFirstChunkProvider()
    engine = _install(app, provider)
    engine._generation_timeout = 0.05
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    events = await asyncio.wait_for(_consume(stream), timeout=2)

    assert events[-1].event == "message.failed"
    message = await _message(app, stream.message_id)
    assert message is not None
    assert message.status == MessageStatus.FAILED.value
    assert message.error_code == "provider_timeout"
    assert message.content == "partial"
    assert engine.generations.get(conversation_id) is None
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None


async def test_immediate_disconnect_cancels_and_releases_lock(client, app) -> None:
    provider = FakeProvider(chunks=["a", "b", "c"], stream_delay=0.05)
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    await stream.close()

    message = await _message(app, stream.message_id)
    assert message is not None
    assert message.status == MessageStatus.CANCELLED.value
    assert message.error_code == "client_disconnect"
    assert engine.generations.get(conversation_id) is None
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None


async def test_start_timeout_cleans_up_task_handle_and_lock(client, app, monkeypatch) -> None:
    provider = FakeProvider(chunks=["a"], stream_delay=0.05)
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    async def never_ready(*args, **kwargs):
        await asyncio.Event().wait()

    async def immediate_timeout(awaitable, **kwargs):
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(engine_module, "_run_stream", never_ready)
    monkeypatch.setattr(engine_module.asyncio, "wait_for", immediate_timeout)

    with pytest.raises(TimeoutError):
        await engine.start_stream(
            conversation_id, content="Hi", provider="fake", model="fake-model"
        )

    assert engine.generations.get(conversation_id) is None
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None

    async with app.state.db.session_factory() as session:
        messages, _ = await ConversationRepository(session).list_messages(conversation_id)
    assistant = messages[-1]
    assert assistant.status == MessageStatus.FAILED.value
    assert assistant.error_code == "generation_start_timeout"


async def test_external_cancel_during_start_cleans_up(client, app, monkeypatch) -> None:
    provider = FakeProvider(chunks=["a"], stream_delay=0.05)
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")
    started = asyncio.Event()

    async def never_ready(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(engine_module, "_run_stream", never_ready)
    start_task = asyncio.create_task(
        engine.start_stream(conversation_id, content="Hi", provider="fake", model="fake-model")
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    start_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await start_task

    assert engine.generations.get(conversation_id) is None
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None

    async with app.state.db.session_factory() as session:
        messages, _ = await ConversationRepository(session).list_messages(conversation_id)
    assistant = messages[-1]
    assert assistant.status == MessageStatus.CANCELLED.value
    assert assistant.error_code == "client_disconnect"


async def test_cancel_immediately_after_start_stream(client, app) -> None:
    provider = FakeProvider(chunks=["a"], stream_delay=0.05)
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    cancelled_id = await engine.cancel(conversation_id)
    events = await asyncio.wait_for(_consume(stream), timeout=2)

    assert cancelled_id == stream.message_id
    assert [event.event for event in events if event.event == "message.cancelled"] == [
        "message.cancelled"
    ]
    message = await _message(app, stream.message_id)
    assert message is not None and message.status == MessageStatus.CANCELLED.value
    assert engine.generations.get(conversation_id) is None


async def test_cancel_waits_for_turn_registration(client, app) -> None:
    provider = FakeProvider(chunks=["a"], stream_delay=0.05)
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    original_begin = engine._begin_turn
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_begin(*args, **kwargs):
        started.set()
        await release.wait()
        return await original_begin(*args, **kwargs)

    engine._begin_turn = blocked_begin  # type: ignore[method-assign]
    start_task = asyncio.create_task(
        engine.start_stream(conversation_id, content="Hi", provider="fake", model="fake-model")
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    cancel_task = asyncio.create_task(engine.cancel(conversation_id))
    await asyncio.sleep(0)
    assert not cancel_task.done()

    release.set()
    stream = await asyncio.wait_for(start_task, timeout=2)
    cancelled_id = await asyncio.wait_for(cancel_task, timeout=2)
    await asyncio.wait_for(_consume(stream), timeout=2)

    assert cancelled_id == stream.message_id
    message = await _message(app, stream.message_id)
    assert message is not None and message.status == MessageStatus.CANCELLED.value
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None


async def test_stalled_consumer_without_timeout_finishes_and_persists(client, app, caplog) -> None:
    caplog.set_level(logging.WARNING, logger="orbit.chat.engine")
    chunks = [f"{index:03d}," for index in range(300)]
    provider = FakeProvider(chunks=chunks, stream_delay=0)
    engine = _install(app, provider)
    engine._generation_timeout = None
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    assert stream._task is not None
    # Bounded but generous: the point is "finishes without a consumer", not a
    # sub-second deadline (the 5 s bound was flaky under instrumented runs).
    await asyncio.wait_for(stream._task, timeout=60)

    response = await client.get(f"{BASE}/{conversation_id}/messages")
    assert response.status_code == 200
    assistant = response.json()["items"][-1]
    assert assistant["status"] == "completed"
    assert assistant["content"] == "".join(chunks)

    events = await asyncio.wait_for(_consume(stream), timeout=30)
    assert events[-1].event == "message.completed"
    assert engine.generations.get(conversation_id) is None
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None
    assert any("dropped" in record.message.lower() for record in caplog.records)


async def test_abort_start_waits_for_task_before_releasing_lock(client, app, monkeypatch) -> None:
    provider = FakeProvider(chunks=["a"], stream_delay=0)
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")
    started = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release = asyncio.Event()
    real_wait_for = asyncio.wait_for

    async def stubborn(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_seen.set()
            await release.wait()

    async def timeout_after_start(awaitable, **kwargs):
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        await started.wait()
        raise TimeoutError

    monkeypatch.setattr(engine_module, "_run_stream", stubborn)
    monkeypatch.setattr(engine_module.asyncio, "wait_for", timeout_after_start)

    start_task = asyncio.create_task(
        engine.start_stream(conversation_id, content="Hi", provider="fake", model="fake-model")
    )
    await real_wait_for(cancellation_seen.wait(), timeout=2)

    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is not None
    assert not start_task.done()

    release.set()
    with pytest.raises(TimeoutError):
        await real_wait_for(start_task, timeout=2)

    assert engine.generations.get(conversation_id) is None
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None
    async with app.state.db.session_factory() as session:
        messages, _ = await ConversationRepository(session).list_messages(conversation_id)
    assistant = messages[-1]
    assert assistant.status == MessageStatus.FAILED.value
    assert assistant.error_code == "generation_start_timeout"


async def test_terminal_delivery_evicts_oldest_when_queue_full(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="orbit.chat.engine")
    queue: asyncio.Queue[GenerationEvent | None] = asyncio.Queue(maxsize=2)
    queue.put_nowait(ContentDelta("m", "old"))
    queue.put_nowait(ContentDelta("m", "new"))
    terminal = MessageCompleted("m", "done", "fake", "fake-model")

    await _deliver(queue, terminal)

    remaining = [queue.get_nowait(), queue.get_nowait()]
    assert [getattr(event, "delta", None) for event in remaining] == ["new", None]
    assert remaining[-1] is terminal
    assert any("queue full" in record.message.lower() for record in caplog.records)


async def test_terminal_event_survives_full_queue_and_sentinel() -> None:
    queue: asyncio.Queue[GenerationEvent | None] = asyncio.Queue(maxsize=1)
    queue.put_nowait(ContentDelta("m", "old"))
    terminal = MessageCompleted("m", "done", "fake", "fake-model")

    await _deliver(queue, terminal)
    await _deliver(queue, None)

    assert queue.qsize() == 1
    assert queue.get_nowait() is terminal


async def test_stream_uses_done_event_when_sentinel_is_dropped() -> None:
    queue: asyncio.Queue[GenerationEvent | None] = asyncio.Queue(maxsize=1)
    queue.put_nowait(ContentDelta("m", "old"))
    terminal = MessageCompleted("m", "done", "fake", "fake-model")
    done = asyncio.Event()

    await _deliver(queue, terminal)
    await _deliver(queue, None)
    done.set()

    stream = GenerationStream(queue, None, done=done, conversation_id="c", message_id="m")
    events = await asyncio.wait_for(_consume(stream), timeout=1)

    assert events[-1] is terminal


async def test_get_messages_reconciles_after_disconnect(client, app) -> None:
    # Two paced chunks keep the producer inside the provider when the consumer
    # disconnects, so the cancellation path (not completion) is under test.
    provider = FakeProvider(chunks=["partial", "more"], stream_delay=0.05)
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    iterator = stream.__aiter__()
    await iterator.__anext__()
    await iterator.__anext__()
    await stream.close()

    response = await client.get(f"{BASE}/{conversation_id}/messages")
    assert response.status_code == 200
    assistant = response.json()["items"][-1]
    assert assistant["status"] == "cancelled"
    assert assistant["content"] == "partial"
    assert assistant["error_code"] == "client_disconnect"


async def test_disconnect_after_partial_output_preserves_content(client, app) -> None:
    provider = FakeProvider(chunks=["alpha", "beta", "gamma"], stream_delay=0.05)
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    iterator = stream.__aiter__()
    await iterator.__anext__()
    delta = await iterator.__anext__()
    assert delta.event == "content.delta"
    await stream.close()

    message = await _message(app, stream.message_id)
    assert message is not None
    assert message.status == MessageStatus.CANCELLED.value
    assert message.error_code == "client_disconnect"
    assert message.content.startswith(str(delta.data()["delta"]))
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None


async def test_duplicate_cancel_requests(client, app) -> None:
    provider = FakeProvider(chunks=["a", "b", "c"], stream_delay=0.05)
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    consumer = asyncio.create_task(_consume(stream))
    await asyncio.sleep(0.03)

    first = await engine.cancel(conversation_id)
    second = await engine.cancel(conversation_id)
    assert first == stream.message_id
    assert second == first

    events = await consumer
    terminals = [
        event
        for event in events
        if event.event.startswith("message.") and event.event != "message.started"
    ]
    assert [event.event for event in terminals] == ["message.cancelled"]
    message = await _message(app, stream.message_id)
    assert message is not None and message.status == MessageStatus.CANCELLED.value

    # After the terminal state is persisted and the handle unregistered, a new
    # cancel request reports that nothing is active.
    assert await engine.cancel(conversation_id) is None


async def test_cancellation_racing_completion_has_one_terminal(client, app) -> None:
    provider = FakeProvider(chunks=["a", "b", "c"], stream_delay=0.01)
    engine = _install(app, provider)
    delays = [0.0, 0.005, 0.01, 0.02, 0.03, 0.04]

    for index in range(12):
        conversation_id = await _create(client, provider="fake", model="fake-model")
        stream = await engine.start_stream(
            conversation_id, content="Hi", provider="fake", model="fake-model"
        )
        consumer = asyncio.create_task(_consume(stream))
        await asyncio.sleep(delays[index % len(delays)])
        await engine.cancel(conversation_id)
        events = await consumer

        terminals = [
            event
            for event in events
            if event.event in {"message.completed", "message.failed", "message.cancelled"}
        ]
        assert len(terminals) == 1, [event.event for event in events]
        message = await _message(app, stream.message_id)
        assert message is not None

        expected = {
            "message.completed": MessageStatus.COMPLETED.value,
            "message.failed": MessageStatus.FAILED.value,
            "message.cancelled": MessageStatus.CANCELLED.value,
        }[terminals[0].event]
        assert message.status == expected
        conversation = await _conversation(app, conversation_id)
        assert conversation is not None and conversation.active_generation_id is None


async def test_shutdown_cancels_active_generations(client, app) -> None:
    provider = FakeProvider(chunks=["a", "b", "c", "d"], stream_delay=0.05)
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    consumer = asyncio.create_task(_consume(stream))
    await asyncio.sleep(0.03)

    await engine.shutdown()
    events = await consumer
    terminals = [
        event
        for event in events
        if event.event in {"message.completed", "message.failed", "message.cancelled"}
    ]
    assert len(terminals) == 1
    assert terminals[0].event == "message.cancelled"
    assert terminals[0].data()["reason"] == "server_shutdown"

    message = await _message(app, stream.message_id)
    assert message is not None
    assert message.status == MessageStatus.CANCELLED.value
    assert message.error_code == "server_shutdown"
    assert engine.generations.get(conversation_id) is None
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None


async def test_no_transaction_open_during_provider_stream(client, app) -> None:
    provider = FakeProvider(chunks=["a", "b", "c"], stream_delay=0.05)
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    consumer = asyncio.create_task(_consume(stream))
    await asyncio.sleep(0.03)

    store = SystemStateStore(app.state.db.session_factory)
    await asyncio.wait_for(store.set("concurrency_probe", "ok"), timeout=1.0)
    assert await store.get("concurrency_probe") == "ok"

    await engine.cancel(conversation_id)
    await consumer


async def test_successful_generation_cleans_registry_and_lock(client, app) -> None:
    provider = FakeProvider(chunks=["a", "b"], stream_delay=0.01)
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    events = await _consume(stream)
    assert events[-1].event == "message.completed"
    assert engine.generations.get(conversation_id) is None

    message = await _message(app, stream.message_id)
    assert message is not None and message.status == MessageStatus.COMPLETED.value
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None


async def test_provider_failure_after_partial_chunks_preserves_content(client, app) -> None:
    provider = FakeProvider(
        chunks=["a", "b", "c"],
        error=ProviderUnavailableError("connection lost"),
        error_after_chunks=1,
    )
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    events = await _consume(stream)
    assert events[-1].event == "message.failed"
    assert events[-1].data()["error"]["code"] == "provider_unavailable"

    message = await _message(app, stream.message_id)
    assert message is not None
    assert message.status == MessageStatus.FAILED.value
    assert message.content == "a"
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None


async def test_empty_stream_is_reported_as_failure(client, app) -> None:
    provider = FakeProvider(chunks=[])
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    events = await _consume(stream)
    assert [event.event for event in events] == ["message.started", "message.failed"]
    assert events[-1].data()["error"]["code"] == "provider_invalid_response"

    message = await _message(app, stream.message_id)
    assert message is not None and message.status == MessageStatus.FAILED.value


async def test_different_conversations_stream_concurrently(client, app) -> None:
    provider = FakeProvider(chunks=["x", "y"], stream_delay=0.02)
    engine = _install(app, provider)
    first = await _create(client, provider="fake", model="fake-model")
    second = await _create(client, provider="fake", model="fake-model")

    first_stream, second_stream = await asyncio.gather(
        engine.start_stream(first, content="one", provider="fake", model="fake-model"),
        engine.start_stream(second, content="two", provider="fake", model="fake-model"),
    )
    first_events, second_events = await asyncio.gather(
        _consume(first_stream), _consume(second_stream)
    )
    assert first_events[-1].event == "message.completed"
    assert second_events[-1].event == "message.completed"

    for conversation_id in (first, second):
        conversation = await _conversation(app, conversation_id)
        assert conversation is not None and conversation.active_generation_id is None


async def test_failure_then_retry_succeeds(client, app) -> None:
    from orbit.providers.errors import ProviderAuthenticationError

    provider = FakeProvider(error=ProviderAuthenticationError("invalid key"))
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    failed = await client.post(f"{BASE}/{conversation_id}/messages", json={"content": "Hi"})
    assert failed.status_code == 502

    provider.error = None
    retried = await client.post(f"{BASE}/{conversation_id}/messages", json={"content": "Hi"})
    assert retried.status_code == 200, retried.text
    assert retried.json()["assistant_message"]["status"] == "completed"
    assert provider.complete_calls == 2

    async with app.state.db.session_factory() as session:
        messages, _ = await ConversationRepository(session).list_messages(conversation_id)
    assert [message.status for message in messages] == [
        MessageStatus.COMPLETED.value,
        MessageStatus.FAILED.value,
        MessageStatus.COMPLETED.value,
        MessageStatus.COMPLETED.value,
    ]

    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None


async def test_replay_while_generation_active_returns_conflict(client, app) -> None:
    provider = FakeProvider(chunks=["a", "b", "c"], stream_delay=0.05)
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id,
        content="Hi",
        provider="fake",
        model="fake-model",
        client_message_id="live-key",
    )
    consumer = asyncio.create_task(_consume(stream))
    await asyncio.sleep(0.03)

    replay = await client.post(
        f"{BASE}/{conversation_id}/messages",
        json={"content": "Hi", "client_message_id": "live-key"},
    )
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "generation_in_progress"

    await engine.cancel(conversation_id)
    await consumer


# ---------------------------------------------------------------------------
# Milestone 5.3-A — deletion during generation and shutdown handshake
# ---------------------------------------------------------------------------


class GatedStreamProvider(FakeProvider):
    """FakeProvider that parks inside ``stream()`` until the test releases it."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]:
        self.stream_calls += 1
        self.last_request = request
        self.entered.set()
        await self.release.wait()
        for index, delta in enumerate(self.chunks):
            last = index == len(self.chunks) - 1
            yield CompletionChunk(
                delta=delta,
                model=request.model,
                finish_reason="stop" if last else None,
                usage=self.usage if last else None,
            )


class GatedCompletionProvider(FakeProvider):
    """FakeProvider that parks inside ``complete()`` until the test releases it."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.complete_calls += 1
        self.last_request = request
        self.entered.set()
        await self.release.wait()
        return CompletionResult(
            content=self.content,
            model=request.model,
            finish_reason="stop",
            usage=self.usage,
        )


class GatedDiscoveryProvider(FakeProvider):
    """FakeProvider that can park inside ``list_models()`` once armed."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.gated = False

    async def list_models(self) -> list[ModelInfo]:
        if self.gated:
            self.entered.set()
            await self.release.wait()
        return await super().list_models()


class UncancelableProvider(FakeProvider):
    """FakeProvider that delays cancellation until the test releases it."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]:
        self.stream_calls += 1
        self.last_request = request
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await self.release.wait()
            raise
        yield CompletionChunk(delta="unreachable", model=request.model)


async def test_delete_conversation_during_stream_ends_with_conversation_deleted(
    client, app
) -> None:
    provider = GatedStreamProvider(chunks=["a", "b"])
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    await asyncio.wait_for(provider.entered.wait(), timeout=1)
    assert stream._task is not None

    deleted = await client.delete(f"{BASE}/{conversation_id}")
    assert deleted.status_code == 204

    provider.release.set()
    events = await asyncio.wait_for(_consume(stream), timeout=2)

    assert events[0].event == "message.started"
    terminals = [
        event
        for event in events
        if event.event in {"message.completed", "message.failed", "message.cancelled"}
    ]
    assert len(terminals) == 1
    assert terminals[0].event == "message.failed"
    assert terminals[0].data()["error"]["code"] == "conversation_deleted"
    assert engine.generations.get(conversation_id) is None

    # Nothing survives the delete: no lock, no conversation, no message history.
    assert (await client.get(f"{BASE}/{conversation_id}")).status_code == 404
    assert (await client.get(f"{BASE}/{conversation_id}/messages")).status_code == 404


async def test_delete_then_disconnect_persists_nothing_and_does_not_raise(client, app) -> None:
    provider = GatedStreamProvider(chunks=["a", "b"])
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    await asyncio.wait_for(provider.entered.wait(), timeout=1)
    assert (await client.delete(f"{BASE}/{conversation_id}")).status_code == 204

    # Cancels the producer; the terminal write must be a no-op, not an exception.
    await stream.close()

    async with app.state.db.session_factory() as session:
        assert await session.get(Message, stream.message_id) is None
    assert engine.generations.get(conversation_id) is None


async def test_delete_conversation_during_non_streaming_generation_returns_404(client, app) -> None:
    provider = GatedCompletionProvider()
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    request_task = asyncio.create_task(
        client.post(f"{BASE}/{conversation_id}/messages", json={"content": "Hi"})
    )
    await asyncio.wait_for(provider.entered.wait(), timeout=1)
    assert (await client.delete(f"{BASE}/{conversation_id}")).status_code == 204

    provider.release.set()
    response = await asyncio.wait_for(request_task, timeout=2)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "conversation_not_found"
    assert engine.generations.get(conversation_id) is None


async def test_start_after_shutdown_is_rejected_before_any_persistence(client, app) -> None:
    provider = GatedStreamProvider()
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    await engine.shutdown()

    with pytest.raises(ServerShuttingDown):
        await engine.start_stream(
            conversation_id, content="Hi", provider="fake", model="fake-model"
        )

    assert provider.stream_calls == 0
    async with app.state.db.session_factory() as session:
        messages, _ = await ConversationRepository(session).list_messages(conversation_id)
    assert messages == []
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None


async def test_non_streaming_generation_after_shutdown_returns_503(client, app) -> None:
    _install(app, GatedCompletionProvider())
    conversation_id = await _create(client, provider="fake", model="fake-model")
    engine = app.state.engine
    await engine.shutdown()

    response = await client.post(f"{BASE}/{conversation_id}/messages", json={"content": "Hi"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "server_shutting_down"
    assert engine.generations.get(conversation_id) is None


async def test_shutdown_during_start_handshake_rejects_the_start(client, app) -> None:
    provider = GatedDiscoveryProvider()
    engine = _install(app, provider)
    # No provider/model on the conversation: discovery is deferred to the request.
    conversation_id = await _create(client)
    provider.gated = True

    start_task = asyncio.create_task(
        engine.start_stream(conversation_id, content="Hi", provider="fake", model="fake-model")
    )
    await asyncio.wait_for(provider.entered.wait(), timeout=1)

    shutdown_task = asyncio.create_task(engine.shutdown())
    await asyncio.sleep(0)  # let shutdown raise the barrier and block on its drain
    assert engine.shutting_down

    provider.release.set()
    with pytest.raises(ServerShuttingDown):
        await asyncio.wait_for(start_task, timeout=2)
    await asyncio.wait_for(shutdown_task, timeout=2)

    assert provider.stream_calls == 0
    async with app.state.db.session_factory() as session:
        messages, _ = await ConversationRepository(session).list_messages(conversation_id)
    assert messages == []
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None


async def test_shutdown_awaits_terminal_persistence_before_returning(client, app) -> None:
    provider = GatedStreamProvider(chunks=["a", "b"])
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    await asyncio.wait_for(provider.entered.wait(), timeout=1)

    await engine.shutdown()

    # Read the row right after shutdown returns: the terminal write must be durable.
    message = await _message(app, stream.message_id)
    assert message is not None
    assert message.status == MessageStatus.CANCELLED.value
    assert message.error_code == "server_shutdown"
    assert engine.generations.get(conversation_id) is None

    events = await asyncio.wait_for(_consume(stream), timeout=2)
    assert events[-1].event == "message.cancelled"
    assert events[-1].data()["reason"] == "server_shutdown"


async def test_shutdown_bounds_the_wait_for_an_uncancellable_generation(
    client, app, caplog
) -> None:
    caplog.set_level(logging.WARNING, logger="orbit.chat.engine")
    provider = UncancelableProvider()
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    await asyncio.wait_for(provider.entered.wait(), timeout=1)

    # Must return even though the producer ignores cancellation until released.
    await asyncio.wait_for(engine.shutdown(timeout_seconds=0.05), timeout=2)
    assert engine.generations.get(conversation_id) is not None
    assert any("timed out waiting" in record.message.lower() for record in caplog.records)

    provider.release.set()
    assert stream._task is not None
    await asyncio.wait_for(stream._task, timeout=2)

    message = await _message(app, stream.message_id)
    assert message is not None
    assert message.status == MessageStatus.CANCELLED.value
    assert message.error_code == "server_shutdown"
    assert engine.generations.get(conversation_id) is None


async def test_shutdown_is_idempotent(client, app) -> None:
    engine = _install(app, GatedStreamProvider())
    await engine.shutdown()
    await engine.shutdown()
    assert engine.shutting_down
