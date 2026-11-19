"""Model resolution priority, validation and discovery caching."""

from __future__ import annotations

import json

import pytest

from orbit.chat.engine import ModelResolver
from orbit.conversations.errors import InvalidSelection, ModelNotAvailable, NoModelSelected
from orbit.conversations.repository import ConversationRepository
from orbit.providers.errors import ProviderNotConfigured
from orbit.providers.registry import ProviderRegistry
from orbit.storage.db import Database
from orbit.storage.models import Conversation
from orbit.storage.system_state import SystemStateStore
from tests.fakes import FakeProvider


async def _conversation(
    database: Database, *, provider: str | None = None, model: str | None = None
) -> Conversation:
    async with database.session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(
            title="resolver", provider=provider, model=model
        )
        await session.commit()
        return conversation


async def _set_default(database: Database, provider: str, model: str) -> None:
    await SystemStateStore(database.session_factory).set(
        "default_model", json.dumps({"provider": provider, "model": model})
    )


async def test_resolution_priority_request_conversation_default(database: Database) -> None:
    provider = FakeProvider(model_ids=["fake-model", "conv-model", "req-model"])
    resolver = ModelResolver(ProviderRegistry([provider]), database.session_factory)
    conversation = await _conversation(database, provider="fake", model="conv-model")
    await _set_default(database, "fake", "fake-model")

    explicit = await resolver.resolve(conversation, provider="fake", model="req-model")
    assert explicit.model == "req-model"

    from_conversation = await resolver.resolve(conversation)
    assert from_conversation.model == "conv-model"

    empty = await _conversation(database)
    from_default = await resolver.resolve(empty)
    assert from_default.model == "fake-model"


async def test_provider_only_inherits_default_for_same_provider(database: Database) -> None:
    provider = FakeProvider(model_ids=["fake-model"])
    resolver = ModelResolver(ProviderRegistry([provider]), database.session_factory)
    conversation = await _conversation(database, provider="fake")
    await _set_default(database, "fake", "fake-model")

    resolved = await resolver.resolve(conversation)
    assert resolved.provider_id == "fake"
    assert resolved.model == "fake-model"


async def test_provider_only_rejects_default_from_another_provider(database: Database) -> None:
    resolver = ModelResolver(ProviderRegistry([FakeProvider()]), database.session_factory)
    conversation = await _conversation(database, provider="fake")
    await _set_default(database, "other", "other-model")

    with pytest.raises(NoModelSelected):
        await resolver.resolve(conversation)


async def test_provider_only_without_compatible_default_is_rejected(database: Database) -> None:
    resolver = ModelResolver(ProviderRegistry([FakeProvider()]), database.session_factory)
    conversation = await _conversation(database, provider="fake")

    with pytest.raises(NoModelSelected):
        await resolver.resolve(conversation)


async def test_provider_only_rejects_missing_default_model(database: Database) -> None:
    resolver = ModelResolver(ProviderRegistry([FakeProvider()]), database.session_factory)
    conversation = await _conversation(database, provider="fake")
    await _set_default(database, "fake", "ghost")

    with pytest.raises(ModelNotAvailable):
        await resolver.resolve(conversation)


async def test_discovery_is_cached(database: Database) -> None:
    provider = FakeProvider()
    resolver = ModelResolver(ProviderRegistry([provider]), database.session_factory)
    conversation = await _conversation(database, provider="fake", model="fake-model")

    await resolver.resolve(conversation)
    await resolver.resolve(conversation)
    assert provider.list_calls == 1


async def test_missing_selection(database: Database) -> None:
    resolver = ModelResolver(ProviderRegistry([FakeProvider()]), database.session_factory)
    conversation = await _conversation(database)
    with pytest.raises(NoModelSelected):
        await resolver.resolve(conversation)


async def test_unknown_provider(database: Database) -> None:
    resolver = ModelResolver(ProviderRegistry([FakeProvider()]), database.session_factory)
    conversation = await _conversation(database, provider="nope", model="fake-model")
    with pytest.raises(InvalidSelection):
        await resolver.resolve(conversation)


async def test_unconfigured_provider(database: Database) -> None:
    provider = FakeProvider(configured_flag=False)
    resolver = ModelResolver(ProviderRegistry([provider]), database.session_factory)
    conversation = await _conversation(database, provider="fake", model="fake-model")
    with pytest.raises(ProviderNotConfigured):
        await resolver.resolve(conversation)


async def test_model_not_in_discovery(database: Database) -> None:
    resolver = ModelResolver(ProviderRegistry([FakeProvider()]), database.session_factory)
    conversation = await _conversation(database, provider="fake", model="ghost")
    with pytest.raises(ModelNotAvailable):
        await resolver.resolve(conversation)
