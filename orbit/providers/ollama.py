"""Ollama provider adapter for local models."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any

import httpx

from orbit.providers.base import (
    CompletionChunk,
    CompletionRequest,
    CompletionResult,
    ConnectionTest,
    ModelInfo,
    ProviderCapabilities,
    TokenUsage,
)
from orbit.providers.errors import (
    ProviderError,
    ProviderInvalidResponseError,
    ProviderNotConfigured,
)
from orbit.providers.http import error_for_response, request_json

DEFAULT_BASE_URL = "http://127.0.0.1:11434"


class OllamaProvider:
    """Adapter for a local or remote Ollama daemon."""

    id = "ollama"
    display_name = "Ollama"
    capabilities = ProviderCapabilities(streaming=True, tools=False, vision=False, json_mode=True)

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
        retry_attempts: int = 3,
        retry_backoff: float = 0.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._retry_attempts = retry_attempts
        self._retry_backoff = retry_backoff
        self._client = client
        self._owns_client = client is None

    @property
    def configured(self) -> bool:
        return bool(self._base_url)

    def _require_configured(self) -> None:
        if not self.configured:
            raise ProviderNotConfigured("Ollama base URL is not configured.", provider=self.id)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def list_models(self) -> list[ModelInfo]:
        return await self._fetch_models(self._retry_attempts)

    async def _fetch_models(self, attempts: int) -> list[ModelInfo]:
        self._require_configured()
        payload = await request_json(
            self._get_client(),
            "GET",
            f"{self._base_url}/api/tags",
            provider=self.id,
            timeout_seconds=self._timeout,
            attempts=attempts,
            backoff=self._retry_backoff,
        )
        data = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise ProviderInvalidResponseError("Ollama model list is malformed.", provider=self.id)
        models = [model for item in data if (model := _parse_model(item)) is not None]
        models.sort(key=lambda model: model.id)
        return models

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self._require_configured()
        payload = await request_json(
            self._get_client(),
            "POST",
            f"{self._base_url}/api/chat",
            provider=self.id,
            payload=_chat_payload(request, stream=False),
            timeout_seconds=self._timeout,
            attempts=self._retry_attempts,
            backoff=self._retry_backoff,
        )
        if not isinstance(payload, dict):
            raise ProviderInvalidResponseError("Ollama response is malformed.", provider=self.id)
        message = payload.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ProviderInvalidResponseError(
                "Ollama response contained no message content.", provider=self.id
            )
        return CompletionResult(
            content=content,
            model=str(payload.get("model") or request.model),
            finish_reason="stop" if payload.get("done") is True else None,
            usage=_parse_usage(payload),
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]:
        self._require_configured()
        client = self._get_client()
        async with client.stream(
            "POST",
            f"{self._base_url}/api/chat",
            headers={"Content-Type": "application/json"},
            json=_chat_payload(request, stream=True),
            timeout=self._timeout,
        ) as response:
            if response.status_code >= 400:
                await response.aread()
                raise error_for_response(response, provider=self.id)
            async for line in response.aiter_lines():
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                if "error" in payload:
                    raise ProviderInvalidResponseError(
                        f"Ollama stream error: {payload.get('error')}", provider=self.id
                    )
                message = payload.get("message")
                text = message.get("content") if isinstance(message, dict) else None
                done = payload.get("done") is True
                chunk = CompletionChunk(
                    delta=text if isinstance(text, str) else "",
                    model=str(payload.get("model") or request.model),
                    finish_reason="stop" if done else None,
                    usage=_parse_usage(payload) if done else None,
                )
                if chunk.delta or chunk.finish_reason:
                    yield chunk

    async def test_connection(self) -> ConnectionTest:
        started = perf_counter()
        try:
            models = await self._fetch_models(1)
        except ProviderNotConfigured as exc:
            return ConnectionTest(ok=False, latency_ms=0.0, detail=exc.message)
        except ProviderError as exc:
            elapsed = round((perf_counter() - started) * 1000, 1)
            return ConnectionTest(ok=False, latency_ms=elapsed, detail=exc.message)
        elapsed = round((perf_counter() - started) * 1000, 1)
        return ConnectionTest(
            ok=True, latency_ms=elapsed, detail="Connected", model_count=len(models)
        )

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
        self._client = None


def _chat_payload(request: CompletionRequest, *, stream: bool) -> dict[str, Any]:
    payload: dict[str, Any] = dict(request.extra)
    payload["model"] = request.model
    payload["messages"] = request.message_payloads()
    payload["stream"] = stream
    options: dict[str, Any] = {}
    if request.temperature is not None:
        options["temperature"] = request.temperature
    if request.max_tokens is not None:
        options["num_predict"] = request.max_tokens
    if options:
        payload["options"] = options
    return payload


def _parse_usage(payload: dict[str, Any]) -> TokenUsage | None:
    prompt = payload.get("prompt_eval_count")
    completion = payload.get("eval_count")
    if not isinstance(prompt, int) and not isinstance(completion, int):
        return None
    prompt_tokens = prompt if isinstance(prompt, int) else 0
    completion_tokens = completion if isinstance(completion, int) else 0
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )


def _parse_model(item: object) -> ModelInfo | None:
    if not isinstance(item, dict):
        return None
    model_id = item.get("model") or item.get("name")
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    details = item.get("details")
    metadata: dict[str, Any] = {}
    if isinstance(details, dict):
        for key in ("parameter_size", "family", "quantization_level"):
            if isinstance(details.get(key), str):
                metadata[key] = details[key]
    size = item.get("size")
    if isinstance(size, int):
        metadata["size_bytes"] = size
    return ModelInfo(
        id=model_id,
        name=model_id,
        provider="ollama",
        metadata=metadata,
    )
