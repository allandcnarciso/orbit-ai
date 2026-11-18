"""Model provider abstraction: interfaces, adapters and registry."""

from orbit.providers.base import (
    ChatMessage,
    CompletionChunk,
    CompletionRequest,
    CompletionResult,
    ConnectionTest,
    ModelInfo,
    ModelProvider,
    ProviderCapabilities,
    Role,
    TokenUsage,
)
from orbit.providers.errors import (
    ModelNotFoundError,
    ProviderAuthenticationError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderNotConfigured,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from orbit.providers.registry import ProviderRegistry, build_registry

__all__ = [
    "ChatMessage",
    "CompletionChunk",
    "CompletionRequest",
    "CompletionResult",
    "ConnectionTest",
    "ModelInfo",
    "ModelNotFoundError",
    "ModelProvider",
    "ProviderAuthenticationError",
    "ProviderCapabilities",
    "ProviderError",
    "ProviderInvalidResponseError",
    "ProviderNotConfigured",
    "ProviderRateLimitError",
    "ProviderRegistry",
    "ProviderRequestError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "Role",
    "TokenUsage",
    "build_registry",
]
