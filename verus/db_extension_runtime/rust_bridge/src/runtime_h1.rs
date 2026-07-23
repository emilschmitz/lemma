//! Explicit physical-plan H1 for lemma_runtime path (scan → filter → agg over chunks).

use lemma_agent_primitives::{DuckDb, DuckStream, PinError};

const H1_LO: u32 = 19960101;
const H1_HI: u32 = 19961231;

/// Stage 1–3: open stream, zone-prune per chunk, filter+sum aggregate.
pub fn runtime_h1_e2e(db: &DuckDb) -> Result<(u64, u64), PinError> {
    let mut stream = DuckStream::open(db, "scan_skew", &["event_date", "amount"])?;
    stream.stream_h1_sum_filtered(H1_LO, H1_HI)
}
