"""Normalised provider errors.

Adapters never leak vendor payloads or credentials to clients: messages are
redacted and truncated, and each error maps to a stable API status and code.
"""

from __future__ import annotations

from orbit.core.logging import redact

_MAX_MESSAGE_LENGTH = 300


class ProviderError(Exception):
    """Base class for every provider failure."""

    code = "provider_error"
    http_status = 502
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        upstream_status: int | None = None,
        retryable: bool | None = None,
    ) -> None:
        self.raw_message = message
        self.message = redact(message).strip()[:_MAX_MESSAGE_LENGTH] or "Provider request failed."
        self.provider = provider
        self.upstream_status = upstream_status
        if retryable is not None:
            self.retryable = retryable
        super().__init__(self.message)


class ProviderNotConfigured(ProviderError):
    code = "provider_not_configured"
    http_status = 400


class ProviderAuthenticationError(ProviderError):
    code = "provider_auth_error"
    http_status = 502


class ProviderRateLimitError(ProviderError):
    code = "provider_rate_limited"
    http_status = 503
    retryable = True


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"
    http_status = 504
    retryable = True


class ProviderUnavailableError(ProviderError):
    code = "provider_unavailable"
    http_status = 502
    retryable = True


class ProviderRequestError(ProviderError):
    code = "provider_bad_request"
    http_status = 502


class ProviderInvalidResponseError(ProviderError):
    code = "provider_invalid_response"
    http_status = 502


class ModelNotFoundError(ProviderError):
    code = "model_not_found"
    http_status = 404
