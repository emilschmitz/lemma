use lemma_runtime_bridge::runtime_h1_e2e;
use lemma_agent_primitives::DuckDb;
use std::env;
use std::time::Instant;

const EXPECT: u64 = 1_260_130_811;

fn main() {
    let db_path = env::args().nth(1).expect("usage: lemma_runtime_h1_e2e <db_path>");

    let t_all = Instant::now();
    let t_open = Instant::now();
    let db = DuckDb::open(&db_path).expect("open db");
    let open_us = t_open.elapsed().as_micros();

    let t_q = Instant::now();
    let (matched, sum) = runtime_h1_e2e(&db).expect("runtime H1");
    let query_us = t_q.elapsed().as_micros();
    let e2e_us = t_all.elapsed().as_micros();

    println!("H1_LEMMA_RUNTIME_OK");
    println!("ENGINE: lemma");
    println!("PATH: lemma_runtime");
    println!("LAYOUT: chunk_api");
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
