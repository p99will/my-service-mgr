#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
PYTHON_BIN="$VENV_DIR/bin/python"
CONFIGURE_HOOKS=1
RECREATE_VENV=0

usage() {
  cat <<'EOF'
Usage: ./install.sh [--recreate-venv] [--no-hooks]

Create or refresh the local development environment in .venv and install the
package in editable mode.

Options:
  --recreate-venv  Delete and recreate the virtualenv before installing
  --no-hooks       Skip configuring git core.hooksPath to .githooks
  -h, --help       Show this help text
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --recreate-venv)
      RECREATE_VENV=1
      ;;
    --no-hooks)
      CONFIGURE_HOOKS=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required." >&2
  exit 1
fi

if [[ "$RECREATE_VENV" -eq 1 && -d "$VENV_DIR" ]]; then
  rm -rf "$VENV_DIR"
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  python3 -m venv "$VENV_DIR"
fi

"$PYTHON_BIN" -m pip install setuptools wheel build
"$PYTHON_BIN" -m pip install -e .

if [[ "$CONFIGURE_HOOKS" -eq 1 && -d "$ROOT_DIR/.git" && -d "$ROOT_DIR/.githooks" ]]; then
  git config core.hooksPath .githooks
fi

echo "Environment is ready."
echo "Activate with: source \"$VENV_DIR/bin/activate\""
echo "Run with: $PYTHON_BIN -m my_service_mgr"
if [[ "$CONFIGURE_HOOKS" -eq 1 && -d "$ROOT_DIR/.githooks" ]]; then
  echo "Git hooks path: .githooks"
fi
