#!/usr/bin/env bash
# Start ORBIT AI from the repository virtualenv.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -x .venv/bin/python ]]; then
  echo "Virtualenv missing. Create it with: python3 -m venv .venv && pip install -e '.[dev]'" >&2
  exit 1
fi

exec .venv/bin/python -m orbit "$@"
