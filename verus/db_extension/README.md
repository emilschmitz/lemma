# Verus `db_extension` — experiment-oriented DuckDB extension

This directory is a **stripped copy** of the root [`db_extension/`](../../db_extension/) for
**Verus** experiments. Humans (or Cursor) write kernels; there is **no** OpenRouter/Docker
sandbox agent step and no Dafny hillclimbing optimizer loop.

## What is here

| Path | Purpose |
|------|---------|
| `src/lemma.cpp`, `src/lemma_pin.cpp`, `src/lemma_stream.cpp` | DuckDB C API extension + pin/lease + streaming scan |
| `duckdb_memory.py` | Load tables; optional `.lemma_cols` sidecar export |
| `run_experiment.py` | Thin experiment runner (SQL + Lemma-on-DuckDB-mem probe / H1) |
| `check_mem.sh` | Abort if `MemAvailable` < 1.5 GiB; forces `CARGO_BUILD_JOBS=1` |
| `catalog.py`, `dataset_config.py`, `prepare_data.py`, `utils.py` | Shared helpers |
| `rust_bridge/` | `lemma_duckdb_load_test`, `lemma_pin_h1_smoke`, `lemma_stream_h1_e2e` |
| `Makefile` | Build `build/lemma_verus.duckdb_extension` |

## Lemma on DuckDB memory (default when `LEMMA_LOAD_FROM_DUCKDB=1`)

**Naming:** Lemma executes the query. DuckDB only stores/hosts the vector buffers
(`LAYOUT: duckdb_mem`). Never call the timed kernel “DuckDB” — that name is reserved
for the DuckDB SQL engine baseline (`duckdb_sql_*`).

1. **Python** opens a DuckDB database file (shared `session.duckdb` when path is `:memory:`).
2. **`lemma_pin_table`** (C++) runs `SELECT … FROM table` and retains the `duckdb_result`
   plus materialized chunks — a **lease** on DuckDB vector buffers for Lemma.
3. **Lemma Rust** (`lemma_agent_primitives::duckdb_pin`) reads raw pointers per chunk via FFI;
   slices are valid until `unpin` / drop.
4. **Concurrency**: global mutex registry; `lemma_unpin` blocks while iterators hold the pin.
   **Writers must wait** — do not mutate pinned tables while a pin is active.
5. **MethodSpec** unchanged (logical). Sidecar export only when `LEMMA_DUCKDB_SIDECAR_EXPORT=1`.

Loads **only** tables listed in `LEMMA_DUCKDB_PIN_TABLES` (default: probe table,
usually `scan_skew`). Reuses an existing `LEMMA_DUCKDB_PATH` file without reloading holdout
tables.

### Limitations

| Aspect | Lemma + DuckDB mem (default) | Sidecar copy (`LEMMA_DUCKDB_SIDECAR_EXPORT=1`) |
|--------|------------------------------|-----------------------------------------------|
| Path | Lemma on zero-copy DuckDB vector pointers | Python/numpy **copy** to `.lemma_cols`, then Lemma |
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

## RAM-safe H1 Lemma (DuckDB mem) smoke

**Hardware budget:** keep agent work under ~6 GiB RSS; one DuckDB host process at a time; never
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
# Expect SUM_AMOUNT: 1260130811; ENGINE: lemma; LAYOUT: duckdb_mem
```

Fair H1 comparison (same protocol; see `measure_pin_h1.py` / `pin_h1_measure.json`):

```bash
verus/db_extension/check_mem.sh uv run python verus/db_extension/measure_pin_h1.py
```

### E2E cached rerun (streaming vs DuckDB SQL)

**Metric:** `E2E_CACHED_RERUN_US` — open db + run H1 from process start (not hot query-only).
Lemma streaming layout is `lemma_st_duckdb_stream` (`LAYOUT: duckdb_stream`); pin materialize
reference is `lemma_st_duckdb_mem_pin_e2e`.

```bash
verus/db_extension/check_mem.sh \
  cargo build --release \
  --manifest-path verus/db_extension/rust_bridge/Cargo.toml \
  --bin lemma_stream_h1_e2e --bin lemma_pin_h1_e2e

verus/db_extension/check_mem.sh uv run python verus/db_extension/measure_e2e_cached_rerun.py
# → verus/db_extension/e2e_cached_rerun_h1.json
```

Latest on this box (scan_skew 500k, see `pin_h1_measure.json`): **lemma_st_duckdb_mem**
~15µs (zone-map prune on pinned buffers), **duckdb_sql** 1T ~456–569µs, **lemma_st**
(Vec/zone-map) ~10µs, **bare_st** ~122µs. The first DuckDB-mem smoke path scanned every
row in every chunk (~427µs); prep now builds 8192-row sub-zones on pinned date vectors
(same `ZONE_ROWS` as holdout) and prunes before filter+sum (13/245 zones kept for H1).

Or via Python (same path, runs `check_mem.sh` wrapper automatically):

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

# Lemma checksum probe on DuckDB mem layout (default duckdb load path)
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
| `LEMMA_LOAD_FROM_DUCKDB` | `0` | Lemma probe on DuckDB vector memory (not DuckDB SQL) |
| `LEMMA_DUCKDB_SIDECAR_EXPORT` | `0` | Use legacy `.lemma_cols` copy export |
| `LEMMA_DUCKDB_H1_SMOKE` | `0` | Run Lemma H1 on DuckDB mem (`lemma_pin_h1_smoke`) |
| `LEMMA_DUCKDB_PIN_TABLES` | probe table | Comma list of holdout tables to load if missing |
| `LEMMA_FORCE_REGENERATE` | `0` | Bust session/export caches |
| `LEMMA_LOAD_FORMAT` | `lemma_columnar` | `duckdb_memory` also enables DuckDB-mem path |
| `LEMMA_DUCKDB_EXPORT_DIR` | `build/duckdb_memory_export` | Sidecar + session db parent dir |
| `LEMMA_DUCKDB_PATH` | `:memory:` | DuckDB path (`:memory:` → shared session file) |
| `LEMMA_DUCKDB_LIB_DIR` | `build/libduckdb` | Prebuilt DuckDB headers + `libduckdb.so` for Rust FFI |
| `LEMMA_EXPERIMENT_WORKLOAD` | `holdout` | `holdout` or `ssb` tables |
| `LEMMA_RUN_HOLDOUT_BENCH` | `0` | Run `bench_holdout` H1 after probe |

Lemma↔DuckDB-mem FFI: `verus/research_loop/agent_primitives/src/duckdb_pin.rs`.
