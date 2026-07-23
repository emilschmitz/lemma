# Path `lemma_chunk` — Lemma owns filter + agg on Chunk API

**Chunk API:** stream column batches from DuckDB; **Lemma owns filter + agg** (default: no SQL `WHERE` pushdown).

## vs other paths

| Path | Folder | Who plans execution |
|------|--------|---------------------|
| `lemma_copy` | `verus/db_extension/` | Copy to `.lemma_cols` → Lemma on owned memory |
| **`lemma_chunk`** | **`verus/db_extension_runtime/`** | **Lemma filter+agg on streamed chunks** |
| `lemma_lease` | `verus/db_extension_lease/` | Pin/lease + zone maps on DuckDB vectors |
| `lemma_storage` | `verus/db_extension_storage/` | DataTable storage scan (`duckdb.hpp`) |

## Build (RAM-safe)

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"

verus/db_extension/check_mem.sh \
  cargo build --release \
  --manifest-path verus/db_extension_runtime/rust_bridge/Cargo.toml \
  --bin lemma_runtime_h1_e2e
```

## E2E timing binary

```bash
verus/db_extension/check_mem.sh \
  verus/db_extension_runtime/rust_bridge/target/release/lemma_runtime_h1_e2e \
  build/duckdb_pin_session/scan.duckdb
```

Chunk FFI reuses `../db_extension/src/lemma_stream.*` via `lemma_agent_primitives`.

Agent brief: `agent/AGENTS.md`.
