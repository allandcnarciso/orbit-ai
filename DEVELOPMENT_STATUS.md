# Development Status

Last updated: 2026-11-19

## Current milestone

**Basic functional homologation COMPLETE (H01…H08-B.3 approved).** The product is ready for the
versioning/publication preparation; a 1.0 release is still blocked by the items in
`docs/HOMOLOGATION.md` §7 (coverage gate, authentication, multi-worker, UI conversation management,
packaging). The CLI remains out of scope until the Web UI is approved.

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
- Conversation persistence (Milestone 3, Phase 2): `conversations` and `messages` tables with
  CHECK constraints, cascade delete, per-conversation `sequence`, partial unique index for
  `client_message_id`, and migration `0002_conversations_messages`.
- `ConversationRepository`: CRUD, pagination, atomic `start_turn` (idempotency check + generation
  lock + both messages in one transaction), lock release, and `recover_interrupted()`.
- Domain errors: `conversation_not_found`, `conversation_archived`, `generation_in_progress`,
  `idempotency_conflict`.
- Migration verified on a copy of the real development database: `0001 → 0002` preserved all
  `system_state` rows and added the new tables/indexes.
- Conversation REST API (Phase 3): create, list with pagination/status filter, retrieve, partial
  update (rename, provider/model selection, archive), physical delete, and chronological message
  history with `before_sequence` cursor. Thin routes → `ConversationService`; ORM models are never
  returned.
- UTC timestamp normalization (`UtcDatetime`) and conversation-domain error envelopes
  (`invalid_selection`, `invalid_status_transition`, `conversation_not_found`, …).
- Startup recovery wired into the lifespan after migrations and before serving requests;
  idempotent, preserves partial content, does not touch completed messages.
- Concurrent idempotency hardening: the generation lock is acquired first, then the
  `client_message_id` is resolved under the write lock; replays release the just-acquired lock,
  conflicting payloads raise `IdempotencyConflict`, and a lost uniqueness race is recovered from
  the savepoint instead of surfacing a raw `IntegrityError`.
- Conversation engine (Phase 4): `orbit/chat` with model resolution (request → conversation →
  default), 60-second per-provider discovery cache, deterministic context budgeting/trimming,
  non-streaming generation via `provider.complete()`, SSE generation via `provider.stream()`,
  partial-content persistence, terminal events, cancellation endpoint and disconnect handling.
- Chat API: `POST /api/v1/conversations/{id}/messages` (JSON default, SSE when `stream=true`)
  and `POST /api/v1/conversations/{id}/cancel`, reusing the atomic turn lock.
- Phase 5 hardening: terminal transitions are conditional writes (exactly one terminal outcome),
  cancel/completion races reconcile the SSE event with the persisted status, the stream queue is
  bounded (backpressure), generations have a hard timeout, app shutdown cancels active
  generations before closing providers (`server_shutdown`), and the producer-start handshake
  guarantees cleanup on immediate disconnect.
- Milestone 5.3-A (concurrency fixes from the Phase 3 audit): deleting a conversation while a
  generation runs no longer raises `ConversationNotFound` out of the generation lifecycle —
  finalization is a no-op and the SSE stream ends with `message.failed`
  (`conversation_deleted`); `shutdown()` raises a barrier before sweeping the registry, holds the
  start lock across cancellation, waits (bounded, non-awaiting-cancel) for generations and for
  starts still resolving their model, and rejects late starts with `503 server_shutting_down`.
  Covered by 9 deterministic event-driven tests (no arbitrary sleeps).
- Milestone 5.3-B (functional integrity of chat): terminal writes run in a shielded task tracked by
  the engine and drained on shutdown, `GenerationStream.close()` is idempotent, and the SSE
  serialiser closes the stream in a `finally` so an ASGI `http.disconnect` cancels the producer
  deterministically (previously the row could be left `pending` with the lock held). Replay events
  report the persisted provider/model. Coverage added for partial persistence (visible `streaming`
  content, flush cadence, failure/cancel after a flush), the non-streaming engine timeout, streaming
  `context_too_large`, replay of completed/failed/cancelled turns, idempotency conflicts (409),
  duplicate-free retries, the cancel-then-resend 409 window and a transport-level disconnect via an
  ASGI harness. Backend 215 tests, frontend 67 tests.
