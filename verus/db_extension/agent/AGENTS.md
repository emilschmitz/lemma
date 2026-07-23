# Agent brief — path `lemma_copy`

You optimize **one path only**: `verus/db_extension/` — **sidecar `.lemma_cols` copy** into Lemma-owned memory.

Pin/stream/lease e2e moved to `verus/db_extension_lease/`; chunk path is `verus/db_extension_runtime/`.

## Default smoke (not primary e2e competitor)

**Copy export → Lemma sum on owned columns**

1. `duckdb_memory.py` (opt-in `LEMMA_DUCKDB_SIDECAR_EXPORT`) writes `.lemma_cols` sidecars.
2. `lemma_copy_h1_smoke <manifest.json>` — Lemma filter+sum on copied columns.
3. Expect SUM `1260130811`.

This path **copies** data (unlike lease/chunk/storage). Use when Lemma must own layout end-to-end after one-time export.

## Other tooling in this tree (legacy FFI)

- `lemma_pin_*`, `lemma_stream_*` — shared C++ for lease/chunk bridges (do not optimize for chunk/lease agents here).
- `duckdb_sql_h1_e2e` — **baseline**, not Lemma.

## Mandate — copy path only

- Minimize export size / memcpy; fast sequential read of sidecars
- Zone maps on **owned** columns after copy
- **Forbidden:** claiming copy is zero-copy lease; editing lease/chunk/storage agent trees

## Metric

Copy smoke is optional in `measure_e2e_paths.py` when `lemma_copy_h1_smoke` exists.

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
verus/db_extension/check_mem.sh uv run python verus/db_extension/measure_e2e_paths.py
```

Dataset: `build/duckdb_pin_session/scan.duckdb` (500k). No full holdout.

## Agent vs scaffolding

See `verus/research_loop/agents/AGENTS.md`. **Current H1 e2e gap vs DuckDB: primarily agent/kernel**, not missing path scaffolding. Do not push analytical WHERE/SUM back to DuckDB SQL to fake a win.
