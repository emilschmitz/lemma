#!/usr/bin/env bash
# Compact timeline: which artifact changed (good overview pane).
set -euo pipefail
source "$(dirname "$0")/_paths.sh"

if ! command -v inotifywait >/dev/null 2>&1; then
  echo "inotifywait not found. Install: sudo apt install inotify-tools"
  exit 1
fi

echo "=== File events (modify / close_write) ==="
echo "  watching: $WORKSPACE, $RUST, $VIEW_DIR"
echo "  Ctrl-C to quit"
echo

WATCH=(
  "$WORKSPACE"
  "$WORKSPACE/context"
  "$RUST"
  "$VIEW_DIR"
)
for d in "${WATCH[@]}"; do
  mkdir -p "$d" 2>/dev/null || true
done

inotifywait -m -r -e modify,close_write,create,moved_to \
  "${WATCH[@]}" \
  --format '%T  %w%f' --timefmt '%H:%M:%S' 2>/dev/null
