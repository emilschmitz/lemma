#!/usr/bin/env bash
# Generate a fresh Lemma holdout query set (6 diverse SEC queries) with a fixed seed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEED="${LEMMA_HOLDOUT_SEED:-20260808}"
OUT_SQL="${SCRIPT_DIR}/queries_lemma_holdout.sql"
SEED_FILE="${SCRIPT_DIR}/queries_lemma_holdout.seed.txt"

echo "${SEED}" > "${SEED_FILE}"

cd "${SCRIPT_DIR}"
uv run python generate_queries.py \
  --seed "${SEED}" \
  --num-select 6 \
  --output "${OUT_SQL}"

echo "Wrote ${OUT_SQL} (seed ${SEED} in ${SEED_FILE})"
