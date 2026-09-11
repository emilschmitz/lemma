#!/usr/bin/env bash
# Local SEC tiny DuckDB product-path driver (Docker agent required).
# Usage: bash research_loop/scripts/local_e2e_tiny_docker.sh [Q1|all|Q1 Q2 Q3]
set -euo pipefail
ROOT="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel)"
cd "$ROOT"
if command -v uv >/dev/null 2>&1; then
  exec uv run python research_loop/scripts/local_e2e_tiny_docker.py "$@"
fi
VENV_PY="$ROOT/.venv/bin/python"
if [[ -x "$VENV_PY" ]]; then
  exec "$VENV_PY" research_loop/scripts/local_e2e_tiny_docker.py "$@"
fi
exec python3 research_loop/scripts/local_e2e_tiny_docker.py "$@"
