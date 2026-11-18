"""Provider-agnostic types and the model provider protocol.

Nothing in the agent runtime may depend on a concrete vendor. Adapters translate
vendor payloads into these types and raise the normalised errors from
``orbit.providers.errors``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str

    def to_payload(self) -> dict[str, str]:
        return {"role": self.role.value, "content": self.content}


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    model: str
    messages: tuple[ChatMessage, ...]
    temperature: float | None = None
    max_tokens: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model must not be empty")
        if not self.messages:
            raise ValueError("messages must not be empty")
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.max_tokens is not None and self.max_tokens < 1:
            raise ValueError("max_tokens must be positive")

    def message_payloads(self) -> list[dict[str, str]]:
        return [message.to_payload() for message in self.messages]


@dataclass(frozen=True, slots=True)
class CompletionResult:
    content: str
    model: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None


@dataclass(frozen=True, slots=True)
class CompletionChunk:
    delta: str
    model: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None


@dataclass(frozen=True, slots=True)
class ModelInfo:
    id: str
    name: str
    provider: str
    context_length: int | None = None
    prompt_price: float | None = None
    completion_price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    streaming: bool = True
    tools: bool = False
    vision: bool = False
    json_mode: bool = False


@dataclass(frozen=True, slots=True)
class ConnectionTest:
    ok: bool
    latency_ms: float
    detail: str | None = None
    model_count: int | None = None


@runtime_checkable
class ModelProvider(Protocol):
    """Contract every inference provider adapter implements."""

    id: str
    display_name: str
    capabilities: ProviderCapabilities

    @property
    def configured(self) -> bool:
        """Whether the adapter has the credentials/endpoint it needs."""
        ...

    async def list_models(self) -> list[ModelInfo]: ...

    async def complete(self, request: CompletionRequest) -> CompletionResult: ...

    def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]: ...

    async def test_connection(self) -> ConnectionTest: ...

    async def aclose(self) -> None: ...