- Milestone 5.3-C1/C2: isolated end-to-end validation on loopback (mock Ollama, temporary SQLite)
  covering health, CRUD, non-streaming, SSE, cancel, 409 conflict, delete-during-generation,
  restart persistence, real-TCP disconnect (RST) with `client_disconnect` persistence, SIGKILL
  recovery (`interrupted`) and controlled shutdown. Added localized `conversation_deleted` /
  `server_shutting_down` messages in the three catalogs, `: keep-alive` SSE comment frames for
  silent generations, and regression tests for both (backend 218, frontend 70). Browser-level
  integration against the Vite dev server could not be evidenced: the process start was denied by
  the approval layer.
- Milestone 5.3-C3 (final audit): the browser → Vite → isolated backend flow was evidenced with
  headless Chromium driven over CDP (create, stream, cancel, history after reload; no uncaught
  exceptions, no 5xx, only React Router deprecation warnings and expected aborted fetches).
  Coverage was measured with a stdlib tracer at 92.3 % for `orbit/chat`,
  `orbit/conversations` and `orbit/providers` (218/218 tests passing under instrumentation);
  `tests/streaming` timing bounds that failed only under instrumentation were widened without
  weakening assertions. `docs/HOMOLOGATION.md` records the checklist, commit/publication plans and
  the 1.0 blockers (coverage gate, authentication, multi-worker, UI conversation management,
  packaging).
- Functional homologation (H01…H08-B.3, approved 2026-11-19): shell/navigation/themes/i18n, health
  and provider/model pages, conversation creation, streaming integrity, cancellation, history
  persistence and responsive/390×844 layout validated manually in the browser, backed by the
  automated suites below. H08-B exercised provider failures through the homologation mock only:
  `[[fail]]` (HTTP 500 before content) and `[[failmid]]` (socket drop after 2 chunks) produced
  `message.failed`/`provider_unavailable` with `retryable=true`, partial content preserved when
  applicable and the generation lock released; a marker-free message then completed normally in
  the same conversation. No product code changed for that.
- H04 root cause and fix (2026-11-19): the reported truncation was a harness misconfiguration
  (`MOCK_CHUNKS=6` instead of the canonical 8), not content loss; the mock now defaults to the
  canonical 8 chunks, and regressions `test_six_chunk_stream_persists_every_delta` (backend) and
  `finishes a short final chunk and re-enables the composer (H04)` (frontend) pin the contract.
- Web UI foundation (Milestone 4, Phase 1): React 18 + TypeScript + Vite 6 under `frontend/`,
  design tokens and light/dark themes (system preference on first use, persisted), responsive
  collapsible sidebar with nine routes, contextual topbar, pt-BR/en-US/es-ES typed catalogs with
  persisted locale, accessible focus/skip-link/reduced-motion baseline, "Coming soon" pages for
  areas without backend contracts, and a Node 20 CI job (lint, typecheck, tests, build).
  Frontend tests: 12 (navigation, i18n switching/persistence/parity, theme toggle/persistence,
  settings information).
- Web UI API integration (Milestone 4, Phase 2): typed fetch client with backend error-envelope
  normalization, request-id surfacing, abort-on-unmount and timeouts; live health/system info on
  Settings; provider list/status and connection tests; aggregated model discovery with
  default-model GET/PUT, client-side search/provider filter and partial-provider warnings; loading,
  empty, error and retry states. No mocks in production paths, no credentials in the browser.
  Frontend tests: 28 (8 API-client + 7 provider/model integration cases plus the Phase 1 suite).
  Node 20 standardised via `frontend/.nvmrc` and `engines` (CI already used Node 20).
