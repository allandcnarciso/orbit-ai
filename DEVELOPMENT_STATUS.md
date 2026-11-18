# Development Status

Last updated: 2026-11-18

## Current milestone

**Milestone 1 — Foundation: implemented, pending final verification run.**

## Completed

- Repository and environment audit (Ubuntu 24.04 ARM64, Python 3.12.3, empty `.venv`).
- Verified `LICENSE` is the canonical Apache License 2.0 text.
- Project packaging (`pyproject.toml`, hatchling, `orbit-ai` distribution, `orbit` package).
- Settings layer: `ORBIT_*` environment variables, `.env` support, `SecretStr` credentials,
  platform-aware data/log directories, validation, derived SQLite URL.
- Structured logging: text/JSON formatters, request correlation fields, credential redaction.
- Persistence: async SQLAlchemy engine (aiosqlite), SQLite pragmas (FK, WAL, busy timeout),
  Alembic migrations with revision `0001_system_state`, `system_state` key/value store.
- FastAPI application factory with lifespan-managed database, startup migrations, startup state
  persistence, loopback defaults, CORS only when explicitly configured.
- Pure-ASGI request context middleware (`X-Request-ID`, `X-Process-Time-Ms`, one access log line).
- Uniform JSON error envelope for HTTP errors, validation errors and unhandled exceptions.
- Endpoints: `GET /health`, `GET /api/v1/health`, `GET /api/v1/system/info`, OpenAPI docs.
- Test suites: unit (config, logging, state store), integration (health, lifecycle, errors,
  migrations, request ids), security (secret leakage, redaction, error sanitisation).
- Developer documentation: README, AGENTS.md, ADRs, CONTRIBUTING, SECURITY, CI workflow.

## In progress

- None. Milestone 1 is complete and committed as `05f2026`; CI has not run remotely yet (push
  requires approval).

## Pending

- Milestone 2: provider abstraction, OpenRouter and Ollama adapters, model discovery,
  connection testing, streaming, error normalisation.

## Latest test results

`pytest -q` → **33 passed** (unit, integration, security) on 2026-11-18.
`ruff check .` → clean. `ruff format --check .` → clean. `mypy` (strict) → clean.
Manual smoke test: `python -m orbit` served `GET /health` → `200 {"status":"ok"}` on
`127.0.0.1:18700`, created `/var/lib/orbit-ai/orbit.db` (mode `0600`, data dir `0700`) and
applied revision `0001_system_state`.

## Known limitations

- No UI, CLI or agent runtime yet; the API exposes only health/system endpoints.
- `system_state` is the only table; conversations/agents/memory arrive with their milestones.
- Settings are process-wide (cached); runtime reconfiguration will be added with the provider
  manager.
- Secrets are read from env/.env; OS keyring integration is not implemented yet.
- Development server binds to loopback only; no authentication layer exists yet (not needed for
  a local-only MVP, required before any remote exposure).
- The web UI and CLI entry points do not exist yet; `python -m orbit` is the only surface.

## Next recommended action

1. Push `05f2026` and confirm the CI workflow is green (requires approval).
2. Begin Milestone 2 with the provider interface (`orbit/providers/base.py`) and an OpenRouter
   adapter tested against a mocked HTTP transport.
