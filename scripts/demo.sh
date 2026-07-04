#!/usr/bin/env bash
# Live demo: clear cache → real agent (no mock) → DuckDB CLI with demo UI on.
# For Twitter/recording: split terminal, right pane = follow-agent-log.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

QUERY_ID="${DEMO_QUERY_ID:-3}"

echo "==> Clearing Lemma cache (all optimized queries)..."
uv run python "$ROOT/scripts/demo_lib.py" clear

SQL_ONELINE="$(uv run python -c "
import sys; sys.path.insert(0, '$ROOT')
from scripts.demo_lib import sql_one_line
print(sql_one_line($QUERY_ID))
")"

export LEMMA_DEMO=1
export LEMMA_DEMO_CLI_WIDTH=30
export LEMMA_DATASET_SIZE=100000
export LEMMA_DEMO_VIEW_DIR="$ROOT/research_loop/demo_view/state"
mkdir -p "$LEMMA_DEMO_VIEW_DIR"
: >"$LEMMA_DEMO_VIEW_DIR/agent.log"
export MOCK_AGENT=0
export USE_AGENT_DOCKER=0
export MAX_ITERATIONS=1
export LEMMA_VERBOSE=0
export LEMMA_LOG_LEVEL=WARN

if [ ! -f "$ROOT/build/lemma.duckdb_extension" ]; then
  echo "==> Building extension (first time)..."
  make extension
fi
uv run python -m db_extension.prepare_data

if [[ -t 1 ]] && command -v clear >/dev/null 2>&1; then
  clear
fi

cat <<EOF

╔══════════════════════════════════════════════════════════════════════╗
║  Lemma live demo (Q${QUERY_ID}, 100k rows) — DuckDB shell below         ║
╚══════════════════════════════════════════════════════════════════════╝

  MOCK_AGENT=0 — real agent streams to agent.log (uses your local \`agent\` CLI auth).

  DuckDB's built-in timer is already on (.timer on in init.sql).
  After a plain SELECT, look for "Run Time (s): real ..." below the result.

  (1) Vanilla DuckDB:

    ${SQL_ONELINE}

  (2) Lemma — progress above the box; result below. Turn off timer first:

    .timer off

    SELECT lemma('${SQL_ONELINE}');

  (3) Run (2) again → cached optimized binary (💾 path in demo UI).

  Paste only the SELECT line — not the emoji progress lines above it.

  Tip: use the default DuckDB prompt (D ); paste full SQL starting with SELECT.

  Right pane (split terminal): ./scripts/demo_view/follow-agent-log.sh

  Mock / offline replay: ./scripts/mockdemo.sh

Press Enter to open DuckDB CLI...
EOF
read -r _

if [[ -t 1 ]] && command -v clear >/dev/null 2>&1; then
  clear
fi

exec "$ROOT/scripts/duckdb_shell.sh"
