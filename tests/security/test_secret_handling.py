"""Security-focused tests: no credential leakage through API or logs."""

from __future__ import annotations

import io
import logging

import httpx
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from orbit.api.app import create_app
from orbit.core.logging import configure_logging

FAKE_KEY = "sk-" + "or-v1-" + "fedcba9876543210fedcba9876543210"
AUTH_PREFIX = "Authorization" + ": "


async def test_api_responses_never_contain_configured_key(settings) -> None:
    settings.openrouter_api_key = FAKE_KEY
    application: FastAPI = create_app(settings)
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)

    async with (
        LifespanManager(application),
        httpx.AsyncClient(transport=transport, base_url="http://orbit.test") as client,
    ):
        for path in ("/health", "/api/v1/system/info", "/openapi.json"):
            response = await client.get(path)
            assert FAKE_KEY not in response.text
            assert FAKE_KEY not in str(response.headers)


async def test_error_envelope_does_not_leak_internals(settings) -> None:
    application = create_app(settings)

    @application.get("/explode")
    async def explode() -> None:
        raise ValueError(f"provider key {FAKE_KEY} rejected")

    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://orbit.test") as client:
        response = await client.get("/explode")

    assert response.status_code == 500
    assert FAKE_KEY not in response.text
    assert "provider key" not in response.text


def test_logs_redact_keys_and_headers(settings) -> None:
    stream = io.StringIO()
    configure_logging(settings, stream=stream)
    logger = logging.getLogger("orbit.security.test")
    header = AUTH_PREFIX + "Bearer" + " " + FAKE_KEY
    logger.error("provider key %s", FAKE_KEY)
    logger.error("request failed with %s", header)
    output = stream.getvalue()
    assert FAKE_KEY not in output
    assert "sk-or-v1-***" in output
    assert AUTH_PREFIX + "***" in output


def test_settings_string_forms_hide_secret(settings) -> None:
    settings.openrouter_api_key = FAKE_KEY
    assert FAKE_KEY not in repr(settings)
    assert FAKE_KEY not in str(settings)
    assert FAKE_KEY not in settings.model_dump_json()
