# Configuration

All backend settings come from environment variables prefixed with `ORBIT_`. `.env` is optional
and must never be committed. Credentials are held as `SecretStr` and are never logged, serialized
or returned by the API.

## Runtime

| Variable | Default | Notes |
| --- | --- | --- |
| `ORBIT_ENV` | `development` | Free-form environment label |
| `ORBIT_HOST` | `127.0.0.1` | Keep loopback unless a reverse proxy terminates TLS |
| `ORBIT_PORT` | `18700` | API port |
| `ORBIT_LOG_LEVEL` | `INFO` | Standard Python levels |
| `ORBIT_LOG_JSON` | `false` | JSON logs for aggregation |
| `ORBIT_DOCS_ENABLED` | `true` | OpenAPI docs at `/docs` |

## Storage

| Variable | Default | Notes |
| --- | --- | --- |
| `ORBIT_DATA_DIR` | platform data dir (`/var/lib/orbit-ai` on Linux) | Created with mode `0700` |
| `ORBIT_LOG_DIR` | platform log dir (`/var/log/orbit-ai` on Linux) | Created on startup |
| `ORBIT_DATABASE_URL` | derived SQLite URL | `sqlite+aiosqlite:////path/orbit.db` |
| `ORBIT_AUTO_MIGRATE` | `true` | Alembic upgrades on startup |

The database file is created with mode `0600`. Back it up with the backend stopped.

## CORS

`ORBIT_CORS_ORIGINS` is empty by default (same-origin only). The Vite development proxy makes CORS
unnecessary. For a separately hosted UI, set an explicit JSON list or comma-separated origins.

## Providers

| Variable | Default | Notes |
| --- | --- | --- |
| `ORBIT_OPENROUTER_API_KEY` | unset | Required to use OpenRouter |
| `ORBIT_OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Override only for compatible gateways |
| `ORBIT_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local Ollama endpoint |
| `ORBIT_REQUEST_TIMEOUT_SECONDS` | `120` | Per-request provider timeout |
| `ORBIT_PROVIDER_MAX_ATTEMPTS` | `3` | Bounded retries with backoff |
| `ORBIT_PROVIDER_RETRY_BACKOFF_SECONDS` | `0.5` | Base backoff |
| `ORBIT_GENERATION_TIMEOUT_SECONDS` | `300` | Total generation budget; `null` disables it |
| `ORBIT_MAX_OUTPUT_TOKENS` | `8192` | Maximum assistant output tokens allowed by ORBIT AI |

Providers appear as *configured* when their required settings exist; availability is confirmed by
`POST /api/v1/providers/{id}/test` and model discovery. The UI never stores credentials.

## Frontend

- `ORBIT_BACKEND_URL` (Vite only): proxy target, default `http://127.0.0.1:18700`.
- API calls use relative `/api/v1` paths; production hosting must serve the UI and API on the same
  origin or configure CORS explicitly.

## Security notes

- Bind to `127.0.0.1` by default; do not expose the API publicly without authentication and TLS.
- Shell and arbitrary code execution tools are disabled by default.
- Treat model output, provider errors and web content as untrusted input.
