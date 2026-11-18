# Changelog

All notable changes to ORBIT AI are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Provider abstraction with vendor-neutral types, a `ModelProvider` protocol and a normalized
  error taxonomy (retryable rate limits/timeouts, auth failures, invalid responses).
- OpenRouter adapter: model discovery with pricing/context metadata, completions, SSE streaming,
  connection test, redacted error mapping, bounded retries with exponential backoff.
- Ollama adapter: `/api/tags` discovery, `/api/chat` completions and NDJSON streaming, metadata.
- Provider registry built from settings at startup and closed on shutdown.
- API: `GET /api/v1/providers`, `GET /api/v1/providers/{id}/models`,
  `POST /api/v1/providers/{id}/test`, `GET /api/v1/models`, `GET|PUT /api/v1/models/default`.
- Mocked-transport test suites for both adapters and the provider/model endpoints.
- Project packaging (`orbit-ai` distribution, `orbit` package, Python 3.12+, hatchling).
- Typed settings layer with `ORBIT_*` variables, `.env` support, `SecretStr` credentials and
  platform-aware data/log directory resolution.
- Structured logging with text and JSON formatters and credential redaction.
- Async SQLAlchemy/aiosqlite persistence with Alembic migrations (`0001_system_state`) and a
  `system_state` key/value store.
- FastAPI application factory with lifespan-managed database, startup migrations and startup
  state persistence.
- Request correlation middleware (`X-Request-ID`, `X-Process-Time-Ms`) and structured access logs.
- Uniform JSON error envelopes for HTTP, validation and unhandled errors.
- Endpoints: `GET /health`, `GET /api/v1/health`, `GET /api/v1/system/info`, OpenAPI docs.
- Unit, integration and security test suites.
- Developer documentation: README, AGENTS.md, ADRs, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT.
- GitHub Actions CI workflow (lint, type check, tests).

[Unreleased]: https://github.com/allandcnarciso/orbit-ai/commits/main
