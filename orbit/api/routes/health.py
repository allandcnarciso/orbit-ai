"""Liveness and readiness endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from orbit import __version__
from orbit.api.schemas import HealthResponse

router = APIRouter(tags=["health"])
_logger = logging.getLogger("orbit.api.health")


@router.get("/health", response_model=HealthResponse, summary="Liveness and database check")
async def health(request: Request) -> HealthResponse | JSONResponse:
    database = request.app.state.db
    try:
        await database.ping()
    except Exception:
        _logger.exception("Database health check failed")
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "version": __version__,
                "checks": {"database": "error"},
            },
        )
    return HealthResponse(status="ok", version=__version__, checks={"database": "ok"})
