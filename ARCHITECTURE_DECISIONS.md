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

---

## ADR-012 — Provider abstraction with normalized errors

**Context.** ORBIT AI must support cloud and local inference without vendor logic leaking into the
agent runtime, and without exposing vendor payloads or credentials to clients.

**Decision.** `orbit/providers/base.py` defines vendor-neutral data types (`ChatMessage`,
`CompletionRequest`, `CompletionChunk`, `ModelInfo`, `TokenUsage`) and a `ModelProvider` protocol
(`list_models`, `complete`, `stream`, `test_connection`, `configured`, `aclose`). Adapters
(OpenRouter, Ollama) translate payloads and raise a normalized `ProviderError` taxonomy with a
stable API code and HTTP status. Retries are bounded (429/5xx, exponential backoff), streams are
parsed as SSE (OpenRouter) or NDJSON (Ollama), and upstream error text is redacted/truncated
before it reaches clients or logs.

**Alternatives.** A single generic OpenAI-compatible adapter (rejected: Ollama and future
providers differ in discovery/stream formats); per-vendor logic inside the runtime (rejected:
untestable, couples the core to vendors).

**Consequences.** New providers are additive (implement the protocol, register in
`build_registry`). Streaming retries are not automatic once tokens have been emitted. The
default model is persisted in `system_state` and is not yet validated against live discovery.

---

## ADR-013 — Conversation/message schema, ordering and idempotency

**Context.** Chat needs durable conversations, strictly ordered messages, resumable
generations and protection against duplicate submissions from retries.

**Decision.** `conversations` and `messages` are additive tables (migration
`0002_conversations_messages`). Primary keys are UUID4 hex strings. Message order is an explicit
per-conversation `sequence` with `UNIQUE (conversation_id, sequence)`; allocation is
MAX+1 inside a savepoint with up to three retries on `IntegrityError`. Roles and statuses are
constrained by CHECK clauses; `status` covers `pending|streaming|completed|failed|cancelled`.
Deletes cascade from conversation to messages via `ON DELETE CASCADE` (SQLite `foreign_keys=ON`
is already enforced per connection). Client retries are made idempotent by an optional
`client_message_id`, unique per conversation through a partial index; replaying the same content
returns the existing pair, reusing it with different content returns 409 `idempotency_conflict`.

**Alternatives.** Integer autoincrement message ids (rejected: leaks volume, awkward for future
sync); ordering by `created_at` (rejected: timestamp ties are common); soft-deleted conversations
(rejected for M3: archive status covers the use case, DELETE must remove data).

**Consequences.** Sequence allocation needs a retry path; callers must keep transactions short.
Batch mode in Alembic keeps future SQLite schema changes possible. Timestamps are stored as
`DateTime(timezone=True)` but SQLite returns naive values; serialization must attach UTC.

---

## ADR-014 — Generation lock, atomic turn creation and startup recovery

**Context.** A conversation must never run two generations concurrently, message creation and
locking must be atomic, and a crash or restart must not leave messages stuck in
`pending`/`streaming` or locks permanently held. SQLite allows a single writer and WAL readers
can fail with `SQLITE_BUSY_SNAPSHOT` if a read snapshot is upgraded to a write.

**Decision.** `conversations.active_generation_id` acts as a per-conversation lock. A turn is
created by a single transaction that (1) performs the lock `UPDATE ... WHERE active_generation_id
IS NULL AND status='active'` **before any read**, (2) inserts the user message (`completed`) and
the assistant placeholder (`pending`), and (3) updates conversation timestamps. A second request
sees `rowcount == 0` and receives `409 generation_in_progress` (or `conversation_archived`).
Repositories never commit; callers own the transaction boundary so no transaction is held during
provider calls or streaming. At startup, before serving traffic, `recover_interrupted()` marks
`pending`/`streaming` messages as `failed` with `error_code='interrupted'`, preserves partial
content, and clears every lock.

