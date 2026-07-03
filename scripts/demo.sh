#!/usr/bin/env bash
# Interactive demo: clear cache → seed hardcoded RunQuery → DuckDB CLI with demo UI on.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

QUERY_ID="${DEMO_QUERY_ID:-3}"

echo "==> Clearing Lemma cache (all optimized queries)..."
uv run python "$ROOT/scripts/demo_lib.py" clear

echo "==> Seeding hardcoded demo RunQuery body for Q${QUERY_ID}..."
uv run python "$ROOT/scripts/demo_lib.py" seed "$QUERY_ID"

SQL_ONELINE="$(uv run python -c "
import sys; sys.path.insert(0, '$ROOT')
from scripts.demo_lib import sql_one_line
print(sql_one_line($QUERY_ID))
")"

export LEMMA_DEMO=1
export MOCK_AGENT=1
export USE_AGENT_DOCKER=0
export MAX_ITERATIONS=1
export LEMMA_VERBOSE=0
export LEMMA_LOG_LEVEL=WARN

if [ ! -f "$ROOT/build/lemma.duckdb_extension" ]; then
  echo "==> Building extension (first time)..."
  make extension
fi
uv run python -m db_extension.prepare_data

cat <<EOF

╔══════════════════════════════════════════════════════════════════════╗
║  Lemma demo (Q${QUERY_ID}) — commands for the DuckDB shell below          ║
╚══════════════════════════════════════════════════════════════════════╝

  DuckDB's built-in timer is already on (.timer on in init.sql).
  After a plain SELECT, look for "Run Time (s): real ..." below the result.

  (1) Vanilla DuckDB:

    ${SQL_ONELINE}

  (2) Lemma — progress prints above; revenue appears in DuckDB's result box. Turn off timer first:

    .timer off

    SELECT lemma('${SQL_ONELINE}');

  (3) Run (2) again → cached optimized binary (💾 path in demo UI).

  Tip: use the default DuckDB prompt (D ); paste full SQL starting with SELECT.

  Our 🦆 DuckDB timing line only appears if LEMMA_DEMO_DUCKDB=1 (off by default).

Press Enter to open DuckDB CLI...
EOF
read -r _

exec "$ROOT/run_duckdb_and_load_extension_and_sbb_dataset.sh"
