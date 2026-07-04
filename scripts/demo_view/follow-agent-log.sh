#!/usr/bin/env bash
# Tail agent.log — live Cursor agent stream (requires AGENT_CMD with stream-json; see config.env).
set -euo pipefail
source "$(dirname "$0")/_paths.sh"

fresh_view_file "$AGENT_LOG"
demo_clear_screen

exec tail -n 0 -F "$AGENT_LOG"
