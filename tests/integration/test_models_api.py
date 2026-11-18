"""Integration tests for model aggregation and default model selection."""

from __future__ import annotations

import httpx

from tests.integration.test_providers_api import API_KEY, MODELS, override_registry


async def test_default_model_is_initially_unset(client) -> None:
    response = await client.get("/api/v1/models/default")
    assert response.status_code == 200
    assert response.json() is None


async def test_default_model_is_persisted(client) -> None:
    payload = {"provider": "ollama", "model": "llama3.2:latest"}

    put = await client.put("/api/v1/models/default", json=payload)
    assert put.status_code == 200
    assert put.json() == payload

    get = await client.get("/api/v1/models/default")
    assert get.status_code == 200
    assert get.json() == payload


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
