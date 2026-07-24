//! H1 smoke: Lemma sum(amount) on **copied** DuckDB columns (`.lemma_cols` sidecar).
//!
//!   lemma_copy_h1_smoke <manifest.json>
//!
//! Export/load are outside the timer. Lemma executes; layout source was a DuckDB copy.

use lemma_agent_primitives::load_cols_from_duckdb_export;
use std::env;
use std::path::PathBuf;
use std::time::Instant;

const H1_LO: u64 = 19960101;
const H1_HI: u64 = 19961231;
const EXPECT: u64 = 1_260_130_811;

fn h1_sum(dates: &[u64], amounts: &[u64]) -> (u64, u64) {
    let mut sum = 0u64;
    let mut matched = 0u64;
    let n = dates.len().min(amounts.len());
    for i in 0..n {
        let d = dates[i];
        if d >= H1_LO && d <= H1_HI {
            sum = sum.wrapping_add(amounts[i]);
            matched += 1;
        }
    }
    (matched, sum)
}

fn main() {
    let manifest = PathBuf::from(
        env::args()
            .nth(1)
            .expect("usage: lemma_copy_h1_smoke <manifest.json>"),
    );

    // Load outside timer (copy already materialized on disk).
    let dates = load_cols_from_duckdb_export(&manifest, "scan_skew", "event_date")
        .expect("load event_date");
    let amounts =
        load_cols_from_duckdb_export(&manifest, "scan_skew", "amount").expect("load amount");

    for _ in 0..3 {
        let _ = h1_sum(&dates, &amounts);
    }

    let mut times = [0u128; 5];
    let mut sum = 0u64;
    let mut matched = 0u64;
    for t in &mut times {
        let t0 = Instant::now();
        let (m, s) = h1_sum(&dates, &amounts);
        matched = m;
        sum = s;
        *t = t0.elapsed().as_micros();
    }
    times.sort();
    let median = times[2];

    println!("H1_LEMMA_OK");
    println!("ENGINE: lemma");
    println!("LAYOUT: duckdb_copy");
    println!("MATCHED_ROWS: {matched}");
    println!("SUM_AMOUNT: {sum}");
    println!("QUERY_LATENCY_US: {median}");
    println!("EXPECT_SUM: {EXPECT}");
    if sum != EXPECT {
        eprintln!("SUM MISMATCH");
        std::process::exit(1);
    }
}
