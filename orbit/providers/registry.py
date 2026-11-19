"""Provider registry owned by the application lifespan."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable

import httpx

from orbit.core.config import Settings
from orbit.providers.base import ModelInfo, ModelProvider
from orbit.providers.ollama import OllamaProvider
from orbit.providers.openrouter import OpenRouterProvider

MODEL_CACHE_TTL_SECONDS = 60.0


class ModelCatalog:
    """Per-provider discovery cache with a short TTL (no cross-provider lock)."""

    def __init__(self, ttl_seconds: float = MODEL_CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, tuple[float, list[ModelInfo]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def models(self, provider: ModelProvider) -> list[ModelInfo]:
        now = time.monotonic()
        cached = self._entries.get(provider.id)
        if cached is not None and cached[0] > now:
            return cached[1]

        lock = self._locks.setdefault(provider.id, asyncio.Lock())
        async with lock:
            cached = self._entries.get(provider.id)
            if cached is not None and cached[0] > time.monotonic():
                return cached[1]
            models = await provider.list_models()
            self._entries[provider.id] = (time.monotonic() + self._ttl, models)
            return models

    def invalidate(self, provider_id: str | None = None) -> None:
        if provider_id is None:
            self._entries.clear()
        else:
            self._entries.pop(provider_id, None)


class ProviderRegistry:
    """Holds one adapter instance per provider id."""

    def __init__(
        self,
        providers: Iterable[ModelProvider],
        *,
        shared_client: httpx.AsyncClient | None = None,
        catalog: ModelCatalog | None = None,
    ) -> None:
        self._providers = {provider.id: provider for provider in providers}
        self._shared_client = shared_client
        self.catalog = catalog or ModelCatalog()

    async def discover_models(self, provider: ModelProvider) -> list[ModelInfo]:
        """Return models for ``provider``, cached for the configured TTL."""
        return await self.catalog.models(provider)

    def invalidate_models(self, provider_id: str | None = None) -> None:
        """Drop cached discovery for one provider, or all providers."""
        self.catalog.invalidate(provider_id)

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
