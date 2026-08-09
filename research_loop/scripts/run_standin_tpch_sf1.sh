#!/usr/bin/env bash
# Run hand-standin TPC-H Q1/Q6 (and Q3 if orders.tbl exists) on SF1 lineitem.
set -euo pipefail
export PATH="${HOME}/bin:${HOME}/.local/bin:${PATH}"
cd "${HOME}/lemma"
LOG="${HOME}/phase1_logs/standin_tpch_sf1.log"
TBL="${HOME}/lemma/data/tpch-sf1/lineitem.tbl"
LIMIT=6001215
mkdir -p "${HOME}/phase1_logs"
{
  echo "=== start $(date -u +%Y-%m-%dT%H:%M:%SZ) host=$(hostname) nproc=$(nproc) ==="
  echo "tbl=${TBL} limit=${LIMIT}"
  for q in Q1 Q6; do
    echo "--- ${q} ---"
    uv run python research_loop/benchmark_verified.py --tpch -q "${q}" --limit "${LIMIT}" --tbl "${TBL}" \
      2>&1 || echo "EXIT ${q}=$?"
  done
  if [[ -f "${HOME}/lemma/data/tpch-sf1/orders.tbl" ]]; then
    echo "--- Q3 ---"
    uv run python research_loop/benchmark_verified.py --tpch -q Q3 --limit "${LIMIT}" --tbl "${TBL}" \
      2>&1 || echo "EXIT Q3=$?"
  else
    echo "SKIP Q3: no orders.tbl"
  fi
  echo "=== end $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
} | tee "${LOG}"
