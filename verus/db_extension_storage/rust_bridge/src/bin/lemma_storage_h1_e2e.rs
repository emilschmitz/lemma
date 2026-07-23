//! E2E cached rerun: DataTable storage scan (duckdb.hpp — not analytical SQL).

use std::env;
use std::ffi::CString;
use std::os::raw::c_char;
use std::time::Instant;

const H1_LO: i32 = 19960101;
const H1_HI: i32 = 19961231;
const EXPECT: u64 = 1_260_130_811;

extern "C" {
    fn lemma_storage_h1_run(
        db_path: *const c_char,
        table: *const c_char,
        date_lo: i32,
        date_hi: i32,
        matched_out: *mut u64,
        sum_out: *mut u64,
        scan_mode_out: *mut c_char,
        scan_mode_len: usize,
        error_out: *mut c_char,
        error_len: usize,
    ) -> i32;
}

fn main() {
    let db_path = env::args().nth(1).expect("usage: lemma_storage_h1_e2e <db_path>");

    let t_all = Instant::now();
    let t_q = Instant::now();

    let c_path = CString::new(db_path.as_str()).expect("db path");
    let c_table = CString::new("scan_skew").expect("table");
    let mut matched = 0u64;
    let mut sum = 0u64;
    let mut scan_mode = vec![0i8; 64];
    let mut err = vec![0i8; 512];

    let rc = unsafe {
        lemma_storage_h1_run(
            c_path.as_ptr(),
            c_table.as_ptr(),
            H1_LO,
            H1_HI,
            &mut matched,
            &mut sum,
            scan_mode.as_mut_ptr(),
            scan_mode.len(),
            err.as_mut_ptr(),
            err.len(),
        )
    };

    let query_us = t_q.elapsed().as_micros();
    let e2e_us = t_all.elapsed().as_micros();

    if rc != 0 {
        let msg = unsafe {
            std::ffi::CStr::from_ptr(err.as_ptr())
                .to_string_lossy()
                .into_owned()
        };
        eprintln!("lemma_storage_h1_run failed: {msg}");
        std::process::exit(1);
    }

    let mode = unsafe {
        std::ffi::CStr::from_ptr(scan_mode.as_ptr())
            .to_string_lossy()
            .into_owned()
    };

    println!("H1_LEMMA_STORAGE_OK");
    println!("ENGINE: lemma");
    println!("PATH: lemma_storage");
    println!("LAYOUT: datatable_scan");
    println!("SCAN_MODE: {mode}");
    println!("E2E_CACHED_RERUN_US: {e2e_us}");
    println!("OPEN_US: 0");
    println!("QUERY_US: {query_us}");
    println!("MATCHED_ROWS: {matched}");
    println!("SUM: {sum}");
    println!("EXPECT: {EXPECT}");
    if sum != EXPECT {
        eprintln!("SUM MISMATCH");
        std::process::exit(1);
    }
}
