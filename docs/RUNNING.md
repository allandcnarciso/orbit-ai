# Running ORBIT AI locally

## Backend

```bash
source .venv/bin/activate
python -m orbit
```

Defaults: `http://127.0.0.1:18700`, SQLite in the platform data directory, logs in the platform log
directory. Useful endpoints:

- `GET /health` — process and database checks
- `GET /api/v1/health` — versioned health
- `GET /api/v1/system/info` — runtime information
- `GET /docs` — OpenAPI UI

Stop with `Ctrl+C`; the lifespan closes the generation engine, providers and database cleanly.

## Web UI development

```bash
cd frontend
nvm use
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies API traffic to `http://127.0.0.1:18700` by default.
Override with `ORBIT_BACKEND_URL=http://127.0.0.1:18701 npm run dev` when testing another port.

The UI supports pt-BR, en-US and es-ES, dark/light themes and a responsive chat layout. Chat
requires a configured provider; without one, the UI shows the real provider/model error states.

## Production-style check

```bash
cd frontend
npm run build
npm run preview             # loopback preview of the production bundle
```

Serve `frontend/dist` from a static server and route `/api`, `/health` and `/docs` to the backend.
Keep everything on loopback unless a reverse proxy provides TLS and authentication.

## Tests

```bash
pytest -q
ruff check . && ruff format --check .
mypy

cd frontend && npm run lint && npm run typecheck && npm run test && npm run build
```

Frontend tests mock the HTTP/SSE boundary; they never call a real provider.

## Troubleshooting

- **Port in use**: set `ORBIT_PORT`; the UI proxy follows `ORBIT_BACKEND_URL`.
- **Database locked**: only one backend process may own the SQLite file; stop duplicates.
- **Provider unavailable**: check the environment variables and run the provider test in the UI.
- **Chat disabled after error**: verify `/health`, then reload the conversation.
- **Node engine warning**: use Node 20 (`nvm use`); CI uses Node 20.
