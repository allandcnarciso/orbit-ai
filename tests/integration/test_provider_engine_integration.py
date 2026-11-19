"""Engine-level integration against OpenRouter and Ollama adapters (mocked HTTP)."""

from __future__ import annotations

import json

import httpx
from pydantic import SecretStr

from orbit.chat.engine import ConversationEngine
from orbit.conversations.repository import ConversationRepository
from orbit.providers.ollama import OllamaProvider
from orbit.providers.openrouter import OpenRouterProvider
from orbit.providers.registry import ProviderRegistry
from orbit.storage.models import Conversation

BASE = "/api/v1/conversations"
FAKE_KEY = "s" + "k-" + "or-v1-" + "test-only-key"

OPENROUTER_SSE = (
    'data: {"choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
    'data: {"choices":[{"delta":{"content":"Hel"},"finish_reason":null}]}\n\n'
    'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}]}\n\n'
    "data: [DONE]\n\n"
)

OLLAMA_NDJSON = (
    '{"model":"llama3.2:latest","message":{"role":"assistant","content":"Ol"},"done":false}\n'
    '{"model":"llama3.2:latest","message":{"role":"assistant","content":"la"},"done":false}\n'
    '{"model":"llama3.2:latest","message":{"role":"assistant","content":""},"done":true,'
    '"prompt_eval_count":5,"eval_count":2}\n'
)


def _install(app, handler) -> tuple[httpx.AsyncClient, ProviderRegistry]:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    registry = ProviderRegistry(
        [
            OpenRouterProvider(
                api_key=SecretStr(FAKE_KEY),
                base_url="https://openrouter.test/api/v1",
                timeout=5,
                retry_attempts=1,
                retry_backoff=0,
                client=client,
            ),
            OllamaProvider(
                base_url="http://ollama.test",
                timeout=5,
                retry_attempts=1,
                retry_backoff=0,
                client=client,
            ),
        ]
    )
    app.state.providers = registry
    app.state.engine = ConversationEngine(app.state.db.session_factory, registry)
    return client, registry


def _openrouter_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/models"):
        return httpx.Response(
            200,
            json={"data": [{"id": "test/model", "name": "Test Model", "context_length": 8192}]},
        )
    payload = json.loads(request.content or b"{}")
    if payload.get("stream"):
        return httpx.Response(
            200,
            content=OPENROUTER_SSE.encode(),
            headers={"content-type": "text/event-stream"},
        )
    return httpx.Response(
        200,
        json={
            "model": "test/model",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "OpenRouter reply"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        },
    )


def _ollama_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/tags":
        return httpx.Response(
            200,
            json={"models": [{"name": "llama3.2:latest", "model": "llama3.2:latest"}]},
        )
    payload = json.loads(request.content or b"{}")
    if payload.get("stream"):
        return httpx.Response(200, content=OLLAMA_NDJSON.encode())
    return httpx.Response(
        200,
        json={
            "model": "llama3.2:latest",
            "message": {"role": "assistant", "content": "Ollama reply"},
            "done": True,
            "prompt_eval_count": 5,
            "eval_count": 2,
        },
    )


async def test_openrouter_non_streaming_through_engine(client, app) -> None:
    http_client, _ = _install(app, _openrouter_handler)
    try:
        conversation = await client.post(
            BASE, json={"provider": "openrouter", "model": "test/model"}
        )
        conversation_id = conversation.json()["id"]

        response = await client.post(f"{BASE}/{conversation_id}/messages", json={"content": "Hi"})
        assert response.status_code == 200, response.text
        assistant = response.json()["assistant_message"]
        assert assistant["content"] == "OpenRouter reply"
        assert assistant["status"] == "completed"
        assert assistant["total_tokens"] == 7
        assert assistant["provider"] == "openrouter"
    finally:
        await http_client.aclose()


async def test_openrouter_sse_through_engine(client, app) -> None:
    http_client, _ = _install(app, _openrouter_handler)
    try:
        conversation = await client.post(
            BASE, json={"provider": "openrouter", "model": "test/model"}
        )
        conversation_id = conversation.json()["id"]

        async with client.stream(
            "POST",
            f"{BASE}/{conversation_id}/messages",
            json={"content": "Hi", "stream": True},
        ) as response:
            assert response.status_code == 200
            text = "".join([chunk async for chunk in response.aiter_text()])

        assert "event: message.completed" in text
        deltas = []
        for block in text.split("\n\n"):
            if "event: content.delta" in block:
                data = json.loads(
                    next(line[6:] for line in block.splitlines() if line.startswith("data: "))
                )
                deltas.append(data["delta"])
        assert "".join(deltas) == "Hello"
    finally:
        await http_client.aclose()


