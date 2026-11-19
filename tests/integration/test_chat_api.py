"""End-to-end tests for chat generation over the REST API and SSE."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import httpx

from orbit.chat.engine import ConversationEngine
from orbit.conversations.enums import MessageStatus
from orbit.conversations.repository import ConversationRepository
from orbit.providers.base import CompletionChunk, CompletionRequest
from orbit.providers.errors import ProviderAuthenticationError, ProviderRateLimitError
from orbit.providers.registry import ProviderRegistry
from orbit.storage.models import Conversation, Message
from tests.fakes import FakeProvider

BASE = "/api/v1/conversations"


def _install(app, provider: FakeProvider) -> None:
    registry = ProviderRegistry([provider])
    app.state.providers = registry
    app.state.engine = ConversationEngine(app.state.db.session_factory, registry)


async def _create(client: httpx.AsyncClient, **payload: object) -> str:
    response = await client.post(BASE, json=payload)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _events(text: str) -> list[tuple[str, dict]]:
    parsed: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        lines = [line for line in block.strip().splitlines() if line]
        if not lines:
            continue
        event = next((line[7:] for line in lines if line.startswith("event: ")), None)
        data = next((line[6:] for line in lines if line.startswith("data: ")), None)
        if event and data:
            parsed.append((event, json.loads(data)))
    return parsed


async def _get_message(app, message_id: str) -> Message | None:
    async with app.state.db.session_factory() as session:
        return await session.get(Message, message_id)


async def _get_conversation(app, conversation_id: str) -> Conversation | None:
    async with app.state.db.session_factory() as session:
        return await session.get(Conversation, conversation_id)


async def test_non_streaming_generation_success(client, app) -> None:
    provider = FakeProvider()
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    response = await client.post(
        f"{BASE}/{conversation_id}/messages", json={"content": "Hi", "stream": False}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_message"]["content"] == "Hi"
    assert body["user_message"]["status"] == "completed"
    assert body["assistant_message"]["content"] == "Hello from fake"
    assert body["assistant_message"]["status"] == "completed"
    assert body["assistant_message"]["total_tokens"] == 7
    assert body["assistant_message"]["provider"] == "fake"
    assert provider.complete_calls == 1

    stored = await _get_message(app, body["assistant_message"]["id"])
    assert stored is not None and stored.status == MessageStatus.COMPLETED.value
    conversation = await _get_conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None


async def test_default_model_fallback(client, app) -> None:
    provider = FakeProvider()
    _install(app, provider)
    conversation_id = await _create(client)

    default = await client.put(
        "/api/v1/models/default", json={"provider": "fake", "model": "fake-model"}
    )
    assert default.status_code == 200

    response = await client.post(f"{BASE}/{conversation_id}/messages", json={"content": "Hi"})
    assert response.status_code == 200, response.text
    assert response.json()["assistant_message"]["model"] == "fake-model"


async def test_request_selection_overrides_conversation(client, app) -> None:
    provider = FakeProvider(model_ids=["fake-model", "alt-model"])
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    response = await client.post(
        f"{BASE}/{conversation_id}/messages",
        json={"content": "Hi", "model": "alt-model"},
    )
    assert response.status_code == 200, response.text
    assert provider.last_request is not None
    assert provider.last_request.model == "alt-model"
    assert response.json()["assistant_message"]["model"] == "alt-model"


async def test_no_model_selected(client, app) -> None:
    _install(app, FakeProvider())
    conversation_id = await _create(client)
    response = await client.post(f"{BASE}/{conversation_id}/messages", json={"content": "Hi"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "no_model_selected"


async def test_unknown_model(client, app) -> None:
    _install(app, FakeProvider())
    conversation_id = await _create(client)
    response = await client.post(
        f"{BASE}/{conversation_id}/messages",
        json={"content": "Hi", "provider": "fake", "model": "ghost"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "model_not_found"


async def test_unconfigured_provider(client, app) -> None:
    _install(app, FakeProvider(configured_flag=False))
    conversation_id = await _create(client)
    response = await client.post(
        f"{BASE}/{conversation_id}/messages",
        json={"content": "Hi", "provider": "fake", "model": "fake-model"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "provider_not_configured"


async def test_provider_failure_persists_failed_message(client, app) -> None:
    provider = FakeProvider(error=ProviderAuthenticationError("bad credentials"))
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    response = await client.post(f"{BASE}/{conversation_id}/messages", json={"content": "Hi"})
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "provider_auth_error"

    async with app.state.db.session_factory() as session:
        repo = ConversationRepository(session)
        messages, _ = await repo.list_messages(conversation_id)
    assert messages[-1].status == MessageStatus.FAILED.value
    assert messages[-1].error_code == "provider_auth_error"

    conversation = await _get_conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None


async def test_context_too_large_is_rejected(client, app) -> None:
    provider = FakeProvider(context_length=40)
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    response = await client.post(
        f"{BASE}/{conversation_id}/messages",
        json={"content": "x" * 1000, "max_tokens": 10},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "context_too_large"

    async with app.state.db.session_factory() as session:
        repo = ConversationRepository(session)
        messages, _ = await repo.list_messages(conversation_id)
    assert messages[-1].status == MessageStatus.FAILED.value
    assert provider.complete_calls == 0


async def test_max_tokens_above_local_limit_is_rejected_before_generation(client, app) -> None:
    provider = FakeProvider()
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    response = await client.post(
        f"{BASE}/{conversation_id}/messages",
        json={"content": "hi", "max_tokens": 9000},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_generation_parameters"
    assert provider.complete_calls == 0

    async with app.state.db.session_factory() as session:
        messages, _ = await ConversationRepository(session).list_messages(conversation_id)
    assert messages == []


async def test_effective_output_budget_uses_model_limit_and_default(client, app) -> None:
    provider = FakeProvider(max_output_tokens=512)
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    accepted = await client.post(f"{BASE}/{conversation_id}/messages", json={"content": "hi"})
    assert accepted.status_code == 200
    assert provider.last_request is not None
    assert provider.last_request.max_tokens == 512

    rejected = await client.post(
        f"{BASE}/{conversation_id}/messages",
        json={"content": "hi", "max_tokens": 600},
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "invalid_generation_parameters"


async def test_default_output_budget_is_1024_without_model_limit(client, app) -> None:
    provider = FakeProvider()
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    response = await client.post(f"{BASE}/{conversation_id}/messages", json={"content": "hi"})
    assert response.status_code == 200
    assert provider.last_request is not None
    assert provider.last_request.max_tokens == 1024


async def test_output_budget_cannot_consume_entire_context(client, app) -> None:
    provider = FakeProvider(context_length=1024)
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    response = await client.post(
        f"{BASE}/{conversation_id}/messages",
        json={"content": "hi", "max_tokens": 1024},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_generation_parameters"
    assert provider.complete_calls == 0


async def test_validation_rejects_blank_and_invalid_temperature(client, app) -> None:
    _install(app, FakeProvider())
    conversation_id = await _create(client, provider="fake", model="fake-model")

    blank = await client.post(f"{BASE}/{conversation_id}/messages", json={"content": "  "})
    assert blank.status_code == 422

    invalid_temp = await client.post(
        f"{BASE}/{conversation_id}/messages",
        json={"content": "hi", "temperature": 3},
    )
    assert invalid_temp.status_code == 422


async def test_streaming_success_events_and_persistence(client, app) -> None:
    provider = FakeProvider()
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    async with client.stream(
        "POST",
        f"{BASE}/{conversation_id}/messages",
        json={"content": "Hi", "stream": True},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        text = "".join([chunk async for chunk in response.aiter_text()])

    events = _events(text)
    names = [name for name, _ in events]
    assert names[0] == "message.started"
    assert names[-1] == "message.completed"
    assert "content.delta" in names
    assert "id:" not in text

    deltas = "".join(data["delta"] for name, data in events if name == "content.delta")
    assert deltas == "Hello from fake"
    completed = events[-1][1]
    assert completed["content"] == "Hello from fake"
    assert completed["usage"]["total_tokens"] == 7

    stored = await _get_message(app, completed["message_id"])
    assert stored is not None and stored.status == MessageStatus.COMPLETED.value
    assert stored.content == "Hello from fake"


async def test_streaming_uses_effective_output_budget(client, app) -> None:
    provider = FakeProvider(max_output_tokens=512)
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    async with client.stream(
        "POST",
        f"{BASE}/{conversation_id}/messages",
        json={"content": "Hi", "stream": True},
    ) as response:
        assert response.status_code == 200
        await response.aread()

    assert provider.last_request is not None
    assert provider.last_request.max_tokens == 512


async def test_streaming_provider_failure_emits_failed(client, app) -> None:
    provider = FakeProvider(error=ProviderRateLimitError("slow down"))
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    async with client.stream(
        "POST",
        f"{BASE}/{conversation_id}/messages",
        json={"content": "Hi", "stream": True},
    ) as response:
        text = "".join([chunk async for chunk in response.aiter_text()])

    events = _events(text)
    assert [name for name, _ in events] == ["message.started", "message.failed"]
    failed = events[-1][1]
    assert failed["error"]["code"] == "provider_rate_limited"
    assert failed["error"]["retryable"] is True

    stored = await _get_message(app, failed["message_id"])
    assert stored is not None and stored.status == MessageStatus.FAILED.value
    conversation = await _get_conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None


async def test_idempotent_replay_does_not_call_provider_twice(client, app) -> None:
    provider = FakeProvider()
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")
    payload = {"content": "Hi", "client_message_id": "key-1"}

    first = await client.post(f"{BASE}/{conversation_id}/messages", json=payload)
    second = await client.post(f"{BASE}/{conversation_id}/messages", json=payload)

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["assistant_message"]["id"] == second.json()["assistant_message"]["id"]
    assert provider.complete_calls == 1

    streamed = await client.post(
        f"{BASE}/{conversation_id}/messages",
        json={**payload, "stream": True},
    )
    assert streamed.status_code == 200
    events = _events(streamed.text)
    assert [name for name, _ in events] == ["message.started", "message.completed"]
    assert events[1][1]["message_id"] == first.json()["assistant_message"]["id"]


async def _wait_terminal(app, message_id: str, deadline_seconds: float = 3.0) -> Message:
    deadline = asyncio.get_running_loop().time() + deadline_seconds
    while asyncio.get_running_loop().time() < deadline:
        message = await _get_message(app, message_id)
        if message is not None and message.status in {
            MessageStatus.COMPLETED.value,
            MessageStatus.FAILED.value,
            MessageStatus.CANCELLED.value,
        }:
            return message
        await asyncio.sleep(0.02)
    raise AssertionError(f"message {message_id} did not reach a terminal state")


class PausedAfterFirstChunkProvider(FakeProvider):
    """Yield one chunk, then park until cancelled (deterministic cancel window)."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]:
        self.stream_calls += 1
        self.last_request = request
        yield CompletionChunk(delta="a", model=request.model)
        self.entered.set()
        await self.release.wait()
        for index, delta in enumerate(self.chunks):
            last = index == len(self.chunks) - 1
            yield CompletionChunk(
                delta=delta,
                model=request.model,
                finish_reason="stop" if last else None,
                usage=self.usage if last else None,
            )


