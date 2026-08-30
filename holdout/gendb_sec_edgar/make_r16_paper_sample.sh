#!/usr/bin/env bash
# GenDB paper §4.1 diversity resample: seed 1616, generate 1000, select 6.
# This is the 6-query diversity sample for paper evaluation — NOT the
# 50-query prove_loop EDGAR shuffle (queries_resample_r1..r15).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEED=1616
DB_PATH="${SCRIPT_DIR}/duckdb/sec_edgar.duckdb"
OUT_SQL="${SCRIPT_DIR}/queries_resample_r16.sql"

if [[ ! -f "${DB_PATH}" ]]; then
  echo "Skip generate: full SEC DuckDB not found at ${DB_PATH}"
  echo "Script landed; run after load_data.sh on a VM with ~5 GB sec_edgar.duckdb."
  exit 0
fi

cd "${SCRIPT_DIR}"
uv run python generate_queries.py \
  --seed "${SEED}" \
  --num-generate 1000 \
  --num-select 6 \
  --db-path "${DB_PATH}" \
  --output "${OUT_SQL}"

echo "Wrote ${OUT_SQL} (seed ${SEED}, GenDB paper §4.1 procedure)"
