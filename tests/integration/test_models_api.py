"""Integration tests for model aggregation and default model selection."""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx

from orbit.chat.engine import ModelResolver
from orbit.conversations.repository import ConversationRepository
from orbit.providers.base import ModelInfo
from orbit.providers.errors import ProviderUnavailableError
from orbit.providers.registry import ProviderRegistry
from tests.fakes import FakeProvider
from tests.integration.test_providers_api import API_KEY, MODELS, override_registry


@asynccontextmanager
async def fake_ollama(app, *, model_ids: list[str] | None = None):
    provider = FakeProvider(id="ollama", model_ids=model_ids or ["llama3.2:latest"])
    original = app.state.providers
    app.state.providers = ProviderRegistry([provider])
    try:
        yield provider
    finally:
        app.state.providers = original
        await provider.aclose()


class UnavailableProvider(FakeProvider):
    async def list_models(self) -> list[ModelInfo]:
        self.list_calls += 1
        raise ProviderUnavailableError("provider is down", provider=self.id)


async def test_default_model_is_initially_unset(client) -> None:
    response = await client.get("/api/v1/models/default")
    assert response.status_code == 200
    assert response.json() is None


async def test_default_model_is_persisted(client, app) -> None:
    payload = {"provider": "ollama", "model": "llama3.2:latest"}

    async with fake_ollama(app):
        put = await client.put("/api/v1/models/default", json=payload)
        assert put.status_code == 200
        assert put.json() == payload

        get = await client.get("/api/v1/models/default")
    assert get.status_code == 200
    assert get.json() == payload


async def test_default_model_must_exist_in_provider_catalog(client, app) -> None:
    async with fake_ollama(app, model_ids=["llama3.2:latest"]):
        response = await client.put(
            "/api/v1/models/default", json={"provider": "ollama", "model": "ghost"}
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "model_not_found"
    assert (await client.get("/api/v1/models/default")).json() is None


async def test_default_model_survives_invalid_followup(client, app) -> None:
    valid = {"provider": "ollama", "model": "llama3.2:latest"}

    async with fake_ollama(app, model_ids=["llama3.2:latest"]):
        assert (await client.put("/api/v1/models/default", json=valid)).status_code == 200
        invalid = await client.put(
            "/api/v1/models/default", json={"provider": "ollama", "model": "ghost"}
        )
        assert invalid.status_code == 400
        assert (await client.get("/api/v1/models/default")).json() == valid


async def test_default_model_is_not_persisted_when_provider_is_unavailable(client, app) -> None:
    original = app.state.providers
    provider = UnavailableProvider(id="ollama")
    app.state.providers = ProviderRegistry([provider])
    try:
        response = await client.put(
            "/api/v1/models/default", json={"provider": "ollama", "model": "llama3.2:latest"}
        )
    finally:
        app.state.providers = original

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert (await client.get("/api/v1/models/default")).json() is None


async def test_default_validation_reuses_the_catalog_cache(client, app) -> None:
    async with fake_ollama(app, model_ids=["llama3.2:latest"]) as provider:
        for _ in range(2):
            response = await client.put(
                "/api/v1/models/default",
                json={"provider": "ollama", "model": "llama3.2:latest"},
            )
            assert response.status_code == 200
        assert provider.list_calls == 1


async def test_default_model_rejects_unknown_provider(client) -> None:
    response = await client.put("/api/v1/models/default", json={"provider": "nope", "model": "m"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_default_model_requires_configured_provider(client) -> None:
    response = await client.put(
        "/api/v1/models/default", json={"provider": "openrouter", "model": "a/b"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "provider_not_configured"


async def test_default_model_rejects_blank_model(client) -> None:
    response = await client.put("/api/v1/models/default", json={"provider": "ollama", "model": ""})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_aggregate_models_reports_partial_failures(client, app, settings) -> None:
    settings.openrouter_api_key = API_KEY
    settings.provider_max_attempts = 1

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/models":
            return httpx.Response(200, json=MODELS)
        return httpx.Response(500, json={"error": "ollama is down"})

    async with override_registry(app, settings, handler):
        response = await client.get("/api/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert len(body["models"]) == 2
    assert {item["provider"] for item in body["models"]} == {"openrouter"}
    assert body["errors"][0]["provider"] == "ollama"
    assert API_KEY not in response.text


async def test_aggregate_skips_unconfigured_providers(client, app, settings) -> None:
    settings.openrouter_api_key = None

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "llama", "model": "llama"}]})

    async with override_registry(app, settings, handler):
        response = await client.get("/api/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert [item["provider"] for item in body["models"]] == ["ollama"]
    assert body["errors"] == []


async def test_endpoint_and_resolver_share_the_catalog_cache(client, app) -> None:
    provider = FakeProvider(model_ids=["fake-model"])
    registry = ProviderRegistry([provider])
    original = app.state.providers
    app.state.providers = registry
    try:
        first = await client.get("/api/v1/providers/fake/models")
        second = await client.get("/api/v1/providers/fake/models")
        assert first.status_code == 200
        assert second.status_code == 200
        assert provider.list_calls == 1

        async with app.state.db.session_factory() as session:
            conversation = await ConversationRepository(session).create_conversation(
                provider="fake", model="fake-model"
            )
            await session.commit()

        resolver = ModelResolver(registry, app.state.db.session_factory)
        resolved = await resolver.resolve(conversation)
        assert resolved.model == "fake-model"
        assert provider.list_calls == 1
    finally:
        app.state.providers = original


async def test_aggregate_and_provider_endpoints_share_the_cache(client, app, settings) -> None:
    settings.openrouter_api_key = API_KEY
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/models":
            return httpx.Response(200, json=MODELS)
        return httpx.Response(200, json={"models": [{"name": "llama", "model": "llama"}]})

    async with override_registry(app, settings, handler):
        await client.get("/api/v1/providers/openrouter/models")
        await client.get("/api/v1/providers/openrouter/models")
        first_aggregate = await client.get("/api/v1/models")
        second_aggregate = await client.get("/api/v1/models")

    assert first_aggregate.status_code == 200
    assert second_aggregate.status_code == 200
    assert calls.count("/api/v1/models") == 1
    assert calls.count("/api/tags") == 1


async def test_connection_test_invalidates_the_provider_catalog(client, app, settings) -> None:
    settings.openrouter_api_key = API_KEY
    calls = {"models": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/models":
            calls["models"] += 1
            return httpx.Response(200, json=MODELS)
        return httpx.Response(500, json={"error": "down"})

    async with override_registry(app, settings, handler):
        await client.get("/api/v1/providers/openrouter/models")
        assert calls["models"] == 1

        test_response = await client.post("/api/v1/providers/openrouter/test")
        assert test_response.status_code == 200
        assert test_response.json()["ok"] is True
        assert calls["models"] == 2

        await client.get("/api/v1/providers/openrouter/models")
        assert calls["models"] == 3
