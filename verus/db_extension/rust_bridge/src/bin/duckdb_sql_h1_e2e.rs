//! E2E cached rerun baseline: open db + DuckDB SQL engine H1.
//!
//!   duckdb_sql_h1_e2e <db_path>

use lemma_agent_primitives::DuckDb;
use std::env;
use std::time::Instant;

const H1_SQL: &str =
    "SELECT SUM(amount) FROM scan_skew WHERE event_date >= 19960101 AND event_date <= 19961231";
const EXPECT: i64 = 1_260_130_811;

fn main() {
    let db_path = env::args().nth(1).expect("usage: duckdb_sql_h1_e2e <db_path>");

    let t_all = Instant::now();
    let t_open = Instant::now();
    let db = DuckDb::open(&db_path).expect("open db");
    let open_us = t_open.elapsed().as_micros();

    let t_q = Instant::now();
    let sum = db.query_i64(H1_SQL).expect("duckdb sql H1");
    let query_us = t_q.elapsed().as_micros();
    let e2e_us = t_all.elapsed().as_micros();

    println!("H1_DUCKDB_SQL_OK");
    println!("ENGINE: duckdb_sql");
    println!("LAYOUT: duckdb_engine");
    println!("E2E_CACHED_RERUN_US: {e2e_us}");
    println!("OPEN_US: {open_us}");
    println!("QUERY_US: {query_us}");
    println!("SUM: {sum}");
    println!("EXPECT: {EXPECT}");
    if sum != EXPECT {
        eprintln!("SUM MISMATCH");
        std::process::exit(1);
    }
}
