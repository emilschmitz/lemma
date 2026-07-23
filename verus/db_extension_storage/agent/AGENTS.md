# Agent brief — path `lemma_storage`

You optimize **one path only**: `verus/db_extension_storage/` (below Chunk API — **DataTable** / row-group storage scan).

Do **not** share code or prompts with chunk, lease, or copy agents.

## Number to optimize

**Primary: `SESSION_HOT_US`** (also printed as `QUERY_US`) — GenDB-comparable warm **recompute**.

Minimize that vs `duckdb_sql_*`. Still **print** `OPEN_US`, `PREP_US`, `COLD_QUERY_US`,
`E2E_CACHED_RERUN_US` (open+cold) — do not optimize those as the headline.

**Forbidden cheat:** return a memoized final SUM on hot runs. Hot must recompute.

## Default H1 plan (GenDB-allowed residency)

**Not SQL `SELECT … WHERE`.** Use `duckdb.hpp` + `libduckdb.so`:

1. `lemma_storage_h1_open` — DuckDB + txn (`OPEN_US`).
2. **Prep (once, `PREP_US` / first scan):** real `DataTable::ScanTableSegment` (band prune OK) →
   keep **decoded** `event_date` / `amount` (and zone maps) on the session.
   Band-bounds-only cache is **not** enough for primary session-hot.
3. **Hot (`SESSION_HOT_US`):** Lemma zone-prune + filter + sum on that resident data only —
   do **not** re-decode via `ScanTableSegment` every hot query (optional diagnostic rescan path OK).
4. Expect SUM `1260130811`. Label scan modes honestly (`…+band_prune`, `…+resident`, etc.).

## Mandate — AGGRESSIVE

- Agent owns residency + kernel (zones, fusion, layout); scaffold only gives session + scan API
- Single-threaded, low RAM; no bundled DuckDB compile
- **TRUSTED:** storage scan I/O at prep. **Spec:** logical `MethodSpec` only.

**Forbidden:** `Connection::Query("SELECT … WHERE …")` for the timed kernel; answer memoization;
editing other extension trees.

## Edit target

`src/lemma_storage.cpp`, `src/lemma_storage_internal.hpp`, e2e bin if prep/hot split needs it.

## Measure

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
verus/db_extension/check_mem.sh uv run python verus/db_extension/measure_e2e_paths.py
```

Dataset: `build/duckdb_pin_session/scan.duckdb` (500k). No full holdout.

## Agent vs scaffolding

See `verus/research_loop/agents/AGENTS.md`. Primary gaps on `SESSION_HOT_US` are **agent/kernel**.
Do not push analytical WHERE/SUM back to DuckDB SQL.
