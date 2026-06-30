# Verified Hill-Climbing Query Optimizer

A research database system that uses **Dafny formal verification** to construct provably correct, hardware-optimized query implementations for analytical SQL workloads. It features a dynamically loadable **DuckDB C++ Extension** that intercepts queries, executes an autonomous optimization loop (using Z3 and Rust compilation), and caches query plans for instant execution.

## What It Does

1. A SQL query is **deterministically transpiled** into a mathematical `MethodSpec` in Dafny — the ground truth.
2. The **hill-climbing optimizer** uses an agent (or mock mode) to write an optimized `method RunQuery`.
3. **Dafny/Z3** formally proves that `RunQuery` satisfies `MethodSpec`.
4. The verified code is **compiled to native Rust** and executed.
5. Successful optimized binaries are **cached** and loaded directly inside **DuckDB** via the C++ extension.

---

## Quick Start

```bash
# 1. Install dependencies
make install

# 2. Build the DuckDB loadable extension
make extension

# 3. Start the interactive REPL shell and load the extension
./run_duckdb_and_load_extension_and_sbb_dataset.sh
# In the shell:
# SELECT hillclimbing('SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) FROM lineorder_flat WHERE LO_ORDERDATE >= 19930101 AND LO_ORDERDATE <= 19931231 AND LO_DISCOUNT >= 1 AND LO_DISCOUNT <= 3 AND LO_QUANTITY < 25');
```

### Requirements
- [uv](https://docs.astral.sh/uv/) — Python package manager
- [Dafny 4.x](https://github.com/dafny-lang/dafny) — in `PATH`
- [Rust/Cargo](https://rustup.rs/) — for native compilation
- [DuckDB CLI](https://duckdb.org/) — (optional) for running the extension in standard terminal sessions

---

## Repository Structure

```
verified-hillclimbing-db/
├── run_duckdb_and_load_extension_and_sbb_dataset.sh  # Interactive C++ CLI shell launcher
├── TODOS.md             # Consolidated project tasks
├── queries.py           # Backward-compat query module forwarder
├── transpiler/          # SQL → Dafny transpiler (Python package: sql-transpiler)
│   ├── src/sql_transpiler/
│   │   └── transpiler.py   # Core transpiler logic
│   └── tests/
├── db_extension/        # DuckDB loadable C++ extension and REPL helpers
│   ├── src/
│   │   └── hillclimbing.cpp # C++ extension source registering UDFs
│   ├── catalog.py       # Dynamic DuckDB schema extractor
│   ├── optimizer.py     # Optimization orchestrator and loop generator
│   ├── run_optimizer.py # Subprocess wrapper running the compiled query
│   ├── utils.py         # Shared cache handlers and dataset helpers
│   └── test_extension.py # Extension unit/integration tests
└── research_loop/       # Autonomous optimization loop
    ├── harness.py          # Orchestrator: verify → compile → benchmark
    ├── agent_scratchpad.md # Agent writes optimized RunQuery implementations here
    └── working_query-rust/ # Cached Cargo workspace for fast incremental builds
```

## How It Works

```
SQL query
   │
   ▼  transpile_sql_to_dafny()
Dafny MethodSpec  ◄─── ground truth (immutable)
   │
   │  + agent's RunQuery
   ▼
dafny verify  ──── Z3 proves RunQuery satisfies MethodSpec
   │
   ▼
dafny translate rs
   │
   ▼
cargo build --release  ──── ~0.8s (cached)
   │
   ▼
./working_query  ──── latency_us measured
   │
   ▼
{"status": "SUCCESS", "proof_verified": true, "latency_us": 17618}
```

## Rust Post-Processing (Optimization Layer)

To achieve maximum hardware performance, the system includes a post-processing pass (`optimize_rust_file` in `research_loop/harness.py`). While Dafny proves query loop safety using mathematical types (e.g., `int` and bitvectors), the post-processor rewrites these types to native Rust primitives (`u64`/`usize`) and native array/slice operations. This step eliminates the overhead of arbitrary-precision integers, dropping latency to **~100 us** (8x faster than DuckDB's standard engine).

## DuckDB Loadable C++ Extension

The repository includes a loadable extension that exposes the hill-climbing query optimizer directly inside any standard DuckDB session (e.g., via Python or the CLI shell).

### 1. Build the Extension
```bash
make extension
```

### 2. Load and Run Queries in DuckDB
In your DuckDB connection (Python, standard CLI, or via `dbcli` wrapper):
```sql
-- Allow loading local unsigned extensions
SET allow_unsigned_extensions=true;

-- Load the extension library
LOAD 'db_extension/hillclimbing.duckdb_extension';

-- Execute a query via the optimizer
SELECT hillclimbing_optimize('SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) FROM ...');
```

## Makefile

| Command | Description |
|---|---|
| `make install` | Install all Python dependencies via `uv sync` |
| `make test` | Run transpiler and database extension unit tests |
| `make test-slow` | Run Dafny functional tests (requires `dafny` in PATH) |
| `make loop` | Run one iteration of the research loop (Query 1, 50k rows) |
| `make extension` | Compile and package the loadable C++ DuckDB extension |
| `make clean` | Remove build artifacts, cached binaries, local cache mapping, and `__pycache__` |

## Components

- **[transpiler/](transpiler/README.md)** — The SQL-to-Dafny transpiler. Supports `SUM`, `COUNT`, `WHERE`, `GROUP BY`, arithmetic expressions, and the full 15-query SSB benchmark suite.
- **[research_loop/](research_loop/README.md)** — The orchestration harness and agent interface. The agent writes code to `agent_scratchpad.md`; the harness handles all verification, compilation, and benchmarking.
