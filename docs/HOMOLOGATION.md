# Homologation checklist — Milestone 5.3

Status: **basic functional homologation COMPLETE — H01…H08-B.3 approved on 2026-11-19.**
The system is ready for the versioning/publication preparation, but **not** for a 1.0 release:
the blockers in §7 remain open. Browser-level integration was evidenced on 2026-11-19.

Legend: [x] verified in this repository · [~] verified with a documented limitation ·
[ ] not verified / blocking.

## 0. Functional homologation result (H01…H08-B.3)

All items below were declared **APPROVED** by the product owner on 2026-11-19, following the manual
script below. The table separates the *manual* validation performed in the browser from the
*automated* evidence that backs each item, so the two are not conflated.

| Item | Official scope | Manual (browser) | Automated / API evidence |
|---|---|---|---|
| H01 | Interface and navigation (shell, sidebar, themes, i18n, pages render) | [x] approved | [x] Vitest app/a11y/contrast/i18n-parity/visual-regression suites |
| H02 | Conversation creation and persistence | [x] approved | [x] `POST/GET /api/v1/conversations` (201/200); conversation API + repository tests |
| H03 | Providers and models (status, catalog, default selection) | [x] approved | [x] `GET /api/v1/providers`, `GET /api/v1/models`, `GET|PUT /models/default`; API-page tests |
| H04 | Message sending and streaming integrity | [x] approved | [x] SSE `started` + 8 `content.delta` + one `completed`; `test_six_chunk_stream_persists_every_delta`; frontend H04 regression |
| H05 | Cancellation (stop button, composer recovery) | [x] approved | [x] `POST /cancel` 200 → `message.cancelled`; lock released; cancel/resend 409 window covered |
| H06 | Message history (pagination, reload, persistence) | [x] approved | [x] `before_sequence` pagination; history survives restart; reload-after-terminal tests |
| H07 | Switching between conversations (isolation, abort of the previous stream) | [x] approved | [x] `isolates conversations and aborts streaming when switching`; stream-abort + history reload tests |
| H08-A | Responsiveness (including 390 × 844) | [x] approved | [x] mobile drawer/focus-trap/Escape tests; ≤390 px topbar regression; 360/390/768/1024/1440 px validation |
| H08-B | Error handling and recovery | [x] approved | see B.1–B.3 below |
| H08-B.1 | Provider failure **before** any content (HTTP 500) | [x] approved | [x] `[[fail]]` → `message.failed`, `provider_unavailable`, `retryable=true`, empty content, lock released |
| H08-B.2 | Provider failure **mid-stream** (socket drop) | [x] approved | [x] `[[failmid]]` → `message.failed`, partial content `"Hello from"` preserved, lock released |
| H08-B.3 | Recovery: new message after a failure | [x] approved | [x] same conversation, history containing the marker → full 8-chunk `completed`; marker only read from the last user message |

H08-B simulation details (deterministic, reversible, homologation mock only):

- The homologation mock (a small standard-library NDJSON server kept outside the repository)
  recognises `[[fail]]` (immediate HTTP 500) and
  `[[failmid]]` (2 chunks, then abrupt socket close) **only in the last user message**, so a marker
  left in the history cannot affect later generations.
- No product code was changed to produce the failures; the provider error taxonomy and the engine
  terminal path already handled them.
- Reversal: stop sending the markers (no state persists), or restore the pre-change copy of the
  mock over the current script and restart mock + backend.
- Not yet reverted at the time of writing; the mock still carries the markers. The product build
  is unaffected.

What is **not** covered by this homologation: real inference quality (the mock is canned), live
OpenRouter credentials, multi-worker deployments, authentication, and the UI conversation
delete/rename affordances.

### Manual script (browser, approved 2026-11-19)

1. H01 — open the app, navigate the sidebar, switch theme and locale; pages render without errors.
2. H02 — create a conversation; confirm it appears in the sidebar and survives a reload.
3. H03 — check provider status and model catalog; select a default model and confirm it persists.
4. H04 — send a message; observe streaming deltas and the final complete text; composer re-enables.
5. H05 — start a generation and press Stop; the stream ends and the composer re-enables.
6. H06 — reopen the conversation; the full message history is present and paginates.
7. H07 — switch to another conversation mid-stream; the previous generation is aborted and the new
   conversation's history is isolated.
