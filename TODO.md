# TODO

Prioritised development backlog. P0 blocks the current milestone; P1 is the next milestone;
P2 is planned but not scheduled.

## P0 — Milestone 1 close-out

- [x] Install dependencies into `.venv` and run the full test suite (32 passed).
- [x] Fix lint (`ruff`), format and type (`mypy --strict`) failures.
- [ ] Configure a git author identity and commit Milestone 1 locally.
- [ ] Confirm CI workflow passes once pushed (requires approval).

## P1 — Milestone 2: model providers

- [ ] `orbit/providers/base.py`: `ModelProvider` protocol, `ModelInfo`, `ChatMessage`,
      `CompletionRequest`, `CompletionChunk`, normalised `ProviderError` taxonomy.
- [ ] Provider registry with capability detection and per-provider configuration.
- [ ] OpenRouter adapter: `/models` discovery, chat completions, SSE streaming, retries with
      backoff, timeout handling.
- [ ] Ollama adapter: `/api/tags` discovery, `/api/chat` streaming, connection test.
- [ ] Credential storage: OS keyring first, encrypted fallback; never plaintext in SQLite.
- [ ] `POST /api/v1/providers/{id}/test` connection endpoint and model listing endpoints.
- [ ] Recorded-fixture tests for both adapters; no live API calls in CI.

## P1 — Milestone 3: chat

- [ ] `conversations` and `messages` tables + migration.
- [ ] Chat service and `POST /api/v1/chat/completions` (SSE), cancellation.
- [ ] Conversation CRUD, history retrieval, basic context-window management.
- [ ] Token/cost accounting fields for later limits.

## P2 — Milestone 4: web and CLI

- [ ] React + Vite + TypeScript app; chat view, navigation shell, dark/light themes.
- [ ] Setup wizard (language, provider, key/endpoint, discovery, model, test, assistant).
- [ ] i18n: pt-BR, en-US, es-ES; UI language independent of model language.
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

- [ ] Add `docs/INSTALL.md` and `docs/CONFIGURATION.md` when packaging lands.
- [ ] Add structured request logging tests for SSE once chat exists.
- [ ] Consider `ruff` rule set expansion (`ARG`, `PT`) after MVP stabilises.
