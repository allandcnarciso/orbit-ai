"""Versioned API router."""

from fastapi import APIRouter

from orbit.api.routes import health, system

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(system.router)

__all__ = ["api_router"]
