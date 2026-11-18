# Development Status

Last updated: 2026-11-18

## Current milestone

**Milestone 2 — Model providers: implemented and validated locally.** Remote CI verification
pending for the new commit.

## Completed

- Milestone 1: foundation (settings, logging, FastAPI bootstrap, SQLite + Alembic, tests, CI).
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
- Provider abstraction (`orbit/providers`): vendor-neutral types and `ModelProvider` protocol,
  normalized error taxonomy, bounded retries with exponential backoff, SSE/NDJSON stream parsers.
- OpenRouter adapter: model discovery with pricing/context metadata, non-streaming completions,
  SSE streaming, connection testing, redacted upstream error mapping.
- Ollama adapter: `/api/tags` discovery, `/api/chat` completions and NDJSON streaming, connection
  testing, metadata (parameter size, quantization, size).
- Provider registry built from settings at startup and closed on shutdown.
- Endpoints: `GET /api/v1/providers`, `GET /api/v1/providers/{id}/models`,
  `POST /api/v1/providers/{id}/test`, `GET /api/v1/models`,
  `GET|PUT /api/v1/models/default` (persisted in `system_state`).
- Direct `starlette` dependency declared; provider retry settings exposed.

## In progress

- Milestone 2 implementation is complete locally and awaiting commit/CI approval.

## Pending

- Milestone 3: chat API, conversation persistence, SSE streaming over HTTP, context window.

## Latest test results

`pytest -q` → **61 passed** (unit, integration, security) on 2026-11-18.
`ruff check .` → clean. `ruff format --check .` → clean. `mypy` (strict) → clean (29 files).
Manual smoke test (arm64 VPS): start on `127.0.0.1:18704`, `GET /api/v1/providers` → OpenRouter
unconfigured / Ollama configured; unconfigured model discovery → `400 provider_not_configured`;
Ollama unreachable → `{"ok": false, "latency_ms": 0.9}`; `PUT /api/v1/models/default` persisted
across a process restart; aggregated discovery returned a partial-failure error entry.

## Known limitations

- No UI, CLI or agent runtime yet; no chat completion endpoint (streaming exists at adapter level).
- `system_state` is the only table; conversations/agents/memory arrive with their milestones.
- Settings are process-wide (cached); runtime reconfiguration is not exposed yet.
- Secrets are read from env/.env; OS keyring integration is not implemented yet.
- Development server binds to loopback only; no authentication layer exists yet (not needed for
  a local-only MVP, required before any remote exposure).
- The web UI and CLI entry points do not exist yet; `python -m orbit` is the only surface.
- Selected default model is not validated against live provider discovery; upstream may reject it.
- Streaming requests are not retried after the first token is emitted.

## Next recommended action

1. Review, commit and push Milestone 2; confirm CI is green.
2. Begin Milestone 3: conversations/messages schema + SSE `POST /api/v1/chat/completions` using the
   provider abstraction, with cancellation and persisted history.
