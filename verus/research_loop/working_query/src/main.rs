mod cols;
mod query;

use std::env;
use std::time::Instant;

use cols::Cols;
use query::{format_result, run_query};

fn main() {
    let args: Vec<String> = env::args().collect();
    let tbl_path = args
        .get(1)
        .map(|s| s.as_str())
        .unwrap_or("ssb-dbgen/lineorder_flat.tbl");
    let limit: usize = args
        .get(2)
        .and_then(|s| s.parse().ok())
        .unwrap_or(50_000);

    let cols = Cols::load_from_tbl(tbl_path, limit);

    let mut last = String::new();
    for run in 0..3 {
        let t0 = Instant::now();
        let res = run_query(&cols);
        let dt = t0.elapsed().as_micros();
        if run == 2 {
            println!("QUERY_LATENCY_US: {}", dt);
            last = format_result(&res);
        }
    }
    println!("{}", last);
}
