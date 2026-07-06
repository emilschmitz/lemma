# Lemma

Verified query synthesis: SQL is transpiled to a Dafny spec, an agent (or mock) writes an optimized `RunQuery`, Dafny/Z3 proves correctness, and the result is compiled to native Rust. Contains a DuckDB extension where optimized binaries are cached and invoked on rerun.

https://github.com/user-attachments/assets/7f7891c7-5ef6-406b-882b-8e01134ed37c

## What It Does

1. A SQL query is **deterministically transpiled** into a mathematical `MethodSpec` in Dafny — the ground truth.
2. The Lemma optimizer uses an agent (or mock mode) to write an optimized `method RunQuery`.
3. Dafny/Z3 formally proves that the agent's output satisfies `MethodSpec`.
4. The verified Dafny is translated to Rust and post-processed for native performance.*
5. The code is compiled and executed.
6. Successful optimized binaries are **cached** and loaded via the DuckDB extension.

* Post-processing rewrites and a few assumptions in the Dafny spec are added for performance. These manipulations should match verified Dafny semantics, but that is only verified empirically; see `research_loop/COMPILATION_GUIDE.md`.

---

## Quick Start

One-time setup, then run the interactive demo:

```bash
make install
./scripts/build_ssb_flat_dataset.sh   # one-time: real ssb-dbgen flat table (~6M rows on disk)
./scripts/demo.sh                     # builds extension if needed, prepares data, opens DuckDB CLI
```

In the DuckDB shell, try Lemma on a query (see the on-screen instructions), e.g.:

```sql
SELECT lemma('SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) FROM lineorder_flat WHERE ...');
```

`demo.sh` handles extension build, dataset loading (`prepare_data`), and launching DuckDB — you do not need to run those steps separately. The flat table only needs to be built once via `build_ssb_flat_dataset.sh`; after that, `prepare_data` runs automatically whenever you start the demo or the lower-level launcher.

**No agent / offline:** `./scripts/mockdemo.sh` — same UX with a pre-seeded RunQuery (no LLM).

**Lower-level launcher** (DuckDB shell only, no demo UI): `make extension` then `./scripts/duckdb_shell.sh`

### Requirements
- [uv](https://docs.astral.sh/uv/) — Python package manager
- [Dafny 4.x](https://github.com/dafny-lang/dafny) — in `PATH`
- [Rust/Cargo](https://rustup.rs/) — for native compilation
- [DuckDB CLI](https://duckdb.org/) — vendored to `build/duckdb` on first launcher run
- [Cursor Agent CLI](https://cursor.com/docs/agent/cli) — `agent` on `PATH` (for `./scripts/demo.sh`; other agents work too if you set `AGENT_CMD` in `research_loop/config.env`)

---

## Results

Hot-loop latency on SSB `lineorder_flat` at **1.5M rows**. All engines run **single-threaded** (DuckDB `threads=1`, PostgreSQL without parallel gather, Rust without OpenMP). Metric: 3rd timed execution of the query loop; load is outside the timer. Raw numbers: `data/benchmarks/scaling_results.json` — see also `docs/verified_benchmark_rundown.md`.

![SSB Q1–Q5 overview: single-thread hot-loop latency](plots/benchmark_overview.png)

**Three queries where verified is strong** (✓ on chart — well ahead of DuckDB, often close to bare):

- **Q2 / Q3** — selective scalar `SUM` with native `AddU64` / `MulU64U32`; almost no allocation in the loop.
- **Q5** — two-key `(year, brand)` group-by via schema-driven `AggPush_*` on `NativeAggMap`; beats DuckDB 1t, still ~1.3× slower than bare.

**Two queries where gains are modest** (~ on chart — verified ≈ DuckDB or worse, clearly behind bare):

- **Q1** — simple revenue sum but enough row traffic that runtime wrapper overhead shows; verified slightly **slower** than DuckDB 1t at this size.
- **Q4** — `(year, brand)` group-by plus string equality filters; hash + string work keeps verified near DuckDB and ~20% above bare.

### What it takes to match bare consistently

Bare is hand-tuned columnar Rust (minimal columns, direct indexing, no proof/runtime wrapper). Verified adds `Object<ColsNative>`, Dafny codegen, and general-purpose agg maps. Closing the gap everywhere means more **schema-driven** pipeline work, not per-query hacks: SQL column projection (done), native agg push for all group-by shapes (2-key string/u32 done; 3-key still on functional maps), skip Dafny result materialization on the engine boundary (`BenchFinish`, done for benchmarks), and eventually tighter encodings for low-cardinality strings where the schema allows it.

Reproduce the chart:

```bash
uv run python research_loop/benchmark_scaling.py   # refresh scaling_results.json if needed
uv run python scripts/generate_benchmark_overview_plot.py
uv run python research_loop/benchmark_verified.py # single-point check at 50k rows
```
