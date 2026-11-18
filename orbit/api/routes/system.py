"""System metadata endpoints used by the CLI and the web UI."""

from __future__ import annotations

import platform as platform_module

from fastapi import APIRouter, Request

from orbit import __version__
from orbit.api.schemas import SystemInfoResponse
from orbit.core.config import APP_NAME

router = APIRouter(tags=["system"])

API_VERSION = "v1"


@router.get("/system/info", response_model=SystemInfoResponse, summary="Runtime information")
async def system_info(request: Request) -> SystemInfoResponse:
    settings = request.app.state.settings
    started_at = request.app.state.started_at
    return SystemInfoResponse(
        name=APP_NAME,
        version=__version__,
        api_version=API_VERSION,
        environment=settings.env,
        python=platform_module.python_version(),
        platform=platform_module.system(),
        architecture=platform_module.machine(),
        started_at=started_at,
    )
