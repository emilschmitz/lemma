#!/usr/bin/env bash
# Live demo: ensure dataset + extension → clear cache → real agent → DuckDB CLI.
# For Twitter/recording: split terminal, right pane = follow-agent-log.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

One-shot Lemma demo. Builds SSB flat data and extension if missing, sets demo
env defaults (only when unset), clears cache, opens DuckDB CLI.

Options (override env vars for this run):
  -q, --query ID     SSB query id for on-screen SQL (default: 3)
  -r, --rows N       LEMMA_DATASET_SIZE cap (default: 100000)
  -s, --scale F      LEMMA_SSB_SCALE when building dataset (default: 1.333)
      --no-clear     Skip Lemma cache clear
  -h, --help         Show this help

Env (used when set; otherwise defaults above apply):
  DEMO_QUERY_ID, LEMMA_DATASET_SIZE, LEMMA_SSB_SCALE, MOCK_AGENT, etc.

Offline / no LLM: ./scripts/mockdemo.sh
EOF
}

SKIP_CLEAR=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -q|--query) export DEMO_QUERY_ID="${2:?}"; shift 2 ;;
    -r|--rows) export LEMMA_DATASET_SIZE="${2:?}"; shift 2 ;;
    -s|--scale) export LEMMA_SSB_SCALE="${2:?}"; shift 2 ;;
    --no-clear) SKIP_CLEAR=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

QUERY_ID="${DEMO_QUERY_ID:-3}"

"$ROOT/scripts/setup.sh"

# Demo defaults — apply only when not already set in the environment.
export LEMMA_DEMO="${LEMMA_DEMO:-1}"
export LEMMA_DEMO_CLI_WIDTH="${LEMMA_DEMO_CLI_WIDTH:-30}"
export LEMMA_DATASET_SIZE="${LEMMA_DATASET_SIZE:-100000}"
export LEMMA_SSB_SCALE="${LEMMA_SSB_SCALE:-1.333}"
export LEMMA_DEMO_VIEW_DIR="${LEMMA_DEMO_VIEW_DIR:-$ROOT/research_loop/demo_view/state}"
export MOCK_AGENT="${MOCK_AGENT:-0}"
export USE_AGENT_DOCKER="${USE_AGENT_DOCKER:-0}"
export MAX_ITERATIONS="${MAX_ITERATIONS:-1}"
export LEMMA_VERBOSE="${LEMMA_VERBOSE:-0}"
export LEMMA_LOG_LEVEL="${LEMMA_LOG_LEVEL:-WARN}"

FLAT_TBL="$(uv run python -c "
import sys; sys.path.insert(0, '$ROOT')
from db_extension.dataset_config import tbl_path
print(tbl_path())
")"

if [[ ! -f "$FLAT_TBL" ]]; then
  echo "==> SSB flat table missing — building dataset (first time, may take a few minutes)..."
  "$ROOT/scripts/build_ssb_flat_dataset.sh"
fi

echo "==> Building DuckDB extension..."
make extension

if [[ "$SKIP_CLEAR" -eq 0 ]]; then
  echo "==> Clearing Lemma cache (all optimized queries)..."
  uv run python "$ROOT/scripts/demo_lib.py" clear
fi

SQL_ONELINE="$(uv run python -c "
import sys; sys.path.insert(0, '$ROOT')
from scripts.demo_lib import sql_one_line
print(sql_one_line($QUERY_ID))
")"

mkdir -p "$LEMMA_DEMO_VIEW_DIR"
: >"$LEMMA_DEMO_VIEW_DIR/agent.log"

echo "==> Preparing DuckDB init SQL (prepare_data)..."
uv run python -m db_extension.prepare_data

if [[ -t 1 ]] && command -v clear >/dev/null 2>&1; then
  clear
fi

cat <<EOF

╔══════════════════════════════════════════════════════════════════════╗
║  Lemma live demo (Q${QUERY_ID}, ${LEMMA_DATASET_SIZE} rows) — DuckDB shell below      ║
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
