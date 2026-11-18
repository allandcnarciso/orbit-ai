"""Typed helpers for the ``system_state`` key/value table."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orbit.storage.models import SystemState


class SystemStateStore:
    """Small persistence facade used for first-run and lifecycle state."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, key: str) -> str | None:
        async with self._session_factory() as session:
            result: str | None = await session.scalar(
                select(SystemState.value).where(SystemState.key == key)
            )
            return result

    async def set(self, key: str, value: str) -> None:
        async with self._session_factory() as session:
            row = await session.get(SystemState, key)
            if row is None:
                session.add(SystemState(key=key, value=value))
            else:
                row.value = value
            await session.commit()

    async def delete(self, key: str) -> bool:
        async with self._session_factory() as session:
            result = cast(
                "CursorResult[Any]",
                await session.execute(delete(SystemState).where(SystemState.key == key)),
            )
            await session.commit()
            return bool(result.rowcount)