- Web UI chat experience (Milestone 4, Phase 3): conversation sidebar (list, local search, create,
  select, pagination), URL-addressable conversations (`/chat/:id`), message history with
  `before_sequence` pagination, POST/SSE streaming through fetch + a custom ReadableStream parser,
  stop generation via the cancel endpoint, partial-content preservation, stable
  `client_message_id` on retries, history reconciliation after terminal events, safe Markdown
  (no raw HTML, URL allow-list), provider/model attribution, intelligent auto-scroll with a
  "jump to latest" control, and responsive desktop/mobile layout. Frontend tests: 42
  (SSE parser fragmentation/UTF-8/CRLF/incomplete frames, Markdown XSS/URL safety, chat streaming,
  cancellation, idempotent retry, conversation isolation during streaming, history pagination).

- Web UI UX/accessibility/reliability (Milestone 4, Phase 4): mobile drawer with
  `aria-expanded`/`aria-controls`, Escape, focus trap/restoration, scroll lock and `inert`;
  polite live announcements for generation start/terminal states; composer limit (32,000),
  accessible counter and `aria-describedby`; remote Markdown images blocked with alt text;
  SSE reader cancellation and 1 MB buffer cap; 30 s connection timeout separate from generation;
  terminal reconciliation with stale-history warning; safe retry vs new send; 8 s cancel fallback;
  WCAG AA contrast tokens with an automated contrast test. Visual validation at 360/390/768/1024/
  1440 px in light and dark themes; five follow-up fixes for localized provider/model errors,
  brand tagline truncation, unavailable-pill contrast, Settings line width and the ≤390 px topbar.
  Frontend tests: 66, including direct regressions for the four visual fix groups.

## In progress

- None. Backend (Phases 1–6), Web UI Phases 1–4 and the basic functional homologation are complete.

## Pending

- Versioning/publication preparation (organised commits, GitHub publication, release notes) — awaiting
  explicit approval; nothing is staged or committed.
- Production readiness: authentication, automated coverage gate, multi-worker strategy, UI
  conversation management (delete/rename), packaging and deployment automation.
- Milestone 4 CLI; Milestones 5–8 afterwards.

## Latest test results

`pytest -q` → **140 passed** (unit, integration, security) on 2026-11-18.
`ruff check .` → clean. `ruff format --check .` → clean. `mypy` (strict) → clean (41 files).
Phase 5 evidence: 11 SSE lifecycle/cancellation/shutdown/persistence tests (immediate disconnect,
disconnect after partial output, duplicate cancel, 12-iteration cancel/completion race, shutdown,
no-open-transaction during streaming, registry cleanup, partial failure, empty stream, concurrent
conversations, failure→retry) plus 7 adapter-through-engine tests (OpenRouter JSON/SSE, Ollama
NDJSON/JSON, HTTP 500, timeout, malformed, empty). Critical concurrency tests (10) re-run 5× with
no flakiness. No real provider credentials were used.

Web UI Phase 4 (in `frontend/`): `npm run test` → **66 passed** (Vitest + Testing Library,
including SSE reader cancellation/buffer limits, connection timeout, Markdown image blocking,
keyboard/focus/Escape, live announcements, contrast, 409/5xx, history-reload failure, the 8 s
fallback, and direct regressions for tagline/collapse/drawer, badge contrast, Settings width and
the ≤390 px topbar); `npm run typecheck` → clean; `npm run lint` → clean; `npm run build` →
success. Chat/cancel-focused suites were repeated 3× without failures.

## Known limitations

- Web UI implements shell, backend data pages and chat; the setup wizard is still a placeholder.
  Model search/filter and conversation search are client-side because the backend exposes no
  query parameters for them.
- Chat Markdown has no syntax highlighting (deliberately avoids a highlighter dependency); code
  blocks are styled for readability.
- No SSE resume/retry protocol: interrupted streams fail with preserved partial content and the
  next message starts a new generation.
