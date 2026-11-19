"""Deterministic in-memory provider used by engine and API tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from orbit.providers.base import (
    CompletionChunk,
    CompletionRequest,
    CompletionResult,
    ConnectionTest,
    ModelInfo,
    ProviderCapabilities,
    TokenUsage,
)
from orbit.providers.errors import ProviderError


@dataclass
class FakeProvider:
    id: str = "fake"
    display_name: str = "Fake Provider"
    model_ids: list[str] = field(default_factory=lambda: ["fake-model"])
    content: str = "Hello from fake"
    chunks: list[str] = field(default_factory=lambda: ["Hello", " from", " fake"])
    error: ProviderError | None = None
    error_after_chunks: int | None = None
    stream_delay: float = 0.0
    complete_delay: float = 0.0
    configured_flag: bool = True
    context_length: int | None = 8192
    max_output_tokens: int | None = None
    usage: TokenUsage | None = field(default_factory=lambda: TokenUsage(4, 3, 7))
    list_calls: int = 0
    stream_calls: int = 0
    complete_calls: int = 0
    last_request: CompletionRequest | None = None
    capabilities: ProviderCapabilities = field(
        default_factory=lambda: ProviderCapabilities(streaming=True)
    )

    @property
    def configured(self) -> bool:
        return self.configured_flag

    async def list_models(self) -> list[ModelInfo]:
        self.list_calls += 1
        return [
            ModelInfo(
                id=model,
                name=model,
                provider=self.id,
                context_length=self.context_length,
                max_output_tokens=self.max_output_tokens,
            )
            for model in self.model_ids
        ]

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.complete_calls += 1
        self.last_request = request
        if self.complete_delay:
            await asyncio.sleep(self.complete_delay)
        if self.error is not None:
            raise self.error
        return CompletionResult(
            content=self.content,
            model=request.model,
            finish_reason="stop",
            usage=self.usage,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]:
        self.stream_calls += 1
        self.last_request = request
        if self.error is not None and self.error_after_chunks is None:
            raise self.error
        for index, delta in enumerate(self.chunks):
            if self.stream_delay:
                await asyncio.sleep(self.stream_delay)
            if (
                self.error is not None
                and self.error_after_chunks is not None
                and index == self.error_after_chunks
            ):
                raise self.error
            last = index == len(self.chunks) - 1
            yield CompletionChunk(
                delta=delta,
                model=request.model,
                finish_reason="stop" if last else None,
                usage=self.usage if last else None,
            )

    async def test_connection(self) -> ConnectionTest:
        return ConnectionTest(ok=True, latency_ms=0.1, model_count=len(self.model_ids))

    async def aclose(self) -> None:
        return None