8. H08-A — repeat the main flow at 390 × 844; layout, drawer and composer remain usable.
9. H08-B — send `[[fail]]` (error before content), `[[failmid]]` (error mid-stream, partial preserved)
   and then a marker-free message in the same conversation (recovery works).

## 1. Backend API and persistence

- [x] `GET /health` and `GET /api/v1/health` return 200 with `checks.database = ok`
      (curl against a loopback uvicorn, temporary SQLite).
- [x] Create/list/get/delete conversations (201/200/204/404) with an error envelope that
      always carries `code`, `message` and `request_id`.
- [x] Send a non-streaming message: persisted as `completed` with provider/model, token
      counts and the full content returned by the provider.
- [x] Validation: blank content → 422 `validation_error`; unknown model → 400
      `model_not_found`; unknown conversation → 404 `conversation_not_found`.
- [x] Duplicate in-flight send → 409 `generation_in_progress`, no duplicate messages.
- [x] History survives a backend restart (same data dir, 12 messages replayed).
- [x] Interrupted generation (SIGKILL) is recovered on startup as `failed` /
      `interrupted`, partial content preserved, generation lock cleared.

## 2. Streaming, cancellation and resilience

- [x] SSE stream: `message.started` → N `content.delta` → exactly one terminal event
      (`completed`, `failed` or `cancelled`), verified over real HTTP/curl.
- [x] `POST /cancel` → terminal `message.cancelled` with `reason = cancelled`, partial
      content persisted, lock released.
- [x] Client disconnect over real TCP (socket reset mid-stream) → `cancelled` /
      `client_disconnect`, partial content persisted, lock released, no orphan task, no
      traceback in the server log.
- [x] Conversation deleted during generation → exactly one `message.failed` with
      `error.code = conversation_deleted`; deleted rows are not resurrected.
- [x] Server shutdown during generation: `shutdown()` barrier, bounded drain of
      generations/starts/finalisations, late starts rejected with 503
      `server_shutting_down`; clean uvicorn shutdown log.
- [x] Silent generation emits `: keep-alive` SSE comment frames (15 s interval) without
      affecting event order or the single-terminal invariant. Covered by engine, serialiser
      and parser tests; **not** re-observed over a live socket (test transport buffers).
- [x] Contention: `finalize_message` is a conditional update, `GenerationStream.close()` is
      idempotent, terminal writes are shielded from cancellation.

## 3. Web UI

- [x] 71 Vitest tests: streaming, cancellation, retry with `client_message_id`, conversation
      isolation/abort, history pagination, dropped deltas reconciled from the terminal
      payload, 409 without unsafe retry, 8 s cancel fallback, error localization for
      `conversation_deleted` and `server_shutting_down`.
- [x] `npm run lint`, `npm run typecheck` and `npm run build` clean on the installed
      toolchain (Node 18.19.1; CI pins Node 20).
- [x] SSE parser ignores comment frames (keep-alive) and caps unterminated frames at 1 MB.
- [x] **Browser → Vite → isolated backend end-to-end session** (Chromium 3572 headless via a raw
      CDP client, Vite `127.0.0.1:5186` proxying to `127.0.0.1:18715`, mock Ollama on `18725`):
      created a conversation from the UI, sent a message, rendered the streamed reply, cancelled a
      second generation ("Cancelada"), reloaded and recovered the persisted history. Evidence:
      `GET /api/v1/models/default 200`, `POST /api/v1/conversations 201`,
      `POST /messages 200` + SSE frames, `POST /cancel 200`; zero uncaught exceptions, zero HTTP
      5xx, only React Router v7 future-flag warnings and the expected `net::ERR_ABORTED` from
      intentional stream aborts.
- [~] Conversation deletion is API-only: the web client has no delete affordance, so DELETE was
      verified with `curl` (204, then 404) rather than from the UI. Feature gap, not a defect.

### H04 — content integrity with the mock provider