async def test_ollama_ndjson_and_non_streaming_through_engine(client, app) -> None:
    http_client, _ = _install(app, _ollama_handler)
    try:
        conversation = await client.post(
            BASE, json={"provider": "ollama", "model": "llama3.2:latest"}
        )
        conversation_id = conversation.json()["id"]

        reply = await client.post(f"{BASE}/{conversation_id}/messages", json={"content": "Hi"})
        assert reply.status_code == 200, reply.text
        assert reply.json()["assistant_message"]["content"] == "Ollama reply"

        async with client.stream(
            "POST",
            f"{BASE}/{conversation_id}/messages",
            json={"content": "Again", "stream": True},
        ) as response:
            text = "".join([chunk async for chunk in response.aiter_text()])
        assert "event: message.completed" in text
        assert '"content":"Olla"' in text.replace(" ", "")
    finally:
        await http_client.aclose()


def _models_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": [{"id": "test/model", "name": "Test", "context_length": 8192}]},
    )


class _DroppedStream(httpx.AsyncByteStream):
    """Emit one SSE chunk and then fail like a dropped connection."""

    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"content":"Hel"},"finish_reason":null}]}\n\n'
        raise httpx.ReadTimeout("read timed out")

    async def aclose(self) -> None:
        return None


async def _failed_chat(client, app, handler) -> tuple[int, dict]:
    http_client, _ = _install(app, handler)
    try:
        conversation = await client.post(
            BASE, json={"provider": "openrouter", "model": "test/model"}
        )
        conversation_id = conversation.json()["id"]
        response = await client.post(f"{BASE}/{conversation_id}/messages", json={"content": "Hi"})
        body = response.json()
        async with app.state.db.session_factory() as session:
            messages = await ConversationRepository(session).list_messages(conversation_id)
        assistant = messages[0][-1]
        assert assistant.status == "failed"
        conversation_row = await session_get_conversation(app, conversation_id)
        assert conversation_row is not None and conversation_row.active_generation_id is None
        return response.status_code, body
    finally:
        await http_client.aclose()


async def session_get_conversation(app, conversation_id: str):
    async with app.state.db.session_factory() as session:
        return await session.get(Conversation, conversation_id)


async def test_http_500_maps_to_provider_unavailable(client, app) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return _models_response()
        return httpx.Response(500, json={"error": {"message": "upstream exploded"}})

    status, body = await _failed_chat(client, app, handler)
    assert status == 502
    assert body["error"]["code"] == "provider_unavailable"


async def test_timeout_maps_to_gateway_timeout(client, app) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return _models_response()
        raise httpx.ConnectTimeout("timed out", request=request)

    status, body = await _failed_chat(client, app, handler)
    assert status == 504
    assert body["error"]["code"] == "provider_timeout"


async def test_malformed_response_is_normalized(client, app) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return _models_response()
        return httpx.Response(200, content=b"this is not json")

    status, body = await _failed_chat(client, app, handler)
    assert status == 502
    assert body["error"]["code"] == "provider_invalid_response"


async def test_empty_completion_is_a_failure(client, app) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return _models_response()
        return httpx.Response(
            200,
            json={
                "model": "test/model",
                "choices": [
                    {"message": {"role": "assistant", "content": "   "}, "finish_reason": "stop"}
                ],
            },
        )

    status, body = await _failed_chat(client, app, handler)
    assert status == 502
    assert body["error"]["code"] == "provider_invalid_response"


async def test_streaming_timeout_is_not_internal_error(client, app) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return _models_response()
        return httpx.Response(
            200,
            stream=_DroppedStream(),
            headers={"content-type": "text/event-stream"},
        )

    http_client, _ = _install(app, handler)
    try:
        conversation = await client.post(
            BASE, json={"provider": "openrouter", "model": "test/model"}
        )
        conversation_id = conversation.json()["id"]

        async with client.stream(
            "POST",
            f"{BASE}/{conversation_id}/messages",
            json={"content": "Hi", "stream": True},
        ) as response:
            text = "".join([chunk async for chunk in response.aiter_text()])

        assert "event: message.failed" in text
        assert '"code":"provider_timeout"' in text
        assert '"code":"internal_error"' not in text

        async with app.state.db.session_factory() as session:
            messages, _ = await ConversationRepository(session).list_messages(conversation_id)
        assistant = messages[-1]
        assert assistant.status == "failed"
        assert assistant.error_code == "provider_timeout"
        assert assistant.content == "Hel"
    finally:
        await http_client.aclose()
