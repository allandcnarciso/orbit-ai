"""Model discovery cache: TTL, invalidation, isolation and concurrency."""

from __future__ import annotations

import asyncio

from orbit.providers.base import ModelInfo
from orbit.providers.registry import ModelCatalog
from tests.fakes import FakeProvider


class BlockingProvider(FakeProvider):
    """Yield discovery only after the test releases it, to force overlap."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def list_models(self) -> list[ModelInfo]:
        self.started.set()
        await self.release.wait()
        return await super().list_models()


async def test_first_discovery_then_cache_reuse() -> None:
    provider = FakeProvider(model_ids=["one", "two"])
    catalog = ModelCatalog(ttl_seconds=60)

    first = await catalog.models(provider)
    second = await catalog.models(provider)

    assert [model.id for model in first] == ["one", "two"]
    assert second is first
    assert provider.list_calls == 1


async def test_cache_expires_after_ttl() -> None:
    provider = FakeProvider()
    catalog = ModelCatalog(ttl_seconds=0.01)

    await catalog.models(provider)
    await asyncio.sleep(0.02)
    await catalog.models(provider)

    assert provider.list_calls == 2


async def test_explicit_invalidation_forces_rediscovery() -> None:
    provider = FakeProvider()
    catalog = ModelCatalog(ttl_seconds=60)

    await catalog.models(provider)
    catalog.invalidate(provider.id)
    await catalog.models(provider)

    assert provider.list_calls == 2


async def test_invalidation_is_scoped_to_one_provider() -> None:
    first = FakeProvider(id="one")
    second = FakeProvider(id="two")
    catalog = ModelCatalog(ttl_seconds=60)

    await catalog.models(first)
    await catalog.models(second)
    catalog.invalidate("one")
    await catalog.models(first)
    await catalog.models(second)

    assert first.list_calls == 2
    assert second.list_calls == 1


async def test_concurrent_discovery_calls_one_provider_once() -> None:
    provider = BlockingProvider()
    catalog = ModelCatalog(ttl_seconds=60)

    first = asyncio.create_task(catalog.models(provider))
    await asyncio.wait_for(provider.started.wait(), timeout=1)
    second = asyncio.create_task(catalog.models(provider))
    await asyncio.sleep(0)
    provider.release.set()

    first_models, second_models = await asyncio.gather(first, second)

    assert first_models is second_models
    assert provider.list_calls == 1
