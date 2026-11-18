"""Unit tests for the system_state store."""

from __future__ import annotations

from orbit.storage.db import Database
from orbit.storage.system_state import SystemStateStore


async def test_set_get_and_upsert(database: Database) -> None:
    store = SystemStateStore(database.session_factory)
    assert await store.get("missing") is None

    await store.set("onboarding", "pending")
    assert await store.get("onboarding") == "pending"

    await store.set("onboarding", "complete")
    assert await store.get("onboarding") == "complete"


async def test_delete(database: Database) -> None:
    store = SystemStateStore(database.session_factory)
    await store.set("temporary", "1")
    assert await store.delete("temporary") is True
    assert await store.get("temporary") is None
    assert await store.delete("temporary") is False
