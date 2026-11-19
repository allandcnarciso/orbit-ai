"""OpenRouter provider adapter (chat completions + model discovery)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any

import httpx
from pydantic import SecretStr

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
    ProviderUnavailableError,
)
from orbit.providers.http import (
    error_for_response,
    iter_sse_json,
    request_json,
    stream_transport_error,
)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider:
    """Adapter for OpenRouter's OpenAI-compatible API."""

    id = "openrouter"
    display_name = "OpenRouter"
    capabilities = ProviderCapabilities(streaming=True, tools=False, vision=False, json_mode=True)

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
        retry_attempts: int = 3,
        retry_backoff: float = 0.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._retry_attempts = retry_attempts
        self._retry_backoff = retry_backoff
        self._client = client
        self._owns_client = client is None

    @property
    def configured(self) -> bool:
        return bool(self._secret())

    def _secret(self) -> str:
        if self._api_key is None:
            return ""
        return self._api_key.get_secret_value().strip()

    def _require_configured(self) -> None:
        if not self.configured:
            raise ProviderNotConfigured("OpenRouter API key is not configured.", provider=self.id)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + self._secret(),
            "Content-Type": "application/json",
        }

    async def list_models(self) -> list[ModelInfo]:
        return await self._fetch_models(self._retry_attempts)

    async def _fetch_models(self, attempts: int) -> list[ModelInfo]:
        self._require_configured()
        payload = await request_json(
            self._get_client(),
            "GET",
            f"{self._base_url}/models",
            provider=self.id,
            headers=self._headers(),
            timeout_seconds=self._timeout,
            attempts=attempts,
            backoff=self._retry_backoff,
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise ProviderInvalidResponseError(
                "OpenRouter model list is malformed.", provider=self.id
            )
        models = [model for item in data if (model := _parse_model(item)) is not None]
        models.sort(key=lambda model: model.id)
        return models

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self._require_configured()
        payload = await request_json(
            self._get_client(),
            "POST",
            f"{self._base_url}/chat/completions",
            provider=self.id,
            headers=self._headers(),
            payload=_chat_payload(request, stream=False),
            timeout_seconds=self._timeout,
            attempts=self._retry_attempts,
            backoff=self._retry_backoff,
        )
        if not isinstance(payload, dict):
            raise ProviderInvalidResponseError(
                "OpenRouter response is malformed.", provider=self.id
            )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderInvalidResponseError(
                "OpenRouter response contained no choices.", provider=self.id
            )
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ProviderInvalidResponseError(
                "OpenRouter response contained no message content.", provider=self.id
            )
        return CompletionResult(
            content=content,
            model=str(payload.get("model") or request.model),
            finish_reason=_as_str(choice.get("finish_reason")),
            usage=_parse_usage(payload.get("usage")),
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]:
        self._require_configured()
        client = self._get_client()
        try:
            async with client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=_chat_payload(request, stream=True),
                timeout=self._timeout,
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise error_for_response(response, provider=self.id)
                async for payload in iter_sse_json(response, provider=self.id):
                    if "error" in payload:
                        raise ProviderUnavailableError(
                            "OpenRouter stream reported an error.", provider=self.id
                        )
                    choices = payload.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice = choices[0] if isinstance(choices[0], dict) else {}
                    delta = choice.get("delta")
                    text = delta.get("content") if isinstance(delta, dict) else None
                    chunk = CompletionChunk(
                        delta=text if isinstance(text, str) else "",
                        model=str(payload.get("model") or request.model),
                        finish_reason=_as_str(choice.get("finish_reason")),
                    )
                    if chunk.delta or chunk.finish_reason:
                        yield chunk
        except ProviderError:
            raise
        except asyncio.CancelledError:
            raise
        except httpx.TimeoutException as exc:
            raise stream_transport_error(self.id, exc) from exc
        except httpx.HTTPError as exc:
            raise stream_transport_error(self.id, exc) from exc

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
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    return payload


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _parse_usage(value: object) -> TokenUsage | None:
    if not isinstance(value, dict):
        return None
    prompt = value.get("prompt_tokens")
    completion = value.get("completion_tokens")
    total = value.get("total_tokens")
    return TokenUsage(
        prompt_tokens=prompt if isinstance(prompt, int) else 0,
        completion_tokens=completion if isinstance(completion, int) else 0,
        total_tokens=total if isinstance(total, int) else 0,
    )


def _parse_model(item: object) -> ModelInfo | None:
    if not isinstance(item, dict):
        return None
    model_id = item.get("id")
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    pricing = item.get("pricing")
    prompt_price: float | None = None
    completion_price: float | None = None
    if isinstance(pricing, dict):
        prompt_price = _as_float(pricing.get("prompt"))
        completion_price = _as_float(pricing.get("completion"))
    context_length = item.get("context_length")
    top_provider = item.get("top_provider")
    max_completion = (
        top_provider.get("max_completion_tokens") if isinstance(top_provider, dict) else None
    )
    name = item.get("name")
    return ModelInfo(
        id=model_id,
        name=name if isinstance(name, str) and name.strip() else model_id,
        provider="openrouter",
        context_length=context_length if isinstance(context_length, int) else None,
        max_output_tokens=(
            max_completion if isinstance(max_completion, int) and max_completion > 0 else None
        ),
        prompt_price=prompt_price,
        completion_price=completion_price,
    )
