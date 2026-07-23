//! E2E cached rerun: open db + operator-shaped batch runner (lemma_ops FFI).
//!
//!   lemma_ops_h1_e2e <db_path>

use lemma_agent_primitives::DuckDb;
use std::env;
use std::ffi::CString;
use std::os::raw::{c_char, c_void};
use std::time::Instant;

const H1_LO: i32 = 19960101;
const H1_HI: i32 = 19961231;
const EXPECT: u64 = 1_260_130_811;

extern "C" {
    fn lemma_ops_h1_run(
        conn: *mut c_void,
        table: *const c_char,
        lo: i32,
        hi: i32,
        matched_out: *mut u64,
        sum_out: *mut u64,
        error_out: *mut c_char,
        error_len: usize,
    ) -> i32;
}

fn main() {
    let db_path = env::args().nth(1).expect("usage: lemma_ops_h1_e2e <db_path>");

    let t_all = Instant::now();
    let t_open = Instant::now();
    let db = DuckDb::open(&db_path).expect("open db");
    let open_us = t_open.elapsed().as_micros();

    let t_q = Instant::now();
    let c_table = CString::new("scan_skew").expect("table");
    let mut matched = 0u64;
    let mut sum = 0u64;
    let mut err = vec![0i8; 512];
    let rc = unsafe {
        lemma_ops_h1_run(
            db.connection_ptr(),
            c_table.as_ptr(),
            H1_LO,
            H1_HI,
            &mut matched,
            &mut sum,
            err.as_mut_ptr(),
            err.len(),
        )
    };
    if rc != 0 {
        let msg = unsafe {
            std::ffi::CStr::from_ptr(err.as_ptr())
                .to_string_lossy()
                .into_owned()
        };
        eprintln!("lemma_ops_h1_run failed: {msg}");
        std::process::exit(1);
    }
    let query_us = t_q.elapsed().as_micros();
    let e2e_us = t_all.elapsed().as_micros();

    println!("H1_LEMMA_OPS_OK");
    println!("ENGINE: lemma");
    println!("PATH: lemma_ops");
    println!("LAYOUT: operator_batch");
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
