# Agent brief — path `lemma_lease`

You optimize **one path only**: `verus/db_extension_lease/` (pin/lease — DuckDB retains result vectors).

Do **not** share code or prompts with chunk, storage, or copy agents.

## Number to optimize

**Primary: `SESSION_HOT_US`** (= `QUERY_US`) — GenDB-comparable warm **recompute** vs `duckdb_sql_*`.

Pin + zone prep is **`PREP_US`** (outside primary). Still print open/cold/e2e-diag.
**Forbidden:** memoized final SUM as the hot path.

## Default H1 plan

**Not a copy path.** Pin holds DuckDB result chunk buffers; Lemma reads pointers + zone maps.

1. **Prep once:** `pin_table("scan_skew", ["event_date", "amount"])` + zone map (`LeaseH1Session::prep`).
2. **Hot:** `session.run_h1()` only — zone-prune + filter + sum on pinned buffers.
3. Expect SUM `1260130811`.

## Mandate — AGGRESSIVE

- Better zones/bitmaps/fusion on **pinned** vectors; never re-pin inside hot
- **TRUSTED:** `lemma_pin_*`. **Spec:** logical `MethodSpec` only.

**Forbidden:** `.lemma_cols` copy; SQL analytical `WHERE` for the timed kernel; answer memoization;
editing other extension trees.

## Edit target

`rust_bridge/src/lease_h1.rs` (+ pin/zone helpers in `lemma_agent_primitives` when lease-specific).

## Measure

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
verus/db_extension/check_mem.sh uv run python verus/db_extension/measure_e2e_paths.py
```

Dataset: `build/duckdb_pin_session/scan.duckdb` (500k).

## Agent vs scaffolding

See `verus/research_loop/agents/AGENTS.md`. Optimize **`SESSION_HOT_US`**.
