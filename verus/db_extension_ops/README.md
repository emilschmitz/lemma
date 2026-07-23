# Path `lemma_ops` — DuckDB operator-shaped kernels

**Option 1:** Compute runs **inside** DuckDB extension callbacks (scalar / table-function style).
DuckDB scheduling drives batch delivery; kernels are hot per-batch loop bodies (scan → filter → agg).

## vs other paths

| Path | Folder | Entry | Execution shape |
|------|--------|-------|-----------------|
| `lemma` / pin_stream | `verus/db_extension/` | `lemma_pin`, stream FFI | Pin/lease or client-side stream loop |
| `lemma_runtime` | `verus/db_extension_runtime/` | `lemma_runtime(VARCHAR)` | External client owns full plan over chunk API |
| **`lemma_ops`** | **`verus/db_extension_ops/`** | **`lemma_ops(VARCHAR)`** | **In-callback batch kernels** (operator-shaped) |

## Build

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
export LD_LIBRARY_PATH="$LEMMA_DUCKDB_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

make -C verus/db_extension_ops extension   # stub .duckdb_extension (optional)

verus/db_extension/check_mem.sh \
  cargo build --release \
  --manifest-path verus/db_extension_ops/rust_bridge/Cargo.toml \
  --bin lemma_ops_h1_e2e
```

## E2E timing binary

Invokes the ops runner FFI (pending stream + per-batch stage callbacks — same shape as an in-extension table function):

```bash
verus/db_extension/check_mem.sh \
  verus/db_extension_ops/rust_bridge/target/release/lemma_ops_h1_e2e \
  build/duckdb_pin_session/scan.duckdb
```

Agent brief: `agent/AGENTS.md`.