- Model pricing fields exist in the API but are not displayed (the backend does not document units
  or currency); the UI avoids inventing them.
- Web UI requires Node 20+; this VPS still has Node 18.19 locally, so npm prints engine warnings
  even though lint/typecheck/tests/build pass. CI uses Node 20.
- `system_state` plus conversation tables; agents/memory arrive later.
- Settings are process-wide (cached); runtime reconfiguration is not exposed yet.
- Secrets are read from env/.env; OS keyring integration is not implemented yet.
- Development server binds to loopback only; no authentication layer exists yet (not needed for
  a local-only MVP, required before any remote exposure).
- `python -m orbit` remains the only runtime surface; the frontend dev server proxies to it.
- Real OpenRouter/Ollama inference was not exercised here (no credentials or local daemon);
  adapters are covered by mocked transports and the engine by fakes. A manual smoke test is
  possible only with explicit approval and configured credentials.
- SSE has no resume/replay protocol; event IDs are intentionally omitted.
- Stream partial content is flushed at most once per second; a hard crash can lose tokens since
  the last flush (startup recovery marks the message failed).
- Streaming requests are not retried after the first token is emitted.
- Cancellation/orphan tracking is in-process; multi-worker deployments need a shared registry.
- The generation timeout is a fixed per-request cap (default 300 s), not a per-token idle timer.
- Provider connection-test failures do not carry a normalized error `code` in the current API
  contract; the UI infers one from safe detail patterns and falls back to a generic localized
  message. A backend `code` field would make this deterministic.
- No real provider inference or remote CI run was validated in this milestone; provider tests use
  mocked transports and local validation used a temporary SQLite database.

## Next recommended action

1. Review/approve this consolidation; commit/push only after explicit approval.
2. Proceed to the CLI milestone; the Web UI Phase 4 work is complete and visually validated.

## Phase 6 quality gate (2026-11-18)

**Architecture.** API → service/repository → context/resolver → provider → engine → persistence
boundaries hold; no circular imports; one generation path with short transactions and exactly one
terminal write. Findings: no critical issues; one high-risk shutdown hang was fixed (bounded
10 s wait); medium items are recorded below as technical debt.

**Security.** No hardcoded credentials in source; `.env` absent; logs/errors redact secrets;
SQL is parameterised (only PRAGMA/`SELECT 1` and partial-index DDL are raw); data dir `0700` and
database `0600`; server binds `127.0.0.1`; `pip check` reports no broken requirements. Dependency
CVE scanning could not be run (`pip-audit` not installed) — tracked as debt.

**API validation.** All endpoints are exercised through ASGI integration tests with temporary
databases and mocked providers: health, providers (list/test), model discovery/default, conversation
CRUD, message history, non-streaming generation, SSE, cancellation. Status codes, error envelopes
and request ids are asserted.

**Provider validation.** OpenRouter and Ollama contracts are validated with mocked HTTP transports
(JSON, SSE/NDJSON, 5xx, timeout, malformed, empty). No live inference was performed; a manual smoke
test requires configured credentials and explicit approval.

**Readiness.** Backend is ready for the Web UI/CLI cycle. Remaining debt is prioritised in
`TODO.md` (technical debt section).

## Technical debt (Phase 6)

- Medium: no SSE keep-alive comment; proxies may time out silent generations.
- Medium: `PUT /api/v1/models/default` validates provider configuration but not model discovery;
  validation happens on send.
- Medium: no coverage tooling configured (`pytest-cov` absent), so coverage is not quantified.
- Medium: assistant output size is not capped independently of provider/model limits.
- Medium: conversation service is bypassed by the engine for generation paths (CRUD service vs
  engine repository access) — acceptable boundary but should be unified before tools/agents.
- Low: WAL/SHM files inherit default modes inside the `0700` directory.
- Low: replay responses do not expose a `replayed` flag to clients.
- Low: live provider integration is unverified (mocks only).
