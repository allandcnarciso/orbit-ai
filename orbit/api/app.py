"""FastAPI application factory and lifecycle management."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from orbit import __version__
from orbit.api.errors import install_exception_handlers
from orbit.api.middleware import RequestContextMiddleware
from orbit.api.routes import api_router
from orbit.api.routes import health as health_routes
from orbit.core.config import APP_NAME, Settings, get_settings
from orbit.core.logging import configure_logging
from orbit.providers.registry import build_registry
from orbit.storage.db import Database, run_migrations
from orbit.storage.system_state import SystemStateStore

_logger = logging.getLogger("orbit.api.lifecycle")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    settings.ensure_directories()
    configure_logging(settings)

    database = Database(settings)
    app.state.db = database
    providers = build_registry(settings)
    app.state.providers = providers
    try:
        if settings.auto_migrate:
            await asyncio.to_thread(run_migrations, settings)
        await database.ping()

        started_at = datetime.now(tz=UTC)
        app.state.started_at = started_at
        await SystemStateStore(database.session_factory).set(
            "last_started_at", started_at.isoformat()
        )
        _logger.info(
            "ORBIT AI %s started (env=%s, data_dir=%s)",
            __version__,
            settings.env,
            settings.data_dir,
        )
        yield
    finally:
        await providers.aclose()
        await database.dispose()
        _logger.info("ORBIT AI stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the ORBIT AI FastAPI application.

    The app factory is used by the server entry point, the CLI and the tests so
    all three share one configuration and one lifecycle.
    """
    resolved = settings or get_settings()
    configure_logging(resolved)

    app = FastAPI(
        title=APP_NAME,
        version=__version__,
        description=(
            "Open-source Agentic AI Harness. One Harness. Any Model. Infinite Possibilities."
        ),
        docs_url="/docs" if resolved.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if resolved.docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = resolved

    app.add_middleware(RequestContextMiddleware)
    if resolved.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
        )

    install_exception_handlers(app)
    app.include_router(health_routes.router)
    app.include_router(api_router, prefix=resolved.api_prefix)
    return app
