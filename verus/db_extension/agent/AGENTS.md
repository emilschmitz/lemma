# Agent brief — path `lemma` / pin_stream

You optimize **one path only**: `verus/db_extension/` (pin + streaming chunk lease).

## Default H1 plan (e2e cached rerun)

**Predicate pushdown at scan + fused amount sum** — not full-column read then Rust refilter.

1. Stream SQL with trusted bounds (agent-chosen, not DuckDB analytical SQL for the timed kernel):
   `SELECT "amount" FROM "scan_skew" WHERE "event_date" >= 19960101 AND "event_date" <= 19961231`
2. DuckDB storage prune applies the date predicate; Lemma **sums `amount` only** (one column).
3. Default e2e: `lemma_stream_h1_sum_optimized` in C++ (no per-chunk Rust FFI). Expect SUM `1260130811`.
4. Agent may tune further (SIMD, tighter loops) but keep pushdown + single-column sum as baseline.

## What Lemma executes here

- **Pin path**: `lemma_pin_table` retains DuckDB vector buffers; build sub-zones (`PIN_ZONE_ROWS`) and prune before scan.
- **Stream path**: `lemma_stream_*` single-pass chunks — no retain-all materialize.
- DuckDB is **layout host only**. Never call the timed kernel “DuckDB”; SQL baseline is `duckdb_sql_*`.

## Your job

- Optimize zone maps / bitmaps on **pinned or streamed** DuckDB chunks.
- Prefer stream when e2e matters (no full materialize tax); use pin when random access or multi-pass prep wins.
- Spec stays **logical** (`MethodSpec`); chunk I/O is TRUSTED.
- Do **not** edit `verus/db_extension_runtime/` or `verus/db_extension_ops/`.

## Metric

**E2E cached rerun** — fresh process, open db + query (`E2E_CACHED_RERUN_US`). Also track `OPEN_US` / `QUERY_US`.

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
verus/db_extension/check_mem.sh uv run python verus/db_extension/measure_e2e_three_paths.py
```

Dataset: `build/duckdb_pin_session/scan.duckdb` (500k). Do **not** load full holdout.
