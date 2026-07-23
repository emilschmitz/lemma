# Agent brief — path `lemma_lease`

You optimize **one path only**: `verus/db_extension_lease/` (pin/lease — DuckDB retains result vectors).

Do **not** share code or prompts with chunk, storage, or copy agents.

## Default H1 plan (e2e cached rerun)

**Not a copy path.** Pin holds DuckDB `SELECT` result chunk buffers; Lemma reads pointers + zone maps.

1. `lemma_pin_table("scan_skew", ["event_date", "amount"])` — materialize pin (SELECT under the hood).
2. `PinH1Prep` builds sub-zones (`PIN_ZONE_ROWS`) on pinned date vectors.
3. `prep.run(H1_LO, H1_HI)` — Lemma zone-prune + filter + sum on pinned buffers.
4. Expect SUM `1260130811`.

## Mandate — AGGRESSIVE

- Optimize zone maps / bitmaps on **pinned** DuckDB vectors (zero-copy pointers).
- Multi-pass prep OK when query-hot wins; minimize pin materialize tax where e2e matters.
- **TRUSTED:** `lemma_pin_*` FFI. **Spec:** logical `MethodSpec` only.

**Forbidden:** `.lemma_cols` sidecar copy; SQL analytical `WHERE` for the timed kernel; editing other extension trees.

## Edit target

`rust_bridge/src/lease_h1.rs` (+ zone/pin helpers in `lemma_agent_primitives` when lease-specific).

## Metric

**E2E cached rerun** vs `duckdb_sql_*`.

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
verus/db_extension/check_mem.sh uv run python verus/db_extension/measure_e2e_paths.py
```

Dataset: `build/duckdb_pin_session/scan.duckdb` (500k). No full holdout.
