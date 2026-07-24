//! Runtime path uses stream FFI from `lemma_agent_primitives` (shared `lemma_stream.*` compile).

fn main() {
    println!("cargo:rerun-if-env-changed=LEMMA_DUCKDB_LIB_DIR");
}
