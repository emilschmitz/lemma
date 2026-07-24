//! E2E H1: DataTable storage scan (session-hot primary metric).
//!
//!   lemma_storage_h1_e2e <db_path>
//!
//! Protocol (one process):
//!   1. Open session → OPEN_US (diagnostic, not primary)
//!   2. Cold query → COLD_QUERY_US
//!   3. 2 untimed warmups
//!   4. 5 timed queries; median → SESSION_HOT_US (= QUERY_US, GenDB-comparable)
//!   E2E_CACHED_RERUN_US = OPEN_US + COLD_QUERY_US (secondary diagnostic only)

use std::env;
use std::ffi::CString;
use std::os::raw::c_char;
use std::time::Instant;

const H1_LO: i32 = 19960101;
const H1_HI: i32 = 19961231;
const EXPECT: u64 = 1_260_130_811;

type LemmaStorageSession = std::ffi::c_void;

extern "C" {
    fn lemma_storage_h1_open(
        db_path: *const c_char,
        session_out: *mut *mut LemmaStorageSession,
        error_out: *mut c_char,
        error_len: usize,
    ) -> i32;

    fn lemma_storage_h1_query(
        session: *mut LemmaStorageSession,
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

    fn lemma_storage_h1_close(session: *mut LemmaStorageSession);
}

fn cstr_err(buf: &[i8]) -> String {
    unsafe {
        std::ffi::CStr::from_ptr(buf.as_ptr())
            .to_string_lossy()
            .into_owned()
    }
}

struct QueryOut {
    matched: u64,
    sum: u64,
    scan_mode: String,
}

fn run_query(
    session: *mut LemmaStorageSession,
    c_table: &CString,
    err: &mut [i8],
    scan_mode: &mut [i8],
) -> Result<QueryOut, String> {
    let mut matched = 0u64;
    let mut sum = 0u64;
    err.fill(0);
    scan_mode.fill(0);
    let rc = unsafe {
        lemma_storage_h1_query(
            session,
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
    if rc != 0 {
        return Err(cstr_err(err));
    }
    Ok(QueryOut {
        matched,
        sum,
        scan_mode: cstr_err(scan_mode),
    })
}

fn main() {
    let db_path = env::args().nth(1).expect("usage: lemma_storage_h1_e2e <db_path>");

    let c_path = CString::new(db_path.as_str()).expect("db path");
    let mut session: *mut LemmaStorageSession = std::ptr::null_mut();
    let mut err = vec![0i8; 512];
    let mut scan_mode = vec![0i8; 64];

    let t_open = Instant::now();
    let rc_open = unsafe {
        lemma_storage_h1_open(
            c_path.as_ptr(),
            &mut session,
            err.as_mut_ptr(),
            err.len(),
        )
    };
    let open_us = t_open.elapsed().as_micros();

    if rc_open != 0 {
        eprintln!("lemma_storage_h1_open failed: {}", cstr_err(&err));
        std::process::exit(1);
    }

    let c_table = CString::new("scan_skew").expect("table");

    let t_cold = Instant::now();
    let cold = match run_query(session, &c_table, &mut err, &mut scan_mode) {
        Ok(o) => o,
        Err(e) => {
            eprintln!("lemma_storage_h1_query failed (cold): {e}");
            unsafe {
                lemma_storage_h1_close(session);
            }
            std::process::exit(1);
        }
    };
    let cold_query_us = t_cold.elapsed().as_micros();
    if cold.sum != EXPECT {
        eprintln!("SUM MISMATCH (cold)");
        unsafe {
            lemma_storage_h1_close(session);
        }
        std::process::exit(1);
    }

    for _ in 0..2 {
        match run_query(session, &c_table, &mut err, &mut scan_mode) {
            Ok(o) if o.sum == EXPECT => {}
            Ok(_) => {
                eprintln!("SUM MISMATCH (warmup)");
                unsafe {
                    lemma_storage_h1_close(session);
                }
                std::process::exit(1);
            }
            Err(e) => {
                eprintln!("lemma_storage_h1_query failed (warmup): {e}");
                unsafe {
                    lemma_storage_h1_close(session);
                }
                std::process::exit(1);
            }
        }
    }

    let mut times = [0u128; 5];
    let mut matched = cold.matched;
    let mut sum = cold.sum;
    let mode = cold.scan_mode.clone();
    for t in &mut times {
        let t0 = Instant::now();
        match run_query(session, &c_table, &mut err, &mut scan_mode) {
            Ok(o) => {
                matched = o.matched;
                sum = o.sum;
                *t = t0.elapsed().as_micros();
                if sum != EXPECT {
                    eprintln!("SUM MISMATCH (timed)");
                    unsafe {
                        lemma_storage_h1_close(session);
                    }
                    std::process::exit(1);
                }
            }
            Err(e) => {
                eprintln!("lemma_storage_h1_query failed (timed): {e}");
                unsafe {
                    lemma_storage_h1_close(session);
                }
                std::process::exit(1);
            }
        }
    }

    unsafe {
        lemma_storage_h1_close(session);
    }

    times.sort();
    let session_hot_us = times[2];
    // NOT GenDB-comparable; old harness mixed open into e2e headline.
    let e2e_cached_rerun_us = open_us + cold_query_us;

    println!("H1_LEMMA_STORAGE_OK");
    println!("ENGINE: lemma");
    println!("PATH: lemma_storage");
    println!("LAYOUT: datatable_scan");
    println!("SCAN_MODE: {mode}");
    println!("OPEN_US: {open_us}");
    println!("COLD_QUERY_US: {cold_query_us}");
    println!("SESSION_HOT_US: {session_hot_us}");
    println!("QUERY_US: {session_hot_us}");
    println!("E2E_CACHED_RERUN_US: {e2e_cached_rerun_us}");
    println!("MATCHED_ROWS: {matched}");
    println!("SUM: {sum}");
    println!("EXPECT: {EXPECT}");
}
