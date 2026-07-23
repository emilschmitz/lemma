//! Lease path uses pin FFI from `lemma_agent_primitives` (shared `lemma_pin.*` compile).

fn main() {
    println!("cargo:rerun-if-env-changed=LEMMA_DUCKDB_LIB_DIR");
}
