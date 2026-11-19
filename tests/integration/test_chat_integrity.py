"""Functional integrity of chat: partial persistence, timeout, replay and disconnects.

Milestone 5.3-B. These tests close the remaining gaps from the Phase 3 audit and
use ``asyncio.Event`` barriers (or a controlled flush interval) instead of
arbitrary sleeps, so the interleavings are deterministic on a loaded machine.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI

import orbit.chat.engine as engine_module
from orbit.chat.engine import ConversationEngine, GenerationStream
from orbit.chat.events import Heartbeat
from orbit.conversations.enums import MessageStatus
from orbit.conversations.repository import ConversationRepository
from orbit.providers.base import (
    CompletionChunk,
    CompletionRequest,
    CompletionResult,
)
from orbit.providers.errors import ProviderError, ProviderUnavailableError
from orbit.providers.registry import ProviderRegistry
from orbit.storage.models import Conversation, Message
from tests.fakes import FakeProvider

BASE = "/api/v1/conversations"
TERMINAL_STATUSES = {
    MessageStatus.COMPLETED.value,
    MessageStatus.FAILED.value,
    MessageStatus.CANCELLED.value,
}


def _install(app, provider: FakeProvider) -> ConversationEngine:
    registry = ProviderRegistry([provider])
    app.state.providers = registry
    engine = ConversationEngine(app.state.db.session_factory, registry)
    app.state.engine = engine
    return engine


async def _create(client, **payload: object) -> str:
    response = await client.post(BASE, json=payload)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _message(app, message_id: str) -> Message | None:
    async with app.state.db.session_factory() as session:
        return await session.get(Message, message_id)


async def _conversation(app, conversation_id: str) -> Conversation | None:
    async with app.state.db.session_factory() as session:
        return await session.get(Conversation, conversation_id)


async def _history(app, conversation_id: str) -> list[Message]:
    async with app.state.db.session_factory() as session:
        messages, _ = await ConversationRepository(session).list_messages(conversation_id)
    return messages


async def _consume(stream: GenerationStream) -> list[Any]:
    return [event async for event in stream]


def _events(text: str) -> list[tuple[str, dict[str, Any]]]:
    parsed: list[tuple[str, dict[str, Any]]] = []
    for block in text.split("\n\n"):
        lines = [line for line in block.strip().splitlines() if line]
        if not lines:
            continue
        event = next((line[7:] for line in lines if line.startswith("event: ")), None)
        data = next((line[6:] for line in lines if line.startswith("data: ")), None)
        if event and data:
            parsed.append((event, json.loads(data)))
    return parsed


async def _wait_terminal(app, conversation_id: str, deadline_seconds: float = 3.0) -> Message:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_seconds
    while loop.time() < deadline:
        messages = await _history(app, conversation_id)
        if messages and messages[-1].status in TERMINAL_STATUSES:
            return messages[-1]
        await asyncio.sleep(0.01)
    raise AssertionError("generation did not reach a terminal state")


class StepwiseProvider(FakeProvider):
    """Yield the first chunk, park, then continue (or fail) when released."""

    def __init__(
        self,
        steps: list[str] | None = None,
        *,
        after_pause_error: ProviderError | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.steps = steps or ["alpha", "beta"]
        self.after_pause_error = after_pause_error
        self.parked = asyncio.Event()
        self.resume = asyncio.Event()

    async def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]:
        self.stream_calls += 1
        self.last_request = request
        for index, delta in enumerate(self.steps):
            last = index == len(self.steps) - 1
            yield CompletionChunk(
                delta=delta,
                model=request.model,
                finish_reason="stop" if last else None,
                usage=self.usage if last else None,
            )
            if index == 0:
                self.parked.set()
                await self.resume.wait()
                if self.after_pause_error is not None:
                    raise self.after_pause_error


class GatedStreamProvider(FakeProvider):
    """Park inside ``stream()`` before the first chunk until released."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]:
        self.stream_calls += 1
        self.last_request = request
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


class HangingCompletionProvider(FakeProvider):
    """Non-streaming provider that can hang (or answer once ``hang`` is cleared)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.hang = True

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.complete_calls += 1
        self.last_request = request
        if self.hang:
            await asyncio.Event().wait()
        return CompletionResult(
            content=self.content,
            model=request.model,
            finish_reason="stop",
            usage=self.usage,
        )


class SlowCancelProvider(FakeProvider):
    """Ignore cancellation until the test releases the provider."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]:
        self.stream_calls += 1
        self.last_request = request
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await self.release.wait()
            raise
        yield CompletionChunk(delta="unreachable", model=request.model)