**Alternatives.** In-memory-only locks (rejected: lost on restart, invisible to recovery);
`SELECT ... FOR UPDATE` (unsupported by SQLite); optimistic version columns (rejected: more
moving parts without extra benefit single-writer).

**Consequences.** The lock is process-agnostic in the database but cancellation orchestration
(Phase 5) is in-process for the MVP. Recovery intentionally converts interrupted generations
into failures rather than resuming them. Multi-worker deployments will need a task registry
outside process memory.

---

## ADR-015 — Conversation REST contract, layering and UTC serialization

**Context.** The chat foundation needs a stable HTTP contract before the engine and SSE exist,
without leaking SQLAlchemy entities or provider logic into routes.

**Decision.** Routes under `/api/v1/conversations` are thin: they validate with Pydantic, call
`ConversationService`, and map entities through `orbit/api/serializers.py`. List endpoints use
explicit pagination envelopes (`items/total/limit/offset`; message history uses
`items/has_more/next_before_sequence` with a `before_sequence` cursor). Ordering is deterministic
(`updated_at DESC, id DESC` for conversations; `sequence` for messages). Status transitions are
limited to `active → archived`; archived conversations cannot be reactivated and DELETE is
physical with cascade. Timestamps are validated into an `UtcDatetime` annotated type that
attaches UTC to SQLite's naive values and serializes as `...Z`, so every API timestamp is
timezone-aware. Startup runs `recover_interrupted()` after migrations and before serving, and
the operation is idempotent.

**Alternatives.** Returning ORM models directly (rejected: leaks schema, invites lazy-loading
bugs); offset pagination for messages (rejected: message volumes grow monotonically, cursors are
stable); allowing archived → active (rejected: archive is terminal for M3).

**Consequences.** Clients must follow `next_before_sequence` for history. `PATCH` with
`provider: null` clears the stored selection. Message creation is intentionally absent until
Phase 4, so archived-conversation rejection is enforced in the repository rather than exposed as
an endpoint yet.

---

## ADR-016 — Deterministic concurrent idempotency

**Context.** Two simultaneous requests with the same `client_message_id` could both pass a
pre-lock idempotency lookup, then collide on the partial unique index and surface a raw
`IntegrityError`. Reading before writing also risks `SQLITE_BUSY_SNAPSHOT` in WAL mode.

**Decision.** `start_turn` acquires the generation lock with a single UPDATE before any read, then
resolves the idempotency key strictly under that write lock: a matching message with identical
content replays the turn and releases the lock acquired by this transaction; different content
raises `IdempotencyConflict`; no match proceeds to insert both messages. The user insert remains
wrapped in a savepoint, so a lost uniqueness race (e.g. an external writer) is rolled back to the
savepoint, the lock is released, the key is re-read, and either a replay is returned or the error
is re-raised. No process-global lock is introduced, so unrelated conversations proceed in
parallel.

