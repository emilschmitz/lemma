# Agent brief — path `lemma_chunk`

You optimize **one path only**: `verus/db_extension_runtime/` (Chunk API — Lemma owns filter + agg).

Do **not** share code or prompts with lease, storage, or copy agents.

## Number to optimize

**Primary: `SESSION_HOT_US`** (= `QUERY_US`) — GenDB-comparable warm **recompute** vs `duckdb_sql_*`.

Prep (`PREP_US`: stream ingest + zones) stays outside the primary clock. Still print
`OPEN_US` / `COLD_QUERY_US` / e2e-diag. **Forbidden:** memoized final SUM as the hot path.

## Default H1 plan

**Lemma does ALL filter + agg** — no SQL `WHERE` pushdown on the default path.

1. **Prep once:** stream raw `event_date`,`amount` (no SQL predicate) → owned vectors + zone map
   (`ChunkH1Prep::ingest`).
2. **Hot:** `prep.run` — zone-prune + filter + sum on resident data only.
3. Legacy: C++ `h1_sum_lemma_filter`; `h1_sum_optimized` (pushdown — **not** default).
4. Expect SUM `1260130811`.

## Mandate — AGGRESSIVE

- Zone/bitmap prune, SIMD/fusion, tighter ingest; specialize to table + HW
- **TRUSTED:** `lemma_stream_*` at prep. **Spec:** logical `MethodSpec` only.

**Forbidden:** SQL `WHERE` on the default timed kernel; answer memoization; editing other trees.

## Edit target

`rust_bridge/src/runtime_h1.rs` (+ `verus/db_extension/src/lemma_stream.cpp` when needed).

## Measure

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
verus/db_extension/check_mem.sh uv run python verus/db_extension/measure_e2e_paths.py
```

Dataset: `build/duckdb_pin_session/scan.duckdb` (500k).

## Agent vs scaffolding

See `verus/research_loop/agents/AGENTS.md`. Optimize **`SESSION_HOT_US`**.
