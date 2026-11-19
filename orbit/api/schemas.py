"""Pydantic response schemas for the public API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, Field, field_validator, model_validator


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


def _ensure_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive datetimes to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_ensure_utc)]


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    provider: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=256)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("title must not be blank")
        return cleaned


class ConversationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    provider: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=256)
    status: Literal["active", "archived"] | None = None

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("title must not be blank")
        return cleaned

    @model_validator(mode="after")
    def _require_change(self) -> ConversationUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        return self


class ConversationResponse(BaseModel):
    id: str
    title: str
    provider: str | None = None
    model: str | None = None
    status: str
    created_at: UtcDatetime
    updated_at: UtcDatetime
    last_message_at: UtcDatetime | None = None


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    total: int
    limit: int
    offset: int


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    sequence: int
    role: str
    content: str
    status: str
    provider: str | None = None
    model: str | None = None
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class MessageListResponse(BaseModel):
    items: list[MessageResponse]
    has_more: bool
    next_before_sequence: int | None = None


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=32000)
    provider: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=256)
    stream: bool = False
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=32000)
    client_message_id: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("content")
    @classmethod
    def _reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class SendMessageResponse(BaseModel):
    user_message: MessageResponse
    assistant_message: MessageResponse


class CancelGenerationResponse(BaseModel):
    cancelled: bool
    message_id: str | None = None