**Alternatives.** In-process per-key `asyncio.Lock` (rejected: not durable across workers,
unnecessary for the single-writer MVP); catch-and-retry around the whole turn (rejected: hides
real errors and complicates the caller's transaction).

**Consequences.** Replay requests do acquire (and immediately release) the conversation lock, and
must commit to persist the release. Multi-process deployments still need a shared lock/task
registry; the database-level unique constraints remain the final safety net.

---

## ADR-017 — Conversation engine: resolution, budgeting, SSE and cancellation

**Context.** The engine must connect the REST/persistence layers to the provider adapters while
keeping transactions out of network calls, guaranteeing one terminal outcome, and supporting
cancellation and disconnects without weakening the generation lock.

**Decision.** `orbit/chat` contains a `ConversationEngine`, a `ModelResolver`, a deterministic
context builder and SSE event types. Resolution order is request → conversation → persisted
default; the selected model is validated against provider discovery cached for 60 seconds per
provider. Context uses a conservative `ceil(chars/4)` estimate, reserves output tokens (requested
or 1024, capped at 25% of the window), trims oldest messages first, and rejects a latest user
message that cannot fit (`context_too_large`). The atomic turn (lock + user message + assistant
placeholder) is committed before any provider call; context and finalization use separate short
sessions. Non-streaming replies use `provider.complete()`; SSE uses `provider.stream()` with a
background producer task feeding an `asyncio.Queue`, so cancellation can abort the provider call
and still persist a terminal `cancelled` outcome. Producer startup is synchronized with an
`asyncio.Event`, ensuring cleanup runs even if a client disconnects immediately. Events carry no
`id:` field; resume is explicitly unsupported. Cancellation and disconnects persist partial
content with reasons `cancelled` / `client_disconnect`; every terminal path releases the lock and
unregisters the generation.

**Alternatives.** Running generation inside the request task (rejected: cancellation races and
cleanup skipped when a task is cancelled before first execution); holding one database
transaction for the whole generation (rejected: SQLite write lock starvation); trusting
configured providers without discovery (rejected by the approved Phase 2 decision).

**Consequences.** Generation state lives in memory for cancellation; multi-worker deployments
need a shared registry. Partial content is flushed at most once per second during streaming;
clients must not assume token-level durability.

---

## ADR-018 — Terminal-state machine, shutdown and streaming resource bounds

**Context.** Phase 5 review found that cancellation could race with completion: a task cancellation
delivered during final persistence could overwrite a committed `completed` message with
`cancelled`, and an SSE client could receive a terminal event that disagreed with the database.
Immediate disconnects could also cancel a producer before its cleanup block ran, and shutdown did
not stop active generations before closing the database.

**Decision.** Terminal transitions are conditional writes
(`UPDATE ... WHERE status IN ('pending','streaming')`). The update returns the row; if another
terminal already won the race, the engine emits the event that matches the persisted status
instead of fabricating a second outcome. Generation producers handshake with an `asyncio.Event`
before `start_stream` returns, guaranteeing that cancellation/disconnect always reaches the
`try/finally` cleanup. The SSE queue is bounded (128 events) so a slow consumer applies
backpressure instead of unbounded memory growth; terminal events are delivered with a short
timeout and a sentinel. Each generation is capped by
`ORBIT_GENERATION_TIMEOUT_SECONDS` (default 300 s). Application shutdown calls
`engine.shutdown()`, which cancels all active handles with reason `server_shutdown`, waits for
their terminal persistence, and only then closes providers and the database.

**Alternatives.** Treating the last write as authoritative (rejected: completed replies could be
turned into cancellations); unbounded queue (rejected: memory growth under slow clients);
cancelling at shutdown without waiting (rejected: lock and status could remain non-terminal).

**Consequences.** Cancellation is idempotent while a generation is registered and reports
"nothing active" afterwards. Partial content is preserved on cancellation, failure and shutdown.
Multi-process deployments still need a shared registry; a crash mid-stream remains recoverable
only through startup recovery (`interrupted`).

---

## ADR-019 — Deletion during generation and the start barrier on process exit

**Context.** The Phase 3 audit found two lifecycle races. (A1) `DELETE /conversations/{id}`
cascades to messages, so a generation finalizing afterwards found no assistant row and raised
`ConversationNotFound` from inside its `CancelledError`/`ProviderError` handlers; the exception
escaped the producer task, `GenerationStream.close()` only suppressed `CancelledError`, and the
SSE response ended without a terminal event. (A2) `engine.shutdown()` swept the generation registry
without coordinating with the `_start_lock` handshake in `start_stream`, and model resolution ran
outside that lock, so a start could register after the sweep and keep calling a provider that the
lifespan was closing.

**Decision.** Finalization is idempotent against deletion: `_finish()` returns `None` when the row
is gone, every streaming branch converts that into a single `message.failed` event with
`error.code = "conversation_deleted"`, and nothing is persisted for a deleted conversation (the
persisted resource is authoritative; follow-up reads return 404). Non-streaming generation maps the
same condition to `404 conversation_not_found`. Process exit is a two-phase barrier: `_shutting_down`
is set before the registry is touched, `_start_lock` is held across `cancel_all` and the bounded
wait, and every start is tracked from entry until its turn is persisted (`_in_flight_starts`). A
start that observes the barrier before persisting raises `ServerShuttingDown` (`503
server_shutting_down`) instead of creating a turn. Waits use `asyncio.wait` rather than
`wait_for(gather(...))` so a task that ignores cancellation cannot stall exit.

**Alternatives.** Treating a missing row as an internal error (rejected: it is a legitimate client
action and must not produce a 500 or a dangling stream); emitting no terminal event for deleted
conversations (rejected: every stream must end deterministically, and silent closes are
indistinguishable from transport failures); holding the start lock across model resolution
(rejected: it would serialise discovery for unrelated conversations); leaving the exit wait
unbounded (rejected: providers may ignore cancellation).

**Consequences.** `conversation_deleted` is a new terminal SSE code and `server_shutting_down` a
new 503 envelope; both only occur at the edges of the lifecycle. The contract "exactly one terminal
event per stream" now holds even when the conversation disappears, and exit ordering is
deterministic: barrier → sweep → wait for generations → wait for in-flight starts → close providers.
A generation that outlives `timeout_seconds` is logged and left to finish; it will fail against the
closed provider, which is recorded as a failure rather than a cancellation.

---

## ADR-020 — Cancellation-safe terminal writes, idempotent stream close and authoritative content

**Context.** Milestone 5.3-B exercised the transport-level disconnect path (ASGI `http.disconnect`
with Starlette 1.10 / anyio, `asgi.spec_version` 2.3 as advertised by the installed uvicorn) and
found that the terminal write could be aborted mid-transaction: the producer was cancelled once by
`GenerationStream.close()` and again by the request's cancellation scope, so `_finish` (an inline
`await` inside the `CancelledError` handler) raised a second `CancelledError` before committing.
The assistant row stayed `pending`, the generation lock was never released and no terminal state was
recorded. The audit had also left partial persistence, the non-streaming engine timeout, streaming
`context_too_large`, replay of non-completed turns and the idempotency conflict at the API surface
without coverage.

