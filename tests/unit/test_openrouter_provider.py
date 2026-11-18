"""OpenRouter adapter tests against a mocked HTTP transport."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from orbit.providers.base import ChatMessage, CompletionRequest, Role
from orbit.providers.errors import (
    ProviderAuthenticationError,
    ProviderInvalidResponseError,
    ProviderNotConfigured,
    ProviderTimeoutError,
)
from orbit.providers.openrouter import OpenRouterProvider

API_KEY = "s" + "k-" + "or-v1-" + "testkey0123456789abcdef"

MODELS = {
    "data": [
        {
            "id": "z-ai/model-z",
            "name": "Model Z",
            "context_length": 8192,
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
        },
        {"id": "a-ai/model-a"},
        "not-a-model",
    ]
}

COMPLETION = {
    "model": "a-ai/model-a",
    "choices": [{"message": {"role": "assistant", "content": "Hello"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
}

SSE_BODY = (
    'data: {"model":"m","choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
    'data: {"model":"m","choices":[{"delta":{"content":"Hel"},"finish_reason":null}]}\n\n'
    ": keep-alive comment\n\n"
    "data: this-is-not-json\n\n"
    'data: {"model":"m","choices":[{"delta":{"content":"lo"},"finish_reason":null}]}\n\n'
    'data: {"model":"m","choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
    "data: [DONE]\n\n"
)


Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
async def make_provider() -> AsyncIterator[Callable[..., OpenRouterProvider]]:
    clients: list[httpx.AsyncClient] = []

    def factory(
        handler: Handler, *, key: str | None = API_KEY, attempts: int = 1, backoff: float = 0.0
    ) -> OpenRouterProvider:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5)
        clients.append(client)
        return OpenRouterProvider(
            api_key=SecretStr(key) if key else None,
            base_url="https://openrouter.test/api/v1",
            timeout=5,
            retry_attempts=attempts,
            retry_backoff=backoff,
            client=client,
        )

    yield factory
    for client in clients:
        await client.aclose()


def _request() -> CompletionRequest:
    return CompletionRequest(
        model="a-ai/model-a",
        messages=(ChatMessage(role=Role.USER, content="Hi"),),
    )


async def test_unconfigured_provider_is_reported(make_provider) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no network call expected without a key")

    provider = make_provider(handler, key=None)
    assert provider.configured is False

    with pytest.raises(ProviderNotConfigured):
        await provider.list_models()

    result = await provider.test_connection()
    assert result.ok is False
    assert result.detail is not None
    assert "not configured" in result.detail


async def test_list_models_parses_and_sorts(make_provider) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/models"
        assert request.headers["authorization"] == "Bearer " + API_KEY
        return httpx.Response(200, json=MODELS)

    provider = make_provider(handler)
    models = await provider.list_models()
    assert [model.id for model in models] == ["a-ai/model-a", "z-ai/model-z"]
    rich = models[1]
    assert rich.name == "Model Z"
    assert rich.context_length == 8192
    assert rich.prompt_price == pytest.approx(0.000001)
    assert models[0].name == "a-ai/model-a"


async def test_complete_parses_content_and_usage(make_provider) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json=COMPLETION)

    provider = make_provider(handler)
    result = await provider.complete(_request())

    assert result.content == "Hello"
    assert result.finish_reason == "stop"
    assert result.usage is not None
    assert result.usage.total_tokens == 8
    assert captured["stream"] is False
    assert captured["model"] == "a-ai/model-a"
    assert captured["messages"] == [{"role": "user", "content": "Hi"}]


async def test_complete_rejects_malformed_payload(make_provider) -> None:
    provider = make_provider(lambda request: httpx.Response(200, json={"choices": []}))
    with pytest.raises(ProviderInvalidResponseError):
        await provider.complete(_request())


async def test_stream_parses_sse_and_ignores_noise(make_provider) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=SSE_BODY.encode(),
        )

    provider = make_provider(handler)
    chunks = [chunk async for chunk in provider.stream(_request())]

    assert "".join(chunk.delta for chunk in chunks) == "Hello"
    assert chunks[-1].finish_reason == "stop"
    assert captured["stream"] is True


async def test_retries_transient_status_then_succeeds(make_provider) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, json={"error": {"message": "slow down"}})
        return httpx.Response(200, json=MODELS)

    provider = make_provider(handler, attempts=2)
    models = await provider.list_models()
    assert calls["count"] == 2
    assert len(models) == 2


async def test_final_rate_limit_is_raised(make_provider) -> None:
    from orbit.providers.errors import ProviderRateLimitError

    provider = make_provider(
        lambda request: httpx.Response(429, json={"error": {"message": "slow down"}})
    )
    with pytest.raises(ProviderRateLimitError) as excinfo:
        await provider.list_models()
    assert excinfo.value.retryable is True


async def test_auth_error_does_not_leak_key(make_provider) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Invalid API key"}})

    provider = make_provider(handler)
    with pytest.raises(ProviderAuthenticationError) as excinfo:
        await provider.list_models()

    message = str(excinfo.value)
    assert "Invalid API key" in message
    assert API_KEY not in message


async def test_timeout_is_normalised(make_provider) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    provider = make_provider(handler)
    with pytest.raises(ProviderTimeoutError):
        await provider.list_models()


async def test_test_connection_reports_model_count(make_provider) -> None:
    provider = make_provider(lambda request: httpx.Response(200, json=MODELS))
    result = await provider.test_connection()
    assert result.ok is True
    assert result.model_count == 2
    assert result.latency_ms >= 0
