# Installation

ORBIT AI runs as a single Python process with an optional React Web UI. The backend must be
installed first; the UI is a pure API client.

## Requirements

- Linux x86_64/aarch64, macOS, or Windows (WSL2 recommended) with Python **3.12+**
- Node.js **20+** and npm (only for the Web UI)
- A writable data directory and a usable SQLite (bundled with Python)
- No Docker, root privileges, or system packages are required

## Backend

```bash
git clone https://github.com/allandcnarciso/orbit-ai.git
cd orbit-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # optional; edit values
python -m orbit             # http://127.0.0.1:18700
```

The first start creates the data directory, the SQLite database (mode `0600`), runs Alembic
migrations, and serves the API. Health check:

```bash
curl -s http://127.0.0.1:18700/health
```

## Web UI

```bash
cd frontend
nvm use                     # reads .nvmrc (Node 20)
npm ci
npm run dev                 # http://127.0.0.1:5173
```

Vite proxies `/api`, `/health`, `/docs` and `/openapi.json` to `http://127.0.0.1:18700`
(override with `ORBIT_BACKEND_URL`). Run the backend in another terminal.

Production build:

```bash
cd frontend
npm run build               # outputs frontend/dist
```

## Verification

```bash
# backend
pytest -q
ruff check .
mypy

# frontend
cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
```

## Updating

Pull the repository, reinstall the editable package if dependencies changed
(`pip install -e ".[dev]"`), run migrations on startup, and rebuild the frontend. Never edit the
SQLite file while the backend is running.
