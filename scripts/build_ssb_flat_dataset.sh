#!/usr/bin/env bash
# Generate real SSB star-schema .tbl files via ssb-dbgen, flatten to lineorder_flat.tbl.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSB="$ROOT/ssb-dbgen"
SCALE="${LEMMA_SSB_SCALE:-1.333}"

echo "==> SSB flat build (real ssb-dbgen, scale=$SCALE)"
echo "    Target flat file: $SSB/lineorder_flat.tbl"

if [[ ! -x "$SSB/dbgen" ]]; then
  echo "==> Compiling ssb-dbgen..."
  make -C "$SSB"
fi

echo "==> Generating dimension + fact tables (dbgen -s $SCALE)..."
(
  cd "$SSB"
  # -f overwrites stale .tbl files; one table at a time so progress is visible.
  for tbl in c p s d l; do
    echo "    dbgen -s $SCALE -f -T $tbl ..."
    ./dbgen -s "$SCALE" -f -T "$tbl" </dev/null
  done
)

echo "==> Flattening to lineorder_flat.tbl (DuckDB join)..."
uv run python "$SSB/flatten_ssb.py" --root "$ROOT"

echo "==> Done. Set LEMMA_DATASET_SIZE to cap rows loaded (default in dataset_config.py)."
