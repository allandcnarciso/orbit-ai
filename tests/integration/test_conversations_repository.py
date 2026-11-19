"""Persistence tests for conversations, messages, locks and idempotency."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from orbit.conversations.enums import ConversationStatus, MessageRole, MessageStatus
from orbit.conversations.errors import (
    ConversationArchived,
    ConversationNotFound,
    GenerationInProgress,
    IdempotencyConflict,
)
from orbit.conversations.repository import ConversationRepository
from orbit.core.config import Settings
from orbit.storage.db import MIGRATIONS_DIR, Database
from orbit.storage.models import Message


@pytest.fixture
async def repo(database: Database) -> AsyncIterator[ConversationRepository]:
    async with database.session_factory() as session:
        yield ConversationRepository(session)
        await session.commit()


async def test_conversation_crud_and_listing(repo: ConversationRepository) -> None:
    first = await repo.create_conversation(
        title="  First   chat  ", provider="ollama", model="llama"
    )
    second = await repo.create_conversation(title="Second")

    assert first.title == "First chat"
    assert first.status == ConversationStatus.ACTIVE.value

    loaded = await repo.get_conversation(first.id)
    assert loaded is not None and loaded.id == first.id

    renamed = await repo.rename_conversation(first.id, "Renamed")
    assert renamed is not None and renamed.title == "Renamed"

    items, total = await repo.list_conversations(limit=10, offset=0)
    assert total == 2
    assert {item.id for item in items} == {first.id, second.id}

    page, _ = await repo.list_conversations(limit=1, offset=1)
    assert len(page) == 1

    await repo.set_conversation_status(second.id, ConversationStatus.ARCHIVED)
    active, _ = await repo.list_conversations(status=ConversationStatus.ACTIVE)
    assert [item.id for item in active] == [first.id]

    assert await repo.delete_conversation(first.id) is True
    assert await repo.get_conversation(first.id) is None
    assert await repo.delete_conversation(first.id) is False


async def test_delete_cascades_messages(database: Database) -> None:
    async with database.session_factory() as session:
        repo = ConversationRepository(session)
        conversation = await repo.create_conversation(title="Cascade")
        await repo.start_turn(conversation.id, content="hello", provider="ollama", model="llama")
        await session.commit()
        conversation_id = conversation.id

    async with database.session_factory() as session:
        repo = ConversationRepository(session)
        assert await repo.count_messages(conversation_id) == 2
        assert await repo.delete_conversation(conversation_id) is True
        await session.commit()

    async with database.session_factory() as session:
        remaining = await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
    assert remaining == 0


async def test_message_ordering_and_pagination(repo: ConversationRepository) -> None:
    conversation = await repo.create_conversation(title="Ordering")
    for index in range(1, 6):
        await repo.add_message(
            conversation.id,
            role=MessageRole.USER,
            content=f"message {index}",
            status=MessageStatus.COMPLETED,
        )

    window, has_more = await repo.list_messages(conversation.id, limit=2)
    assert [message.sequence for message in window] == [4, 5]
    assert has_more is True

    older, has_more_older = await repo.list_messages(conversation.id, limit=2, before_sequence=4)
    assert [message.sequence for message in older] == [2, 3]
    assert has_more_older is True

    first, has_more_first = await repo.list_messages(conversation.id, limit=10)
    assert [message.sequence for message in first] == [1, 2, 3, 4, 5]
    assert has_more_first is False
    assert await repo.count_messages(conversation.id) == 5


async def test_sequence_unique_constraint(database: Database) -> None:
    async with database.session_factory() as session:
        repo = ConversationRepository(session)
        conversation = await repo.create_conversation(title="Unique")
        session.add(
            Message(
                id="a" * 32,
                conversation_id=conversation.id,
                sequence=1,
                role=MessageRole.USER.value,
                content="first",
                status=MessageStatus.COMPLETED.value,
            )
        )
        session.add(
            Message(
                id="b" * 32,
                conversation_id=conversation.id,
                sequence=1,
                role=MessageRole.ASSISTANT.value,
                content="duplicate",
                status=MessageStatus.PENDING.value,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_idempotent_turn_replay(repo: ConversationRepository) -> None:
    conversation = await repo.create_conversation(title="Idempotent")
    first = await repo.start_turn(
        conversation.id,
        content="hello",
        provider="ollama",
        model="llama",
        client_message_id="client-1",
    )
    assert first.replayed is False

    replay = await repo.start_turn(
        conversation.id,
        content="hello",
        provider="ollama",
        model="llama",
        client_message_id="client-1",
    )
    assert replay.replayed is True
    assert replay.user_message.id == first.user_message.id
    assert replay.assistant_message.id == first.assistant_message.id
    assert await repo.count_messages(conversation.id) == 2


async def test_idempotency_conflict_on_different_content(repo: ConversationRepository) -> None:
    conversation = await repo.create_conversation(title="Conflict")
    await repo.start_turn(
        conversation.id,
        content="original",
        provider="ollama",
        model="llama",
        client_message_id="client-2",
    )
    with pytest.raises(IdempotencyConflict):
        await repo.start_turn(
            conversation.id,
            content="changed",
            provider="ollama",
            model="llama",
            client_message_id="client-2",
        )


async def test_generation_lock_blocks_second_turn(database: Database) -> None:
    async with database.session_factory() as session:
        repo = ConversationRepository(session)
        conversation = await repo.create_conversation(title="Locked")
        turn = await repo.start_turn(
            conversation.id, content="one", provider="ollama", model="llama"
        )
        await session.commit()
        conversation_id = conversation.id
        assistant_id = turn.assistant_message.id

    async with database.session_factory() as session:
        repo = ConversationRepository(session)
        with pytest.raises(GenerationInProgress):
            await repo.start_turn(conversation_id, content="two", provider="ollama", model="llama")
        await session.rollback()

    async with database.session_factory() as session:
        repo = ConversationRepository(session)
        assert await repo.release_generation_lock(conversation_id, assistant_id) is True
        await session.commit()

    async with database.session_factory() as session:
        repo = ConversationRepository(session)
        second = await repo.start_turn(
            conversation_id, content="two", provider="ollama", model="llama"
        )
        await session.commit()
        assert second.user_message.sequence == 3
        assert second.assistant_message.sequence == 4


async def test_archived_conversation_rejects_turn(repo: ConversationRepository) -> None:
    conversation = await repo.create_conversation(title="Archived")
    await repo.set_conversation_status(conversation.id, ConversationStatus.ARCHIVED)
    with pytest.raises(ConversationArchived):
        await repo.start_turn(conversation.id, content="hi", provider="ollama", model="llama")


async def test_unknown_conversation_raises_not_found(repo: ConversationRepository) -> None:
    with pytest.raises(ConversationNotFound):
        await repo.start_turn("missing", content="hi", provider="ollama", model="llama")


async def test_recovery_marks_interrupted_and_preserves_content(database: Database) -> None:
    async with database.session_factory() as session:
        repo = ConversationRepository(session)
        conversation = await repo.create_conversation(title="Recovery")
        turn = await repo.start_turn(
            conversation.id, content="question", provider="ollama", model="llama"
        )
        await repo.update_message(
            turn.assistant_message.id,
            status=MessageStatus.STREAMING,
            content="partial answer",
        )
        await session.commit()
        conversation_id = conversation.id
        assistant_id = turn.assistant_message.id

    async with database.session_factory() as session:
        report = await ConversationRepository(session).recover_interrupted()
        await session.commit()
    assert report.messages_recovered == 1
    assert report.locks_cleared == 1

    async with database.session_factory() as session:
        repo = ConversationRepository(session)
        assistant = await repo.get_message(conversation_id, assistant_id)
        conversation = await repo.get_conversation(conversation_id)
        assert assistant is not None
        assert assistant.status == MessageStatus.FAILED.value
        assert assistant.error_code == "interrupted"
        assert assistant.content == "partial answer"
        assert conversation is not None
        assert conversation.active_generation_id is None


async def test_concurrent_turns_have_single_winner(database: Database) -> None:
    async with database.session_factory() as session:
        repo = ConversationRepository(session)
        conversation = await repo.create_conversation(title="Race")
        await session.commit()
        conversation_id = conversation.id

    async def attempt(content: str) -> str:
        async with database.session_factory() as session:
            repo = ConversationRepository(session)
            try:
                await repo.start_turn(
                    conversation_id, content=content, provider="ollama", model="llama"
                )
                await session.commit()
                return "started"
            except GenerationInProgress:
                await session.rollback()
                return "blocked"

    results = await asyncio.gather(attempt("a"), attempt("b"))
    assert sorted(results) == ["blocked", "started"]

    async with database.session_factory() as session:
        repo = ConversationRepository(session)
        assert await repo.count_messages(conversation_id) == 2


def _table_names(db_path: object) -> set[str]:
    with sqlite3.connect(str(db_path)) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {row[0] for row in rows}


def test_migration_0001_to_0002_preserves_system_state(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        env="test",
        data_dir=tmp_path / "migration",
        log_dir=tmp_path / "logs",
    )
    settings.ensure_directories()

    config = AlembicConfig()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", settings.resolved_database_url.replace("%", "%%"))

    command.upgrade(config, "0001_system_state")
    database_path = settings.database_path
    assert "conversations" not in _table_names(database_path)

    with sqlite3.connect(str(database_path)) as connection:
        connection.execute(
            "INSERT INTO system_state (key, value, updated_at) VALUES (?, ?, ?)",
            ("seed", "keep-me", "2026-11-18T00:00:00+00:00"),
        )
        connection.commit()

    command.upgrade(config, "head")
    tables = _table_names(database_path)
    assert {"conversations", "messages", "system_state"} <= tables

    with sqlite3.connect(str(database_path)) as connection:
        value = connection.execute("SELECT value FROM system_state WHERE key = 'seed'").fetchone()[
            0
        ]
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert value == "keep-me"
    assert version == "0002_conversations_messages"

    command.downgrade(config, "0001_system_state")
    assert "messages" not in _table_names(database_path)
    assert "conversations" not in _table_names(database_path)
    with sqlite3.connect(str(database_path)) as connection:
        preserved = connection.execute(
            "SELECT value FROM system_state WHERE key = 'seed'"
        ).fetchone()[0]
    assert preserved == "keep-me"


CONCURRENCY_REPEATS = 8


async def _attempt_turn(
    database: Database,
    conversation_id: str,
    *,
    content: str,
    client_message_id: str | None,
) -> tuple[str, str | None, str | None, bool | None]:
    async with database.session_factory() as session:
        repo = ConversationRepository(session)
        try:
            turn = await repo.start_turn(
                conversation_id,
                content=content,
                provider="ollama",
                model="llama",
                client_message_id=client_message_id,
            )
            await session.commit()
        except IdempotencyConflict:
            await session.rollback()
            return ("conflict", None, None, None)
        except GenerationInProgress:
            await session.rollback()
            return ("blocked", None, None, None)
        return ("ok", turn.user_message.id, turn.assistant_message.id, turn.replayed)


async def _new_conversation(database: Database, title: str) -> str:
    async with database.session_factory() as session:
        repo = ConversationRepository(session)
        conversation = await repo.create_conversation(title=title)
        await session.commit()
        return conversation.id


async def _count(database: Database, conversation_id: str) -> int:
    async with database.session_factory() as session:
        return await ConversationRepository(session).count_messages(conversation_id)


async def test_concurrent_same_key_same_content_is_single_turn(database: Database) -> None:
    for iteration in range(CONCURRENCY_REPEATS):
        conversation_id = await _new_conversation(database, f"same-content-{iteration}")
        results = await asyncio.gather(
            _attempt_turn(database, conversation_id, content="hello", client_message_id="same-key"),
            _attempt_turn(database, conversation_id, content="hello", client_message_id="same-key"),
        )

        assert [result[0] for result in results] == ["ok", "ok"], results
        assert results[0][1] is not None
        assert results[0][1] == results[1][1]
        assert results[0][2] is not None
        assert results[0][2] == results[1][2]
        assert {result[3] for result in results} == {True, False}
        assert await _count(database, conversation_id) == 2


async def test_concurrent_same_key_different_content_conflicts(database: Database) -> None:
    for iteration in range(CONCURRENCY_REPEATS):
        conversation_id = await _new_conversation(database, f"conflict-{iteration}")
        results = await asyncio.gather(
            _attempt_turn(
                database, conversation_id, content="original", client_message_id="race-key"
            ),
            _attempt_turn(
                database, conversation_id, content="changed", client_message_id="race-key"
            ),
        )

        statuses = sorted(result[0] for result in results)
        assert statuses == ["conflict", "ok"], results
        assert await _count(database, conversation_id) == 2

        async with database.session_factory() as session:
            user_message = await ConversationRepository(session).find_by_client_message_id(
                conversation_id, "race-key"
            )
        assert user_message is not None
        stored_content = user_message.content
        assert stored_content in {"original", "changed"}

        replay = await _attempt_turn(
            database, conversation_id, content=stored_content, client_message_id="race-key"
        )
        assert replay[0] == "ok"

        conflicting_content = "changed" if stored_content == "original" else "original"
        conflict = await _attempt_turn(
            database,
            conversation_id,
            content=conflicting_content,
            client_message_id="race-key",
        )
        assert conflict[0] == "conflict"
        assert await _count(database, conversation_id) == 2


async def test_concurrent_different_conversations_do_not_block(database: Database) -> None:
    for iteration in range(CONCURRENCY_REPEATS):
        first = await _new_conversation(database, f"parallel-a-{iteration}")
        second = await _new_conversation(database, f"parallel-b-{iteration}")

        results = await asyncio.gather(
            _attempt_turn(database, first, content="alpha", client_message_id="a-key"),
            _attempt_turn(database, second, content="beta", client_message_id="b-key"),
        )

        assert [result[0] for result in results] == ["ok", "ok"], results
        assert await _count(database, first) == 2
        assert await _count(database, second) == 2


async def test_finalize_message_is_a_no_op_after_the_terminal_write(database: Database) -> None:
    async with database.session_factory() as session:
        repo = ConversationRepository(session)
        conversation = await repo.create_conversation(title="Terminal once")
        turn = await repo.start_turn(
            conversation.id, content="question", provider="ollama", model="llama"
        )
        await session.commit()
        message_id = turn.assistant_message.id

        first = await repo.finalize_message(
            message_id,
            status=MessageStatus.COMPLETED,
            content="the answer",
            finish_reason="stop",
            prompt_tokens=4,
            completion_tokens=3,
            total_tokens=7,
        )
        await session.commit()
        assert first is not None
        assert first.status == MessageStatus.COMPLETED.value
        assert first.content == "the answer"
        assert first.total_tokens == 7

        # A late failure/cancellation must not demote a committed completion.
        second = await repo.finalize_message(
            message_id,
            status=MessageStatus.FAILED,
            content="overwritten?",
            error_code="provider_unavailable",
        )
        await session.commit()
        assert second is not None
        assert second.status == MessageStatus.COMPLETED.value
        assert second.content == "the answer"
        assert second.error_code is None
        assert second.total_tokens == 7

    async with database.session_factory() as session:
        stored = await session.get(Message, message_id)
    assert stored is not None
    assert stored.status == MessageStatus.COMPLETED.value
    assert stored.content == "the answer"


async def test_finalize_message_returns_none_for_a_missing_message(database: Database) -> None:
    async with database.session_factory() as session:
        repo = ConversationRepository(session)
        assert (
            await repo.finalize_message("missing-message", status=MessageStatus.CANCELLED) is None
        )
        await session.rollback()
