//! Pin/lease H1 for lemma_lease path: SELECT retains DuckDB vectors; Lemma zone-prune + filter + sum.

use lemma_agent_primitives::{DuckDb, PinH1Prep, PinError};

const H1_LO: u32 = 19960101;
const H1_HI: u32 = 19961231;

/// Default: pin `scan_skew` columns, build sub-zones on pinned date vectors, run H1.
pub fn lease_h1_e2e(db: &DuckDb) -> Result<(u64, u64), PinError> {
    let pin = db.pin_table("scan_skew", &["event_date", "amount"])?;
    let date_col = pin.column_index("event_date")?;
    let amount_col = pin.column_index("amount")?;
    let prep = PinH1Prep::new(&pin, date_col, amount_col)?;
    let (matched, sum, _, _) = prep.run(H1_LO, H1_HI)?;
    pin.unpin();
    Ok((matched, sum))
}
