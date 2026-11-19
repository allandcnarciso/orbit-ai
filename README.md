# ORBIT AI

**One Harness. Any Model. Infinite Possibilities.**

ORBIT AI is an open-source, cross-platform **Agentic AI Harness**: a single environment to
create, configure, operate and inspect AI agents across cloud and local models, with a shared
runtime behind a Web UI, a CLI and a documented REST API.

> Status: **pre-alpha Web UI chat functional**. Milestones 1–3 (backend) and Web UI Phases 1–4
> are implemented: foundation, providers, chat engine/SSE, React shell, API integration, chat
> experience and the UX/accessibility/reliability pass, visually validated at 360/390/768/1024/
> 1440 px in light and dark themes. The setup wizard, CLI, agent runtime, tools and memory are in
> progress. See [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md).

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
- Linux x64/ARM64, macOS, or Windows 10/11
- Node.js **20+** and npm (only needed to run/build the Web UI; CI uses Node 20)

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

See [docs/INSTALL.md](docs/INSTALL.md), [docs/CONFIGURATION.md](docs/CONFIGURATION.md) and
[docs/RUNNING.md](docs/RUNNING.md) for complete guides.
| `ORBIT_OPENROUTER_API_KEY` | unset | OpenRouter credential (never commit) |
| `ORBIT_OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter-compatible endpoint |
| `ORBIT_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local Ollama endpoint |
| `ORBIT_REQUEST_TIMEOUT_SECONDS` | `120` | Outbound provider timeout |
| `ORBIT_PROVIDER_MAX_ATTEMPTS` | `3` | Retry attempts for transient provider failures |
| `ORBIT_PROVIDER_RETRY_BACKOFF_SECONDS` | `0.5` | Base exponential backoff between retries |
| `ORBIT_GENERATION_TIMEOUT_SECONDS` | `300` | Hard cap for one generation (both modes) |

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
| `POST` | `/api/v1/conversations` | Create a conversation |
| `GET` | `/api/v1/conversations` | List conversations (`limit`, `offset`, `status`) |
| `GET` | `/api/v1/conversations/{id}` | Retrieve one conversation |
| `PATCH` | `/api/v1/conversations/{id}` | Rename, reselect model/provider or archive |
| `DELETE` | `/api/v1/conversations/{id}` | Delete a conversation and its messages |
| `GET` | `/api/v1/conversations/{id}/messages` | Chronological history (`limit`, `before_sequence`) |
| `POST` | `/api/v1/conversations/{id}/messages` | Send a message; JSON reply or SSE when `stream=true` |
| `POST` | `/api/v1/conversations/{id}/cancel` | Cancel the active generation |
| `GET` | `/docs`, `/openapi.json` | OpenAPI documentation |

Errors use a stable envelope: `{"error": {"code", "message", "request_id", "details"}}`.
Every response carries `X-Request-ID` (echoed when a valid one is supplied) and
`X-Process-Time-Ms`.

## Streaming contract (SSE)

When `stream=true`, `POST /api/v1/conversations/{id}/messages` responds with
`text/event-stream`. Events carry `event:` and `data:` (JSON) only — no `id:` field is sent, so
clients must not assume resume support. Exactly one terminal event is emitted:

| Event | Payload |
| --- | --- |
| `message.started` | `conversation_id`, `message_id`, `user_message_id`, `provider`, `model`, `sequence` |
| `content.delta` | `message_id`, `delta` |
| `message.completed` | `message_id`, `content`, `provider`, `model`, `finish_reason`, `usage` |
| `message.failed` | `message_id`, `error{code,message,retryable}` |
| `message.cancelled` | `message_id`, `content` (partial), `reason` (`cancelled`, `client_disconnect` or `server_shutdown`) |

With `stream=false` (default) the endpoint returns `{user_message, assistant_message}`. Provider
failures map to the standard error envelope; partial content is preserved on failure or
cancellation.

The persisted message is authoritative: deltas may be dropped under backpressure (slow consumer),
so `message.completed.content` — not the concatenation of deltas — is the full reply. The same
applies to `message.cancelled.content`, and the UI replaces its accumulated text with the terminal
payload before reloading history.

While a generation is silent (no provider chunk for 15 s) the server emits an SSE comment frame,
`: keep-alive`. Comment frames are part of the SSE specification and must be ignored by clients;
they exist so idle proxies and load balancers do not close a healthy stream.

Cancellation is eventually consistent: `POST /api/v1/conversations/{id}/cancel` returns as soon as
cancellation is requested (it never waits for the terminal write), so the assistant message may
still be `pending`/`streaming` right after the response. A send issued in that window is rejected
with `409 generation_in_progress`; clients should wait for the terminal SSE event (or retry) before
sending again. If the client closes the connection, the backend cancels the producer, persists
`cancelled`/`client_disconnect` and releases the generation lock.

If the conversation is deleted while a generation is running, the stream still ends with exactly one
terminal event: `message.failed` with `error.code = "conversation_deleted"`. Nothing is persisted for
a deleted conversation, and a follow-up request returns 404. Starts received while the server is
shutting down are rejected with `503 server_shutting_down`.

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
orbit/providers/  provider protocol and OpenRouter/Ollama adapters
orbit/conversations/  conversation/message persistence and generation locks
orbit/chat/       context budgeting, model resolution, generation engine, SSE events
orbit/api/        FastAPI app factory, routes, middleware, error handling
frontend/         React 18 + TypeScript + Vite 6 web interface
tests/            unit / integration / security suites
docs/             architecture and operational documentation
```

## Web UI (development)

Requires Node.js 20+ (see `frontend/.nvmrc`; the CI frontend job uses Node 20).

```bash
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173, proxies /api and /health to 127.0.0.1:18700
```

Run the backend with `python -m orbit` in another terminal. Set
`ORBIT_BACKEND_URL=http://127.0.0.1:<port>` to point the dev proxy at a different backend port.
Frontend quality gates: `npm run lint`, `npm run typecheck`, `npm run test`, `npm run build`. See
[frontend/README.md](frontend/README.md).

The current UI renders real backend data for health/system info, providers, model discovery and
default model selection, and a complete chat experience: conversation list/creation, paginated
history, POST/SSE streaming, cancellation, provider/model attribution and safe Markdown rendering.
The UI includes keyboard/focus management for the mobile drawer, polite screen-reader
announcements for generation start/terminal states, a 32,000-character composer limit, WCAG AA
text contrast and blocked remote Markdown images (no external image requests).
The setup wizard and remaining areas arrive in later phases.

Design decisions are recorded in [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md).
Agent-facing engineering rules live in [AGENTS.md](AGENTS.md).

## Roadmap

1. Foundation — settings, logging, API bootstrap, SQLite + migrations, tests ✅
2. Model providers — OpenRouter, Ollama, discovery, streaming adapters, connection tests ✅
3. Chat — conversations, SSE streaming, persistence, context window ✅
4. Web UI and CLI — Web UI chat, UX/accessibility/reliability and visual validation ✅;
   setup wizard and CLI pending
5. Agent runtime — execution loop, planning, tools, limits, cancellation
6. Tools and security — sandboxed tools, permissions, approvals, audit log
7. Memory and skills — persistent memory, retrieval, skill registry
8. Packaging and release — Linux/Windows installers, PyInstaller, CI builds

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) before opening a PR.
Please report vulnerabilities privately, never in public issues.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
