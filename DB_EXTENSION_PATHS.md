# Lemma ↔ DuckDB paths (clear names)

Four **Lemma** ways to run a query, plus one **baseline** (DuckDB SQL). Benchmark tables show **Lemma paths + duckdb_sql**, not “four Lemma designs.”

---

## Lemma paths (+ baseline)

| Clear name | Folder | What it does | Copies data into Lemma? |
|------------|--------|--------------|-------------------------|
| **`lemma_copy`** | `db_extension_paths/` (sidecar `.lemma_cols`, `lemma_copy_*`) | DuckDB → **memcpy** into `.lemma_cols` / `Vec`s → Lemma runs on owned memory | **Yes** |
| **`lemma_chunk`** | `db_extension_runtime/` | **Chunk API**: stream column batches; **Lemma owns filter + agg** (default: no SQL `WHERE` pushdown) | **No** |
| **`lemma_lease`** | `db_extension_lease/` | **Pin/lease**: `SELECT` retains DuckDB result vectors; Lemma reads pointers + zone maps | **No** (lease, not copy) |
| **`lemma_storage`** | `db_extension_storage/` | **Below Chunk API**: `duckdb.hpp` + `DataTable::ScanTableSegment` on row-group storage (not analytical SQL) | **No** |
| **`duckdb_sql`** | `db_extension_paths/rust_bridge/` (`duckdb_sql_h1_e2e`) | DuckDB runs the SQL engine baseline | N/A (not Lemma) |

Agent briefs (one path only each):

- `db_extension_paths/agent/AGENTS.md` → **`lemma_copy`** (+ legacy pin/stream FFI sources)
- `db_extension_runtime/agent/AGENTS.md` → **`lemma_chunk`**
- `db_extension_lease/agent/AGENTS.md` → **`lemma_lease`**
- `db_extension_storage/agent/AGENTS.md` → **`lemma_storage`**

**Removed:** `db_extension_ops/` (stages) — not a product path.

---

## Pinning vs copy vs lease

| Mechanism | Clear name | Meaning |
|-----------|------------|---------|
| Sidecar `.lemma_cols` | **`lemma_copy`** | Lemma **owns** a second copy of columns |
| Pin / lease | **`lemma_lease`** | DuckDB **keeps** vector buffers alive; Lemma reads pointers until unpin |
| Stream chunks | **`lemma_chunk`** | Single-pass batches; no full-table retain |
| Storage scan | **`lemma_storage`** | Read `DataTable` / row groups directly |

Pin/lease is **not** a SQL `VIEW` and **not** `lemma_copy`.

---

## Default H1 semantics (500k `scan_skew`)

| Path | Who filters? | Default kernel |
|------|--------------|----------------|
| `lemma_chunk` | **Lemma** (zone-prune + filter in C++/Rust) | `lemma_stream_h1_sum_lemma_filter` |
| `lemma_lease` | **Lemma** on pinned buffers | `PinH1Prep::run` |
| `lemma_storage` | **Lemma** on storage `DataChunk`s | `DataTable::ScanTableSegment` + sparse **band prune** + fused filter/sum (`+band_prune` when probes hit) |
| `duckdb_sql` | **DuckDB** | `SELECT SUM(amount) … WHERE …` |

Expect SUM **`1260130811`** on all paths.

Legacy **`lemma_stream_h1_sum_optimized`** (SQL `WHERE` pushdown) remains in tree for experiments; it is **not** the chunk default.

---

## Agent vs scaffolding (H1)

**Number every path agent optimizes: `SESSION_HOT_US`** (GenDB hot recompute). Keep open / prep /
cold / e2e-diag as side metrics.

- Allowed prep: residency, decoded columns, zonemaps (GenDB-like).
- Forbidden: memoized final answer; SQL `WHERE`/`SUM` pushdown on Lemma paths.
- Storage agents: band-only is not enough — keep decoded+zones for primary hot.

See `research_loop/agents/AGENTS.md`.

---

## Build / measure

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
db_extension_paths/check_mem.sh uv run python db_extension_paths/measure_e2e_paths.py
```

Output: `db_extension_paths/e2e_paths_h1.json`

Build e2e binaries (release):

```bash
CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1 LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb" \
  cargo build --release -p lemma_runtime_bridge --bin lemma_runtime_h1_e2e
CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1 LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb" \
  cargo build --release -p lemma_lease_bridge --bin lemma_lease_h1_e2e
CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1 LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb" \
  cargo build --release -p lemma_storage_bridge --bin lemma_storage_h1_e2e
CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1 LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb" \
  cargo build --release -p lemma_duckdb_bridge --bin duckdb_sql_h1_e2e
```

---

## Alias cheat sheet

| Old / confusing | Clear |
|-----------------|--------|
| runtime | **`lemma_chunk`** |
| pin / pin_stream | **`lemma_lease`** (moved e2e to `db_extension_lease/`) |
| ops / stages | **removed** |
| sidecar / `.lemma_cols` | **`lemma_copy`** |
| duckdb_sql | **baseline** |
