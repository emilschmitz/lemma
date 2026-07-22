# Verus `db_extension` — experiment-oriented DuckDB extension

This directory is a **stripped copy** of the root [`db_extension/`](../../db_extension/) for
**Verus** experiments. Humans (or Cursor) write kernels; there is **no** OpenRouter/Docker
sandbox agent step and no Dafny hillclimbing optimizer loop.

## What is here

| Path | Purpose |
|------|---------|
| `src/lemma.cpp`, `src/lemma_pin.cpp` | DuckDB C API extension + pin/lease core |
| `duckdb_memory.py` | Load tables; optional `.lemma_cols` sidecar export |
| `run_experiment.py` | Thin experiment runner (SQL + Rust pin probe / H1 smoke) |
| `check_mem.sh` | Abort if `MemAvailable` < 1.5 GiB; forces `CARGO_BUILD_JOBS=1` |
| `catalog.py`, `dataset_config.py`, `prepare_data.py`, `utils.py` | Shared helpers |
| `rust_bridge/` | `lemma_duckdb_load_test`, `lemma_pin_h1_smoke` (pin smoke binaries) |
| `Makefile` | Build `build/lemma_verus.duckdb_extension` |

## DuckDB pin path (default when `LEMMA_LOAD_FROM_DUCKDB=1`)

1. **Python** opens DuckDB (shared `session.duckdb` file when path is `:memory:`).
2. **`lemma_pin_table`** (C++) runs `SELECT … FROM table` and retains the `duckdb_result`
   plus materialized chunks — a **lease** on DuckDB vector buffers.
3. **Rust** (`lemma_agent_primitives::duckdb_pin`) reads raw pointers per chunk via FFI;
   slices are valid until `unpin` / drop.
4. **Concurrency**: global mutex registry; `lemma_unpin` blocks while iterators hold the pin.
   **Writers must wait** — do not mutate pinned tables while a pin is active.
5. **MethodSpec** unchanged (logical). Sidecar export only when `LEMMA_DUCKDB_SIDECAR_EXPORT=1`.

Pin path loads **only** tables listed in `LEMMA_DUCKDB_PIN_TABLES` (default: probe table,
usually `scan_skew`). Reuses an existing `LEMMA_DUCKDB_PATH` file without reloading holdout
tables.

### Limitations

| Aspect | Pin path (default) | Sidecar (`LEMMA_DUCKDB_SIDECAR_EXPORT=1`) |
|--------|-------------------|-------------------------------------------|
| DuckDB → Rust | Zero-copy pointers into query result buffers | Python/numpy **copy** to `.lemma_cols` |
| Lifetime | Pin lease; writers unsafe during pin | Files on disk |
| Full-table arena | **Not used** | N/A |

## Build

Uses **prebuilt** `libduckdb.so` (never bundled compile). Set `LEMMA_DUCKDB_LIB_DIR` if not
at `build/libduckdb/`. Keep builds single-threaded on small boxes:

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
export LD_LIBRARY_PATH="$LEMMA_DUCKDB_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

make -C verus/db_extension extension
# → build/lemma_verus.duckdb_extension

cargo build --release --manifest-path verus/db_extension/rust_bridge/Cargo.toml
cargo test --manifest-path verus/research_loop/agent_primitives/Cargo.toml
```

## RAM-safe H1 pin smoke (scan.duckdb only)

**Hardware budget:** keep agent work under ~6 GiB RSS; one DuckDB at a time; never
compile DuckDB from source (`bundled`). Prefer this tiny session (~500k rows / ~3 MiB
file). Does **not** load the full holdout suite.

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
export LD_LIBRARY_PATH="$LEMMA_DUCKDB_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

verus/db_extension/check_mem.sh \
  cargo build --release \
  --manifest-path verus/db_extension/rust_bridge/Cargo.toml \
  --bin lemma_pin_h1_smoke

verus/db_extension/check_mem.sh \
  verus/db_extension/rust_bridge/target/release/lemma_pin_h1_smoke \
  build/duckdb_pin_session/scan.duckdb
# Expect SUM_AMOUNT: 1260130811

Fair H1 comparison (same protocol; see `measure_pin_h1.py` / `pin_h1_measure.json`):

```bash
verus/db_extension/check_mem.sh uv run python verus/db_extension/measure_pin_h1.py
```

Latest on this box (scan_skew 500k): pin chunk ~427µs, DuckDB 1T ~880–960µs,
lemma_st (zone-map) ~14µs, bare_st ~123µs. Pin beats DuckDB SQL (~0.45×) but is not
the Vec/zone-map path — that remains the agent-optimized holdout baseline.
```

Or via Python (same pin path, runs `check_mem.sh` wrapper automatically):

```bash
LEMMA_LOAD_FROM_DUCKDB=1 LEMMA_DUCKDB_H1_SMOKE=1 \
  LEMMA_DUCKDB_PATH=build/duckdb_pin_session/scan.duckdb \
  uv run python -m verus.db_extension.run_experiment
```

## Run experiments

```bash
# Default SQL only
uv run python -m verus.db_extension.run_experiment \
  "SELECT COUNT(*) FROM scan_skew"

# Pin + Rust checksum probe (default duckdb load path)
LEMMA_LOAD_FROM_DUCKDB=1 uv run python -m verus.db_extension.run_experiment \
  "SELECT SUM(AMOUNT) FROM scan_skew WHERE EVENT_DATE BETWEEN 19960101 AND 19961231"

# Legacy sidecar export
LEMMA_LOAD_FROM_DUCKDB=1 LEMMA_DUCKDB_SIDECAR_EXPORT=1 \
  uv run python -m verus.db_extension.run_experiment

# Cache bust
LEMMA_FORCE_REGENERATE=1 LEMMA_LOAD_FROM_DUCKDB=1 \
  uv run python -m verus.db_extension.run_experiment
```

In DuckDB SQL (extension loaded):

```sql
LOAD 'build/lemma_verus.duckdb_extension';
SELECT lemma_pin('scan_skew');           -- all columns
SELECT lemma_pin('scan_skew:AMOUNT');   -- subset
SELECT lemma_unpin(1);
```

## Environment flags

| Flag | Default | Effect |
|------|---------|--------|
| `LEMMA_LOAD_FROM_DUCKDB` | `0` | Pin + Rust probe on DuckDB buffers |
| `LEMMA_DUCKDB_SIDECAR_EXPORT` | `0` | Use legacy `.lemma_cols` copy export |
| `LEMMA_DUCKDB_H1_SMOKE` | `0` | Run `lemma_pin_h1_smoke` instead of checksum probe |
| `LEMMA_DUCKDB_PIN_TABLES` | probe table | Comma list of holdout tables to load if missing |
| `LEMMA_FORCE_REGENERATE` | `0` | Bust session/export caches |
| `LEMMA_LOAD_FORMAT` | `lemma_columnar` | `duckdb_memory` also enables pin path |
| `LEMMA_DUCKDB_EXPORT_DIR` | `build/duckdb_memory_export` | Sidecar + session db parent dir |
| `LEMMA_DUCKDB_PATH` | `:memory:` | DuckDB path (`:memory:` → shared session file) |
| `LEMMA_DUCKDB_LIB_DIR` | `build/libduckdb` | Prebuilt DuckDB headers + `libduckdb.so` for Rust FFI |
| `LEMMA_EXPERIMENT_WORKLOAD` | `holdout` | `holdout` or `ssb` tables |
| `LEMMA_RUN_HOLDOUT_BENCH` | `0` | Run `bench_holdout` H1 after probe |

Rust pin module: `verus/research_loop/agent_primitives/src/duckdb_pin.rs`.