**Decision.**
1. *Shielded terminal writes.* `ConversationEngine._finish` schedules `_persist_terminal` in its own
   task and awaits it with `asyncio.shield`. Cancellation of the producer can no longer abort the
   conditional UPDATE or the lock release; the caller still observes `CancelledError`.
2. *Tracked and drained finalisations.* Every shielded task is registered in `_finalizations` (removed
   on completion) and `engine.shutdown()` drains the set with a bounded `asyncio.wait`, so durable
   terminal state still precedes provider/database teardown.
3. *Idempotent close.* `GenerationStream.close()` cancels the producer at most once. A second call
   (the SSE serialiser and the nested async-generator finaliser both reach it) is a no-op instead of
   interrupting an in-flight finalisation.
4. *Deterministic disconnect plumbing.* `_sse_events` closes the stream in a `finally`, so the
   route-level cancellation from `http.disconnect` cancels and awaits the producer instead of
   depending on garbage collection of a suspended async generator.
5. *Authoritative content.* Deltas remain advisory under backpressure; `message.completed.content`
   and `message.cancelled.content` (and the persisted row) are the full reply. The web UI replaces
   its accumulated text with the terminal payload before reloading history.
6. *Eventually consistent cancellation.* `POST /cancel` only requests cancellation. The terminal
   write happens asynchronously, so the row may still be open immediately afterwards and a resend in
   that window receives `409 generation_in_progress`. This is documented behaviour, not an error.
7. *Replay attribution.* `_terminal_event` reports `message.provider`/`message.model`, so a replay
   describes the turn that was persisted rather than the conversation's current selection.

