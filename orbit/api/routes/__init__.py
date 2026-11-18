"""Versioned API router."""

from fastapi import APIRouter

from orbit.api.routes import health, models, providers, system

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(system.router)
api_router.include_router(providers.router)
api_router.include_router(models.router)

__all__ = ["api_router"]
