# Lemma

Verified query synthesis for DuckDB: SQL is transpiled to a Dafny spec, an agent (or mock) writes an optimized `RunQuery`, Dafny/Z3 proves correctness, and the result is compiled to native Rust. Optimized binaries are cached and invoked via the **Lemma** DuckDB extension.

## What It Does

1. A SQL query is **deterministically transpiled** into a mathematical `MethodSpec` in Dafny — the ground truth.
2. The Lemma optimizer uses an agent (or mock mode) to write an optimized `method RunQuery`.
3. Dafny/Z3 formally proves that the agent's output satisfies `MethodSpec`.
4. The verified Dafny is translated to Rust and post-processed for native performance.*
5. The code is compiled and executed.
6. Successful optimized binaries are **cached** and loaded via the DuckDB extension.

* Post-processing rewrites are trusted to match verified Dafny semantics; see `research_loop/COMPILATION_GUIDE.md`.

---

## Quick Start

```bash
make install
make extension
./run_duckdb_and_load_extension_and_sbb_dataset.sh
# In the shell:
# SELECT lemma('SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) FROM lineorder_flat WHERE ...');
```

Interactive demo (clears cache, seeds mock body, opens DuckDB CLI): `./scripts/demo.sh`

### Requirements
- [uv](https://docs.astral.sh/uv/) — Python package manager
- [Dafny 4.x](https://github.com/dafny-lang/dafny) — in `PATH`
- [Rust/Cargo](https://rustup.rs/) — for native compilation
- [DuckDB CLI](https://duckdb.org/) — vendored to `build/duckdb` on first launcher run

---

## Repository Structure

```
Lemma/
├── run_duckdb_and_load_extension_and_sbb_dataset.sh  # DuckDB CLI launcher
├── transpiler/          # SQL → Dafny transpiler (sql-transpiler)
├── db_extension/        # Lemma DuckDB extension + optimizer entrypoint
├── research_loop/       # Verify, compile, agent sandbox
└── scripts/demo.sh      # Interactive demo
```

## Makefile

| Command | Description |
|---|---|
| `make install` | Install all Python dependencies via `uv sync` |
| `make test` | Run transpiler and database extension unit tests |
| `make test-slow` | Run Dafny functional tests (requires `dafny` in PATH) |
| `make loop` | Run one iteration of the research loop (Query 1, 50k rows) |
| `make extension` | Build `build/lemma.duckdb_extension` |
| `make clean` | Remove build artifacts and `__pycache__` |
