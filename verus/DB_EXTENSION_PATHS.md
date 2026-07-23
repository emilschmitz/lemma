# DuckDB extension paths (Verus)

Three **separate trees**, each with its **own agent environment** (`agent/AGENTS.md`).
One agent implementation optimizes **one path only**.

| Path | Folder | SQL / entry | Agent brief |
|------|--------|-------------|-------------|
| **`lemma` / pin_stream** | [`db_extension/`](db_extension/) | `lemma`, `lemma_pin`, stream FFI | [`db_extension/agent/AGENTS.md`](db_extension/agent/AGENTS.md) |
| **`lemma_runtime`** | [`db_extension_runtime/`](db_extension_runtime/) | `lemma_runtime(VARCHAR)` | [`db_extension_runtime/agent/AGENTS.md`](db_extension_runtime/agent/AGENTS.md) |
| **`lemma_ops`** | [`db_extension_ops/`](db_extension_ops/) | `lemma_ops(VARCHAR)` | [`db_extension_ops/agent/AGENTS.md`](db_extension_ops/agent/AGENTS.md) |

**Baseline:** `duckdb_sql_*` — DuckDB SQL engine executes the query (not Lemma).

## Naming

- Lemma **executes** on all three Lemma paths → never call timed Lemma kernels “DuckDB”.
- `duckdb_sql_*` = DuckDB SQL baseline only.

## Metric

**E2E cached rerun** — fresh process, `E2E_CACHED_RERUN_US` = open db + query. Track `OPEN_US` / `QUERY_US`.

## Build (RAM-safe)

Prebuilt `libduckdb.so` at `build/libduckdb` only — **never** bundled DuckDB compile.

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
export LD_LIBRARY_PATH="$LEMMA_DUCKDB_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# Path 1 (pin_stream)
cargo build --release --manifest-path verus/db_extension/rust_bridge/Cargo.toml \
  --bin lemma_stream_h1_e2e --bin duckdb_sql_h1_e2e

# Path 2 (runtime)
cargo build --release --manifest-path verus/db_extension_runtime/rust_bridge/Cargo.toml \
  --bin lemma_runtime_h1_e2e

# Path 3 (ops)
cargo build --release --manifest-path verus/db_extension_ops/rust_bridge/Cargo.toml \
  --bin lemma_ops_h1_e2e

# Optional extension stubs (.duckdb_extension)
make -C verus/db_extension extension
make -C verus/db_extension_runtime extension
make -C verus/db_extension_ops extension
```

## Measure (all four competitors)

Uses `build/duckdb_pin_session/scan.duckdb` (500k). **Do not** load full holdout.
`check_mem.sh` requires MemAvailable ≥ 1.5 GiB.

```bash
verus/db_extension/check_mem.sh uv run python verus/db_extension/measure_e2e_three_paths.py
# → verus/db_extension/e2e_three_paths_h1.json
```

## E2E binaries

| Label | Binary |
|-------|--------|
| `lemma_pin_stream_e2e` | `verus/db_extension/rust_bridge/target/release/lemma_stream_h1_e2e` |
| `lemma_runtime_e2e` | `verus/db_extension_runtime/rust_bridge/target/release/lemma_runtime_h1_e2e` |
| `lemma_ops_e2e` | `verus/db_extension_ops/rust_bridge/target/release/lemma_ops_h1_e2e` |
| `duckdb_sql_e2e` | `verus/db_extension/rust_bridge/target/release/duckdb_sql_h1_e2e` |
