# Verus `db_extension` — experiment-oriented DuckDB extension

This directory is a **stripped copy** of the root [`db_extension/`](../../db_extension/) for
**Verus** experiments. Humans (or Cursor) write kernels; there is **no** OpenRouter/Docker
sandbox agent step and no Dafny hillclimbing optimizer loop.

## What is here

| Path | Purpose |
|------|---------|
| `src/lemma.cpp` | DuckDB C API extension: `lemma()`, `lemma_experiment()`, `lemma_export_table()` |
| `duckdb_memory.py` | Load tables into DuckDB once → export columnar `.lemma_cols` + `manifest.json` |
| `run_experiment.py` | Thin experiment runner (SQL + optional Rust load probe) |
| `catalog.py`, `dataset_config.py`, `prepare_data.py`, `utils.py` | Shared helpers (adapted imports) |
| `rust_bridge/` | `lemma_duckdb_load_test` binary reading export manifests |
| `Makefile` | Build `build/lemma_verus.duckdb_extension` |

## What is **not** here (use root `db_extension/` instead)

- `agent/` OpenRouter sandbox
- `run_optimizer.py` / `optimizer.py` agent hillclimb
- Docker-dependent generation loop

## `extension-template-c`

The DuckDB C API headers live in the **root** tree (not duplicated):

```
../../db_extension/extension-template-c/duckdb_capi/
```

Symlink if you want a local path:

```bash
ln -s ../../db_extension/extension-template-c extension-template-c
```

## Build

From repo root:

```bash
make -C verus/db_extension extension
# → build/lemma_verus.duckdb_extension
```

Requires `g++` and Python (for extension metadata script).

## Run experiments (Python, no DuckDB shell)

```bash
# Holdout tables (generates data if missing)
uv run python -m verus.db_extension.run_experiment \
  "SELECT COUNT(*) FROM scan_skew"

# Enable DuckDB → column sidecar export + Rust load probe
LEMMA_LOAD_FROM_DUCKDB=1 uv run python -m verus.db_extension.run_experiment \
  "SELECT SUM(AMOUNT) FROM scan_skew WHERE EVENT_DATE BETWEEN 19960101 AND 19961231"

# Same via LEMMA_LOAD_FORMAT
LEMMA_LOAD_FORMAT=duckdb_memory uv run python -m verus.db_extension.run_experiment
```

Optional: run holdout bench binary after export probe:

```bash
LEMMA_LOAD_FROM_DUCKDB=1 LEMMA_RUN_HOLDOUT_BENCH=1 \
  uv run python -m verus.db_extension.run_experiment
```

Build the Rust probe binary:

```bash
cargo build --release --manifest-path verus/db_extension/rust_bridge/Cargo.toml
```

## Run via DuckDB CLI (like root demo)

```bash
make -C verus/db_extension extension
uv run python verus/db_extension/prepare_data.py
./build/duckdb -init verus/db_extension/init.sql   # if you have duckdb CLI in build/
```

In SQL:

```sql
LOAD 'build/lemma_verus.duckdb_extension';
SELECT lemma('SELECT COUNT(*) FROM scan_skew');
-- optional export helper (requires table already loaded in session)
SELECT lemma_export_table('scan_skew');
```

## Environment flags

| Flag | Default | Effect |
|------|---------|--------|
| `LEMMA_LOAD_FROM_DUCKDB` | `0` | When `1`, export DuckDB tables to `.lemma_cols` sidecars for Rust |
| `LEMMA_LOAD_FORMAT` | `lemma_columnar` | Set to `duckdb_memory` to enable the same export path |
| `LEMMA_DUCKDB_EXPORT_DIR` | `build/duckdb_memory_export` | Output directory for manifests + column files |
| `LEMMA_DUCKDB_PATH` | `:memory:` | DuckDB database path |
| `LEMMA_EXPERIMENT_WORKLOAD` | `holdout` | `holdout` or `ssb` tables to load |
| `LEMMA_DUCKDB_EXPORT_TABLES` | *(probe table)* | Comma-separated tables to export (default: probe table only) |
| `LEMMA_RUN_HOLDOUT_BENCH` | `0` | When `1`, also run `bench_holdout` H1 after export probe |
| `LEMMA_HOLDOUT_DATA` | *(holdout/data)* | Override holdout `.tbl` directory |
| `LEMMA_DATASET_SIZE` | `2000000` | Row limit for SSB flat load |

Wired in `verus/research_loop/lemma_flags.py`: `lemma_load_from_duckdb()`.

## DuckDB memory load path (MVP)

1. **Python** opens DuckDB, `CREATE TABLE` / `read_csv` **once**.
2. **`duckdb_memory.export_tables`** copies each column via DuckDB → numpy → `.lemma_cols` binary
   (32-byte header + raw little-endian payload).
3. **`manifest.json`** records table/column names, dtypes, lengths, file paths.
4. **Rust** (`lemma_agent_primitives::duckdb_export`) reads manifest + files into `Vec<u64>` etc.
5. **`lemma_duckdb_load_test`** prints row count + wrapping checksum of first column (smoke test).

### Limitations (copy vs zero-copy)

| Aspect | This MVP | True zero-copy |
|--------|----------|----------------|
| DuckDB → Rust | Python/numpy **copy** to sidecar files | mmap DuckDB storage or C API buffer handoff |
| Strings | UTF-8 blob in `.lemma_cols` | Dictionary / Arrow C Data Interface |
| Re-load cost | One export per session (cached on disk) | Shared memory with live DB |
| Extension `lemma_export_table` | Shells out to Python | Would call export in-process |

Future work: DuckDB C API / Arrow C Data Interface for in-process export; mmap sidecars for
read-only experiments.

## Directory tree

```
verus/db_extension/
├── README.md
├── Makefile
├── __init__.py
├── catalog.py
├── dataset_config.py
├── duckdb_memory.py
├── prepare_data.py
├── run_experiment.py
├── utils.py
├── init.sql                 # generated by prepare_data.py
├── queries/
│   ├── q2.sql
│   └── q3.sql
├── rust_bridge/
│   ├── Cargo.toml
│   └── src/bin/lemma_duckdb_load_test.rs
└── src/
    └── lemma.cpp
```

Rust loader library: `verus/research_loop/agent_primitives/src/duckdb_export.rs`.
