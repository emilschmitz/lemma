//! H1 smoke: sum(amount) with date filter over DuckDB pin chunks (no sidecar).
//!
//!   lemma_pin_h1_smoke <db_path>
//!
//! Expects `scan_skew` already loaded. Uses chunk vector pointers under a pin lease.

use lemma_agent_primitives::DuckDb;
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

    // Warmup
    for _ in 0..3 {
        let mut _s = 0u64;
        for chunk in pin.chunks() {
            let (m, s) = chunk
                .col_i64_or_i32_sum_filtered(date_col, amount_col, H1_LO, H1_HI)
                .expect("sum");
            let _ = m;
            _s = _s.wrapping_add(s);
        }
    }

    let mut times = [0u128; 5];
    let mut sum = 0u64;
    let mut matched = 0u64;
    for t in &mut times {
        let t0 = Instant::now();
        sum = 0;
        matched = 0;
        for chunk in pin.chunks() {
            let (m, s) = chunk
                .col_i64_or_i32_sum_filtered(date_col, amount_col, H1_LO, H1_HI)
                .expect("sum");
            matched += m;
            sum = sum.wrapping_add(s);
        }
        *t = t0.elapsed().as_micros();
    }
    times.sort();
    let median = times[2];

    println!("H1_PIN_OK");
    println!("MATCHED_ROWS: {matched}");
    println!("SUM_AMOUNT: {sum}");
    println!("QUERY_LATENCY_US: {median}");
    println!("EXPECT_SUM: {EXPECT}");
    if sum != EXPECT {
        eprintln!("SUM MISMATCH");
        std::process::exit(1);
    }
}
