#!/usr/bin/env bash
# Generated + post-processed Rust (updates after Dafny→Rust + postprocess).
set -euo pipefail
source "$(dirname "$0")/_paths.sh"

echo "=== working_query.rs ==="
echo "  $RUST"
echo "  Ctrl-C to quit"
echo

touch "$RUST" 2>/dev/null || true
if command -v bat >/dev/null 2>&1; then
  bat --plain --language=rust "$RUST" 2>/dev/null || true
  echo "--- live (tail -F) ---"
fi
exec tail -n 40 -F "$RUST"
