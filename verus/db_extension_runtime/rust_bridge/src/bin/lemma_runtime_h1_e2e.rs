//! E2E H1: Lemma chunk API (session-hot primary metric).
//!
//!   lemma_runtime_h1_e2e <db_path>
//!
//! Protocol (one process):
//!   1. Open DB → OPEN_US (diagnostic, not primary)
//!   2. Ingest + zone prep → PREP_US (outside query timers)
//!   3. Cold query → COLD_QUERY_US (prep.run only)
//!   4. 2 untimed warmups
//!   5. 5 timed queries; median → SESSION_HOT_US (= QUERY_US, GenDB-comparable)
//!   E2E_CACHED_RERUN_US = OPEN_US + COLD_QUERY_US (secondary diagnostic only)

use lemma_agent_primitives::DuckDb;
use lemma_runtime_bridge::ChunkH1Prep;
use std::env;
use std::time::Instant;

const EXPECT: u64 = 1_260_130_811;

fn main() {
    let db_path = env::args().nth(1).expect("usage: lemma_runtime_h1_e2e <db_path>");

    let t_open = Instant::now();
    let db = DuckDb::open(&db_path).expect("open db");
    let open_us = t_open.elapsed().as_micros();

    let t_prep = Instant::now();
    let prep = ChunkH1Prep::ingest(&db).expect("ingest + zone prep");
    let prep_us = t_prep.elapsed().as_micros();

    let t_cold = Instant::now();
    let (cold_matched, cold_sum) = prep.run_h1();
    let cold_query_us = t_cold.elapsed().as_micros();
    if cold_sum != EXPECT {
        eprintln!("SUM MISMATCH (cold)");
        std::process::exit(1);
    }

    for _ in 0..2 {
        let (_, s) = prep.run_h1();
        if s != EXPECT {
            eprintln!("SUM MISMATCH (warmup)");
            std::process::exit(1);
        }
    }

    let mut times = [0u128; 5];
    let mut matched = cold_matched;
    let mut sum = cold_sum;
    for t in &mut times {
        let t0 = Instant::now();
        let (m, s) = prep.run_h1();
        matched = m;
        sum = s;
        *t = t0.elapsed().as_micros();
        if sum != EXPECT {
            eprintln!("SUM MISMATCH (timed)");
            std::process::exit(1);
        }
    }
    times.sort();
    let session_hot_us = times[2];
    // NOT GenDB-comparable; old harness mixed open into e2e headline.
    let e2e_cached_rerun_us = open_us + cold_query_us;

    println!("H1_LEMMA_RUNTIME_OK");
    println!("ENGINE: lemma");
    println!("PATH: lemma_chunk");
    println!("LAYOUT: chunk_api");
    println!("OPEN_US: {open_us}");
    println!("PREP_US: {prep_us}");
    println!("COLD_QUERY_US: {cold_query_us}");
    println!("SESSION_HOT_US: {session_hot_us}");
    println!("QUERY_US: {session_hot_us}");
    println!("E2E_CACHED_RERUN_US: {e2e_cached_rerun_us}");
    println!("MATCHED_ROWS: {matched}");
    println!("SUM: {sum}");
    println!("EXPECT: {EXPECT}");
}
