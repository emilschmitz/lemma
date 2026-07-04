#!/usr/bin/env bash
# Refreshes whole file ~5×/s (less smooth than tail -F, but readable snapshot).
set -euo pipefail
source "$(dirname "$0")/_paths.sh"

echo "=== RunQuery (watch refresh) ==="
echo "  $BODY"
touch "$BODY" 2>/dev/null || true

if command -v bat >/dev/null 2>&1; then
  exec watch -n 0.2 "bat --plain --language=dafny --paging=never '$BODY' 2>/dev/null | tail -n 45"
else
  exec watch -n 0.2 "tail -n 45 '$BODY'"
fi