**Alternatives.** Awaiting `_finish` inline and retrying on cancellation (rejected: a retry loop
cannot distinguish repeated cancellation from a slow provider and risks a busy loop); backgrounding
the finalisation without tracking (rejected: shutdown could close the database under a pending
write); fire-and-forget terminal writes on disconnect (rejected: it breaks the "one durable terminal
state" guarantee and can leave the lock held); waiting for the write inside `POST /cancel` (rejected:
it would make cancellation latency provider-bound and could block the event loop).

**Consequences.** Terminal persistence is decoupled from the producer's cancellation state at the
cost of one short-lived task per terminal outcome. On a disconnect the client may never see a
terminal event (it is gone) while the row still transitions to `cancelled`/`client_disconnect`. The
ASGI harness covers application-level disconnects, not raw TCP loss: the same code path is exercised
(Starlette cancels the response generator), but socket-level behaviour remains unverified in tests.

---

## ADR-021 — SSE keep-alive comments, error localization and coverage tooling

**Context.** Milestone 5.3-C1 validated the HTTP/SSE surface over loopback and found no heartbeat:
a generation whose provider stayed silent (reasoning models, slow first token, proxies with idle
timeouts) could be closed by an intermediary even though the backend was healthy. The audit also
flagged that `conversation_deleted` and `server_shutting_down` — both introduced after the initial
web UI — had no translations, so the chat bubble fell back to a generic message or the server's
English text. Finally, coverage is still unquantified because `pytest-cov`/`coverage` are not
installed in the pinned environment, and installing them was out of scope.

**Decision.**
1. *Keep-alive as SSE comments.* `GenerationStream.__aiter__` waits on the queue with
   `asyncio.wait_for(..., SSE_HEARTBEAT_INTERVAL_SECONDS)` (default 15 s) and yields a `Heartbeat`
   event on timeout. `Heartbeat.to_sse()` renders `: keep-alive\n\n`. Cancelling `Queue.get()` is
   safe: a delivered item stays queued, so no event is lost. Comment frames are not domain events,
   are not persisted, and do not affect the "exactly one terminal event" invariant.
2. *Localized new error codes.* `errors.conversationDeleted` and `errors.serverShuttingDown` were
   added to pt-BR/en-US/es-ES (parity test enforces equality) and mapped in
   `describeError.codeKeys`. `localizedErrorForCode` lets the SSE handler prefer the local string and
   fall back to the server text only for unknown codes. HTTP status/retry semantics are unchanged.
3. *Coverage.* stdlib `trace --count --summary` is used as a stop-gap. It produced 100 % line
   coverage for 21 modules but did not instrument `orbit/chat/engine.py`, so the most important
   module remains unmeasured. `pytest-cov` (+ a coverage floor for `orbit/chat`,
   `orbit/conversations`, `orbit/providers`) remains a P1 TODO requiring an approved dependency
   install.

**Alternatives.** WebSocket pings (rejected: the contract is HTTP+SSE and resumes are out of scope);
`event: heartbeat` frames (rejected: clients would need to special-case a new event; comments are
stock SSE and parsers already ignore them); heartbeat inside the route generator with
`wait_for(anext(...))` (rejected: cancelling `anext` closes the stream and would abort generation);
blocking `POST /cancel` until finalization (rejected in 5.3-B); adding `uuid`/`expires` headers
(rejected: no contract benefit).

**Consequences.** Idle streams stay open behind proxies and the wire carries one comment line per
15 s of silence. Because the interval is a module constant, tests patch it to milliseconds; the
default stays conservative to avoid needless traffic. httpx's ASGITransport buffers whole bodies,
so mid-stream keep-alive cannot be observed through it — the serialiser and the stream are tested
directly, and real uvicorn behaviour was observed in 5.3-C1 with curl. Browser-level UI validation
against the Vite dev server is still pending because the process start is blocked by the approval
layer; this must not be reported as validated until it actually runs.
