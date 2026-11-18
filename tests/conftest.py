"""Shared pytest fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from orbit.api.app import create_app
from orbit.core.config import Settings
from orbit.storage.db import Database, run_migrations


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Isolated settings pointing at a temporary data directory."""
    return Settings(
        _env_file=None,
        env="test",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        log_level="WARNING",
        log_json=False,
        cors_origins=[],
    )


@pytest.fixture
async def database(settings: Settings) -> AsyncIterator[Database]:
    settings.ensure_directories()
    await asyncio.to_thread(run_migrations, settings)
    db = Database(settings)
    try:
        yield db
    finally:
        await db.dispose()


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://orbit.test") as client:
        yield client
