# Verus research loop

Verified query pipeline for **Verus-annotated Rust** that proves and runs a
**single artifact** per query.

```
SQL → MethodSpec (transpile) → proved run_query ≡ MethodSpec → verus verify → verus --compile → run binary
```

## Default path (unified)

One generated `.rs` file under `generated/` contains:

- Transpiled `Cols` / `valid_cols` / `method_spec` / `method_spec_helper`
- Trusted arithmetic prelude (`add_u64`, …)
- **`pub exec fn run_query`** with real loop invariants (no `external_body` on `run_query`)
- Trusted `load_cols` (tbl I/O boundary)
- `main` that loads `.tbl`, warms up, times the 3rd run, prints `QUERY_LATENCY_US:` and `RESULT:`

`proof_verified=True` means **Verus verified the whole file**, including `run_query` ≡ `method_spec`.

`REQUIRE_PROOF=1` (default when verify is enabled): verify or compile failure → pipeline `FAILURE`.

Set `LEGACY_UNPROVED_EXEC=1` to restore the old dual path (verify `spec.rs` only + cargo unproved `query.rs`) for debugging.

## Quick start

From repo root:

```bash
export PATH=$HOME/tools/verus:$PATH
uv sync
uv run python research_loop/benchmark_verified.py --limit 50000
uv run python research_loop/benchmark_verified.py --tpch --limit 50000
uv run python research_loop/benchmark_verified.py --basic-sql --limit 50000
```

Smoke test (no data file):

```bash
uv run python research_loop/benchmark_verified.py --smoke
```

Single query / basic-sql fixture:

```bash
uv run python research_loop/harness.py -q 1
uv run python research_loop/harness.py --basic-sql inner_join_sum
uv run python research_loop/harness.py --basic-sql all
```

Requires `ssb-dbgen/lineorder_flat.tbl` (SSB) or `data/tpch-sf1/lineitem.tbl` (TPC-H) for timing.

## Layout

- `harness.py` — transpile → assemble → verus verify → verus `--compile` → run binary
- `assemble_verified_program.py` — single-file assembly (spec + proved body + load + main)
- `bench_standins/` — optional bench/CI stand-in `run_query` bodies (artifacts, not engine)
- `benchmark_verified.py` — multi-query bench vs bare Rust
- `benchmark_runqueries.py` — legacy unproved exec bodies (`LEGACY_UNPROVED_EXEC=1` only)
- `harness_legacy.py` — old dual-path harness
- `native/` — optional helpers (unified path uses transpiler prelude)
- `generated/` — per-query `.rs` sources and compiled binaries (gitignored)

## Fixtures (stand-in agents for bench/CI)

SSB: Q1–Q15 (`bench_standins.verified_runqueries.SSB_RUNQUERIES`)  
TPC-H: Q1, Q3, Q6 only (not the full TPC-H suite)

Scalars use backward `while i > 0` with `res == method_spec_helper(cols, i as int)`.
Group-bys prove a ghost `Map` tied to `method_spec_helper` in the **same** backward loop that accumulates exec `HashMap` via **TRUSTED** NativeAgg-style helpers (`hashmap_*_view`, `agg_new_*`, `agg_add_*`) — no separate rematerialize scan.

### Trust model (summary)

**Verified:** `run_query` exec ≡ `method_spec` for scalar + group-by fixtures (ghost map + same-loop NativeAgg).

**Still TRUSTED:** wrapping arith under `valid_cols`; `hashmap_*_view` / `agg_new_*` / `agg_add_*`; `load_cols` I/O; LIKE / LEFT JOIN / UNION / EXISTS / IN / DISTINCT / ORDER BY helpers when those SQL features are used.

### Basic SQL fixtures

Stand-in agents (pre-written proved `run_query` bodies) for optional CI/bench only, under
`bench_standins/` (artifacts, not engine): scalars (`basic_sql_fixtures.py`), joins
(`basic_sql_join_fixtures.py`), set/subquery/CTE (`basic_sql_set_cte_fixtures.py`),
projection/order/arith (`basic_sql_proj_order_fixtures.py`), extended
(`basic_sql_extended_fixtures.py`). See root `AGENTS.md` for the product contract.

Cheating inside TRUSTED `external_body` bodies can still “verify” while returning wrong SQL results — that is the residual gap; agent-written `run_query` cannot.

`agg_add_*` postconditions use Verus mutable-ref syntax: `old(hm)@` / `final(hm)@` (not `old(view(hm@))`). String `get_*_exec` / `eq_at_*` ensures are emitted by the transpiler (exec filters connect to the spec proof).

## Transpiler

Package `verus_transpiler/` — see `verus_transpiler/README.md`.
