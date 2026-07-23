# Lemma agent & engine rules

## General engine — not SSB-specialized

Lemma is a **general** verified query engine. The transpiler, postprocessor, admission
lint, native externs, and agent pipeline must stay **schema-driven**.

- **Never** hardcode dataset-specific column names, table names, or literals in engine
  code (`transpiler/`, `research_loop/postprocessor.py`, `admit_runquery.py`,
  `native.dfy`, loaders, etc.).
- **OK** in unit tests, benchmark query bodies (`benchmark_runqueries.py`), and
  workload SQL fixtures (`ssb_workload.py`) — those are query instances, not the engine.
- **OK** for global policies that apply to every query: `ValidCols` row/cell bounds
  (`transpiler/src/sql_transpiler/value_bounds.py`), `LemmaMax*` constants, lemmas
  emitted per schema column type — not per benchmark query.

`ValidCols` is a **specification assumption** (host-injected via transpiler), not an
optimization. It is never hand-tuned for one query.

## Development workflow

During development, do **not** run the optimization agent loop. Write and test queries
directly (`research_loop/benchmark_verified.py`).

### E2E cached rerun (db_extension)

When comparing Lemma on DuckDB layouts vs the DuckDB SQL engine, use **e2e cached rerun**:
timer starts at process launch and includes **open/connect + query** on
`build/duckdb_pin_session/scan.duckdb` only. Primary metric: `E2E_CACHED_RERUN_US`.
Lemma stream layout: `lemma_st_duckdb_stream` (`ENGINE: lemma`, `LAYOUT: duckdb_stream`).
See `verus/db_extension/measure_e2e_cached_rerun.py`.

Use `NativeU32` / `NativeU64` / `NativeI64` extern newtypes from the transpiler — do
not rely on unsafe postprocessor type rewrites.

## Agent contract (`RunQuery` body only)

The host injects signature + `requires ValidCols(cols)` + `ensures res == MethodSpec(cols)`.
The agent must **not** add `requires`, `ensures`, or new declarations.

### Group-by (2-key, `NativeU64` values)

`NativeAggMap` accumulates `NativeI64`. For `SUM(u64)` group-bys, use one `new NativeAggMap()`,
a **ghost** `NativeU64` map tied to `MethodSpecHelper`, and system lemmas.

When the query group-by is `(NativeU32, string)`, the transpiler emits
`cols.AggPush_<U32COL>_<STRCOL>(agg, i, delta)` — prefer that over `agg.Add` (avoids Dafny
string allocation on the hot path):

```dafny
var agg := new NativeAggMap();
ghost var g: map<(NativeU32, string), NativeU64> := map[];
// loop invariant: g == MethodSpecHelper(cols, i) && agg.Snapshot() matches g as int
// on match: ValidCols_Get<MoneyCol>(cols, i); term := ((cell as int) as NativeU64);
//   cols.AggPush_<U32COL>_<STRCOL>(agg, i, term as NativeI64);
// end: res := agg.ToU64Map();
```

`ValidCols_Get*` lemmas are **transpiler-generated per schema column**, not written by hand
in engine code.
