"""Integration tests for health, system info, request ids and error envelopes."""

from __future__ import annotations

import os

import httpx
import pytest

from orbit import __version__


async def test_health_reports_ok_and_database(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["checks"]["database"] == "ok"


async def test_health_is_also_available_under_api_prefix(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_database_file_is_created_and_migrated(app) -> None:
    settings = app.state.settings
    assert settings.database_path.exists()

    from sqlalchemy import text

    async with app.state.db.engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == "0002_conversations_messages"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
async def test_database_file_is_owner_only(app) -> None:
    mode = app.state.settings.database_path.stat().st_mode & 0o777
    assert mode == 0o600
    assert app.state.settings.data_dir.stat().st_mode & 0o777 == 0o700


async def test_request_id_is_generated_and_returned(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    request_id = response.headers.get("x-request-id")
    assert request_id
    assert len(request_id) == 32
    assert "x-process-time-ms" in response.headers


async def test_valid_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "trace-42"})
    assert response.headers["x-request-id"] == "trace-42"


async def test_malformed_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "bad id with spaces"})
    assert response.headers["x-request-id"] != "bad id with spaces"
    assert len(response.headers["x-request-id"]) == 32


async def test_system_info(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/system/info")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "ORBIT AI"
    assert body["version"] == __version__
    assert body["api_version"] == "v1"
    assert body["environment"] == "test"
    assert body["started_at"]


async def test_unknown_route_uses_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"] == response.headers["x-request-id"]


async def test_unhandled_error_is_generic(settings) -> None:
    from orbit.api.app import create_app

    application = create_app(settings)

    @application.get("/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://orbit.test") as client:
        response = await client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "hunter2" not in response.text
    assert "RuntimeError" not in response.text


async def test_health_returns_503_when_database_is_unreachable(
    client: httpx.AsyncClient, app
) -> None:
    class BrokenDatabase:
        async def ping(self) -> None:
            raise RuntimeError("database is down")

    original = app.state.db
    app.state.db = BrokenDatabase()
    try:
        response = await client.get("/health")
    finally:
        app.state.db = original

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "error"


async def test_start_state_persists_across_restart(settings) -> None:
    from orbit.api.app import create_app
    from orbit.storage.system_state import SystemStateStore

    first = create_app(settings)
    from asgi_lifespan import LifespanManager

    async with LifespanManager(first):
        pass

    second = create_app(settings)
    async with LifespanManager(second):
        store = SystemStateStore(second.state.db.session_factory)
        last_started = await store.get("last_started_at")

    assert last_started is not None
    assert settings.database_path.exists()


@pytest.mark.parametrize("path", ["/openapi.json"])
async def test_openapi_schema_is_served(client: httpx.AsyncClient, path: str) -> None:
    response = await client.get(path)
    assert response.status_code == 200
    assert "/health" in response.json()["paths"]
