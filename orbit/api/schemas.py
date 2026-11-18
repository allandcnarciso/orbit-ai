"""Pydantic response schemas for the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    version: str
    checks: dict[str, str] = Field(default_factory=dict)


class SystemInfoResponse(BaseModel):
    name: str
    version: str
    api_version: str
    environment: str
    python: str
    platform: str
    architecture: str
    started_at: datetime


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: Any | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
