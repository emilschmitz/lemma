# Path `lemma_chunk` — Lemma owns filter + agg on Chunk API

**Chunk API:** stream column batches from DuckDB; **Lemma owns filter + agg** (default: no SQL `WHERE` pushdown).

## vs other paths

| Path | Folder | Who plans execution |
|------|--------|---------------------|
| `lemma_copy` | `db_extension_paths/` | Copy to `.lemma_cols` → Lemma on owned memory |
| **`lemma_chunk`** | **`db_extension_runtime/`** | **Lemma filter+agg on streamed chunks** |
| `lemma_lease` | `db_extension_lease/` | Pin/lease + zone maps on DuckDB vectors |
| `lemma_storage` | `db_extension_storage/` | DataTable storage scan (`duckdb.hpp`) |

## Build (RAM-safe)

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"

db_extension_paths/check_mem.sh \
  cargo build --release \
  --manifest-path db_extension_runtime/rust_bridge/Cargo.toml \
  --bin lemma_runtime_h1_e2e
```

## E2E timing binary

```bash
db_extension_paths/check_mem.sh \
  db_extension_runtime/rust_bridge/target/release/lemma_runtime_h1_e2e \
  build/duckdb_pin_session/scan.duckdb
```

Chunk FFI reuses `../db_extension/src/lemma_stream.*` via `lemma_agent_primitives`.

Agent brief: `agent/AGENTS.md`.
