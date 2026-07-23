# Agent brief — path `lemma_chunk`

You optimize **one path only**: `verus/db_extension_runtime/` (Chunk API — Lemma owns filter + agg).

Do **not** share code or prompts with lease, storage, or copy agents.

## Default H1 plan (e2e cached rerun)

**Lemma does ALL filter + agg** — no SQL `WHERE` pushdown on the default path.

1. Stream raw columns: `SELECT "event_date", "amount" FROM "scan_skew"` (no predicate in SQL).
2. Default e2e: `lemma_stream_h1_sum_lemma_filter` — C++ zone-prune per chunk + filter + sum.
3. Alternatives in `runtime_h1.rs`: Rust `open` + `stream_h1_sum_filtered`; legacy `h1_sum_optimized` (pushdown — **not** default).
4. Expect SUM `1260130811`.

## Mandate — AGGRESSIVE

Own the **entire physical plan** on DuckDB chunk batches:

- Chunk order, projection, zone/bitmap prune, SIMD filter+agg fusion
- Minimize FFI round-trips; specialize to this table + HW
- **TRUSTED:** `lemma_stream_*` chunk I/O. **Spec:** logical `MethodSpec` only.

**Forbidden:** SQL `WHERE` on the default timed kernel; calling Lemma work “DuckDB”; editing lease/storage/copy trees.

## Edit target

`rust_bridge/src/runtime_h1.rs` (+ C++ in `verus/db_extension/src/lemma_stream.cpp` when chunk kernel work belongs here).

## Metric

**E2E cached rerun** vs `duckdb_sql_*`.

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
verus/db_extension/check_mem.sh uv run python verus/db_extension/measure_e2e_paths.py
```

Dataset: `build/duckdb_pin_session/scan.duckdb` (500k). No full holdout.