The mock's canonical reply is `Hello from the mock provider with slow chunks` (8 chunks). A
homologation run started the mock with `MOCK_CHUNKS=6`, so the wire (and therefore the persisted
row) legitimately ended at `...provider with`; the H04 expectation assumed the canonical 8-chunk
text. Pipeline integrity was verified end to end: mock emits 7 NDJSON lines → adapter yields 6
deltas → engine `parts` → persisted row → `message.completed.content`, all identical.
Regression tests: `test_six_chunk_stream_persists_every_delta` (backend) and
`finishes a short final chunk and re-enables the composer (H04)` (frontend). Start the mock without
`MOCK_CHUNKS` for the canonical text.

## 4. Security and repository hygiene

- [x] `.gitignore` covers `.env`, `.env.*` (except `.env.example`), `*.db`, `*.sqlite*`,
      `*.log`, `logs/`, `data/`, `.venv/`, `node_modules/`, `dist/`, `.coverage`,
      `htmlcov/`, `*.pem`, `*.key`.
- [x] No credential, token or key present in tracked or untracked-to-be-committed files
      (pattern scan over `docs/`, `orbit/`, `tests/`, `frontend/src`, `.env.example`).
- [x] `.env` is not tracked; `.env.example` contains only placeholders and comments.
- [x] Backend binds `127.0.0.1` by default, CORS list empty by default, no authentication
      layer (documented as loopback-only deployment).
- [x] `GET /api/v1/system/info` exposes platform/version only — no paths, env or secrets.
- [x] No build artefacts or databases staged; `git diff --cached` empty.
- [x] Preliminary security audit re-run on 2026-11-19 over tracked files plus the untracked-to-be-
      committed set: 0 matches for `sk-…`, `sk-or-v1-…`, `AKIA…`, `ghp_…`, private-key headers or
      `api_key=` assignments. `.env` is not tracked (`git check-ignore` confirms `.gitignore:16`).
      Only `.mypy_cache/3.12/cache.db` exists on disk outside the excluded trees — an ignored tool
      cache, not a database.
- [x] `LICENSE` is the canonical Apache-2.0 text and `SECURITY.md` exists (private reporting
      policy). Remote is `git@github.com:allandcnarciso/orbit-ai.git`; repo-local identity is
      `Allan Narciso <allandcnarciso@gmail.com>`.
- [x] Untracked-to-be-committed volume is 80 files / ~880 KB (frontend sources, new backend
      modules, tests, docs). `node_modules/`, `dist/`, `.venv/`, `*.db`, `*.log` and `.env` are
      excluded by `.gitignore` and were verified with `git check-ignore`.

## 5. Quality gates

- [x] `pytest -q` → 219 passed.
- [x] `ruff check .`, `ruff format --check .`, `mypy` → clean.
- [x] `npm test` → 71 passed; `npm run lint`, `npm run typecheck`, `npm run build` → clean.
- [x] Concurrency tests repeated: `test_chat_integrity + test_streaming_hardening +
      test_chat_api` → 70 passed three times consecutively.
- [x] Line coverage measured with a stdlib `sys.settrace` harness (no dependency install):
      `orbit/chat` 91.7–100 %, `orbit/conversations` 91.2–100 %, `orbit/providers`
      86.2–100 %, total **92.3 % (2222/2407 lines)** with 218/218 tests passing under
      instrumentation (measured at the 218-test baseline; the suite has since grown to 219).
      `orbit/providers/http.py` (86.2 %) and `orbit/chat/context.py` (94.4 %) are the weakest
      modules.
- [ ] `pytest-cov` installed and wired into CI with a floor (needs an approved install).

## 6. Commit and publication plan (NOT executed)

Ordered commits, each expected to be green in isolation:

1. `feat(providers): provider abstraction, HTTP retry client, model catalog`
   — `orbit/providers/*`, `orbit/api/routes/{models,providers}.py`, `orbit/api/schemas.py`,
   provider unit/integration tests, `.env.example`, `docs/{CONFIGURATION,INSTALL,RUNNING}.md`.
2. `feat(storage): conversations, messages, generations and migration 0002`
   — `orbit/storage/models.py`, `orbit/storage/migrations/versions/0002_*.py`,
   `orbit/conversations/*`, repository/service tests.
