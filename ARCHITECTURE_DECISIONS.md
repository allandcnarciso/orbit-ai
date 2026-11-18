# Architecture Decisions

Significant, hard-to-reverse decisions only. Each entry: context, decision, alternatives,
consequences. New decisions append; superseded ones are marked, never deleted.

---

## ADR-001 — Modular monolith for the MVP

**Context.** One small team, a 4-core ARM64 VPS, and a 14-week horizon to a usable alpha.
The product surface (API, web UI, CLI, providers, tools, memory) is broad but the runtime is
a single process per user installation.

**Decision.** Ship a modular monolith: one Python package (`orbit`) with explicit module
boundaries (`core`, `storage`, `api`, `providers`, `agents`, `tools`, `memory`, `skills`,
`security`, `i18n`). Modules communicate through typed interfaces and dependency injection,
not through each other's internals.

**Alternatives.** Microservices (rejected: operational cost, no demonstrated need); a single
flat module (rejected: untestable, no boundary enforcement).

**Consequences.** Simple deployment and debugging; module boundaries must be policed by review
and tests. Splitting a module into a service later stays possible because the API layer only
depends on interfaces.

---

## ADR-002 — Independent agent runtime (no Hermes dependency)

**Context.** Hermes Agent is the development assistant used to build ORBIT AI. The product must
not inherit that dependency.

**Decision.** ORBIT AI owns its agent lifecycle, execution loop, planning, tool invocation,
permission checks, memory and provider abstraction. No runtime import of Hermes, no Hermes
configuration files, no reliance on its skill format at runtime.

**Consequences.** More code to write, but the product can outlive any single coding assistant.
Hermes-specific workflows stay in `AGENTS.md` and are never shipped in the wheel.

---

## ADR-003 — FastAPI application factory + lifespan

**Context.** The web server, CLI and tests must share configuration, database and startup
behaviour.

**Decision.** `orbit.api.app:create_app(settings)` builds the app; an `asynccontextmanager`
lifespan creates the engine, applies migrations, records startup state and disposes the engine
on shutdown. The CLI and tests call the same factory.

**Alternatives.** Module-level `app = FastAPI()` (rejected: implicit global config, hard to test
with isolated temp directories); dependency-injection frameworks (rejected: unnecessary weight).

**Consequences.** Two apps with different settings can coexist in one process (used by tests).
State lives on `app.state`, accessed through `orbit.api.deps`.

---

## ADR-004 — Async SQLAlchemy 2.0 + aiosqlite + Alembic

**Context.** Agent execution is I/O-bound (model streaming, tool HTTP calls). SQLite is the MVP
database; schema will evolve quickly.

**Decision.** Async engine (`sqlite+aiosqlite`), `async_sessionmaker`, declarative models with
`Mapped[...]`, Alembic as the single schema authority (including in tests and at startup).
`PRAGMA foreign_keys=ON`, WAL and a busy timeout are applied on connect.

**Alternatives.** Sync SQLAlchemy in a threadpool (rejected: awkward inside async agent loops);
`create_all()` without migrations (rejected: no upgrade path for installed users); PostgreSQL
(rejected for MVP: external service, install friction).

**Consequences.** SQLite writes remain serialised; long transactions must be avoided. The
database file is created with mode `0600` inside a `0700` directory because it will hold
credentials and conversation history. Alembic must be able to locate
`orbit/storage/migrations` in packaged builds (packaging milestone).

---

## ADR-005 — Auto-migrate on startup (desktop semantics)

**Context.** ORBIT AI installs as a local application, not a fleet of servers. Users will not run
migration commands manually.

**Decision.** Run `alembic upgrade head` during lifespan startup (`ORBIT_AUTO_MIGRATE=true`),
in a worker thread. A failure aborts startup rather than serving on a stale schema.

**Consequences.** One process per data directory is assumed for the MVP. Multi-worker deployments
would need an external migration step; not a supported configuration yet.

---

## ADR-006 — Pure ASGI request middleware

**Context.** Chat streaming will use Server-Sent Events. `BaseHTTPMiddleware` buffers and has
historically interfered with streaming and context variables.

**Decision.** Implement request-id/timing/access-log middleware as a raw ASGI callable that
wraps `send`, avoids buffering, and uses a `ContextVar` for correlation.

**Consequences.** Slightly more code; streaming responses stay unbuffered and errors are still
correlated. Access logging happens once per request.

---

## ADR-007 — Stable JSON error envelope

**Context.** CLI, web UI and third-party clients all consume the API; FastAPI's default error
shapes differ between validation errors and HTTP errors.

**Decision.** All errors return `{"error": {"code", "message", "request_id", "details?"}}`.
Unhandled exceptions return a fixed `internal_error` message; details go to logs only.

**Consequences.** Clients get one shape to parse. Documentation must list error codes per route;
internal messages are never leaked, which also limits debuggability from the client side.

---

## ADR-008 — Settings via pydantic-settings, secrets as `SecretStr`

**Context.** Configuration must work identically for the web server, CLI, tests and future
packaging; credentials must never be logged.

**Decision.** `Settings(BaseSettings)` with `ORBIT_` prefix and optional `.env`; credentials are
`SecretStr`; logging runs every formatted line through a redaction filter; `data_dir`/`log_dir`
resolve to platform-appropriate defaults with `/var/lib/orbit-ai` and `/var/log/orbit-ai` when
writable.

**Alternatives.** Dynaconf (extra dependency, less typed); bespoke env parsing (error-prone).

**Consequences.** `.env` is a development convenience only. Keyring-backed storage arrives with
the provider manager; until then credentials live in env or `.env` with `0600` permissions.

---

## ADR-009 — `system_state` key/value table for lifecycle state

**Context.** The setup wizard, first-run detection and last-start timestamp need durable state
before domain tables exist.

**Decision.** A small `system_state(key, value, updated_at)` table, accessed through a typed
`SystemStateStore`, created by migration `0001_system_state`.

**Consequences.** Domain-specific settings should graduate to typed tables rather than accreting
as opaque keys; the table stays limited to cross-cutting lifecycle flags.

---

## ADR-010 — Repository layout and documentation discipline

**Context.** Multiple agents and humans will contribute; the prompt defines a target tree.

**Decision.** `orbit/` (product code), `tests/{unit,integration,security}`, `docs/`, `installer/`
and `packaging/` later. Every module carries a docstring stating its responsibility; empty
placeholder packages are forbidden. Decisions, status and backlog are maintained in
`ARCHITECTURE_DECISIONS.md`, `DEVELOPMENT_STATUS.md` and `TODO.md`.

**Consequences.** Structure changes require an ADR and a doc update in the same change set.

---

## ADR-011 — Loopback-only development, no auth in the MVP

**Context.** The development VPS is shared with unrelated services.

**Decision.** Bind to `127.0.0.1:18700` by default; no CORS unless configured; never expose the
development API publicly. Authentication is out of scope until remote/multi-user use is designed.

**Consequences.** Acceptable for a local desktop-style MVP. Any remote exposure requires TLS,
authentication and a threat-model review first.
