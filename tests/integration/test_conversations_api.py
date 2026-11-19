"""Integration tests for the conversation REST API."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from asgi_lifespan import LifespanManager

from orbit.api.app import create_app
from orbit.conversations.enums import MessageRole, MessageStatus
from orbit.conversations.repository import ConversationRepository
from orbit.core.config import Settings
from orbit.providers.registry import ProviderRegistry
from orbit.storage.db import Database, run_migrations
from orbit.storage.models import Conversation, Message
from tests.fakes import FakeProvider

BASE = "/api/v1/conversations"


@asynccontextmanager
async def fake_provider_registry(app, *, model_ids: list[str] | None = None):
    """Swap the app registry for a deterministic fake Ollama provider."""
    provider = FakeProvider(id="ollama", model_ids=model_ids or ["llama3.2:latest"])
    original = app.state.providers
    app.state.providers = ProviderRegistry([provider])
    try:
        yield provider
    finally:
        app.state.providers = original
        await provider.aclose()


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0
    return parsed


async def _create(client: httpx.AsyncClient, **payload: object) -> dict[str, object]:
    response = await client.post(BASE, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_conversation_defaults_and_timestamps(client: httpx.AsyncClient) -> None:
    body = await _create(client, title="  My   chat  ")

    assert body["title"] == "My chat"
    assert body["status"] == "active"
    assert body["provider"] is None
    assert body["model"] is None
    assert body["last_message_at"] is None
    _parse_utc(str(body["created_at"]))
    _parse_utc(str(body["updated_at"]))


async def test_create_conversation_rejects_blank_title(client: httpx.AsyncClient) -> None:
    response = await client.post(BASE, json={"title": "   "})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_create_conversation_rejects_long_title(client: httpx.AsyncClient) -> None:
    response = await client.post(BASE, json={"title": "x" * 201})
    assert response.status_code == 422


async def test_create_conversation_validates_selection(client: httpx.AsyncClient, app) -> None:
    unknown = await client.post(BASE, json={"provider": "nope", "model": "m"})
    assert unknown.status_code == 400
    assert unknown.json()["error"]["code"] == "invalid_selection"

    orphan_model = await client.post(BASE, json={"model": "m"})
    assert orphan_model.status_code == 400
    assert orphan_model.json()["error"]["code"] == "invalid_selection"

    async with fake_provider_registry(app):
        valid = await _create(client, provider="ollama", model="llama3.2:latest")
    assert valid["provider"] == "ollama"


async def test_list_conversations_pagination(client: httpx.AsyncClient) -> None:
    created = [await _create(client, title=f"chat {index}") for index in range(3)]

    first_page = await client.get(BASE, params={"limit": 2, "offset": 0})
    assert first_page.status_code == 200
    body = first_page.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["items"]) == 2

    second_page = await client.get(BASE, params={"limit": 2, "offset": 2})
    assert len(second_page.json()["items"]) == 1

    seen = {item["id"] for item in body["items"]} | {
        item["id"] for item in second_page.json()["items"]
    }
    assert seen == {item["id"] for item in created}

    invalid = await client.get(BASE, params={"limit": 0})
    assert invalid.status_code == 422


async def test_list_conversations_filters_by_status(client: httpx.AsyncClient) -> None:
    active = await _create(client, title="active chat")
    archived = await _create(client, title="archived chat")
    patch = await client.patch(f"{BASE}/{archived['id']}", json={"status": "archived"})
    assert patch.status_code == 200

    response = await client.get(BASE, params={"status": "active"})
    assert [item["id"] for item in response.json()["items"]] == [active["id"]]

    response = await client.get(BASE, params={"status": "archived"})
    assert [item["id"] for item in response.json()["items"]] == [archived["id"]]


async def test_get_conversation_and_not_found(client: httpx.AsyncClient) -> None:
    created = await _create(client, title="fetch me")
    response = await client.get(f"{BASE}/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]

    missing = await client.get(f"{BASE}/does-not-exist")
    assert missing.status_code == 404
    body = missing.json()
    assert body["error"]["code"] == "conversation_not_found"
    assert body["error"]["request_id"] == missing.headers["x-request-id"]


async def test_rename_and_selection_update(client: httpx.AsyncClient, app) -> None:
    async with fake_provider_registry(app):
        created = await _create(client, provider="ollama", model="llama3.2:latest")

        renamed = await client.patch(f"{BASE}/{created['id']}", json={"title": "Renamed chat"})
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Renamed chat"

        cleared = await client.patch(f"{BASE}/{created['id']}", json={"provider": None})
        assert cleared.status_code == 200
        assert cleared.json()["provider"] is None
        assert cleared.json()["model"] is None

        invalid_model = await client.patch(
            f"{BASE}/{created['id']}", json={"model": "llama3.2:latest"}
        )
        assert invalid_model.status_code == 400
        assert invalid_model.json()["error"]["code"] == "invalid_selection"

        unknown_provider = await client.patch(f"{BASE}/{created['id']}", json={"provider": "nope"})
        assert unknown_provider.status_code == 400

        empty = await client.patch(f"{BASE}/{created['id']}", json={})
        assert empty.status_code == 422

        blank = await client.patch(f"{BASE}/{created['id']}", json={"title": "  "})
        assert blank.status_code == 422


async def test_create_rejects_unknown_model_without_persisting(client, app) -> None:
    async with fake_provider_registry(app, model_ids=["known"]):
        response = await client.post(BASE, json={"provider": "ollama", "model": "ghost"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "model_not_found"
        listing = await client.get(BASE)
    assert listing.json()["total"] == 0


async def test_selection_validation_uses_the_shared_cache(client, app) -> None:
    async with fake_provider_registry(app, model_ids=["known"]) as provider:
        created = await _create(client, provider="ollama", model="known")
        assert provider.list_calls == 1

        same = await client.patch(f"{BASE}/{created['id']}", json={"model": "known"})
        assert same.status_code == 200
        assert provider.list_calls == 1


async def test_partial_provider_and_model_updates_remain_consistent(client, app) -> None:
    first = FakeProvider(id="one", model_ids=["a", "b"])
    second = FakeProvider(id="two", model_ids=["a"])
    original = app.state.providers
    app.state.providers = ProviderRegistry([first, second])
    try:
        created = await _create(client, provider="one", model="a")

        model_only = await client.patch(f"{BASE}/{created['id']}", json={"model": "b"})
        assert model_only.status_code == 200
        assert model_only.json()["model"] == "b"

        incompatible = await client.patch(f"{BASE}/{created['id']}", json={"provider": "two"})
        assert incompatible.status_code == 400
        assert incompatible.json()["error"]["code"] == "model_not_found"

        unchanged = await client.get(f"{BASE}/{created['id']}")
        assert unchanged.json()["provider"] == "one"
        assert unchanged.json()["model"] == "b"

        second_conversation = await _create(client, provider="one", model="a")
        provider_only = await client.patch(
            f"{BASE}/{second_conversation['id']}", json={"provider": "two"}
        )
        assert provider_only.status_code == 200
        assert provider_only.json()["provider"] == "two"
        assert provider_only.json()["model"] == "a"

        inheriting = await _create(client, title="inherits")
        provider_for_inheritance = await client.patch(
            f"{BASE}/{inheriting['id']}", json={"provider": "one"}
        )
        assert provider_for_inheritance.status_code == 200
        assert provider_for_inheritance.json()["provider"] == "one"
        assert provider_for_inheritance.json()["model"] is None
    finally:
        app.state.providers = original


async def test_failed_update_preserves_previous_configuration(client, app) -> None:
    async with fake_provider_registry(app, model_ids=["known"]):
        created = await _create(client, provider="ollama", model="known")

        failed = await client.patch(
            f"{BASE}/{created['id']}", json={"title": "Should not persist", "model": "ghost"}
        )
        assert failed.status_code == 400
        assert failed.json()["error"]["code"] == "model_not_found"

        current = await client.get(f"{BASE}/{created['id']}")
        assert current.json()["title"] != "Should not persist"
        assert current.json()["provider"] == "ollama"
        assert current.json()["model"] == "known"


async def test_archive_transitions(client: httpx.AsyncClient) -> None:
    created = await _create(client)

    archived = await client.patch(f"{BASE}/{created['id']}", json={"status": "archived"})
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    again = await client.patch(f"{BASE}/{created['id']}", json={"status": "archived"})
    assert again.status_code == 200
    assert again.json()["status"] == "archived"

    reactivate = await client.patch(f"{BASE}/{created['id']}", json={"status": "active"})
    assert reactivate.status_code == 409
    assert reactivate.json()["error"]["code"] == "invalid_status_transition"

    invalid = await client.patch(f"{BASE}/{created['id']}", json={"status": "deleted"})
    assert invalid.status_code == 422


async def test_delete_conversation_cascades_messages(client: httpx.AsyncClient, app) -> None:
    created = await _create(client, title="delete me")
    conversation_id = str(created["id"])

    async with app.state.db.session_factory() as session:
        repo = ConversationRepository(session)
        await repo.start_turn(conversation_id, content="hello", provider="ollama", model="llama")
        await session.commit()

    response = await client.delete(f"{BASE}/{conversation_id}")
    assert response.status_code == 204
    assert response.content == b""

    async with app.state.db.session_factory() as session:
        repo = ConversationRepository(session)
        assert await repo.count_messages(conversation_id) == 0
        assert await repo.get_conversation(conversation_id) is None

    again = await client.delete(f"{BASE}/{conversation_id}")
    assert again.status_code == 404
    assert again.json()["error"]["code"] == "conversation_not_found"


async def test_message_history_ordering_and_pagination(client: httpx.AsyncClient, app) -> None:
    created = await _create(client, title="history")
    conversation_id = str(created["id"])

    async with app.state.db.session_factory() as session:
        repo = ConversationRepository(session)
        conversation = await repo.get_conversation(conversation_id)
        assert conversation is not None
        for index in range(1, 4):
            await repo.add_message(
                conversation_id,
                role=MessageRole.USER if index % 2 else MessageRole.ASSISTANT,
                content=f"message {index}",
                status=MessageStatus.COMPLETED,
            )
        await session.commit()

    response = await client.get(f"{BASE}/{conversation_id}/messages")
    assert response.status_code == 200
    body = response.json()
    assert [item["sequence"] for item in body["items"]] == [1, 2, 3]
    assert body["has_more"] is False
    assert body["next_before_sequence"] is None
    _parse_utc(body["items"][0]["created_at"])

    page = await client.get(
        f"{BASE}/{conversation_id}/messages", params={"limit": 2, "before_sequence": 3}
    )
    assert [item["sequence"] for item in page.json()["items"]] == [1, 2]

    last_two = await client.get(f"{BASE}/{conversation_id}/messages", params={"limit": 2})
    assert [item["sequence"] for item in last_two.json()["items"]] == [2, 3]
    assert last_two.json()["has_more"] is True
    assert last_two.json()["next_before_sequence"] == 2

    conversation = await client.get(f"{BASE}/{conversation_id}")
    _parse_utc(conversation.json()["last_message_at"])


async def test_message_isolation_between_conversations(client: httpx.AsyncClient, app) -> None:
    first = await _create(client, title="first")
    second = await _create(client, title="second")

    async with app.state.db.session_factory() as session:
        repo = ConversationRepository(session)
        await repo.add_message(
            str(first["id"]),
            role=MessageRole.USER,
            content="only in first",
            status=MessageStatus.COMPLETED,
        )
        await repo.add_message(
            str(second["id"]),
            role=MessageRole.USER,
            content="only in second",
            status=MessageStatus.COMPLETED,
        )
        await session.commit()

    first_messages = await client.get(f"{BASE}/{first['id']}/messages")
    second_messages = await client.get(f"{BASE}/{second['id']}/messages")

    assert [item["content"] for item in first_messages.json()["items"]] == ["only in first"]
    assert [item["content"] for item in second_messages.json()["items"]] == ["only in second"]
    assert first_messages.json()["items"][0]["conversation_id"] == first["id"]


async def test_messages_unknown_conversation(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{BASE}/missing/messages")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "conversation_not_found"


async def test_startup_recovery_marks_interrupted_and_is_idempotent(settings: Settings) -> None:
    settings.ensure_directories()
    await asyncio.to_thread(run_migrations, settings)

    seed = Database(settings)
    async with seed.session_factory() as session:
        repo = ConversationRepository(session)
        conversation = await repo.create_conversation(title="recover")
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
        user_id = turn.user_message.id
    await seed.dispose()

    application = create_app(settings)
    async with (
        LifespanManager(application),
        application.state.db.session_factory() as session,
    ):
        assistant = await session.get(Message, assistant_id)
        user = await session.get(Message, user_id)
        stored = await session.get(Conversation, conversation_id)
        assert assistant is not None and user is not None and stored is not None
        assert assistant.status == MessageStatus.FAILED.value
        assert assistant.error_code == "interrupted"
        assert assistant.content == "partial answer"
        assert user.status == MessageStatus.COMPLETED.value
        assert stored.active_generation_id is None
        recovered_at = assistant.updated_at

    # A second startup has nothing left to recover and must not rewrite the record.
    second = create_app(settings)
    async with (
        LifespanManager(second),
        second.state.db.session_factory() as session,
    ):
        again = await session.get(Message, assistant_id)
        assert again is not None
        assert again.status == MessageStatus.FAILED.value
        assert again.updated_at == recovered_at


async def test_pagination_and_path_boundaries(client: httpx.AsyncClient) -> None:
    created = await _create(client)

    negative_offset = await client.get(BASE, params={"offset": -1})
    assert negative_offset.status_code == 422

    invalid_cursor = await client.get(
        f"{BASE}/{created['id']}/messages", params={"before_sequence": 0}
    )
    assert invalid_cursor.status_code == 422

    oversized_limit = await client.get(f"{BASE}/{created['id']}/messages", params={"limit": 500})
    assert oversized_limit.status_code == 422

    oversized_id = await client.get(f"{BASE}/{'x' * 100}")
    assert oversized_id.status_code == 422
    assert oversized_id.json()["error"]["code"] == "validation_error"
