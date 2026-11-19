# Changelog

All notable changes to ORBIT AI are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- SSE keep-alive: a silent generation now emits `: keep-alive` comment frames every 15 s
  (`SSE_HEARTBEAT_INTERVAL_SECONDS`), so idle proxies do not close healthy streams. Comment frames
  are ignored by the web client and are not persisted or counted as events; exactly one terminal
  event is still emitted.
- Error localization: `conversation_deleted` and `server_shutting_down` are translated in pt-BR,
  en-US and es-ES; SSE failures use the local translation when the code is known and fall back to
  the server text only for unknown codes. Retry behaviour for 5xx responses is unchanged.

### Fixed

- Terminal writes are now cancellation-safe: `_finish` persists through a shielded task, so a
  producer cancelled by a transport disconnect (or shutdown) can no longer abort the conditional
  terminal UPDATE or leave the generation lock held; pending writes are tracked and drained by
  `engine.shutdown()`.
- `GenerationStream.close()` is idempotent, so the second close performed while a cancelled stream
  unwinds no longer interrupts an in-flight terminal write; the SSE serialiser also closes the
  stream in a `finally`, making `http.disconnect` handling deterministic at the ASGI level.
- Replay terminal events now report the persisted `provider`/`model` of the turn instead of the
  conversation's current selection.
- Deleting a conversation while a generation is running no longer raises `ConversationNotFound`
  out of the generation lifecycle: the terminal write becomes a no-op (nothing can be persisted
  for a deleted conversation), the registry/lock are released, and the SSE stream terminates
  exactly once with `message.failed` (`conversation_deleted`). A non-streaming request for a
  conversation deleted mid-generation returns `404 conversation_not_found` instead of `500`.
- Application shutdown now serialises with the streaming start handshake: a shutdown barrier is
  raised before the registry sweep, the start lock is held across cancellation, starts still
  resolving their model are tracked and drained (bounded), and generations are awaited with
  `asyncio.wait` so a provider that ignores cancellation cannot block exit. Starts that arrive
  after shutdown begins are rejected with `503 server_shutting_down` instead of running against
  closing providers.
- Application shutdown now bounds the wait for active generations (10 s) so a provider that
  ignores cancellation cannot block process exit.
- Streaming lifecycle hardening: terminal writes are conditional (`pending|streaming → terminal`),
  so a cancellation racing with completion can no longer demote a committed completion; SSE
  terminal events are reconciled with the persisted status.
- Immediate client disconnects no longer skip cleanup (producer-start handshake), duplicate
  cancellation is idempotent while active and reports inactive afterwards, app shutdown cancels
  active generations (`server_shutdown`) before providers close, and generations have a hard
  timeout (`ORBIT_GENERATION_TIMEOUT_SECONDS`, default 300 s).
- The SSE queue is bounded (128 events) to provide backpressure, and empty provider responses are
  treated as `provider_invalid_response` failures instead of empty completions.
- Concurrent requests sharing a `client_message_id` are now deterministic: the generation lock is
  acquired before idempotency resolution, replays release the lock acquired by the transaction,
  conflicting content returns 409 `idempotency_conflict`, and uniqueness races are recovered from
  a savepoint instead of surfacing a raw `IntegrityError`.

### Added

- Web UI foundation (Milestone 4, Phase 1): React 18 + TypeScript + Vite 6 application with a
  nine-item navigation shell, contextual topbar, collapsible/responsive sidebar, design tokens,
  dark/light themes (system preference on first use, persisted), and pt-BR/en-US/es-ES catalogs
  with typed keys, persisted locale and parity tests.
- Frontend quality tooling: ESLint flat config, Vitest + Testing Library, strict TypeScript,
  production build check and a Node 20 CI job (lint, typecheck, tests, build).
