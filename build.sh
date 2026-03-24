#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "Error: python3 is required." >&2
  exit 1
fi

if ! "$PYTHON_BIN" -m build --version >/dev/null 2>&1; then
  echo "Error: python build backend is not installed in this environment." >&2
  echo "Run: $PYTHON_BIN -m pip install build" >&2
  exit 1
fi

exec "$PYTHON_BIN" -m build
