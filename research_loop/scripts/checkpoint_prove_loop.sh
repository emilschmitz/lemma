#!/usr/bin/env bash
# Snapshot gitignored prove_loop agent bodies for rollback (see AGENTS.md).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL="${1:-$(date -u +%Y%m%dT%H%M%SZ)}"
SRC="$ROOT/research_loop/generated/prove_loop"
OUT_DIR="$ROOT/research_loop/artifacts"
OUT="$OUT_DIR/prove_loop_${LABEL}.tar.gz"

if [[ ! -d "$SRC" ]]; then
  echo "missing $SRC" >&2
  exit 1
fi
mkdir -p "$OUT_DIR"
# Only agent bodies + query.sql/meta — skip assembled/verify logs (large, regenerable).
tar -C "$ROOT/research_loop/generated" -czf "$OUT" \
  --exclude='*/assembled.rs' \
  --exclude='*/verify_*.log' \
  --exclude='*/verify_run.out' \
  --exclude='*/spec_transpiled.rs' \
  prove_loop

echo "wrote $OUT ($(du -h "$OUT" | awk '{print $1}'))"
echo "restore: tar -xzf $OUT -C $ROOT/research_loop/generated"
