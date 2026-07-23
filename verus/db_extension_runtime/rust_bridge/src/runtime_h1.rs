//! Explicit physical-plan H1 for lemma_chunk path.
//!
//! Default e2e: stream raw `event_date,amount`; Lemma zone-prune + filter + sum in C++.
//! Legacy pushdown available via `DuckStream::h1_sum_optimized` (not default).

use lemma_agent_primitives::{DuckDb, DuckStream, PinError};

const H1_LO: u32 = 19960101;
const H1_HI: u32 = 19961231;

/// Default: raw two-column stream + Lemma filter/sum (`lemma_stream_h1_sum_lemma_filter`).
pub fn runtime_h1_e2e(db: &DuckDb) -> Result<(u64, u64), PinError> {
    DuckStream::h1_sum_lemma_filter(db)
}

/// Agent-editable Rust plan: chunk API + Rust-side zone prune + filter (no SQL WHERE).
#[allow(dead_code)]
pub fn runtime_h1_rust_filtered(db: &DuckDb) -> Result<(u64, u64), PinError> {
    let mut stream = DuckStream::open(db, "scan_skew", &["event_date", "amount"])?;
    stream.stream_h1_sum_filtered(H1_LO, H1_HI)
}

/// Legacy pushdown at scan (DuckDB SQL WHERE); kept for experiments only.
#[allow(dead_code)]
pub fn runtime_h1_pushdown(db: &DuckDb) -> Result<(u64, u64), PinError> {
    DuckStream::h1_sum_optimized(db)
}
