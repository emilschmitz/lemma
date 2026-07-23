# Agent brief — path `lemma_runtime` (Lemma owns pipeline)

You optimize **one path only**: `verus/db_extension_runtime/`.
Do **not** share code or prompts with pin_stream or ops agents.

## Default H1 plan (e2e cached rerun)

**Predicate pushdown at scan + fused amount sum** — same strategy as pin_stream path.

1. Pushdown: `SELECT "amount" FROM "scan_skew" WHERE "event_date" >= 19960101 AND "event_date" <= 19961231`
2. Default e2e (`runtime_h1_e2e`): `lemma_stream_h1_sum_optimized` via `DuckStream::h1_sum_optimized`.
3. Agent-editable alternative in `runtime_h1.rs`: `DuckStream::open_range` + `sum_amounts_only`.
4. Optimize harder from there; expect SUM `1260130811`.

## Mandate — AGGRESSIVE (capable agent)

Assume you can beat DuckDB on **e2e cached rerun** by owning the **entire physical plan**.
Optimize as hard as the hardware and TRUSTED chunk API allow:

- Chunk scan order, projection, filter placement, join build/probe, aggregation layout
- Skew / zone / bitmap pruning, dictionary codes, SIMD / auto-vectorization, cache blocking
- Minimize allocations and FFI round-trips; fuse scan+filter+agg when profitable
- Specialize to this HW, this DuckDB layout, this table stats (`context.json` when present)

**TRUSTED:** chunk I/O (`lemma_stream_*` / runtime helpers). **Spec:** logical `MethodSpec` only — prove body ≡ Spec; do not invent row semantics.

**Forbidden:** DuckDB SQL for the analytical query; calling Lemma work “DuckDB”; editing other extension trees.

## Edit target

`rust_bridge/src/runtime_h1.rs` (and modules you add under this tree). SQL stub: `lemma_runtime(...)`.

## Metric

**E2E cached rerun** vs `duckdb_sql_*` (primary). Query-hot is secondary diagnostic only.

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
verus/db_extension/check_mem.sh uv run python verus/db_extension/measure_e2e_three_paths.py
```

Dataset: `build/duckdb_pin_session/scan.duckdb` (500k). No full holdout.
