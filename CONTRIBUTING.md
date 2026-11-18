# Contributing to ORBIT AI

Thanks for helping build ORBIT AI. This guide covers the development loop; the engineering rules
in [AGENTS.md](AGENTS.md) apply to humans and automated agents alike.

## Before you start

- Read [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) to understand the intended design.
- For anything larger than a bug fix, open an issue describing the problem before writing code.
- Security issues go through [SECURITY.md](SECURITY.md), never a public issue.

## Setup

```bash
git clone https://github.com/allandcnarciso/orbit-ai.git
cd orbit-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Workflow

1. Create a branch: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`.
2. Make the smallest coherent change; include tests and documentation.
3. Run `pytest -q`, `ruff check .`, `ruff format --check .`, `mypy`.
4. Commit with an imperative message (`feat: add ollama provider discovery`).
5. Open a pull request describing behaviour, tests and any trade-offs.

## Expectations for a pull request

- Tests cover new behaviour and any fixed bug.
- No secrets, credentials, personal paths or generated build artifacts committed.
- Public API changes are reflected in `README.md` and the OpenAPI schema.
- New persistent state ships with an Alembic migration.
- Security-sensitive changes explain their threat model in the PR description.

## Code style

Python 3.12, type hints everywhere, `ruff` for lint/format (line length 100), `mypy --strict`.
Prefer small functions, explicit interfaces and dependency injection over globals.

## Commit messages

`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `security:` followed by a short
imperative summary. Explain *why* in the body when the change is not obvious.

## License

By contributing you agree that your contributions are licensed under the Apache License 2.0.
