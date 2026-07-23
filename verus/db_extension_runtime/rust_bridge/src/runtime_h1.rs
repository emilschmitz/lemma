//! Explicit physical-plan H1 for lemma_runtime path.
//!
//! Default e2e uses fused C++ pushdown+sum; agents may swap in `open_range` + `sum_amounts_only`.

use lemma_agent_primitives::{DuckDb, DuckStream, PinError};

const H1_LO: u32 = 19960101;
const H1_HI: u32 = 19961231;

/// Default: fused pushdown scan + amount sum in C++ (`lemma_stream_h1_sum_optimized`).
pub fn runtime_h1_e2e(db: &DuckDb) -> Result<(u64, u64), PinError> {
    DuckStream::h1_sum_optimized(db)
}

/// Agent-editable plan: pushdown at scan, Rust-side amount sum over single-column chunks.
#[allow(dead_code)]
pub fn runtime_h1_pushdown_rust(db: &DuckDb) -> Result<(u64, u64), PinError> {
    let mut stream = DuckStream::open_range(db, "scan_skew", "amount", "event_date", H1_LO, H1_HI)?;
    stream.sum_amounts_only()
}
