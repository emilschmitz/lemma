# Agent brief — path `lemma_storage`

You optimize **one path only**: `verus/db_extension_storage/` (below Chunk API — **DataTable** / row-group storage scan).

Do **not** share code or prompts with chunk, lease, or copy agents.

## Default H1 plan (e2e cached rerun)

**Not SQL `SELECT … WHERE`.** Scan table storage via `duckdb.hpp` + `libduckdb.so`:

1. `Catalog::GetEntry<TableCatalogEntry>` → `GetStorage()` → `DataTable`.
2. `DataTable::ScanTableSegment` — walks row groups / `DataChunk`s from on-disk layout.
3. Lemma zone-prune + filter + sum on each storage chunk (`lemma_storage.cpp`).
4. Expect SUM `1260130811`. Default `SCAN_MODE: real_datatable_scan`.

If true DataTable scan is blocked on this DuckDB build, document fallback honestly in `SCAN_MODE` — do not silently use analytical SQL.

## Mandate — AGGRESSIVE

- Maximize control: column projection at storage bind, segment zonemap skip, fused filter+agg
- Single-threaded, low RAM; no bundled DuckDB compile
- **TRUSTED:** storage scan I/O. **Spec:** logical `MethodSpec` only.

**Forbidden:** `Connection::Query("SELECT … WHERE …")` for the timed kernel; editing other extension trees.

## Edit target

`src/lemma_storage.cpp`, `src/lemma_storage_internal.hpp`.

## Metric

**E2E cached rerun** vs `duckdb_sql_*`.

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
verus/db_extension/check_mem.sh uv run python verus/db_extension/measure_e2e_paths.py
```

Dataset: `build/duckdb_pin_session/scan.duckdb` (500k). No full holdout.

## Agent vs scaffolding

See `verus/research_loop/agents/AGENTS.md`. **Current H1 e2e gap vs DuckDB: primarily agent/kernel**, not missing path scaffolding. Do not push analytical WHERE/SUM back to DuckDB SQL to fake a win.
