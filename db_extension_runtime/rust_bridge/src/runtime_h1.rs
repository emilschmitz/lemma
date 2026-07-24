//! Explicit physical-plan H1 for lemma_chunk path.
//!
//! Session-hot: ingest raw columns once via chunk API; hot path = zone-prune + filter + sum.
//! Legacy pushdown available via `DuckStream::h1_sum_optimized` (not default).

use lemma_agent_primitives::{
    build_zone_map_u32, may_satisfy_range_u32, DuckDb, DuckStream, PinError, ZoneSegmentU32,
};

const H1_LO: u32 = 19960101;
const H1_HI: u32 = 19961231;
/// Same row budget as holdout / pin paths.
pub const CHUNK_ZONE_ROWS: usize = 8192;

/// Owned columnar data + zone map built once after open (outside query timers).
pub struct ChunkH1Prep {
    dates: Vec<u32>,
    amounts: Vec<u64>,
    zones: Vec<ZoneSegmentU32>,
}

impl ChunkH1Prep {
    /// Stream `event_date,amount` once; build zone map on owned vectors.
    pub fn ingest(db: &DuckDb) -> Result<Self, PinError> {
        let mut stream = DuckStream::open(db, "scan_skew", &["event_date", "amount"])?;
        let (dates, amounts) = stream.ingest_u32_dates_u64_amounts()?;
        let zones = build_zone_map_u32(&dates, CHUNK_ZONE_ROWS);
        Ok(Self {
            dates,
            amounts,
            zones,
        })
    }

    /// Hot kernel: zone-prune + fused filter + sum on resident slices.
    pub fn run(&self, lo: u32, hi: u32) -> (u64, u64) {
        let mut matched = 0u64;
        let mut sum = 0u64;
        for z in &self.zones {
            if may_satisfy_range_u32(z, lo, hi) {
                for i in z.start..z.end {
                    let d = self.dates[i];
                    if d >= lo && d <= hi {
                        sum = sum.wrapping_add(self.amounts[i]);
                        matched += 1;
                    }
                }
            }
        }
        (matched, sum)
    }

    pub fn run_h1(&self) -> (u64, u64) {
        self.run(H1_LO, H1_HI)
    }
}

/// Legacy one-shot (full stream each call). Prefer [`ChunkH1Prep`].
pub fn runtime_h1_e2e(db: &DuckDb) -> Result<(u64, u64), PinError> {
    let prep = ChunkH1Prep::ingest(db)?;
    Ok(prep.run_h1())
}

/// Agent-editable Rust plan: chunk API + Rust-side zone prune + filter (no SQL WHERE).
#[allow(dead_code)]
pub fn runtime_h1_rust_filtered(db: &DuckDb) -> Result<(u64, u64), PinError> {
    let prep = ChunkH1Prep::ingest(db)?;
    Ok(prep.run_h1())
}

/// Legacy pushdown at scan (DuckDB SQL WHERE); kept for experiments only.
#[allow(dead_code)]
pub fn runtime_h1_pushdown(db: &DuckDb) -> Result<(u64, u64), PinError> {
    DuckStream::h1_sum_optimized(db)
}
