# ORBIT AI

**One Harness. Any Model. Infinite Possibilities.**

ORBIT AI is an open-source, cross-platform **Agentic AI Harness**: a single environment to
create, configure, operate and inspect AI agents across cloud and local models, with a shared
runtime behind a Web UI, a CLI and a documented REST API.

> Status: **pre-alpha**. Milestone 1 (foundation) is implemented; the agent runtime, providers,
> chat, tools, memory and the web interface are in progress. See
> [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md).

## Why ORBIT AI

- **Model-agnostic.** OpenRouter and Ollama first, OpenAI-compatible endpoints next. No vendor
  lock-in in the agent runtime.
- **One core, three surfaces.** The Web UI, CLI and API share the same settings, runtime and
  database.
- **Secure defaults.** Loopback-only development server, explicit tool permissions, human
  approval for protected actions, credentials never stored or logged in plaintext.
- **Local-first.** SQLite storage, no external services required, runs on Linux, macOS and
  Windows.

## Requirements

- Python **3.12+**
- Linux x64/ARM64, macOS, or Windows 10/11 (Node.js 18+ only needed to build the web UI)

## Quickstart (development)

```bash
git clone https://github.com/allandcnarciso/orbit-ai.git
cd orbit-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env       # optional; safe defaults work out of the box
python -m orbit            # serves http://127.0.0.1:18700
```

Verify the installation:

```bash
curl -s http://127.0.0.1:18700/health
curl -s http://127.0.0.1:18700/api/v1/system/info
```

Interactive API docs: <http://127.0.0.1:18700/docs>

## Configuration

All settings are environment variables with the `ORBIT_` prefix, optionally loaded from `.env`
in the working directory. Secrets are read as `SecretStr` and are redacted from logs.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ORBIT_ENV` | `development` | `development`, `test` or `production` |
| `ORBIT_HOST` | `127.0.0.1` | Bind address; keep loopback unless you know why |
| `ORBIT_PORT` | `18700` | HTTP port |
| `ORBIT_DATA_DIR` | `/var/lib/orbit-ai` if writable, else `~/.local/share/orbit-ai` | Database and user data |
| `ORBIT_LOG_DIR` | `/var/log/orbit-ai` if writable, else `<data>/logs` | Log destination |
| `ORBIT_DATABASE_URL` | derived from `ORBIT_DATA_DIR` | Full SQLAlchemy URL override |
| `ORBIT_AUTO_MIGRATE` | `true` | Apply pending migrations on startup |
| `ORBIT_LOG_LEVEL` | `INFO` | `DEBUG` … `CRITICAL` |
| `ORBIT_LOG_JSON` | `false` | Emit JSON log lines |
| `ORBIT_DOCS_ENABLED` | `true` | Serve `/docs` and `/openapi.json` |
| `ORBIT_CORS_ORIGINS` | empty | Allowed browser origins (JSON list or comma-separated) |
| `ORBIT_OPENROUTER_API_KEY` | unset | OpenRouter credential (never commit) |
| `ORBIT_OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter-compatible endpoint |
| `ORBIT_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local Ollama endpoint |
| `ORBIT_REQUEST_TIMEOUT_SECONDS` | `120` | Outbound provider timeout |
| `ORBIT_PROVIDER_MAX_ATTEMPTS` | `3` | Retry attempts for transient provider failures |
| `ORBIT_PROVIDER_RETRY_BACKOFF_SECONDS` | `0.5` | Base exponential backoff between retries |

Credentials belong in the OS keyring (planned) or `.env` during development.
`.env` is git-ignored.

## API (v1, current)

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` and `/api/v1/health` | Liveness + database check; `503` when the DB is down |
| `GET` | `/api/v1/system/info` | Version, environment, Python/platform/architecture, start time |
| `GET` | `/api/v1/providers` | Provider list with configured state and capabilities |
| `GET` | `/api/v1/providers/{id}/models` | Live model discovery for one provider |
| `POST` | `/api/v1/providers/{id}/test` | Connection test with latency and model count |
| `GET` | `/api/v1/models` | Aggregated discovery across configured providers |
| `GET`/`PUT` | `/api/v1/models/default` | Read or persist the default model selection |
| `GET` | `/docs`, `/openapi.json` | OpenAPI documentation |

Errors use a stable envelope: `{"error": {"code", "message", "request_id", "details"}}`.
Every response carries `X-Request-ID` (echoed when a valid one is supplied) and
`X-Process-Time-Ms`.

## Development

```bash
pytest -q            # unit, integration and security tests
ruff check .         # lint
ruff format --check .# formatting
mypy                 # strict type checking
```

Project layout:

```
orbit/core/       settings, logging, shared services
orbit/storage/    SQLAlchemy models, async engine, Alembic migrations
orbit/api/        FastAPI app factory, routes, middleware, error handling
tests/            unit / integration / security suites
docs/             architecture and operational documentation
```

Design decisions are recorded in [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md).
Agent-facing engineering rules live in [AGENTS.md](AGENTS.md).

## Roadmap

1. Foundation — settings, logging, API bootstrap, SQLite + migrations, tests ✅
2. Model providers — OpenRouter, Ollama, discovery, streaming adapters, connection tests ✅
3. Chat — conversations, SSE streaming, persistence, context window
4. Web UI and CLI — React app, chat, setup wizard, i18n (pt-BR, en-US, es-ES), themes
5. Agent runtime — execution loop, planning, tools, limits, cancellation
6. Tools and security — sandboxed tools, permissions, approvals, audit log
7. Memory and skills — persistent memory, retrieval, skill registry
8. Packaging and release — Linux/Windows installers, PyInstaller, CI builds

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) before opening a PR.
Please report vulnerabilities privately, never in public issues.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
