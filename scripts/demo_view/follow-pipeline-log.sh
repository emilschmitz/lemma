#!/usr/bin/env bash
# Structured pipeline logs (optimizer, harness, agent_sandbox) if you tee stderr here.
set -euo pipefail
source "$(dirname "$0")/_paths.sh"

echo "=== Pipeline log ==="
echo "  $PIPE_LOG"
echo
echo "Left pane example (inside DuckDB, before lemma):"
echo "  export LEMMA_LOG_LEVEL=INFO"
echo "  .timer off"
echo "  .shell tee -a $PIPE_LOG"
echo "  -- then run SELECT lemma('...'); errors go to log"
echo "Or from shell:"
echo "  MOCK_AGENT=0 LEMMA_DEMO=1 LEMMA_LOG_LEVEL=INFO uv run python -m db_extension.run_optimizer 'SELECT ...' 2>>$PIPE_LOG"
echo "  Ctrl-C to quit"
echo

fresh_view_file "$PIPE_LOG"
exec tail -n 0 -F "$PIPE_LOG"
