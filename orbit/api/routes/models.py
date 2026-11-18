"""Aggregated model discovery and default model selection."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from orbit.api.schemas import (
    AggregatedModelsResponse,
    ModelInfoSchema,
    ModelSelection,
    ProviderErrorInfo,
)
from orbit.providers.base import ModelInfo
from orbit.providers.errors import ProviderError, ProviderNotConfigured
from orbit.providers.registry import ProviderRegistry
from orbit.storage.system_state import SystemStateStore

router = APIRouter(prefix="/models", tags=["models"])

_SELECTION_KEY = "default_model"


def _registry(request: Request) -> ProviderRegistry:
    registry: ProviderRegistry = request.app.state.providers
    return registry


def _store(request: Request) -> SystemStateStore:
    return SystemStateStore(request.app.state.db.session_factory)


def _to_schema(model: ModelInfo) -> ModelInfoSchema:
    return ModelInfoSchema(
        id=model.id,
        name=model.name,
        provider=model.provider,
        context_length=model.context_length,
        prompt_price=model.prompt_price,
        completion_price=model.completion_price,
        metadata=model.metadata,
    )


@router.get(
    "",
    response_model=AggregatedModelsResponse,
    summary="List models from configured providers",
)
async def aggregate_models(request: Request) -> AggregatedModelsResponse:
    response = AggregatedModelsResponse()
    for provider in _registry(request).configured():
        try:
            models = await provider.list_models()
        except ProviderNotConfigured:
            continue
        except ProviderError as exc:
            response.errors.append(
                ProviderErrorInfo(provider=provider.id, code=exc.code, message=exc.message)
            )
            continue
        response.models.extend(_to_schema(model) for model in models)
    response.models.sort(key=lambda item: (item.provider, item.id))
    return response


@router.get("/default", response_model=ModelSelection | None, summary="Read the default model")
async def get_default_model(request: Request) -> ModelSelection | None:
    raw = await _store(request).get(_SELECTION_KEY)
    if not raw:
        return None
    try:
        return ModelSelection.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError):
        return None


@router.put("/default", response_model=ModelSelection, summary="Select the default model")
async def set_default_model(payload: ModelSelection, request: Request) -> ModelSelection:
    provider = _registry(request).get(payload.provider)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {payload.provider}")
    if not provider.configured:
        raise ProviderNotConfigured(
            f"Provider {payload.provider} is not configured.", provider=payload.provider
        )
    await _store(request).set(
        _SELECTION_KEY,
        json.dumps({"provider": payload.provider, "model": payload.model}),
    )
    return payload
