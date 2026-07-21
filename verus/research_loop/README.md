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
uv run python verus/research_loop/benchmark_verified.py --limit 50000
uv run python verus/research_loop/benchmark_verified.py --tpch --limit 50000
uv run python verus/research_loop/benchmark_verified.py --basic-sql --limit 50000
```

Smoke test (no data file):

```bash
uv run python verus/research_loop/benchmark_verified.py --smoke
```

Single query / basic-sql fixture:

```bash
uv run python verus/research_loop/harness.py -q 1
uv run python verus/research_loop/harness.py --basic-sql inner_join_sum
uv run python verus/research_loop/harness.py --basic-sql all
```

Requires `ssb-dbgen/lineorder_flat.tbl` (SSB) or `data/tpch-sf1/lineitem.tbl` (TPC-H) for timing.

## Layout

- `harness.py` — transpile → assemble → verus verify → verus `--compile` → run binary
- `assemble_verified_program.py` — single-file assembly (spec + proved body + load + main)
- `verified_runqueries.py` — hand-written proved `run_query` bodies for all fixtures
- `benchmark_verified.py` — multi-query bench vs bare Rust
- `benchmark_runqueries.py` — legacy unproved exec bodies (`LEGACY_UNPROVED_EXEC=1` only)
- `harness_legacy.py` — old dual-path harness
- `native/` — optional helpers (unified path uses transpiler prelude)
- `generated/` — per-query `.rs` sources and compiled binaries (gitignored)

## Fixtures

SSB: Q1, Q2, Q3, Q4, Q5, Q6, Q10, Q11, Q13  
TPC-H: Q1, Q6

Scalars use backward `while i > 0` with `res == method_spec_helper(cols, i as int)`.
Group-bys prove a ghost `Map` tied to `method_spec_helper` in the **same** backward loop that accumulates exec `HashMap` via **TRUSTED** NativeAgg-style helpers (`hashmap_*_view`, `agg_new_*`, `agg_add_*`) — no separate rematerialize scan.

### Trust model (summary)

**Verified:** `run_query` exec ≡ `method_spec` for scalar + group-by fixtures (ghost map + same-loop NativeAgg).

**Still TRUSTED:** wrapping arith under `valid_cols`; `hashmap_*_view` / `agg_new_*` / `agg_add_*`; `load_cols` I/O; LIKE / LEFT JOIN / UNION / EXISTS / IN / DISTINCT / ORDER BY helpers when those SQL features are used.

### Basic SQL fixtures

Batch-1 scalars (`basic_sql_fixtures.py`), joins (`basic_sql_join_fixtures.py`), set/subquery/CTE (`basic_sql_set_cte_fixtures.py`), projection/order/arith (`basic_sql_proj_order_fixtures.py`). See feature table in `verus/README.md` and [basic_sql_primer.md](../docs/basic_sql_primer.md).

Cheating inside TRUSTED `external_body` bodies can still “verify” while returning wrong SQL results — that is the residual gap; agent-written `run_query` cannot.

`agg_add_*` postconditions use Verus mutable-ref syntax: `old(hm)@` / `final(hm)@` (not `old(view(hm@))`). String `get_*_exec` / `eq_at_*` ensures are emitted by the transpiler (exec filters connect to the spec proof).

## Transpiler

Package `verus/src/verus_transpiler/` — see `verus/README.md`.
