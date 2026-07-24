//! H1 smoke: Lemma sum(amount) with date filter over pinned DuckDB vector buffers.
//!
//!   lemma_pin_h1_smoke <db_path>
//!
//! Expects `scan_skew` already loaded. Lemma executes; DuckDB only supplies layout/memory.
//! Zone maps are built at prep time (outside query timer), matching holdout H1LemmaPrep.

use lemma_agent_primitives::{DuckDb, PinH1Prep};
use std::env;
use std::time::Instant;

const H1_LO: u32 = 19960101;
const H1_HI: u32 = 19961231;
const EXPECT: u64 = 1_260_130_811;

fn main() {
    let db_path = env::args().nth(1).expect("usage: lemma_pin_h1_smoke <db_path>");
    let db = DuckDb::open(&db_path).expect("open db");
    let pin = db
        .pin_table("scan_skew", &["event_date", "amount"])
        .expect("pin scan_skew");

    let date_col = pin.column_index("event_date").expect("event_date");
    let amount_col = pin.column_index("amount").expect("amount");

    // Prep: zone maps over pinned date vectors (outside query timer).
    let prep = PinH1Prep::new(&pin, date_col, amount_col).expect("zone prep");

    // Warmup
    for _ in 0..3 {
        let _ = prep.run(H1_LO, H1_HI).expect("warmup");
    }

    let mut times = [0u128; 5];
    let mut matched = 0u64;
    let mut sum = 0u64;
    let mut zones_kept = 0usize;
    let mut zones_total = prep.zone_count();
    for t in &mut times {
        let t0 = Instant::now();
        let (m, s, kept, total) = prep.run(H1_LO, H1_HI).expect("query");
        matched = m;
        sum = s;
        zones_kept = kept;
        zones_total = total;
        *t = t0.elapsed().as_micros();
    }
    times.sort();
    let median = times[2];

    println!("H1_LEMMA_OK");
    println!("ENGINE: lemma");
    println!("LAYOUT: duckdb_mem");
    println!("ZONES_TOTAL: {zones_total}");
    println!("ZONES_KEPT: {zones_kept}");
    println!("MATCHED_ROWS: {matched}");
    println!("SUM_AMOUNT: {sum}");
    println!("QUERY_LATENCY_US: {median}");
    println!("EXPECT_SUM: {EXPECT}");
    if sum != EXPECT {
        eprintln!("SUM MISMATCH");
        std::process::exit(1);
    }
}
