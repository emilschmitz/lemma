//! E2E H1 baseline: DuckDB SQL engine (session-hot primary metric).
//!
//!   duckdb_sql_h1_e2e <db_path>
//!
//! Protocol (one process):
//!   1. Open DB → OPEN_US (diagnostic, not primary)
//!   2. Cold query → COLD_QUERY_US
//!   3. 2 untimed warmups
//!   4. 5 timed queries; median → SESSION_HOT_US (= QUERY_US, GenDB-comparable)
//!   E2E_CACHED_RERUN_US = OPEN_US + COLD_QUERY_US (secondary diagnostic only)

use lemma_agent_primitives::DuckDb;
use std::env;
use std::time::Instant;

const H1_SQL: &str =
    "SELECT SUM(amount) FROM scan_skew WHERE event_date >= 19960101 AND event_date <= 19961231";
const EXPECT: i64 = 1_260_130_811;

fn run_query(db: &DuckDb) -> i64 {
    db.query_i64(H1_SQL).expect("duckdb sql H1")
}

fn main() {
    let db_path = env::args().nth(1).expect("usage: duckdb_sql_h1_e2e <db_path>");

    let t_open = Instant::now();
    let db = DuckDb::open(&db_path).expect("open db");
    let open_us = t_open.elapsed().as_micros();

    let t_cold = Instant::now();
    let cold_sum = run_query(&db);
    let cold_query_us = t_cold.elapsed().as_micros();
    if cold_sum != EXPECT {
        eprintln!("SUM MISMATCH (cold)");
        std::process::exit(1);
    }

    for _ in 0..2 {
        let s = run_query(&db);
        if s != EXPECT {
            eprintln!("SUM MISMATCH (warmup)");
            std::process::exit(1);
        }
    }

    let mut times = [0u128; 5];
    let mut sum = cold_sum;
    for t in &mut times {
        let t0 = Instant::now();
        sum = run_query(&db);
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

    println!("H1_DUCKDB_SQL_OK");
    println!("ENGINE: duckdb_sql");
    println!("LAYOUT: duckdb_engine");
    println!("OPEN_US: {open_us}");
    println!("COLD_QUERY_US: {cold_query_us}");
    println!("SESSION_HOT_US: {session_hot_us}");
    println!("QUERY_US: {session_hot_us}");
    println!("E2E_CACHED_RERUN_US: {e2e_cached_rerun_us}");
    println!("SUM: {sum}");
    println!("EXPECT: {EXPECT}");
}
