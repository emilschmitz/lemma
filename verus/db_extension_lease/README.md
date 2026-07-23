# `lemma_lease` — pin/lease path

SELECT/pin retains DuckDB result vectors; Lemma reads raw pointers + zone maps (`PinH1Prep`).

- **Folder:** `verus/db_extension_lease/`
- **E2E binary:** `rust_bridge/target/release/lemma_lease_h1_e2e`
- **Agent brief:** [`agent/AGENTS.md`](agent/AGENTS.md)
- **Not** `lemma_copy` (sidecar `.lemma_cols` lives under `verus/db_extension/`).

Pin FFI is compiled via `lemma_agent_primitives` (`lemma_pin.cpp` in `db_extension/src/`).
