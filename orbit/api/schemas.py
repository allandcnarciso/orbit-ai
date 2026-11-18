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


class ProviderCapabilitiesSchema(BaseModel):
    streaming: bool
    tools: bool
    vision: bool
    json_mode: bool


class ProviderStatus(BaseModel):
    id: str
    name: str
    configured: bool
    capabilities: ProviderCapabilitiesSchema


class ModelInfoSchema(BaseModel):
    id: str
    name: str
    provider: str
    context_length: int | None = None
    prompt_price: float | None = None
    completion_price: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelListResponse(BaseModel):
    provider: str
    count: int
    models: list[ModelInfoSchema]


class ConnectionTestResponse(BaseModel):
    provider: str
    ok: bool
    latency_ms: float
    detail: str | None = None
    model_count: int | None = None


class ProviderErrorInfo(BaseModel):
    provider: str
    code: str
    message: str


class AggregatedModelsResponse(BaseModel):
    models: list[ModelInfoSchema] = Field(default_factory=list)
    errors: list[ProviderErrorInfo] = Field(default_factory=list)


class ModelSelection(BaseModel):
    provider: str
    model: str = Field(min_length=1, max_length=256)
