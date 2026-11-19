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
3. Creates the async engine (SQLite pragmas: foreign keys, WAL, busy timeout) and the provider
   registry (with a 60-second discovery cache) plus the conversation engine.
4. Applies Alembic migrations in a worker thread when `ORBIT_AUTO_MIGRATE=true`.
5. Pings the database, recovers interrupted generations (idempotent), records `last_started_at`.
6. On shutdown: raises the shutdown barrier (new generations are rejected with `503
   server_shutting_down`), cancels active generations (`server_shutdown`, bounded wait), waits for
   starts still resolving their model, closes provider HTTP clients, then disposes the engine.

Configuration is validated at process start; an invalid setting aborts the process instead of
producing a half-configured server.

## Configuration

`orbit/core/config.py` defines `Settings` (`ORBIT_*`, optional `.env`). Data and log directories
default to `/var/lib/orbit-ai` and `/var/log/orbit-ai` when writable and fall back to per-user
XDG/`LOCALAPPDATA` paths, so the same code works on a VPS and on a developer laptop.

## Persistence

- `orbit/storage/models.py` — declarative models (`SystemState`, `Conversation`, `Message`).
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

## Module map

Implemented:

| Module | Responsibility |
| --- | --- |
| `orbit/providers` | Provider protocol, OpenRouter/Ollama adapters, discovery, streaming, retries |
| `orbit/conversations` | Conversation/message persistence, service layer, ordering, idempotency, generation lock |
| `orbit/chat` | Context budgeting, model resolution, generation engine, SSE events |

Planned (not yet implemented):

| Module | Responsibility |
| --- | --- |
| `orbit/agents` | Agent definitions, execution loop, planning, limits, retries |
| `orbit/orchestrator` | Task submission/state/history; multi-agent coordination |
| `orbit/tools` | Tool registry, schemas, permissions, sandboxed execution |
| `orbit/memory` | Conversation, short-term and persistent memory with retrieval |
| `orbit/skills` | Skill discovery/installation/activation and permissions |
| `orbit/security` | Credential vault, permission policies, approvals, audit log |
| `orbit/i18n` | pt-BR / en-US / es-ES message catalogues for API and UI |

Each module lands with tests and an ADR if it changes the architecture.

## Chat execution path

```
HTTP POST /conversations/{id}/messages
  → orbit/api/routes/conversations.py   (validation, status codes, SSE framing)
  → orbit/chat/engine.py                (model resolution, context, lifecycle, events)
  → orbit/conversations/repository.py   (atomic turn, message transitions, lock)
  → orbit/providers/*                   (OpenRouter/Ollama transport and parsing)
```

Transaction boundaries: the atomic turn (lock + user message + assistant placeholder) commits
before any network call; context reads and partial/final writes use short sessions. Provider
calls and streaming never run inside a database transaction. Exactly one terminal transition is
persisted per assistant message (conditional UPDATE), and the generation lock is released in the
same transaction as the terminal write. Cancellation/disconnect/shutdown all funnel through that
path; SSE events are derived from the persisted outcome. An idle generation (no provider chunk for
`SSE_HEARTBEAT_INTERVAL_SECONDS`, default 15 s) emits an SSE comment frame (`: keep-alive`) so
proxies do not drop the connection; the frame is not a domain event and the web client ignores it.

Terminal writes are protected against cancellation: `_finish` runs `_persist_terminal` in its own
task and awaits it through `asyncio.shield`, so a producer cancelled by a transport disconnect (or
by shutdown) cannot abort the transition or leave the lock held. Those tasks are registered in
`_finalizations` and drained by `engine.shutdown()`. `GenerationStream.close()` is idempotent — a
second close never re-cancels a producer that is already finalising — and the SSE serialiser closes
the stream in a `finally`, so an ASGI `http.disconnect` reaches the producer deterministically
instead of relying on async-generator garbage collection. Cancellation is eventually consistent:
`POST /cancel` only requests cancellation, so the row may still be `pending`/`streaming` when it
returns and an immediate resend can race the finalisation (HTTP 409 `generation_in_progress`). The
persisted message is authoritative for content; deltas are advisory under backpressure.

## Web UI data flow (Milestone 4, Phases 2–3)

The React app is a pure API client: business rules, persistence, provider access and model
selection stay in the backend.

- Dev: Vite serves `frontend/` on `127.0.0.1:5173` and proxies `/api`, `/health`, `/docs` and
  `/openapi.json` to `ORBIT_BACKEND_URL` (default `http://127.0.0.1:18700`). No browser-side
  credentials or CORS configuration are required in this mode; a separately hosted build needs
  `ORBIT_CORS_ORIGINS`.
- `src/api/client.ts` centralises fetch, JSON parsing, timeouts (20 s default, 60 s for discovery
  and connection tests), abort propagation, backend error-envelope normalization and request-id
  capture. Pages consume `useApiResource`, which aborts on unmount and exposes loading/success/error
  states plus an explicit reload.
- `GET /health` lives outside `/api/v1`; all other calls use the `/api/v1` prefix. Provider
  connection tests and model discovery call the real backend and may fail; failures are shown as
  normalized errors, never replaced with fabricated data.
- The UI never writes credentials: provider configuration remains an environment-variable concern
  of the backend until a credential-management API exists.
- Chat: `src/api/sse.ts` parses `POST` responses with `fetch` + `ReadableStream`; event names and
  payloads mirror `orbit/chat/events.py`. `client_message_id` is generated per send and reused on
  retry; switching conversations aborts the stream (the backend persists a cancellation). Terminal
  events trigger a history reload. Markdown is rendered from the stored message text with
  `react-markdown`, `skipHtml`, and an http/https/mailto URL allow-list.
- Accessibility: the mobile drawer exposes `aria-expanded`/`aria-controls`, closes on Escape,
  traps focus while open, restores focus to the trigger, locks background scroll and is
  `inert`/`aria-hidden` when closed. Chat generation start/terminal states are announced in a
  polite live region; the message stream itself is not announced fragment by fragment. Composer
  enforces a 32,000-character limit with an accessible counter.
- Reliability: the SSE reader is cancelled when a terminal event ends consumption and an
  unterminated frame above 1 MB aborts the stream. `openMessageStream` applies a 30 s connection
  timeout; the generation budget remains backend-controlled. After success, failure, cancellation
  or the 8 s cancel fallback the UI reconciles terminal state with `GET /messages`, retaining
  partial content and warning when history cannot be confirmed. Markdown images are never fetched.

### Phase 4 visual validation and localization

- The Web UI was inspected at 360/390/768/1024/1440 px in light and dark themes using the local
  Chromium binary against a temporary backend database; no real provider inference was used.
- Brand text uses the sidebar class structure: the tagline wraps in expanded and mobile-drawer
  states and the whole text block is hidden when the sidebar is collapsed, leaving the icon and
  accessible name.
- Unavailable capability badges use `--text-muted` on the card surface with a dashed border and
  no opacity reduction (WCAG AA). Settings descriptions are capped at 58–62ch. At ≤390 px the
  locale selector is width-capped and the topbar title cannot ellipsize.
- Provider and model failures are rendered through the i18n catalogs. Because connection-test
  responses currently expose only `detail`, the UI infers a normalized code from safe patterns
  (`provider_unavailable`, `provider_timeout`, `provider_auth_error`, `provider_rate_limited`) and
  otherwise shows a generic localized diagnostic; model discovery already provides `code`.
- `frontend/src/__tests__/visual-regressions.test.tsx` asserts the CSS contracts and the effective
  badge color combination, complementing the existing token-level contrast test and the
  browser captures stored outside the repository.
