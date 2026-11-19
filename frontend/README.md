# ORBIT AI — Web UI

React 18 + TypeScript + Vite 6 frontend for ORBIT AI.

Requires **Node.js 20+** (`nvm use` reads `frontend/.nvmrc`). CI uses Node 20.

## Development

```bash
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173 (proxies /api and /health to 127.0.0.1:18700)
```

Start the backend separately from the repository root:

```bash
source .venv/bin/activate
python -m orbit
```

Override the proxy target with `ORBIT_BACKEND_URL=http://127.0.0.1:<port> npm run dev`.

## Quality gates

```bash
npm run lint
npm run typecheck
npm run test
npm run build
```

## Accessibility and reliability

- Mobile navigation: `aria-expanded`/`aria-controls`, Escape to close, focus trap, focus
  restoration, background scroll lock and `inert`/`aria-hidden` while closed.
- Chat: polite live announcements for generation start/completion/cancellation/failure; focus
  returns to the composer after cancellation or failure.
- Composer: 32,000-character limit, accessible counter and `aria-describedby` guidance.
- Markdown: raw HTML disabled, unsafe protocols dropped, remote images blocked with alt text.
- Reliability: SSE buffer cap and reader cancellation, 30 s connection timeout, terminal-state
  reconciliation with the backend, safe retry via a stable `client_message_id`, and an 8 s
  cancellation fallback that aborts and reconciles the persisted history.
- Theme tokens meet WCAG AA for normal text; the contrast check is enforced by a unit test.

## Current scope

Milestone 4, Phase 3 (chat experience): application shell, nine-item navigation, dark/light
themes, pt-BR/en-US/es-ES internationalization, live backend data pages and a full chat UI.

| UI area | Backend contract |
| --- | --- |
| Settings → backend health | `GET /health` |
| Settings → system information | `GET /api/v1/system/info` |
| Providers → list/status | `GET /api/v1/providers` |
| Providers → test connection | `POST /api/v1/providers/{id}/test` |
| Models → discovery | `GET /api/v1/models` |
| Models → default selection | `GET`/`PUT /api/v1/models/default` |
| Chat → conversations | `GET`/`POST /api/v1/conversations` |
| Chat → history | `GET /api/v1/conversations/{id}/messages` |
| Chat → send/stream | `POST /api/v1/conversations/{id}/messages` (`stream=true`, SSE) |
| Chat → stop generation | `POST /api/v1/conversations/{id}/cancel` |

All requests go through a typed client (`src/api/client.ts`) with 20-second defaults, longer
timeouts for discovery/connection tests, abort-on-unmount, backend error-envelope normalization
and request-id display. The SSE endpoint is consumed with `fetch` + `ReadableStream`
(`src/api/sse.ts`), never `EventSource`; the parser handles fragmented chunks, multiple events per
chunk, CRLF, comments, multibyte UTF-8, malformed frames and premature termination (shown as an
interrupted generation with partial content preserved).

Chat guarantees: a stable `client_message_id` per send (reused on retry), no duplicate sends while
streaming, history reconciliation after terminal events, cancellation with partial content, and
conversation isolation when switching. Markdown uses `react-markdown` with raw HTML skipped and
URL protocols restricted to http/https/mailto; no `dangerouslySetInnerHTML`.

The setup wizard remains out of scope. Placeholder areas show a "Coming soon" state instead of
simulated data.

## Conventions

- All user-facing strings live in `src/i18n/*` (no hardcoded functional copy in components).
- Design tokens and breakpoints live in `src/styles/tokens.css` and `src/styles/global.css`.
- The backend is the single source of truth; the UI never invents providers, models or messages.
- No credentials are ever stored in `localStorage`, `sessionStorage` or frontend config.
- Provider credentials are configured only through backend environment variables.