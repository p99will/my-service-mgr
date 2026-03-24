#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
PYTHON_BIN="$VENV_DIR/bin/python"
RUN_TESTS=1
CLEAN_FIRST=0

usage() {
  cat <<'EOF'
Usage: ./build.sh [--clean] [--skip-tests]

Build source and wheel distributions from the repo virtualenv.

Options:
  --clean       Remove existing build artifacts before building
  --skip-tests  Skip the unittest preflight step
  -h, --help    Show this help text
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --clean)
      CLEAN_FIRST=1
      ;;
    --skip-tests)
      RUN_TESTS=0
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

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Error: missing virtualenv at $VENV_DIR. Run ./install.sh first." >&2
  exit 1
fi

if [[ "$CLEAN_FIRST" -eq 1 ]]; then
  rm -rf "$ROOT_DIR/build" "$ROOT_DIR/dist" "$ROOT_DIR/src"/*.egg-info
fi

if ! "$PYTHON_BIN" -c "import build" >/dev/null 2>&1; then
  echo "Error: missing Python package 'build' in $VENV_DIR. Run ./install.sh first." >&2
  exit 1
fi

if [[ "$RUN_TESTS" -eq 1 ]]; then
  "$PYTHON_BIN" -m unittest discover -s tests
fi

"$PYTHON_BIN" -m build --no-isolation

echo "Build complete."
echo "Artifacts: $ROOT_DIR/dist"
