"""Persistence access for conversations and messages.

Repositories never commit: callers own the transaction boundary so a turn can
be created atomically (idempotency check, generation lock, both messages).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from orbit.conversations.enums import ConversationStatus, MessageRole, MessageStatus
from orbit.conversations.errors import (
    ConversationArchived,
    ConversationError,
    ConversationNotFound,
    GenerationInProgress,
    IdempotencyConflict,
)
from orbit.storage.models import Conversation, Message, utcnow

MAX_SEQUENCE_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class StartedTurn:
    conversation: Conversation
    user_message: Message
    assistant_message: Message
    replayed: bool


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    messages_recovered: int
    locks_cleared: int


class ConversationRepository:
    """Conversation and message persistence on a caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------
    async def create_conversation(
        self,
        *,
        title: str = "New conversation",
        provider: str | None = None,
        model: str | None = None,
        conversation_id: str | None = None,
    ) -> Conversation:
        conversation = Conversation(
            id=conversation_id or uuid4().hex,
            title=_clean_title(title),
            provider=provider,
            model=model,
            status=ConversationStatus.ACTIVE.value,
        )
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        return await self._session.get(Conversation, conversation_id)

    async def list_conversations(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: ConversationStatus | None = None,
    ) -> tuple[list[Conversation], int]:
        conditions = []
        if status is not None:
            conditions.append(Conversation.status == status.value)
        total = await self._session.scalar(
            select(func.count()).select_from(Conversation).where(*conditions)
        )
        result = await self._session.scalars(
            select(Conversation)
            .where(*conditions)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.all()), int(total or 0)

    async def delete_conversation(self, conversation_id: str) -> bool:
        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                delete(Conversation).where(Conversation.id == conversation_id)
            ),
        )
        return bool(result.rowcount)

    async def rename_conversation(self, conversation_id: str, title: str) -> Conversation | None:
        conversation = await self.get_conversation(conversation_id)
        if conversation is None:
            return None
        conversation.title = _clean_title(title)
        conversation.updated_at = utcnow()
        await self._session.flush()
        return conversation

    async def set_conversation_selection(
        self, conversation_id: str, *, provider: str | None, model: str | None
    ) -> Conversation | None:
        conversation = await self.get_conversation(conversation_id)
        if conversation is None:
            return None
        conversation.provider = provider
        conversation.model = model
        conversation.updated_at = utcnow()
        await self._session.flush()
        return conversation

    async def set_conversation_status(
        self, conversation_id: str, status: ConversationStatus
    ) -> Conversation | None:
        conversation = await self.get_conversation(conversation_id)
        if conversation is None:
            return None
        conversation.status = status.value
        conversation.updated_at = utcnow()
        await self._session.flush()
        return conversation

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------
    async def get_message(self, conversation_id: str, message_id: str) -> Message | None:
        message = await self._session.get(Message, message_id)
        if message is None or message.conversation_id != conversation_id:
            return None
        return message

    async def list_messages(
        self, conversation_id: str, *, limit: int = 100, before_sequence: int | None = None
    ) -> tuple[list[Message], bool]:
        statement = select(Message).where(Message.conversation_id == conversation_id)
        if before_sequence is not None:
            statement = statement.where(Message.sequence < before_sequence)
        statement = statement.order_by(Message.sequence.desc()).limit(limit + 1)
        rows = list((await self._session.scalars(statement)).all())
        has_more = len(rows) > limit
        window = rows[:limit]
        window.reverse()
        return window, has_more

    async def list_completed_dialogue(
        self, conversation_id: str, *, before_sequence: int | None = None
    ) -> list[Message]:
        """Completed user/assistant/system messages in sequence order (for context)."""
        statement = select(Message).where(
            Message.conversation_id == conversation_id,
            Message.status == MessageStatus.COMPLETED.value,
            Message.role.in_(
                [
                    MessageRole.USER.value,
                    MessageRole.ASSISTANT.value,
                    MessageRole.SYSTEM.value,
                ]
            ),
        )
        if before_sequence is not None:
            statement = statement.where(Message.sequence < before_sequence)
        statement = statement.order_by(Message.sequence.asc())
        rows = await self._session.scalars(statement)
        return list(rows.all())

    async def count_messages(self, conversation_id: str) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
        return int(total or 0)

    async def find_by_client_message_id(
        self, conversation_id: str, client_message_id: str
    ) -> Message | None:
        result: Message | None = await self._session.scalar(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.client_message_id == client_message_id,
            )
        )
        return result

    async def add_message(
        self,
        conversation_id: str,
        *,
        role: MessageRole,
        content: str = "",
        status: MessageStatus = MessageStatus.COMPLETED,
        provider: str | None = None,
        model: str | None = None,
        client_message_id: str | None = None,
        message_id: str | None = None,
    ) -> Message:
        """Append a message, allocating the next per-conversation sequence."""
        message_id = message_id or uuid4().hex
        for attempt in range(1, MAX_SEQUENCE_ATTEMPTS + 1):
            try:
                async with self._session.begin_nested():
                    sequence = await self._next_sequence(conversation_id)
                    message = Message(
                        id=message_id,
                        conversation_id=conversation_id,
                        sequence=sequence,
                        role=role.value,
                        content=content,
                        status=status.value,
                        provider=provider,
                        model=model,
                        client_message_id=client_message_id,
                    )
                    self._session.add(message)
                    await self._session.flush()
                await self._session.execute(
                    update(Conversation)
                    .where(Conversation.id == conversation_id)
                    .values(last_message_at=utcnow(), updated_at=utcnow())
                )
                return message
            except IntegrityError:
                if attempt == MAX_SEQUENCE_ATTEMPTS:
                    raise
        raise ConversationError("Could not allocate a message sequence.")

    async def finalize_message(
        self,
        message_id: str,
        *,
        status: MessageStatus,
        content: str | None = None,
        finish_reason: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> Message | None:
        """Transition a message to a terminal status exactly once.

        A second terminal write is a no-op: the existing row is returned so the
        caller can reconcile its terminal event with the persisted outcome.
        """
        values: dict[str, Any] = {
            "status": status.value,
            "updated_at": utcnow(),
        }
        if content is not None:
            values["content"] = content
        if finish_reason is not None:
            values["finish_reason"] = finish_reason
        if prompt_tokens is not None:
            values["prompt_tokens"] = prompt_tokens
        if completion_tokens is not None:
            values["completion_tokens"] = completion_tokens
        if total_tokens is not None:
            values["total_tokens"] = total_tokens
        if error_code is not None:
            values["error_code"] = error_code
        if error_message is not None:
            values["error_message"] = error_message

        await self._session.execute(
            update(Message)
            .where(
                Message.id == message_id,
                Message.status.in_([MessageStatus.PENDING.value, MessageStatus.STREAMING.value]),
            )
            .values(**values)
        )
        await self._session.flush()
        result: Message | None = await self._session.scalar(
            select(Message)
            .where(Message.id == message_id)
            .execution_options(populate_existing=True)
        )
        return result

    async def update_message(
        self,
        message_id: str,
        *,
        status: MessageStatus | None = None,
        content: str | None = None,
        finish_reason: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> Message | None:
        message = await self._session.get(Message, message_id)
        if message is None:
            return None
        if status is not None:
            message.status = status.value
        if content is not None:
            message.content = content
        if finish_reason is not None:
            message.finish_reason = finish_reason
        if prompt_tokens is not None:
            message.prompt_tokens = prompt_tokens
        if completion_tokens is not None:
            message.completion_tokens = completion_tokens
        if total_tokens is not None:
            message.total_tokens = total_tokens
        if error_code is not None:
            message.error_code = error_code
        if error_message is not None:
            message.error_message = error_message
        message.updated_at = utcnow()
        await self._session.flush()
        return message

    async def start_turn(
        self,
        conversation_id: str,
        *,
        content: str,
        provider: str,
        model: str,
        client_message_id: str | None = None,
    ) -> StartedTurn:
        """Atomically create a user message, assistant placeholder and lock.

        The generation lock is acquired with a single UPDATE before any read, so
        concurrent requests never upgrade a WAL read snapshot into a write.
        Idempotency is then resolved *under* the write lock: a matching
        ``client_message_id`` replays the existing turn (releasing our lock if we
        acquired one), different content raises ``IdempotencyConflict``, and a
        lost uniqueness race is recovered from the savepoint without surfacing a
        raw ``IntegrityError``.
        """
        assistant_id = uuid4().hex
        lock = cast(
            "CursorResult[Any]",
            await self._session.execute(
                update(Conversation)
                .where(
                    Conversation.id == conversation_id,
                    Conversation.status == ConversationStatus.ACTIVE.value,
                    Conversation.active_generation_id.is_(None),
                )
                .values(active_generation_id=assistant_id, updated_at=utcnow())
            ),
        )
        conversation = await self.get_conversation(conversation_id)
        if conversation is None:
            raise ConversationNotFound("Conversation not found.", conversation_id=conversation_id)

        if client_message_id:
            replay = await self._replay_turn(conversation, client_message_id, content)
            if replay is not None:
                if lock.rowcount == 1:
                    # Undo the lock acquired by this transaction; the caller commits.
                    await self.release_generation_lock(conversation_id, assistant_id)
                return replay

        if lock.rowcount != 1:
            if conversation.status == ConversationStatus.ARCHIVED.value:
                raise ConversationArchived(
                    "Conversation is archived.", conversation_id=conversation_id
                )
            raise GenerationInProgress(
                "A generation is already running for this conversation.",
                conversation_id=conversation_id,
            )

        try:
            user_message = await self.add_message(
                conversation_id,
                role=MessageRole.USER,
                content=content,
                status=MessageStatus.COMPLETED,
                client_message_id=client_message_id,
            )
        except IntegrityError:
            if client_message_id is None:
                raise
            # add_message rolled back its savepoint; the transaction is still usable.
            await self.release_generation_lock(conversation_id, assistant_id)
            replay = await self._replay_turn(conversation, client_message_id, content)
            if replay is not None:
                return replay
            raise

        assistant_message = await self.add_message(
            conversation_id,
            role=MessageRole.ASSISTANT,
            content="",
            status=MessageStatus.PENDING,
            provider=provider,
            model=model,
            message_id=assistant_id,
        )

        now = utcnow()
        conversation.last_message_at = now
        conversation.updated_at = now
        await self._session.flush()
        return StartedTurn(conversation, user_message, assistant_message, replayed=False)

    async def release_generation_lock(
        self, conversation_id: str, assistant_message_id: str
    ) -> bool:
        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                update(Conversation)
                .where(
                    Conversation.id == conversation_id,
                    Conversation.active_generation_id == assistant_message_id,
                )
                .values(active_generation_id=None, updated_at=utcnow())
            ),
        )
        return bool(result.rowcount)

    async def recover_interrupted(self) -> RecoveryReport:
        """Mark interrupted generations as failed and clear stale locks.

        Partial content is preserved; the failure reason is recorded. Intended to
        run at startup before the application accepts requests.
        """
        now = utcnow()
        recovered = cast(
            "CursorResult[Any]",
            await self._session.execute(
                update(Message)
                .where(
                    Message.status.in_([MessageStatus.PENDING.value, MessageStatus.STREAMING.value])
                )
                .values(
                    status=MessageStatus.FAILED.value,
                    error_code="interrupted",
                    error_message="Generation interrupted by application restart.",
                    updated_at=now,
                )
            ),
        )
        cleared = cast(
            "CursorResult[Any]",
            await self._session.execute(
                update(Conversation)
                .where(Conversation.active_generation_id.is_not(None))
                .values(active_generation_id=None, updated_at=now)
            ),
        )
        return RecoveryReport(
            messages_recovered=int(recovered.rowcount or 0),
            locks_cleared=int(cleared.rowcount or 0),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _replay_turn(
        self, conversation: Conversation, client_message_id: str, content: str
    ) -> StartedTurn | None:
        """Return the existing turn for an idempotency key, if any.

        Called while holding the conversation write lock, so the row cannot change
        between the lookup and the caller's commit.
        """
        existing = await self.find_by_client_message_id(conversation.id, client_message_id)
        if existing is None:
            return None
        if existing.content != content:
            raise IdempotencyConflict(
                "client_message_id was already used with different content.",
                conversation_id=conversation.id,
            )
        assistant = await self._replay_assistant(conversation.id, existing.sequence)
        if assistant is None:
            raise ConversationError(
                "Idempotent replay is missing its assistant message.",
                conversation_id=conversation.id,
            )
        return StartedTurn(conversation, existing, assistant, replayed=True)

    async def _replay_assistant(self, conversation_id: str, user_sequence: int) -> Message | None:
        result: Message | None = await self._session.scalar(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.sequence == user_sequence + 1,
                Message.role == MessageRole.ASSISTANT.value,
            )
        )
        return result

    async def _next_sequence(self, conversation_id: str) -> int:
        current = await self._session.scalar(
            select(func.coalesce(func.max(Message.sequence), 0)).where(
                Message.conversation_id == conversation_id
            )
        )
        return int(current or 0) + 1


def _clean_title(title: str) -> str:
    cleaned = " ".join(title.split())
    return cleaned[:200] if cleaned else "New conversation"
