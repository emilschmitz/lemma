# Path `lemma_runtime` — Lemma owns the physical plan

**Option 2:** Lemma drives the full end-to-end pipeline (scan chunks → filter → join → agg).
DuckDB supplies storage and chunk I/O only; **do not** run the analytical query via DuckDB SQL.

## vs other paths

| Path | Folder | Entry | Who plans execution |
|------|--------|-------|---------------------|
| `lemma` / pin_stream | `verus/db_extension/` | `lemma`, `lemma_pin`, `lemma_stream_*` | Pin/lease + optional stream; zone maps on DuckDB chunks |
| **`lemma_runtime`** | **`verus/db_extension_runtime/`** | **`lemma_runtime(VARCHAR)`** | **Agent owns entire physical plan** |
| `lemma_ops` | `verus/db_extension_ops/` | `lemma_ops(VARCHAR)` | DuckDB operator callbacks drive batch kernels |

## Build (RAM-safe)

Prebuilt `libduckdb.so` at `build/libduckdb` only — never bundled compile.

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
export LD_LIBRARY_PATH="$LEMMA_DUCKDB_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

make -C verus/db_extension_runtime extension   # stub .duckdb_extension (optional)

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

Chunk FFI reuses `../db_extension/src/lemma_stream.*` (shared compile in `build.rs`) to avoid drift.

Agent brief: `agent/AGENTS.md`.
