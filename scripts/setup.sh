#!/usr/bin/env bash
# One-time / idempotent dev setup: deps, Python env, ssb-dbgen clone.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

WITH_DATASET=0
CHECK_ONLY=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Install Python deps, clone ssb-dbgen if missing, optionally build SSB flat data.

Options:
  --with-dataset   Run build_ssb_flat_dataset.sh (slow; ~2M rows, several minutes)
  --check          Verify required tools only; exit 1 if any missing
  -h, --help       Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-dataset) WITH_DATASET=1; shift ;;
    --check) CHECK_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

require() {
  local label="$1"
  shift
  for cmd in "$@"; do
    if command -v "$cmd" >/dev/null 2>&1; then
      return 0
    fi
  done
  echo "Missing required tool: $label (need one of: $*)" >&2
  return 1
}

missing=0
require "uv" uv || missing=1
require "Dafny" dafny || missing=1
require "Rust/Cargo" cargo || missing=1
require "C++ compiler" g++ c++ || missing=1
require "make" make || missing=1
require "curl" curl || missing=1
require "unzip" unzip || missing=1
require "git" git || missing=1

if [[ "$missing" -ne 0 ]]; then
  echo "Install missing tools, then re-run ./scripts/setup.sh" >&2
  exit 1
fi

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  echo "All required tools present."
  exit 0
fi

echo "==> Python dependencies (uv sync --all-groups)..."
uv sync --all-groups

echo "==> ssb-dbgen..."
"$ROOT/scripts/ensure_ssb_dbgen.sh"

if [[ "$WITH_DATASET" -eq 1 ]]; then
  echo "==> Building SSB flat dataset..."
  "$ROOT/scripts/build_ssb_flat_dataset.sh"
fi

echo "Setup OK. Run: ./scripts/demo.sh  (or ./scripts/mockdemo.sh without LLM agent)"