async def test_cancel_active_generation(client, app) -> None:
    provider = PausedAfterFirstChunkProvider(chunks=["b", "c"])
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    async def consume() -> str:
        collected: list[str] = []
        async with client.stream(
            "POST",
            f"{BASE}/{conversation_id}/messages",
            json={"content": "Hi", "stream": True},
        ) as response:
            async for chunk in response.aiter_text():
                collected.append(chunk)
        return "".join(collected)

    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(provider.entered.wait(), timeout=3)
    cancel = await client.post(f"{BASE}/{conversation_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["cancelled"] is True

    text = await consumer
    events = _events(text)
    names = [name for name, _ in events]
    assert names[-1] == "message.cancelled"
    assert events[-1][1]["reason"] == "cancelled"

    message_id = str(cancel.json()["message_id"])
    assistant = await _wait_terminal(app, message_id)
    assert assistant.status == MessageStatus.CANCELLED.value
    assert assistant.error_code == "cancelled"
    assert assistant.content in {"", "a", "ab", "abc"}

    conversation = await _get_conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None


async def test_cancel_without_active_generation(client, app) -> None:
    _install(app, FakeProvider())
    conversation_id = await _create(client, provider="fake", model="fake-model")
    response = await client.post(f"{BASE}/{conversation_id}/cancel")
    assert response.status_code == 200
    assert response.json() == {"cancelled": False, "message_id": None}


async def test_client_disconnect_marks_cancelled(client, app) -> None:
    provider = FakeProvider(chunks=["a", "b", "c", "d"], stream_delay=0.05)
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await app.state.engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    iterator = stream.__aiter__()
    first = await iterator.__anext__()
    assert first.event == "message.started"
    await stream.close()

    message_id = first.data()["message_id"]
    assistant = await _wait_terminal(app, str(message_id))
    assert assistant.status == MessageStatus.CANCELLED.value
    assert assistant.error_code == "client_disconnect"
