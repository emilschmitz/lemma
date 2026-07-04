#!/usr/bin/env bash
# Best for watching the agent edit RunQuery live (file grows on save).
set -euo pipefail
source "$(dirname "$0")/_paths.sh"

echo "=== RunQuery body ==="
echo "  $BODY"
echo "  (MOCK_AGENT=1: lines appear during 🦾 Generating RunQuery. Real agent: on save.)"
echo "  Ctrl-C to quit"
echo

touch "$BODY" 2>/dev/null || true
if command -v bat >/dev/null 2>&1; then
  # bat doesn't tail; use tail for stream, bat for initial snapshot
  bat --plain --language=dafny "$BODY" 2>/dev/null || true
  echo "--- live (tail -F) ---"
fi
exec tail -n 24 -F "$BODY"
