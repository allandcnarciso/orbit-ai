"""Async database engine, session factory and migration runner."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from orbit.core.config import Settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the async engine for the configured database."""
    settings.ensure_directories()
    sqlite_path = _prepare_sqlite_file(settings)
    engine = create_async_engine(
        settings.resolved_database_url,
        echo=settings.debug,
        pool_pre_ping=True,
    )

    if sqlite_path is not None:
        _install_sqlite_pragmas(engine, sqlite_path)

    return engine


def _prepare_sqlite_file(settings: Settings) -> Path | None:
    """Create the SQLite file with owner-only permissions when file-backed.

    The database will hold provider credentials and conversation history, so it
    must never be group/world readable. SQLite respects an existing file's mode;
    WAL/SHM siblings inherit the private parent directory.
    """
    url = make_url(settings.resolved_database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None

    path = Path(url.database)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
    return path


def _install_sqlite_pragmas(engine: AsyncEngine, database_path: Path) -> None:
    """Enable foreign keys and WAL journaling for file-backed SQLite."""

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()
        if os.name != "nt":
            with contextlib.suppress(OSError):
                database_path.chmod(0o600)


def run_migrations(settings: Settings) -> None:
    """Apply all pending Alembic migrations for ``settings``.

    Runs synchronously; call it from ``asyncio.to_thread`` when inside an event
    loop.
    """
    settings.ensure_directories()
    config = AlembicConfig()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    # ConfigParser interpolation requires escaping percent signs in URLs.
    config.set_main_option("sqlalchemy.url", settings.resolved_database_url.replace("%", "%%"))
    command.upgrade(config, "head")


class Database:
    """Owns the engine and produces scoped async sessions."""

    def __init__(self, settings: Settings) -> None:
        self._engine = create_engine(settings)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    async def ping(self) -> None:
        """Raise if the database cannot execute a trivial query."""
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self._engine.dispose()