3. `feat(chat): generation engine, SSE contract and lifecycle hardening`
   — `orbit/chat/*`, `orbit/api/routes/conversations.py`, `orbit/api/serializers.py`,
   `tests/integration/test_chat_*.py`, `tests/integration/test_streaming_hardening.py`,
   `tests/fakes.py`.
4. `feat(web): React chat client with SSE, i18n and themes`
   — `frontend/**`.
5. `docs: architecture decisions ADR-017…ADR-021, status, changelog, homologation checklist`
   — `README.md`, `docs/ARCHITECTURE.md`, `ARCHITECTURE_DECISIONS.md`, `CHANGELOG.md`,
   `DEVELOPMENT_STATUS.md`, `TODO.md`, `docs/HOMOLOGATION.md`, `.github/workflows/ci.yml`.

Publication checklist (GitHub):

- [ ] Confirm `git log` author identity (repo-local `Allan Narciso <allandcnarciso@gmail.com>`).
- [ ] `git status` clean; no untracked secrets; `git diff --cached` reviewed file by file.
- [ ] `LICENSE` (Apache-2.0) and `SECURITY.md` present; prefer private vulnerability reporting.
- [ ] CI green on Node 20 + Python 3.12 with the same commands as §5.
- [ ] Tag `v0.1.0-dev` only after the browser integration item above is verified.
- [ ] Repository description/README do not claim features that are not in the tree.

## 7. Blocking gaps for a 1.0 release

1. Automated coverage gate (`pytest-cov` + floor) in CI; today coverage is measured manually with a
   stdlib tracer and is not enforced.
2. Credential management API and authentication — 1.0 must not ship with an unauthenticated
   API even on loopback (documented limitation today).
3. Multi-worker safety: generation registry and shutdown barrier are in-process; running
   more than one worker requires an external lock/queue.
4. Conversation management in the UI (create and read exist; delete/rename do not).
5. Remaining wall-clock `asyncio.sleep` pacing in race tests (13 occurrences) — acceptable
   today, but a load-sensitive CI risk.
6. Packaging/release automation (no `pyproject` console-script install story for the UI
   bundle, no container image, no versioned migration policy beyond auto-migrate).

## 8. Production deployment checklist (NOT executed)

Preparation only; every item needs explicit approval and a maintenance window.

**Host and network**

- [ ] Dedicated Unix user (no root), data dir `0700`, database `0600`, logs rotated.
- [ ] Bind `127.0.0.1` and expose only through a reverse proxy with TLS (Caddy/nginx); never `0.0.0.0`.
- [ ] Firewall: no inbound port except 443 (and 22 for administration); no public access to 18700/18716.
- [ ] `ORBIT_ENV=production`, `ORBIT_DOCS_ENABLED=false`, explicit `ORBIT_CORS_ORIGINS` if the UI is
      served from another origin.
- [ ] Secrets supplied by the service manager/environment, never in the repo or the SQLite file.

**Authentication (blocker for 1.0)**

- [ ] Authenticate the API (session or bearer token) before any non-loopback exposure; the proxy must
      not be the only control.
- [ ] Rate limiting and request-size limits at the proxy.

**Data**

- [ ] Back up `orbit.db` (WAL checkpoint + copy) on a schedule; test a restore.
- [ ] Document migration policy: `ORBIT_AUTO_MIGRATE=true` on start, with a pre-migration backup.
- [ ] Confirm startup recovery (`interrupted` messages, stale locks) after an unclean stop.

**Runtime**

- [ ] One worker only (in-process generation registry and shutdown barrier); a second worker needs a
      shared lock/queue.
- [ ] Health check on `/health` (database included) with restart-on-failure.
- [ ] Log aggregation and alerting on 5xx / `provider_unavailable` / `internal_error` rates.
- [ ] Resource limits: `ORBIT_REQUEST_TIMEOUT_SECONDS`, `ORBIT_GENERATION_TIMEOUT_SECONDS`,
      `ORBIT_MAX_OUTPUT_TOKENS` tuned to the host.

**Post-deploy verification**

- [ ] `GET /health` 200 with `checks.database = ok`.
- [ ] One streaming round-trip, one cancellation, one provider failure and one history reload.
- [ ] `/docs` reachable only from an authorised network (or disabled).
- [ ] Confirm no credentials or database files are reachable over HTTP.
