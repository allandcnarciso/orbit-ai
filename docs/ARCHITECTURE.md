# Architecture Overview

## Shape

ORBIT AI is a modular monolith. One Python package, one process per installation, explicit
module boundaries, no internal network hops.

```
+---------------------------------------------------------------+
| Surfaces:  React Web UI   |   Typer CLI   |   REST/SSE clients |
+---------------------------------------------------------------+
                              |
+---------------------------------------------------------------+
| API layer          FastAPI app factory, routers, schemas,     |
|                    middleware, error envelope                 |
+---------------------------------------------------------------+
| Domain services    providers · agents/runtime · tools ·       |
|                    memory · skills · security · orchestrator  |
+---------------------------------------------------------------+
| Core               settings · logging · lifecycle · i18n      |
| Storage            async SQLAlchemy · SQLite · Alembic        |
+---------------------------------------------------------------+
```

The web UI and CLI are clients of the same API/services; business logic never lives in a
surface. The agent runtime depends on `providers` interfaces, never on a specific vendor.

## Request lifecycle

1. The ASGI server calls the app built by `create_app(settings)`.
2. `RequestContextMiddleware` assigns/validates `X-Request-ID` and starts a timer.
3. The router resolves the handler; dependencies in `orbit/api/deps.py` provide the database and
   request-scoped sessions.
4. Handler errors become the standard envelope via `orbit/api/errors.py`; unexpected exceptions
   are logged with a traceback and reported generically.
5. The middleware adds correlation/timing headers and emits one access log line.

## Startup and shutdown

`orbit.api.app.lifespan`:

1. Ensures data/log directories exist (mode `0700`).
2. Configures logging (idempotent, redacting).
3. Creates the async engine (SQLite pragmas: foreign keys, WAL, busy timeout).
4. Applies Alembic migrations in a worker thread when `ORBIT_AUTO_MIGRATE=true`.
5. Pings the database, records `last_started_at` in `system_state`.
6. On shutdown, disposes the engine.

Configuration is validated at process start; an invalid setting aborts the process instead of
producing a half-configured server.

## Configuration

`orbit/core/config.py` defines `Settings` (`ORBIT_*`, optional `.env`). Data and log directories
default to `/var/lib/orbit-ai` and `/var/log/orbit-ai` when writable and fall back to per-user
XDG/`LOCALAPPDATA` paths, so the same code works on a VPS and on a developer laptop.

## Persistence

- `orbit/storage/models.py` — declarative models (`SystemState` today).
- `orbit/storage/db.py` — engine creation, session factory, migration runner.
- `orbit/storage/migrations/` — Alembic environment and revisions. Schema changes ship as
  revisions; application code never calls `create_all`.
- SQLite is the MVP database. Repository interfaces keep PostgreSQL/vector stores possible later.

## Observability

- One access log line per request with method, path, status, duration and request id.
- JSON logging opt-in (`ORBIT_LOG_JSON`) for machine ingestion.
- `/health` reports database reachability; `/api/v1/system/info` reports build/runtime metadata.
- Agent traces, token/cost accounting and an audit log arrive with the runtime and security
  milestones.

## Planned modules (not yet implemented)

| Module | Responsibility |
| --- | --- |
| `orbit/providers` | Provider protocol, OpenRouter/Ollama adapters, discovery, streaming |
| `orbit/agents` | Agent definitions, execution loop, planning, limits, retries |
| `orbit/orchestrator` | Task submission/state/history; multi-agent coordination |
| `orbit/tools` | Tool registry, schemas, permissions, sandboxed execution |
| `orbit/memory` | Conversation, short-term and persistent memory with retrieval |
| `orbit/skills` | Skill discovery/installation/activation and permissions |
| `orbit/security` | Credential vault, permission policies, approvals, audit log |
| `orbit/i18n` | pt-BR / en-US / es-ES message catalogues for API and UI |

Each module lands with tests and an ADR if it changes the architecture.
