//! E2E cached rerun: open db + streaming H1 sum (Lemma on DuckDB stream layout).
//!
//!   lemma_stream_h1_e2e <db_path>
//!
//! Prints E2E_CACHED_RERUN_US (= open+query), plus OPEN_US and QUERY_US splits.

use lemma_agent_primitives::{DuckDb, DuckStream};
use std::env;
use std::time::Instant;

const H1_LO: u32 = 19960101;
const H1_HI: u32 = 19961231;
const EXPECT: u64 = 1_260_130_811;

fn main() {
    let db_path = env::args().nth(1).expect("usage: lemma_stream_h1_e2e <db_path>");

    let t_all = Instant::now();
    let t_open = Instant::now();
    let db = DuckDb::open(&db_path).expect("open db");
    let open_us = t_open.elapsed().as_micros();

    let t_q = Instant::now();
    let mut stream = DuckStream::open(&db, "scan_skew", &["event_date", "amount"]).expect("stream");
    let (matched, sum) = stream
        .stream_h1_sum_filtered(H1_LO, H1_HI)
        .expect("stream H1");
    let query_us = t_q.elapsed().as_micros();
    let e2e_us = t_all.elapsed().as_micros();

    println!("H1_LEMMA_STREAM_OK");
    println!("ENGINE: lemma");
    println!("LAYOUT: duckdb_stream");
    println!("E2E_CACHED_RERUN_US: {e2e_us}");
    println!("OPEN_US: {open_us}");
    println!("QUERY_US: {query_us}");
    println!("MATCHED_ROWS: {matched}");
    println!("SUM: {sum}");
    println!("EXPECT: {EXPECT}");
    if sum != EXPECT {
        eprintln!("SUM MISMATCH");
        std::process::exit(1);
    }
}
