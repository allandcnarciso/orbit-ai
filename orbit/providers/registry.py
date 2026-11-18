"""Provider registry owned by the application lifespan."""

from __future__ import annotations

from collections.abc import Iterable

import httpx

from orbit.core.config import Settings
from orbit.providers.base import ModelProvider
from orbit.providers.ollama import OllamaProvider
from orbit.providers.openrouter import OpenRouterProvider


class ProviderRegistry:
    """Holds one adapter instance per provider id."""

    def __init__(
        self,
        providers: Iterable[ModelProvider],
        *,
        shared_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._providers = {provider.id: provider for provider in providers}
        self._shared_client = shared_client

    def get(self, provider_id: str) -> ModelProvider | None:
        return self._providers.get(provider_id)

    def all(self) -> list[ModelProvider]:
        return list(self._providers.values())

    def configured(self) -> list[ModelProvider]:
        return [provider for provider in self._providers.values() if provider.configured]

    async def aclose(self) -> None:
        for provider in self._providers.values():
            await provider.aclose()
        if self._shared_client is not None:
            await self._shared_client.aclose()
            self._shared_client = None


def build_registry(
    settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> ProviderRegistry:
    """Create adapters from settings; ``transport`` is used by tests."""
    shared_client: httpx.AsyncClient | None = None
    if transport is not None:
        shared_client = httpx.AsyncClient(
            transport=transport, timeout=settings.request_timeout_seconds
        )

    providers: list[ModelProvider] = [
        OpenRouterProvider(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            timeout=settings.request_timeout_seconds,
            retry_attempts=settings.provider_max_attempts,
            retry_backoff=settings.provider_retry_backoff_seconds,
            client=shared_client,
        ),
        OllamaProvider(
            base_url=settings.ollama_base_url,
            timeout=settings.request_timeout_seconds,
            retry_attempts=settings.provider_max_attempts,
            retry_backoff=settings.provider_retry_backoff_seconds,
            client=shared_client,
        ),
    ]
    return ProviderRegistry(providers, shared_client=shared_client)
