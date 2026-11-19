# TODO

Prioritised development backlog. P0 blocks the current milestone; P1 is the next milestone;
P2 is planned but not scheduled.

## P0 — Milestone 1 close-out

- [x] Install dependencies into `.venv` and run the full test suite (33 passed).
- [x] Fix lint (`ruff`), format and type (`mypy --strict`) failures.
- [x] Configure a git author identity and commit Milestone 1 locally (`05f2026`).
- [ ] Confirm CI workflow passes once pushed (requires approval).

## P0 — Homologation close-out and publication preparation

- [x] Functional homologation H01…H08-B.3 approved (2026-11-19) on an isolated loopback stack
      (backend 18716, mock Ollama 18726, Vite 5187, temporary SQLite). Results and evidence matrix in
      `docs/HOMOLOGATION.md`.
- [x] `docs/HOMOLOGATION.md`, `DEVELOPMENT_STATUS.md` and this file updated with the homologation
      result, security audit, quality gates and open blockers.
- [ ] Organised commits per milestone (`docs/HOMOLOGATION.md` §6) — requires approval; nothing staged.
- [ ] GitHub publication (remote `git@github.com:allandcnarciso/orbit-ai.git`): identity, diff review,
      CI green on Node 20 + Python 3.12, tag `v0.1.0-dev` — requires approval.
- [ ] Production deployment checklist: authentication, HTTPS/reverse proxy, data dir permissions,
      backups, health monitoring, single-worker constraint documented.

## P1 — Milestone 2: model providers

- [x] `orbit/providers/base.py`: `ModelProvider` protocol, `ModelInfo`, `ChatMessage`,
      `CompletionRequest`, `CompletionChunk`, normalized `ProviderError` taxonomy.
- [x] Provider registry with capability detection and per-provider configuration.
- [x] OpenRouter adapter: `/models` discovery, chat completions, SSE streaming, retries with
      backoff, timeout handling.
- [x] Ollama adapter: `/api/tags` discovery, `/api/chat` streaming, connection test.
- [ ] Credential storage: OS keyring first, encrypted fallback; never plaintext in SQLite.
- [x] Provider endpoints: listing, model discovery, connection test, aggregated models and
      persisted default-model selection.
- [x] Recorded/mocked-transport tests for both adapters; no live API calls in CI.

## P1 — Milestone 3: chat

- [x] `conversations` and `messages` tables + migration `0002_conversations_messages`
      (cascade, ordering, idempotency index, generation lock).
- [x] `ConversationRepository` with atomic `start_turn`, pagination, lock release and
      `recover_interrupted()`; persistence tests including concurrency and migration replay.
- [x] Conversation REST API (CRUD, message listing, schemas, error mapping) and startup
      recovery wiring with UTC timestamps.
- [x] Deterministic concurrent idempotency: lock-first resolution under the write lock, replay
      release, conflict detection and savepoint recovery (no raw IntegrityError).
- [x] `ConversationEngine`: history/context construction, model resolution, non-streaming chat.
- [x] `POST /api/v1/conversations/{id}/messages` (SSE), cancellation, disconnect handling.
- [x] Token/cost accounting fields surfaced in chat responses.
- [x] Generation registry, terminal-event guarantees and lock release on every outcome.
- [x] Phase 5 hardening: conditional terminal transitions (no completed→cancelled regressions),
      bounded stream queue, generation timeout, app-shutdown cancellation, adapter-through-engine
      integration tests and 12-iteration cancel/completion race coverage.
- [x] Milestone 5.3-A: deletion during generation is finalized without raising
      (`conversation_deleted` terminal event, nothing persisted) and `shutdown()` serialises with
      the start handshake (barrier + bounded drain, late starts → 503 `server_shutting_down`).
- [x] Milestone 5.3-B: shielded terminal writes drained on shutdown, idempotent
      `GenerationStream.close()`, deterministic ASGI disconnect handling, replay reporting the
      persisted provider/model, and coverage for partial persistence, non-streaming timeout,
      streaming `context_too_large`, replay of failed/cancelled turns, idempotency 409, the
      cancel-then-resend window, `finalize_message` idempotency and frontend terminal reconciliation.
- [x] Milestone 5.3-C1/C2: loopback end-to-end validation (health, CRUD, SSE, cancel, 409,
      delete-during-generation, restart persistence, real-TCP disconnect, SIGKILL recovery,
      controlled shutdown); localized `conversation_deleted` / `server_shutting_down`; SSE
      `: keep-alive` comment frames for silent generations; one arbitrary `sleep` replaced by an
      event barrier in the cancel test. Browser integration against Vite remains blocked by the
      approval layer (pending for 5.3-C3).
