#!/usr/bin/env bash
# Dafny MethodSpec (written when agent iteration starts / workspace prepared).
set -euo pipefail
source "$(dirname "$0")/_paths.sh"

TARGET="${VIEW_DIR}/spec.dfy"
if [[ -f "$SPEC" ]]; then
  TARGET="$SPEC"
fi

echo "=== Dafny spec ==="
echo "  $TARGET"
echo "  Ctrl-C to quit"
echo

if [[ ! -f "$TARGET" ]]; then
  echo "(waiting for spec — run lemma or start agent iteration...)"
  touch "$TARGET"
fi

if command -v bat >/dev/null 2>&1; then
  bat --plain --language=dafny "$TARGET" 2>/dev/null || true
  echo "--- live (tail -F) ---"
fi
exec tail -n 32 -F "$TARGET"
