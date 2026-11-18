"""HTTP helpers shared by provider adapters: retries, error mapping, SSE."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from orbit.providers.errors import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

_logger = logging.getLogger("orbit.providers.http")
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    provider: str,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float,
    attempts: int = 3,
    backoff: float = 0.5,
) -> Any:
    """Perform a JSON request with bounded retries for transient failures."""
    attempts = max(1, attempts)
    for attempt in range(1, attempts + 1):
        try:
            response = await client.request(
                method, url, headers=headers, json=payload, timeout=timeout_seconds
            )
        except httpx.TimeoutException as exc:
            error: ProviderError = ProviderTimeoutError(
                f"{provider} timed out after {timeout_seconds:g}s", provider=provider
            )
            if attempt < attempts:
                await asyncio.sleep(backoff * (2 ** (attempt - 1)))
                continue
            raise error from exc
        except httpx.HTTPError as exc:
            unavailable = ProviderUnavailableError(f"Could not reach {provider}", provider=provider)
            if attempt < attempts:
                await asyncio.sleep(backoff * (2 ** (attempt - 1)))
                continue
            raise unavailable from exc

        if response.status_code >= 400:
            mapped = error_for_response(response, provider=provider)
            if mapped.retryable and attempt < attempts:
                await asyncio.sleep(backoff * (2 ** (attempt - 1)))
                continue
            raise mapped

        try:
            return response.json()
        except ValueError as exc:
            raise ProviderInvalidResponseError(
                f"{provider} returned a non-JSON response", provider=provider
            ) from exc

    raise ProviderUnavailableError(f"Could not reach {provider}", provider=provider)


def _extract_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip()[:200]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("detail") or "")[:200]
        if isinstance(error, str):
            return error[:200]
        for key in ("message", "detail"):
            value = payload.get(key)
            if isinstance(value, str):
                return value[:200]
    return ""


def error_for_response(response: httpx.Response, *, provider: str) -> ProviderError:
    """Map an upstream HTTP failure onto the normalised provider taxonomy."""
    status = response.status_code
    detail = _extract_error_message(response)
    message = f"{provider} request failed ({status})"
    if detail:
        message = f"{message}: {detail}"
    kwargs: dict[str, Any] = {"provider": provider, "upstream_status": status}
    if status in (401, 403):
        return ProviderAuthenticationError(message, **kwargs)
    if status == 429:
        return ProviderRateLimitError(message, **kwargs)
    if status in (400, 404, 422):
        return ProviderRequestError(message, **kwargs)
    if status >= 500:
        return ProviderUnavailableError(message, **kwargs)
    return ProviderInvalidResponseError(message, **kwargs)


async def iter_sse_json(
    response: httpx.Response, *, provider: str
) -> AsyncIterator[dict[str, Any]]:
    """Yield JSON objects from a text/event-stream body."""
    async for line in response.aiter_lines():
        stripped = line.strip()
        if not stripped or stripped.startswith(":"):
            continue
        if not stripped.startswith("data:"):
            continue
        data = stripped[len("data:") :].strip()
        if not data or data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            _logger.debug("%s stream: skipping malformed payload", provider)
            continue
        if isinstance(payload, dict):
            yield payload
