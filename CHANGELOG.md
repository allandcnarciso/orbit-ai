# Changelog

All notable changes to ORBIT AI are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
