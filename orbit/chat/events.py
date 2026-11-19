"""Server-Sent Event payloads for chat generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, ClassVar

from orbit.providers.base import TokenUsage


@dataclass(frozen=True, slots=True)
class GenerationEvent:
    event: ClassVar[str] = "event"

    def data(self) -> dict[str, Any]:
        raise NotImplementedError

    def to_sse(self) -> str:
        # No ``id:`` field: streaming resume is not supported yet.
        payload = json.dumps(self.data(), ensure_ascii=False, separators=(",", ":"))
        return f"event: {self.event}\ndata: {payload}\n\n"


@dataclass(frozen=True, slots=True)
class MessageStarted(GenerationEvent):
    event: ClassVar[str] = "message.started"
    conversation_id: str
    message_id: str
    user_message_id: str
    provider: str
    model: str
    sequence: int

    def data(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "user_message_id": self.user_message_id,
            "provider": self.provider,
            "model": self.model,
            "sequence": self.sequence,
        }


@dataclass(frozen=True, slots=True)
class ContentDelta(GenerationEvent):
    event: ClassVar[str] = "content.delta"
    message_id: str
    delta: str

    def data(self) -> dict[str, Any]:
        return {"message_id": self.message_id, "delta": self.delta}


def _usage(usage: TokenUsage | None) -> dict[str, int] | None:
    if usage is None:
        return None
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


@dataclass(frozen=True, slots=True)
class MessageCompleted(GenerationEvent):
    event: ClassVar[str] = "message.completed"
    message_id: str
    content: str
    provider: str
    model: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None

    def data(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "content": self.content,
            "provider": self.provider,
            "model": self.model,
            "finish_reason": self.finish_reason,
            "usage": _usage(self.usage),
        }


@dataclass(frozen=True, slots=True)
class MessageFailed(GenerationEvent):
    event: ClassVar[str] = "message.failed"
    message_id: str
    error_code: str
    error_message: str
    retryable: bool = False

    def data(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "error": {
                "code": self.error_code,
                "message": self.error_message,
                "retryable": self.retryable,
            },
        }


@dataclass(frozen=True, slots=True)
class MessageCancelled(GenerationEvent):
    event: ClassVar[str] = "message.cancelled"
    message_id: str
    content: str
    reason: str

    def data(self) -> dict[str, Any]:
        return {"message_id": self.message_id, "content": self.content, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class Heartbeat(GenerationEvent):
    """Keep-alive comment emitted while a generation is silent.

    Serialised as an SSE comment (``: keep-alive``), so clients that follow the
    SSE specification ignore it. It exists only to stop idle proxies and load
    balancers from closing an otherwise healthy stream.
    """

    event: ClassVar[str] = "heartbeat"

    def data(self) -> dict[str, Any]:
        return {}

    def to_sse(self) -> str:
        return ": keep-alive\n\n"
