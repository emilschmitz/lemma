# `lemma_storage` — storage-layer scan path

Below the Chunk API: **`duckdb.hpp`** + **`libduckdb.so`** scan `DataTable` / row groups directly (not analytical SQL).

- **Folder:** `db_extension_storage/`
- **E2E binary:** `rust_bridge/target/release/lemma_storage_h1_e2e`
- **Agent brief:** [`agent/AGENTS.md`](agent/AGENTS.md)
- Default scan: `DataTable::ScanTableSegment` (`SCAN_MODE: real_datatable_scan`)

Build: `-I build/libduckdb`, `-L build/libduckdb -lduckdb`, `-Wl,-rpath,...`
