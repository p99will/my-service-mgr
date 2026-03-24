#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
PYTHON_BIN="$VENV_DIR/bin/python"
REMOVE_VENV=0
REMOVE_ARTIFACTS=0

usage() {
  cat <<'EOF'
Usage: ./uninstall.sh [--remove-venv] [--remove-artifacts]

Uninstall the package from the repo virtualenv and optionally clean local files.

Options:
  --remove-venv       Delete the repo virtualenv after uninstalling
  --remove-artifacts  Delete build/, dist/, and src/*.egg-info
  -h, --help          Show this help text
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remove-venv)
      REMOVE_VENV=1
      ;;
    --remove-artifacts)
      REMOVE_ARTIFACTS=1
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

if [[ -x "$PYTHON_BIN" ]]; then
  "$PYTHON_BIN" -m pip uninstall -y my-service-mgr || true
else
  echo "No repo virtualenv found at $VENV_DIR; skipping package uninstall."
fi

if [[ "$REMOVE_ARTIFACTS" -eq 1 ]]; then
  rm -rf "$ROOT_DIR/build" "$ROOT_DIR/dist" "$ROOT_DIR/src"/*.egg-info
fi

if [[ "$REMOVE_VENV" -eq 1 ]]; then
  rm -rf "$VENV_DIR"
fi

echo "Uninstall cleanup complete."
