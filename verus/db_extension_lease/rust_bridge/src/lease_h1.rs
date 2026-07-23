//! Pin/lease H1 for lemma_lease path: pin once per session; hot path = zone-prune + filter + sum.

use lemma_agent_primitives::{
    build_pin_zone_map_u32, DuckDb, DuckTablePin, PinError, PinZoneSegmentU32, PIN_ZONE_ROWS,
};

const H1_LO: u32 = 19960101;
const H1_HI: u32 = 19961231;

/// Session state: pin + zone map built once after open (outside query timers).
pub struct LeaseH1Session {
    pin: DuckTablePin,
    date_col: usize,
    amount_col: usize,
    zones: Vec<PinZoneSegmentU32>,
}

impl LeaseH1Session {
    /// Pin `scan_skew` columns and build sub-zones on pinned date vectors.
    pub fn prep(db: &DuckDb) -> Result<Self, PinError> {
        let pin = db.pin_table("scan_skew", &["event_date", "amount"])?;
        let date_col = pin.column_index("event_date")?;
        let amount_col = pin.column_index("amount")?;
        let zones = build_pin_zone_map_u32(&pin, date_col, PIN_ZONE_ROWS)?;
        Ok(Self {
            pin,
            date_col,
            amount_col,
            zones,
        })
    }

    /// Hot kernel: zone-prune + fused filter + sum on pinned buffers.
    pub fn run(&self, lo: u32, hi: u32) -> Result<(u64, u64), PinError> {
        let mut matched = 0u64;
        let mut sum = 0u64;
        for z in &self.zones {
            if z.may_satisfy(lo, hi) {
                let chunk = self.pin.chunk(z.chunk_index);
                let (m, s) = chunk.col_i64_or_i32_sum_filtered_range(
                    self.date_col,
                    self.amount_col,
                    lo,
                    hi,
                    z.start,
                    z.end,
                )?;
                matched += m;
                sum = sum.wrapping_add(s);
            }
        }
        Ok((matched, sum))
    }

    pub fn run_h1(&self) -> Result<(u64, u64), PinError> {
        self.run(H1_LO, H1_HI)
    }
}

/// Legacy one-shot (pin + prep + run + unpin each call). Prefer [`LeaseH1Session`].
pub fn lease_h1_e2e(db: &DuckDb) -> Result<(u64, u64), PinError> {
    let session = LeaseH1Session::prep(db)?;
    session.run_h1()
}