- Web UI API integration (Milestone 4, Phase 2): typed fetch client with timeout/abort handling,
  normalized backend errors and request ids; live health/system information on Settings; provider
  status cards with connection tests; aggregated model discovery, client-side filtering and
  default-model selection; loading, empty, error, retry and partial-provider warning states.
  Node 20 pinned through `.nvmrc` and `engines`.
- Web UI chat (Milestone 4, Phase 3): conversation sidebar with creation/selection/search and
  pagination; URL-addressable conversations; paginated history; POST/SSE streaming via fetch and a
  custom ReadableStream parser (fragmentation, CRLF, comments, multibyte UTF-8, malformed and
  incomplete frames); stop generation through the cancel endpoint; partial-response preservation;
  stable `client_message_id` retries; history reconciliation after terminal events; conversation
  isolation when switching; safe Markdown via react-markdown with raw HTML skipped and URL
  allow-listing; provider/model attribution; intelligent auto-scroll; responsive chat layout.
- Web UI UX/accessibility/reliability (Milestone 4, Phase 4): mobile drawer with
  `aria-expanded`/`aria-controls`, Escape, focus trap/restoration, scroll lock and `inert`;
  polite live announcements for generation start/terminal states; composer limit (32,000),
  accessible counter and `aria-describedby`; remote Markdown images blocked with alt text;
  SSE reader cancellation and 1 MB buffer cap; 30 s connection timeout separate from generation;
  terminal reconciliation with stale-history warning; safe retry vs new send; 8 s cancel fallback;
  WCAG AA contrast tokens plus a direct contrast regression test. The UI was visually validated
  at 360/390/768/1024/1440 px in light and dark themes.
- Visual/localization pass: provider and model failures are rendered through i18n instead of raw
  provider text (provider test responses without a `code` use a small client-side heuristic;
  see limitations); brand tagline wraps in expanded/drawer states and is hidden when collapsed;
  unavailable capability pills meet WCAG AA; Settings descriptions use bounded line lengths;
  the mobile topbar keeps “Chat” visible and compacts the locale selector.
- Frontend tests expanded to 66, including direct regressions for tagline/collapse/drawer,
  badge contrast, Settings width rules, mobile topbar, plus the earlier SSE, Markdown, chat,
  accessibility and reliability coverage.
- Conversation engine (`orbit/chat`): model resolution (request → conversation → default) with
  60-second per-provider discovery caching, deterministic token-budgeted context trimming,
  non-streaming generation and SSE streaming through the provider abstraction.
- Chat API: `POST /api/v1/conversations/{id}/messages` (`stream=false` default JSON, SSE when
  `stream=true`) and `POST /api/v1/conversations/{id}/cancel`; terminal events
  `message.completed` / `message.failed` / `message.cancelled` with partial-content persistence.
- Generation registry: cancellation and client disconnects abort the provider stream, preserve
  partial content and always release the conversation lock.
- Conversation REST API: create, list (paginated, status filter), retrieve, partial update
  (title/provider/model/status), delete, and chronological message history with cursor
  pagination. Thin routes delegate to `ConversationService`; no SQLAlchemy models are exposed.
- UTC-normalized timestamp serialization (`...Z`), stable error envelope for conversation
  domain errors (`conversation_not_found`, `conversation_archived`, `generation_in_progress`,
  `idempotency_conflict`, `invalid_status_transition`, `invalid_selection`).
- Startup recovery: interrupted `pending`/`streaming` messages become `failed` with
  `error_code=interrupted` (partial content preserved) and stale generation locks are cleared
  before the app serves traffic; the operation is idempotent.
- Conversation persistence: `conversations` and `messages` tables (migration
  `0002_conversations_messages`), cascade delete, per-conversation ordering, CHECK constraints,
  partial unique index for `client_message_id` and per-conversation generation lock.
- `ConversationRepository` with atomic turn creation (idempotency + lock + messages), pagination,
  lock release and startup recovery of interrupted generations.
- Domain errors for conversations: not found, archived, generation in progress and idempotency
  conflict.
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
