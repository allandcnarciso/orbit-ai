"""Integration tests for provider discovery and connection endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx

from orbit.providers.registry import build_registry

API_KEY = "s" + "k-" + "or-v1-" + "integration0123456789abcdef"
Handler = Callable[[httpx.Request], httpx.Response]

MODELS = {
    "data": [
        {
            "id": "openai/gpt-x",
            "name": "GPT X",
            "context_length": 4096,
            "pricing": {"prompt": "0.000001", "completion": "0.000003"},
        },
        {"id": "meta/llama-y", "name": "Llama Y"},
    ]
}


@asynccontextmanager
async def override_registry(app, settings, handler: Handler) -> AsyncIterator[None]:
    original = app.state.providers
    registry = build_registry(settings, transport=httpx.MockTransport(handler))
    app.state.providers = registry
    try:
        yield
    finally:
        await registry.aclose()
        app.state.providers = original


async def test_providers_are_listed_with_status(client, app) -> None:
    response = await client.get("/api/v1/providers")
    assert response.status_code == 200
    providers = {item["id"]: item for item in response.json()}

    assert set(providers) == {"openrouter", "ollama"}
    assert providers["openrouter"]["configured"] is False
    assert providers["ollama"]["configured"] is True
    assert providers["openrouter"]["capabilities"]["streaming"] is True


async def test_unknown_provider_returns_envelope(client) -> None:
    response = await client.get("/api/v1/providers/nope/models")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"


async def test_models_require_configuration(client) -> None:
    response = await client.get("/api/v1/providers/openrouter/models")
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "provider_not_configured"
    assert "key" in body["error"]["message"].lower()


async def test_model_discovery_with_mock_transport(client, app, settings) -> None:
    settings.openrouter_api_key = API_KEY

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/models"
        return httpx.Response(200, json=MODELS)

    async with override_registry(app, settings, handler):
        response = await client.get("/api/v1/providers/openrouter/models")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "openrouter"
    assert body["count"] == 2
    models = {item["id"]: item for item in body["models"]}
    assert models["openai/gpt-x"]["prompt_price"] == 0.000001
    assert models["openai/gpt-x"]["context_length"] == 4096
    assert API_KEY not in response.text


async def test_connection_test_endpoint(client, app, settings) -> None:
    settings.openrouter_api_key = API_KEY

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=MODELS)

    async with override_registry(app, settings, handler):
        response = await client.post("/api/v1/providers/openrouter/test")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "openrouter"
    assert body["ok"] is True
    assert body["model_count"] == 2


async def test_upstream_auth_failure_is_mapped_without_leaking_key(client, app, settings) -> None:
    settings.openrouter_api_key = API_KEY

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "No auth credentials found"}})

    async with override_registry(app, settings, handler):
        response = await client.get("/api/v1/providers/openrouter/models")

    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "provider_auth_error"
    assert API_KEY not in response.text
    assert body["error"]["request_id"] == response.headers["x-request-id"]


async def test_unreachable_ollama_reports_not_ok(client, app, settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with override_registry(app, settings, handler):
        response = await client.post("/api/v1/providers/ollama/test")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "Could not reach ollama" in body["detail"]
    assert "refused" not in body["detail"].lower()