class AsgiStreamRequest:
    """Minimal ASGI client able to deliver a real ``http.disconnect`` mid-stream."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self.receive_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.started = asyncio.Event()
        self.body_chunks: list[bytes] = []
        self.status_code: int | None = None

    async def receive(self) -> dict[str, Any]:
        return await self.receive_queue.get()

    async def send(self, message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self.status_code = int(message["status"])
        elif message["type"] == "http.response.body":
            body = bytes(message.get("body", b""))
            if body:
                self.body_chunks.append(body)
                if b"message.started" in body:
                    self.started.set()

    async def run(self, scope: dict[str, Any]) -> None:
        await self._app(scope, self.receive, self.send)

    def disconnect(self) -> None:
        self.receive_queue.put_nowait({"type": "http.disconnect"})


def _stream_scope(conversation_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    """HTTP scope for an SSE request.

    ``spec_version`` is 2.3 on purpose: that is what the installed uvicorn
    advertises, and Starlette only listens for ``http.disconnect`` below 2.4.
    """
    body = json.dumps(payload).encode()
    path = f"{BASE}/{conversation_id}/messages"
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"orbit.test"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 4321),
        "server": ("orbit.test", 80),
    }
    return scope, body


# ---------------------------------------------------------------------------
# Scope 1 — partial persistence
# ---------------------------------------------------------------------------


async def test_partial_content_is_visible_while_generating(client, app, monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "PARTIAL_FLUSH_INTERVAL_SECONDS", 0.0)
    provider = StepwiseProvider(steps=["alpha", "beta"])
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    await asyncio.wait_for(provider.parked.wait(), timeout=2)

    # Read through the public API while the producer is parked in the provider:
    # this also proves no SQLite transaction is held across provider I/O.
    response = await client.get(f"{BASE}/{conversation_id}/messages")
    assert response.status_code == 200
    live = response.json()["items"][-1]
    assert live["id"] == stream.message_id
    assert live["status"] == "streaming"
    assert live["content"] == "alpha"

    provider.resume.set()
    events = await asyncio.wait_for(_consume(stream), timeout=2)
    assert events[-1].event == "message.completed"
    assert events[-1].data()["content"] == "alphabeta"

    final = (await client.get(f"{BASE}/{conversation_id}/messages")).json()["items"][-1]
    assert final["status"] == "completed"
    assert final["content"] == "alphabeta"


async def test_message_stays_pending_before_the_first_flush(client, app, monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "PARTIAL_FLUSH_INTERVAL_SECONDS", 3600.0)
    provider = StepwiseProvider(steps=["alpha", "beta"])
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    await asyncio.wait_for(provider.parked.wait(), timeout=2)

    live = (await client.get(f"{BASE}/{conversation_id}/messages")).json()["items"][-1]
    assert live["status"] == "pending"
    assert live["content"] == ""

    provider.resume.set()
    await asyncio.wait_for(_consume(stream), timeout=2)
    message = await _message(app, stream.message_id)
    assert message is not None
    assert message.status == MessageStatus.COMPLETED.value


async def test_failure_after_partial_flush_preserves_flushed_content(
    client, app, monkeypatch
) -> None:
    monkeypatch.setattr(engine_module, "PARTIAL_FLUSH_INTERVAL_SECONDS", 0.0)
    provider = StepwiseProvider(
        steps=["alpha", "beta"],
        after_pause_error=ProviderUnavailableError("connection lost"),
    )
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    await asyncio.wait_for(provider.parked.wait(), timeout=2)

    live = (await client.get(f"{BASE}/{conversation_id}/messages")).json()["items"][-1]
    assert live["status"] == "streaming"
    assert live["content"] == "alpha"

    provider.resume.set()
    events = await asyncio.wait_for(_consume(stream), timeout=2)
    assert events[-1].event == "message.failed"
    assert events[-1].data()["error"]["code"] == "provider_unavailable"

    message = await _message(app, stream.message_id)
    assert message is not None
    assert message.status == MessageStatus.FAILED.value
    assert message.content == "alpha"
    assert engine.generations.get(conversation_id) is None


async def test_cancel_after_partial_flush_persists_content(client, app, monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "PARTIAL_FLUSH_INTERVAL_SECONDS", 0.0)
    provider = StepwiseProvider(steps=["alpha", "beta", "gamma"])
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    await asyncio.wait_for(provider.parked.wait(), timeout=2)
    assert (await client.get(f"{BASE}/{conversation_id}/messages")).json()["items"][-1][
        "content"
    ] == "alpha"

    cancelled_id = await engine.cancel(conversation_id)
    events = await asyncio.wait_for(_consume(stream), timeout=2)

    assert cancelled_id == stream.message_id
    assert events[-1].event == "message.cancelled"
    assert events[-1].data()["content"] == "alpha"
    assert events[-1].data()["reason"] == "cancelled"

    message = await _message(app, stream.message_id)
    assert message is not None
    assert message.status == MessageStatus.CANCELLED.value
    assert message.content == "alpha"
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None


# ---------------------------------------------------------------------------
# Scope 2 — non-streaming engine timeout
# ---------------------------------------------------------------------------


async def test_non_streaming_generation_timeout_releases_lock_and_allows_retry(client, app) -> None:
    provider = HangingCompletionProvider()
    engine = _install(app, provider)
    engine._generation_timeout = 0.05
    conversation_id = await _create(client, provider="fake", model="fake-model")

    timed_out = await client.post(f"{BASE}/{conversation_id}/messages", json={"content": "Hi"})
    assert timed_out.status_code == 504
    assert timed_out.json()["error"]["code"] == "provider_timeout"

    messages = await _history(app, conversation_id)
    assert [message.status for message in messages] == [
        MessageStatus.COMPLETED.value,
        MessageStatus.FAILED.value,
    ]
    assert messages[-1].error_code == "provider_timeout"
    # Non-streaming has no partial content to preserve: the reply is all-or-nothing.
    assert messages[-1].content == ""
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None
    assert engine.generations.get(conversation_id) is None

    provider.hang = False
    retried = await client.post(f"{BASE}/{conversation_id}/messages", json={"content": "Hi"})
    assert retried.status_code == 200, retried.text
    assert retried.json()["assistant_message"]["status"] == "completed"
    assert provider.complete_calls == 2
    assert len(await _history(app, conversation_id)) == 4


# ---------------------------------------------------------------------------
# Scope 3 — context too large over SSE
# ---------------------------------------------------------------------------


async def test_context_too_large_streaming_emits_failed_and_releases_resources(client, app) -> None:
    provider = FakeProvider(context_length=40)
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    async with client.stream(
        "POST",
        f"{BASE}/{conversation_id}/messages",
        json={"content": "x" * 1000, "max_tokens": 10, "stream": True},
    ) as response:
        assert response.status_code == 200
        text = "".join([chunk async for chunk in response.aiter_text()])

    events = _events(text)
    assert [name for name, _ in events] == ["message.started", "message.failed"]
    assert events[-1][1]["error"]["code"] == "context_too_large"

    message = await _message(app, str(events[-1][1]["message_id"]))
    assert message is not None
    assert message.status == MessageStatus.FAILED.value
    assert message.error_code == "context_too_large"
    assert provider.stream_calls == 0

    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None
    assert engine.generations.get(conversation_id) is None


# ---------------------------------------------------------------------------
# Scope 4 — replay and idempotency
# ---------------------------------------------------------------------------


async def test_replay_of_completed_turn_reports_persisted_provider_and_model(client, app) -> None:
    provider = FakeProvider(model_ids=["fake-model", "alt-model"])
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    first = await engine.start_stream(
        conversation_id,
        content="Hi",
        provider="fake",
        model="fake-model",
        client_message_id="replay-completed",
    )
    original = await _consume(first)
    assert original[-1].event == "message.completed"
    assert original[-1].data()["model"] == "fake-model"

    # Replay while requesting a different model: the event must describe the
    # reply that was actually persisted, not the current selection.
    replay = await engine.start_stream(
        conversation_id,
        content="Hi",
        client_message_id="replay-completed",
        provider="fake",
        model="alt-model",
    )
    events = await _consume(replay)

    assert [event.event for event in events] == ["message.started", "message.completed"]
    assert events[-1].data()["message_id"] == first.message_id
    assert events[-1].data()["model"] == "fake-model"
    assert events[-1].data()["provider"] == "fake"
    assert provider.stream_calls == 1
    assert len(await _history(app, conversation_id)) == 2


async def test_replay_of_completed_turn_over_http_returns_terminal_event(client, app) -> None:
    provider = FakeProvider()
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")
    payload = {"content": "Hi", "client_message_id": "wire-replay"}

    first = await client.post(f"{BASE}/{conversation_id}/messages", json=payload)
    assert first.status_code == 200

    async with client.stream(
        "POST", f"{BASE}/{conversation_id}/messages", json={**payload, "stream": True}
    ) as response:
        text = "".join([chunk async for chunk in response.aiter_text()])

    events = _events(text)
    assert [name for name, _ in events] == ["message.started", "message.completed"]
    completed = events[-1][1]
    assert completed["message_id"] == first.json()["assistant_message"]["id"]
    assert completed["model"] == "fake-model"
    assert provider.complete_calls == 1


async def test_replay_of_failed_turn_emits_failed_terminal(client, app) -> None:
    provider = FakeProvider(error=ProviderUnavailableError("down"))
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    first = await engine.start_stream(
        conversation_id,
        content="Hi",
        provider="fake",
        model="fake-model",
        client_message_id="replay-failed",
    )
    assert (await _consume(first))[-1].event == "message.failed"

    replay = await engine.start_stream(
        conversation_id,
        content="Hi",
        provider="fake",
        model="fake-model",
        client_message_id="replay-failed",
    )
    events = await _consume(replay)

    assert [event.event for event in events] == ["message.started", "message.failed"]
    assert events[-1].data()["message_id"] == first.message_id
    assert events[-1].data()["error"]["code"] == "provider_unavailable"
    assert provider.stream_calls == 1
    assert len(await _history(app, conversation_id)) == 2


async def test_replay_of_cancelled_turn_emits_cancelled_terminal(client, app) -> None:
    provider = StepwiseProvider(steps=["alpha", "beta"])
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    first = await engine.start_stream(
        conversation_id,
        content="Hi",
        provider="fake",
        model="fake-model",
        client_message_id="replay-cancelled",
    )
    await asyncio.wait_for(provider.parked.wait(), timeout=2)
    await engine.cancel(conversation_id)
    assert (await _consume(first))[-1].event == "message.cancelled"

    replay = await engine.start_stream(
        conversation_id,
        content="Hi",
        provider="fake",
        model="fake-model",
        client_message_id="replay-cancelled",
    )
    events = await _consume(replay)

    assert [event.event for event in events] == ["message.started", "message.cancelled"]
    assert events[-1].data()["message_id"] == first.message_id
    assert events[-1].data()["reason"] == "cancelled"
    assert events[-1].data()["content"] == "alpha"
    assert provider.stream_calls == 1
    assert len(await _history(app, conversation_id)) == 2


async def test_idempotency_conflict_returns_409(client, app) -> None:
    provider = FakeProvider()
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")
    payload = {"content": "original", "client_message_id": "conflict-key"}

    first = await client.post(f"{BASE}/{conversation_id}/messages", json=payload)
    assert first.status_code == 200

    conflicting = await client.post(
        f"{BASE}/{conversation_id}/messages",
        json={"content": "changed", "client_message_id": "conflict-key"},
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "idempotency_conflict"
    assert provider.complete_calls == 1
    assert len(await _history(app, conversation_id)) == 2


async def test_retries_do_not_duplicate_messages(client, app) -> None:
    provider = FakeProvider()
    _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")
    payload = {"content": "Hi", "client_message_id": "retry-key"}

    responses = [
        await client.post(f"{BASE}/{conversation_id}/messages", json=payload) for _ in range(3)
    ]
    assert all(response.status_code == 200 for response in responses)
    assistant_ids = {response.json()["assistant_message"]["id"] for response in responses}
    assert len(assistant_ids) == 1
    assert provider.complete_calls == 1
    assert len(await _history(app, conversation_id)) == 2


# ---------------------------------------------------------------------------
# Scope 5 — cancel followed by an immediate resend
# ---------------------------------------------------------------------------


async def test_cancel_then_immediate_resend_is_rejected_until_finalized(client, app) -> None:
    provider = SlowCancelProvider()
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    await asyncio.wait_for(provider.entered.wait(), timeout=2)

    cancel = await client.post(f"{BASE}/{conversation_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json() == {"cancelled": True, "message_id": stream.message_id}

    # Cancellation is requested but the producer has not finalized yet: the lock
    # is still held, so a resend is rejected deterministically.
    blocked = await client.post(f"{BASE}/{conversation_id}/messages", json={"content": "again"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "generation_in_progress"

    provider.release.set()
    events = await asyncio.wait_for(_consume(stream), timeout=2)
    assert events[-1].event == "message.cancelled"
    assert events[-1].data()["reason"] == "cancelled"

    retried = await client.post(f"{BASE}/{conversation_id}/messages", json={"content": "again"})
    assert retried.status_code == 200, retried.text
    assert retried.json()["assistant_message"]["status"] == "completed"
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None


# ---------------------------------------------------------------------------
# Scope 6 — transport-level disconnect
# ---------------------------------------------------------------------------


async def test_http_disconnect_cancels_generation_and_releases_lock(client, app) -> None:
    provider = GatedStreamProvider(chunks=["a", "b"])
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    harness = AsgiStreamRequest(app)
    scope, body = _stream_scope(conversation_id, {"content": "Hi", "stream": True})
    harness.receive_queue.put_nowait({"type": "http.request", "body": body, "more_body": False})
    app_task = asyncio.create_task(harness.run(scope))

    await asyncio.wait_for(harness.started.wait(), timeout=2)
    await asyncio.wait_for(provider.entered.wait(), timeout=2)
    assert harness.status_code == 200

    harness.disconnect()
    await asyncio.wait_for(app_task, timeout=3)

    message = await _wait_terminal(app, conversation_id)
    assert message.status == MessageStatus.CANCELLED.value
    assert message.error_code == "client_disconnect"
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None
    assert engine.generations.get(conversation_id) is None


# ---------------------------------------------------------------------------
# Scope 3 — SSE keep-alive during silence
# ---------------------------------------------------------------------------


async def test_six_chunk_stream_persists_every_delta(client, app) -> None:
    """H04 regression: a short stream must persist every delta, exactly once."""

    chunks = ["Hello", " from", " the", " mock", " provider", " with"]
    provider = FakeProvider(chunks=chunks, stream_delay=0)
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Olá", provider="fake", model="fake-model"
    )
    events = await asyncio.wait_for(_consume(stream), timeout=5)

    assert [event.event for event in events] == (
        ["message.started"] + ["content.delta"] * len(chunks) + ["message.completed"]
    )
    expected = "".join(chunks)
    assert "".join(event.data()["delta"] for event in events if event.event == "content.delta") == (
        expected
    )
    assert events[-1].data()["content"] == expected

    message = await _message(app, stream.message_id)
    assert message is not None
    assert message.status == MessageStatus.COMPLETED.value
    assert message.finish_reason == "stop"
    assert message.content == expected


async def test_silent_generation_emits_heartbeats_and_one_terminal(
    client, app, monkeypatch
) -> None:
    monkeypatch.setattr(engine_module, "SSE_HEARTBEAT_INTERVAL_SECONDS", 0.02)
    provider = GatedStreamProvider(chunks=["a", "b"])
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    await asyncio.wait_for(provider.entered.wait(), timeout=2)

    iterator = stream.__aiter__()
    seen: list[Any] = []
    heartbeats = 0
    # At least one keep-alive is enough to prove the frame exists; the exact
    # count depends on scheduling and is not part of the contract.
    while heartbeats < 1:
        event = await asyncio.wait_for(anext(iterator), timeout=10)
        seen.append(event)
        if isinstance(event, Heartbeat):
            heartbeats += 1

    provider.release.set()
    seen.extend([event async for event in iterator])

    assert heartbeats >= 1
    assert seen[0].event == "message.started"
    terminals = [
        event
        for event in seen
        if event.event in {"message.completed", "message.failed", "message.cancelled"}
    ]
    assert [event.event for event in terminals] == ["message.completed"]
    message = await _message(app, stream.message_id)
    assert message is not None
    assert message.status == MessageStatus.COMPLETED.value
    assert message.content == "ab"


async def test_sse_serializer_emits_keepalive_comments(client, app, monkeypatch) -> None:
    # httpx's ASGITransport buffers the whole body, so mid-stream frames cannot be
    # observed through it; the route serialiser is exercised directly instead.
    from orbit.api.routes.conversations import _sse_events

    monkeypatch.setattr(engine_module, "SSE_HEARTBEAT_INTERVAL_SECONDS", 0.02)
    provider = GatedStreamProvider(chunks=["a"])
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    await asyncio.wait_for(provider.entered.wait(), timeout=2)

    frames: list[str] = []

    async def consume() -> None:
        async for frame in _sse_events(stream):
            frames.append(frame)
            if ": keep-alive" in "".join(frames):
                provider.release.set()

    await asyncio.wait_for(consume(), timeout=10)

    text = "".join(frames)
    assert ": keep-alive" in text
    assert "event: message.started" in text
    assert "event: message.completed" in text


async def test_disconnect_during_silence_cancels_and_releases_lock(client, app) -> None:
    provider = GatedStreamProvider(chunks=["a"])
    engine = _install(app, provider)
    conversation_id = await _create(client, provider="fake", model="fake-model")

    stream = await engine.start_stream(
        conversation_id, content="Hi", provider="fake", model="fake-model"
    )
    await asyncio.wait_for(provider.entered.wait(), timeout=2)
    await stream.close()

    message = await _message(app, stream.message_id)
    assert message is not None
    assert message.status == MessageStatus.CANCELLED.value
    assert message.error_code == "client_disconnect"
    conversation = await _conversation(app, conversation_id)
    assert conversation is not None and conversation.active_generation_id is None
    assert engine.generations.get(conversation_id) is None
