"""Ollama adapter tests against a mocked HTTP transport."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

from orbit.providers.base import ChatMessage, CompletionRequest, Role
from orbit.providers.errors import (
    ProviderInvalidResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from orbit.providers.ollama import OllamaProvider

Handler = Callable[[httpx.Request], httpx.Response]


class FailingStream(httpx.AsyncByteStream):
    """Yield chunks, then fail like a dropped upstream connection."""

    def __init__(self, chunks: list[bytes], error: Exception) -> None:
        self._chunks = chunks
        self._error = error
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk
        raise self._error

    async def aclose(self) -> None:
        self.closed = True


class BlockingStream(httpx.AsyncByteStream):
    """Yield one chunk and then wait forever, for cancellation tests."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"message":{"content":"Hi"},"done":false}\n'
        self.started.set()
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed = True


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


async def test_stream_timeout_before_first_chunk_is_normalised(make_provider) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    provider = make_provider(handler)
    with pytest.raises(ProviderTimeoutError):
        await anext(provider.stream(_request()))


async def test_stream_timeout_after_chunks_preserves_previous_output(make_provider) -> None:
    stream = FailingStream(
        [b'{"message":{"content":"Hel"},"done":false}\n'],
        httpx.ReadTimeout("read timed out"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    provider = make_provider(handler)
    iterator = provider.stream(_request())
    first = await anext(iterator)
    assert first.delta == "Hel"

    with pytest.raises(ProviderTimeoutError):
        await anext(iterator)
    assert stream.closed is True


async def test_stream_connection_loss_is_normalised(make_provider) -> None:
    stream = FailingStream(
        [b'{"message":{"content":"Hel"},"done":false}\n'],
        httpx.ReadError("connection reset"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    provider = make_provider(handler)
    with pytest.raises(ProviderUnavailableError) as excinfo:
        [chunk async for chunk in provider.stream(_request())]

    assert excinfo.value.code == "provider_unavailable"
    assert stream.closed is True


async def test_stream_http_error_keeps_normalised_status(make_provider) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "upstream down"})

    provider = make_provider(handler)
    with pytest.raises(ProviderUnavailableError) as excinfo:
        await anext(provider.stream(_request()))

    assert excinfo.value.code == "provider_unavailable"


async def test_stream_cancellation_is_not_converted(make_provider) -> None:
    stream = BlockingStream()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    provider = make_provider(handler)

    async def drain() -> None:
        async for _ in provider.stream(_request()):
            pass

    task = asyncio.create_task(drain())
    await asyncio.wait_for(stream.started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


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
