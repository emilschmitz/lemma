//! E2E cached rerun reference: open + pin materialize + zone prep + H1 run.
//!
//!   lemma_pin_h1_e2e <db_path>

use lemma_agent_primitives::{DuckDb, PinH1Prep};
use std::env;
use std::time::Instant;

const H1_LO: u32 = 19960101;
const H1_HI: u32 = 19961231;
const EXPECT: u64 = 1_260_130_811;

fn main() {
    let db_path = env::args().nth(1).expect("usage: lemma_pin_h1_e2e <db_path>");

    let t_all = Instant::now();
    let t_open = Instant::now();
    let db = DuckDb::open(&db_path).expect("open db");
    let open_us = t_open.elapsed().as_micros();

    let t_q = Instant::now();
    let pin = db
        .pin_table("scan_skew", &["event_date", "amount"])
        .expect("pin");
    let date_col = pin.column_index("event_date").expect("event_date");
    let amount_col = pin.column_index("amount").expect("amount");
    let prep = PinH1Prep::new(&pin, date_col, amount_col).expect("zone prep");
    let (matched, sum, _, _) = prep.run(H1_LO, H1_HI).expect("H1");
    pin.unpin();
    let query_us = t_q.elapsed().as_micros();
    let e2e_us = t_all.elapsed().as_micros();

    println!("H1_LEMMA_PIN_E2E_OK");
    println!("ENGINE: lemma");
    println!("LAYOUT: duckdb_mem");
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
