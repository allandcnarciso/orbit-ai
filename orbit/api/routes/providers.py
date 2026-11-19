"""Provider and model discovery endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from orbit.api.schemas import (
    ConnectionTestResponse,
    ModelInfoSchema,
    ModelListResponse,
    ProviderCapabilitiesSchema,
    ProviderStatus,
)
from orbit.providers.base import ModelProvider
from orbit.providers.registry import ProviderRegistry

router = APIRouter(prefix="/providers", tags=["providers"])


def _registry(request: Request) -> ProviderRegistry:
    registry: ProviderRegistry = request.app.state.providers
    return registry


def _provider(request: Request, provider_id: str) -> ModelProvider:
    provider = _registry(request).get(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_id}")
    return provider


@router.get("", response_model=list[ProviderStatus], summary="List configured providers")
async def list_providers(request: Request) -> list[ProviderStatus]:
    return [
        ProviderStatus(
            id=provider.id,
            name=provider.display_name,
            configured=provider.configured,
            capabilities=ProviderCapabilitiesSchema(
                streaming=provider.capabilities.streaming,
                tools=provider.capabilities.tools,
                vision=provider.capabilities.vision,
                json_mode=provider.capabilities.json_mode,
            ),
        )
        for provider in _registry(request).all()
    ]


@router.get(
    "/{provider_id}/models",
    response_model=ModelListResponse,
    summary="Discover models exposed by a provider",
)
async def list_models(provider_id: str, request: Request) -> ModelListResponse:
    provider = _provider(request, provider_id)
    models = await _registry(request).discover_models(provider)
    return ModelListResponse(
        provider=provider.id,
        count=len(models),
        models=[
            ModelInfoSchema(
                id=model.id,
                name=model.name,
                provider=model.provider,
                context_length=model.context_length,
                prompt_price=model.prompt_price,
                completion_price=model.completion_price,
                metadata=model.metadata,
            )
            for model in models
        ],
    )


@router.post(
    "/{provider_id}/test",
    response_model=ConnectionTestResponse,
    summary="Test provider connectivity",
)
async def test_provider(provider_id: str, request: Request) -> ConnectionTestResponse:
    provider = _provider(request, provider_id)
    try:
        result = await provider.test_connection()
    finally:
        # A fresh connectivity probe is the explicit refresh signal available
        # without changing the public API: discard any stale catalog entry.
        _registry(request).invalidate_models(provider.id)
    return ConnectionTestResponse(
        provider=provider.id,
        ok=result.ok,
        latency_ms=result.latency_ms,
        detail=result.detail,
        model_count=result.model_count,
    )