- [x] Milestone 5.3-C3: final audit. Coverage measured with a stdlib `sys.settrace` harness
      (92.3 % of `orbit/chat` + `orbit/conversations` + `orbit/providers`, 218/218 tests passing
      under instrumentation); two flaky wall-clock bounds replaced by generous/event-based waits;
      browser → Vite → isolated backend session evidenced with headless Chromium over CDP;
      `docs/HOMOLOGATION.md` added with the functional checklist, commit plan, publication
      security checklist and 1.0 blockers. Web UI still has no conversation delete/rename.

## P2 — Milestone 4: web and CLI

- [x] React + Vite + TypeScript scaffold, nine-item navigation shell, responsive layout,
      dark/light themes with persisted/system preference.
- [x] i18n foundation: pt-BR, en-US, es-ES with typed catalogs, persisted locale, parity tests.
- [x] Frontend CI job (Node 20: lint, typecheck, tests, build) and Vitest/RTL setup.
- [x] API integration: typed client, health/system info, providers, models, default selection,
      uniform errors and loading/empty/unavailable states, with mocked-API tests.
- [x] Chat experience: conversations, history, POST/SSE streaming, cancellation, safe Markdown.
- [x] Phase 4 UX/quality pass: a11y (drawer/escape/focus/live regions), composer limits,
      Markdown image blocking, reliability tests, WCAG AA contrast, docs. Visual validation
      completed at 360/390/768/1024/1440 px and five localized visual fixes applied; frontend
      regression coverage includes tagline/collapse/drawer, badge contrast, Settings width and
      the ≤390 px topbar.
- [ ] Setup wizard using only real backend contracts (no browser credential storage).
- [ ] Typer CLI (`orbit`, `orbit doctor`, `orbit status`, `orbit models`, …) reusing the same
      app factory and settings; auto-start/reuse local server.
- [ ] Playwright smoke tests.

## P2 — Milestone 5: agent runtime

- [ ] Agent definition model and lifecycle.
- [ ] Async execution loop with planning, tool selection and observation phases.
- [ ] Iteration, token, cost and wall-clock limits; cancellation; retry policy.
- [ ] Execution event stream and persisted traces.
- [ ] Orchestrator for task submission/state/history (multi-agent ready).

## P2 — Milestone 6: tools and security

- [ ] Tool registry with JSON-schema inputs/outputs, timeouts and audit logging.
- [ ] Tools: calculator, file read/write/list/search, HTTP fetch, JSON, CSV.
- [ ] Filesystem sandbox rooted at authorised directories; path traversal protection.
- [ ] Permission policy engine and human-approval workflow (API + UI + CLI).
- [ ] Audit log storage and inspection endpoints; prompt-injection mitigations.

## P2 — Milestone 7: memory and skills

- [ ] Conversation, short-term, agent and user memory with retrieval API.
- [ ] Memory inspection/correction/deletion endpoints and UI.
- [ ] Skill discovery, installation, activation, permissions, versioning; untrusted by default.

## P2 — Milestone 8: packaging and release

- [ ] PyInstaller `onedir` build for Linux ARM64, validated locally.
- [ ] Linux x64 and Windows x64 builds via GitHub Actions.
- [ ] Install/uninstall scripts with checksum verification and data preservation.
- [ ] Alpha release checklist, changelog, install documentation.

## Technical debt / hygiene

Priority: P1 blocks external exposure, P2 before agent runtime/tools, P3 polish.

- [x] P1: measure a real coverage baseline for `orbit/chat`, `orbit/conversations`,
      `orbit/providers` (92.3 % with a stdlib tracer, 2026-11-19).
- [ ] P1: add `pytest-cov` + a coverage threshold in CI and lockfiles (`pip-audit` in CI too).
- [ ] P1: run a dependency vulnerability scan (`pip-audit` or equivalent) in CI; add lockfile.
- [x] P2: SSE keep-alive comments for silent generations behind proxies (implemented, 15 s).
- [ ] P2: validate `PUT /api/v1/models/default` against provider discovery (cached) instead of
      deferring to send time.
- [ ] P2: cap assistant output size independently of provider/model limits.
- [ ] P2: bound context queries (the builder currently loads the full completed dialogue before
      trimming); add a windowed query for very long conversations.
- [ ] P2: unify conversation CRUD service and engine repository access before tools/agents.
- [ ] P2: expose a `replayed` flag in generation responses for idempotent retries.
- [ ] P3: explicitly chmod `-wal`/`-shm` files to `0600` on connect.
- [x] P3: `docs/INSTALL.md` and `docs/CONFIGURATION.md` added (plus `docs/RUNNING.md`,
      `docs/HOMOLOGATION.md`).
- [ ] P3: add structured request logging tests for SSE.
- [ ] P3: expand `ruff` rules (`ARG`, `PT`) after MVP stabilises.
- [ ] Live smoke test against a configured provider (requires approval, not paid by default).
