"""Ollama adapter tests against a mocked HTTP transport."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

from orbit.providers.base import ChatMessage, CompletionRequest, Role
from orbit.providers.errors import ProviderInvalidResponseError, ProviderUnavailableError
from orbit.providers.ollama import OllamaProvider

Handler = Callable[[httpx.Request], httpx.Response]

TAGS = {
    "models": [
        {
            "name": "qwen2.5:7b",
            "model": "qwen2.5:7b",
            "size": 4683087265,
            "details": {
                "parameter_size": "7.6B",
                "family": "qwen2",
                "quantization_level": "Q4_K_M",
            },
        },
        {"name": "llama3.2:latest", "size": 2019393189},
    ]
}

COMPLETION = {
    "model": "llama3.2:latest",
    "message": {"role": "assistant", "content": "Hi there"},
    "done": True,
    "prompt_eval_count": 10,
    "eval_count": 4,
}

NDJSON = "\n".join(
    [
        json.dumps({"model": "m", "message": {"content": "Hel"}, "done": False}),
        '{"model": "m", "message": {"content": "lo"}, "done": false}',
        "not json at all",
        json.dumps(
            {
                "model": "m",
                "message": {"content": ""},
                "done": True,
                "prompt_eval_count": 2,
                "eval_count": 2,
            }
        ),
    ]
)


@pytest.fixture
async def make_provider() -> AsyncIterator[Callable[..., OllamaProvider]]:
    clients: list[httpx.AsyncClient] = []

    def factory(handler: Handler, *, attempts: int = 1) -> OllamaProvider:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5)
        clients.append(client)
        return OllamaProvider(
            base_url="http://ollama.test:11434",
            timeout=5,
            retry_attempts=attempts,
            retry_backoff=0.0,
            client=client,
        )

    yield factory
    for client in clients:
        await client.aclose()


def _request() -> CompletionRequest:
    return CompletionRequest(
        model="llama3.2:latest",
        messages=(ChatMessage(role=Role.USER, content="Hi"),),
        temperature=0.2,
        max_tokens=64,
    )


async def test_list_models_parses_details(make_provider) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json=TAGS)

    provider = make_provider(handler)
    models = await provider.list_models()

    assert [model.id for model in models] == ["llama3.2:latest", "qwen2.5:7b"]
    qwen = models[1]
    assert qwen.metadata["parameter_size"] == "7.6B"
    assert qwen.metadata["size_bytes"] == 4683087265


async def test_complete_maps_options_and_usage(make_provider) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=COMPLETION)

    provider = make_provider(handler)
    result = await provider.complete(_request())

    assert result.content == "Hi there"
    assert result.finish_reason == "stop"
    assert result.usage is not None
    assert result.usage.total_tokens == 14
    assert captured["stream"] is False
    assert captured["options"] == {"temperature": 0.2, "num_predict": 64}


async def test_stream_parses_ndjson(make_provider) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=NDJSON.encode())

    provider = make_provider(handler)
    chunks = [chunk async for chunk in provider.stream(_request())]

    assert "".join(chunk.delta for chunk in chunks) == "Hello"
    assert chunks[-1].finish_reason == "stop"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 4


async def test_unreachable_daemon_is_normalised(make_provider) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = make_provider(handler)
    with pytest.raises(ProviderUnavailableError):
        await provider.list_models()


async def test_malformed_tag_list_is_rejected(make_provider) -> None:
    provider = make_provider(lambda request: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(ProviderInvalidResponseError):
        await provider.list_models()
