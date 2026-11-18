"""FastAPI dependencies shared by API routes."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from orbit.storage.db import Database


def get_database(request: Request) -> Database:
    database: Database = request.app.state.db
    return database


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session; routes own the commit boundary."""
    database = get_database(request)
    async with database.session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
