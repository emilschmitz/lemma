// Profiling tool for the cold stream path (plain Rust, not part of the product): where does the time of `SELECT f(col) FROM t` go versus DuckDB's own aggregate?
//   cold_profile <db> "<SET ...;SET ...>" "<label>=<sql>" ...
// Registered aggregates (INTEGER -> BIGINT): zc_noop (update does nothing), zc_touch (sums every cell, no branch), zc_cnt3 (branch-free count of cells == 3),
// zc_cnt3_scalar_state (same, but accumulates per vector in a local and adds once). Each SQL: first execution time and the median of 9, same connection.
// Build (prototype link, the python wheel's DuckDB 1.5.4 C API): see research_loop/scripts/zero_copy_oneshot.py::python_wheel_link.
use std::ffi::{c_char, c_void, CStr, CString};
use std::time::Instant;

#[repr(C)]
#[derive(Clone, Copy)]
struct DResult {
    a: u64,
    b: u64,
    c: u64,
    d: *mut c_void,
    e: *mut c_char,
    internal: *mut c_void,
}

#[link(name = "duckdb")]
extern "C" {
    fn duckdb_create_config(out: *mut *mut c_void) -> i32;
    fn duckdb_set_config(c: *mut c_void, n: *const c_char, o: *const c_char) -> i32;
    fn duckdb_open_ext(path: *const c_char, out: *mut *mut c_void, cfg: *mut c_void, err: *mut *mut c_char) -> i32;
    fn duckdb_connect(db: *mut c_void, out: *mut *mut c_void) -> i32;
    fn duckdb_query(con: *mut c_void, q: *const c_char, out: *mut DResult) -> i32;
    fn duckdb_result_error(r: *mut DResult) -> *const c_char;
    fn duckdb_destroy_result(r: *mut DResult);
    fn duckdb_value_varchar(r: *mut DResult, col: u64, row: u64) -> *mut c_char;
    fn duckdb_data_chunk_get_size(c: *mut c_void) -> u64;
    fn duckdb_data_chunk_get_vector(c: *mut c_void, col: u64) -> *mut c_void;
    fn duckdb_vector_get_data(v: *mut c_void) -> *mut c_void;
    fn duckdb_create_logical_type(t: u32) -> *mut c_void;
    fn duckdb_destroy_logical_type(t: *mut *mut c_void);
    fn duckdb_create_aggregate_function() -> *mut c_void;
    fn duckdb_aggregate_function_set_name(f: *mut c_void, n: *const c_char);
    fn duckdb_aggregate_function_add_parameter(f: *mut c_void, t: *mut c_void);
    fn duckdb_aggregate_function_set_return_type(f: *mut c_void, t: *mut c_void);
    fn duckdb_aggregate_function_set_functions(
        f: *mut c_void,
        size: extern "C" fn(*mut c_void) -> u64,
        init: extern "C" fn(*mut c_void, *mut c_void),
        update: extern "C" fn(*mut c_void, *mut c_void, *mut *mut c_void),
        combine: extern "C" fn(*mut c_void, *mut *mut c_void, *mut *mut c_void, u64),
        fin: extern "C" fn(*mut c_void, *mut *mut c_void, *mut c_void, u64, u64),
    );
    fn duckdb_register_aggregate_function(con: *mut c_void, f: *mut c_void) -> i32;
    fn duckdb_create_scalar_function() -> *mut c_void;
    fn duckdb_create_int32(v: i32) -> *mut c_void;
    fn duckdb_create_decimal_type(w: u8, s: u8) -> *mut c_void;
    fn duckdb_vector_reference_value(v: *mut c_void, val: *mut c_void);
    fn duckdb_scalar_function_set_special_handling(f: *mut c_void);
    fn duckdb_scalar_function_set_name(f: *mut c_void, n: *const c_char);
    fn duckdb_scalar_function_add_parameter(f: *mut c_void, t: *mut c_void);
    fn duckdb_scalar_function_set_return_type(f: *mut c_void, t: *mut c_void);
    fn duckdb_scalar_function_set_function(f: *mut c_void, func: extern "C" fn(*mut c_void, *mut c_void, *mut c_void));
    fn duckdb_register_scalar_function(con: *mut c_void, f: *mut c_void) -> i32;
}

extern "C" fn size(_i: *mut c_void) -> u64 {
    8
}
extern "C" fn init(_i: *mut c_void, s: *mut c_void) {
    unsafe { std::ptr::write_unaligned(s as *mut u64, 0) }
}
extern "C" fn combine(_i: *mut c_void, src: *mut *mut c_void, tgt: *mut *mut c_void, n: u64) {
    unsafe {
        for i in 0..n as usize {
            let a = std::ptr::read_unaligned(*src.add(i) as *const u64);
            let b = std::ptr::read_unaligned(*tgt.add(i) as *const u64);
            std::ptr::write_unaligned(*tgt.add(i) as *mut u64, a.wrapping_add(b));
        }
    }
}
extern "C" fn fin(_i: *mut c_void, src: *mut *mut c_void, res: *mut c_void, n: u64, off: u64) {
    unsafe {
        let d = duckdb_vector_get_data(res) as *mut i64;
        for i in 0..n as usize {
            *d.add(off as usize + i) = std::ptr::read_unaligned(*src.add(i) as *const u64) as i64;
        }
    }
}
extern "C" fn noop_update(_i: *mut c_void, _input: *mut c_void, _states: *mut *mut c_void) {}
unsafe fn cells<'a>(input: *mut c_void) -> &'a [i32] {
    let n = duckdb_data_chunk_get_size(input) as usize;
    let p = duckdb_vector_get_data(duckdb_data_chunk_get_vector(input, 0)) as *const i32;
    std::slice::from_raw_parts(p, n)
}
extern "C" fn touch_update(_i: *mut c_void, input: *mut c_void, states: *mut *mut c_void) {
    unsafe {
        let xs = cells(input);
        if xs.is_empty() { return; }
        let mut t = 0u64;
        for x in xs { t = t.wrapping_add(*x as u64); }
        let p = *states as *mut u64;
        std::ptr::write_unaligned(p, std::ptr::read_unaligned(p).wrapping_add(t));
    }
}
// + the glue's per-vector work, one at a time: the XOR check that all rows belong to one state, the fused branch-free cap check
extern "C" fn cnt3_s_update(_i: *mut c_void, input: *mut c_void, states: *mut *mut c_void) {
    unsafe {
        let xs = cells(input);
        if xs.is_empty() { return; }
        let mut diff = 0usize;
        for i in 1..xs.len() { diff |= (*states.add(i) as usize) ^ (*states as usize); }
        if diff != 0 { return; }
        let mut c = 0u64;
        for x in xs { c += (*x == 3) as u64; }
        let p = *states as *mut u64;
        std::ptr::write_unaligned(p, std::ptr::read_unaligned(p).wrapping_add(c));
    }
}
extern "C" fn cnt3_sc_update(_i: *mut c_void, input: *mut c_void, states: *mut *mut c_void) {
    unsafe {
        let xs = cells(input);
        if xs.is_empty() { return; }
        let mut diff = 0usize;
        for i in 1..xs.len() { diff |= (*states.add(i) as usize) ^ (*states as usize); }
        if diff != 0 { return; }
        let mut c = 0u64;
        let mut bad = 0u32;
        for x in xs { c += (*x == 3) as u64; bad += (*x < -65535) as u32 + (*x > 65535) as u32; }
        if bad != 0 { return; }
        let p = *states as *mut u64;
        std::ptr::write_unaligned(p, std::ptr::read_unaligned(p).wrapping_add(c));
    }
}
extern "C" fn cnt3_update(_i: *mut c_void, input: *mut c_void, states: *mut *mut c_void) {
    unsafe {
        let xs = cells(input);
        if xs.is_empty() { return; }
        let mut c = 0u64;
        for x in xs { c += (*x == 3) as u64; }
        let p = *states as *mut u64;
        std::ptr::write_unaligned(p, std::ptr::read_unaligned(p).wrapping_add(c));
    }
}

// Scalar-function route: DuckDB calls the function once per vector inside a projection; the fold accumulates into thread-local state and the function returns a constant
// column that a cheap builtin (MAX) consumes. The per-thread totals are merged after the query (here: a global atomic add at the end of each vector, only for the profile).
static TOTAL: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
extern "C" fn scalar_noop(_i: *mut c_void, input: *mut c_void, out: *mut c_void) {
    unsafe {
        let n = duckdb_data_chunk_get_size(input) as usize;
        let o = duckdb_vector_get_data(out) as *mut i32;
        std::ptr::write_bytes(o, 0, n);
    }
}
extern "C" fn scalar_cnt3(_i: *mut c_void, input: *mut c_void, out: *mut c_void) {
    unsafe {
        let xs = cells(input);
        let mut c = 0u64;
        for x in xs { c += (*x == 3) as u64; }
        TOTAL.fetch_add(c, std::sync::atomic::Ordering::Relaxed);
        let o = duckdb_vector_get_data(out) as *mut i32;
        std::ptr::write_bytes(o, 0, xs.len());
    }
}
static ZERO: std::sync::atomic::AtomicPtr<c_void> = std::sync::atomic::AtomicPtr::new(std::ptr::null_mut());
// the output is a CONSTANT vector (no per-row write): the consumer sees one value
extern "C" fn scalar_noop_ref(_i: *mut c_void, _input: *mut c_void, out: *mut c_void) {
    unsafe { duckdb_vector_reference_value(out, ZERO.load(std::sync::atomic::Ordering::Relaxed)); }
}
extern "C" fn scalar_cnt3_ref(_i: *mut c_void, input: *mut c_void, out: *mut c_void) {
    unsafe {
        let xs = cells(input);
        let mut c = 0u64;
        for x in xs { c += (*x == 3) as u64; }
        TOTAL.fetch_add(c, std::sync::atomic::Ordering::Relaxed);
        duckdb_vector_reference_value(out, ZERO.load(std::sync::atomic::Ordering::Relaxed));
    }
}
// two DECIMAL(15,2) columns (TPC-H lineitem l_extendedprice, l_quantity): sum price where qty < 24.00, branch-free
unsafe fn cells2<'a>(input: *mut c_void) -> (&'a [i64], &'a [i64]) {
    let n = duckdb_data_chunk_get_size(input) as usize;
    let a = duckdb_vector_get_data(duckdb_data_chunk_get_vector(input, 0)) as *const i64;
    let q = duckdb_vector_get_data(duckdb_data_chunk_get_vector(input, 1)) as *const i64;
    (std::slice::from_raw_parts(a, n), std::slice::from_raw_parts(q, n))
}
extern "C" fn s2_noop(_i: *mut c_void, _input: *mut c_void, out: *mut c_void) {
    unsafe { duckdb_vector_reference_value(out, ZERO.load(std::sync::atomic::Ordering::Relaxed)); }
}
extern "C" fn s2_fold(_i: *mut c_void, input: *mut c_void, out: *mut c_void) {
    unsafe {
        let (a, q) = cells2(input);
        let mut s = 0i128;
        let mut c = 0u64;
        for i in 0..a.len() {
            let hit = q[i] < 2400;
            s += (a[i] & -(hit as i64)) as i128;
            c += hit as u64;
        }
        TOTAL.fetch_add(s as u64 ^ c, std::sync::atomic::Ordering::Relaxed);
        duckdb_vector_reference_value(out, ZERO.load(std::sync::atomic::Ordering::Relaxed));
    }
}
extern "C" fn s2_fold_i64(_i: *mut c_void, input: *mut c_void, out: *mut c_void) {
    unsafe {
        let (a, q) = cells2(input);
        let mut s = 0i64;
        let mut c = 0u64;
        for i in 0..a.len() {
            let hit = q[i] < 2400;
            s += a[i] & -(hit as i64);
            c += hit as u64;
        }
        TOTAL.fetch_add(s as u64 ^ c, std::sync::atomic::Ordering::Relaxed);
        duckdb_vector_reference_value(out, ZERO.load(std::sync::atomic::Ordering::Relaxed));
    }
}
fn reg_scalar2(con: *mut c_void, name: &str, f: extern "C" fn(*mut c_void, *mut c_void, *mut c_void)) {
    unsafe {
        let s = duckdb_create_scalar_function();
        duckdb_scalar_function_set_name(s, CString::new(name).unwrap().as_ptr());
        for _ in 0..2 {
            let mut t = duckdb_create_decimal_type(15, 2);
            duckdb_scalar_function_add_parameter(s, t);
            duckdb_destroy_logical_type(&mut t);
        }
        let mut r = duckdb_create_logical_type(4);
        duckdb_scalar_function_set_return_type(s, r);
        duckdb_destroy_logical_type(&mut r);
        duckdb_scalar_function_set_function(s, f);
        assert!(duckdb_register_scalar_function(con, s) == 0);
    }
}
fn reg_scalar(con: *mut c_void, name: &str, f: extern "C" fn(*mut c_void, *mut c_void, *mut c_void)) {
    unsafe {
        let s = duckdb_create_scalar_function();
        duckdb_scalar_function_set_name(s, CString::new(name).unwrap().as_ptr());
        let mut t = duckdb_create_logical_type(4);
        duckdb_scalar_function_add_parameter(s, t);
        duckdb_destroy_logical_type(&mut t);
        let mut r = duckdb_create_logical_type(4);
        duckdb_scalar_function_set_return_type(s, r);
        duckdb_destroy_logical_type(&mut r);
        duckdb_scalar_function_set_function(s, f);
        assert!(duckdb_register_scalar_function(con, s) == 0);
    }
}

fn q(con: *mut c_void, sql: &str) -> String {
    unsafe {
        let mut r: DResult = std::mem::zeroed();
        let s = CString::new(sql).unwrap();
        assert!(duckdb_query(con, s.as_ptr(), &mut r) == 0, "{}: {:?}", sql, CStr::from_ptr(duckdb_result_error(&mut r)));
        let p = duckdb_value_varchar(&mut r, 0, 0);
        let out = if p.is_null() { "NULL".into() } else { CStr::from_ptr(p).to_string_lossy().into_owned() };
        duckdb_destroy_result(&mut r);
        out
    }
}

fn reg(con: *mut c_void, name: &str, update: extern "C" fn(*mut c_void, *mut c_void, *mut *mut c_void)) {
    unsafe {
        let f = duckdb_create_aggregate_function();
        duckdb_aggregate_function_set_name(f, CString::new(name).unwrap().as_ptr());
        let mut t = duckdb_create_logical_type(4);
        duckdb_aggregate_function_add_parameter(f, t);
        duckdb_destroy_logical_type(&mut t);
        let mut r = duckdb_create_logical_type(5);
        duckdb_aggregate_function_set_return_type(f, r);
        duckdb_destroy_logical_type(&mut r);
        duckdb_aggregate_function_set_functions(f, size, init, update, combine, fin);
        assert!(duckdb_register_aggregate_function(con, f) == 0);
    }
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    unsafe {
        let mut cfg = std::ptr::null_mut();
        duckdb_create_config(&mut cfg);
        duckdb_set_config(cfg, CString::new("access_mode").unwrap().as_ptr(), CString::new("READ_ONLY").unwrap().as_ptr());
        let (mut db, mut con) = (std::ptr::null_mut(), std::ptr::null_mut());
        let mut err = std::ptr::null_mut();
        assert!(duckdb_open_ext(CString::new(a[1].as_str()).unwrap().as_ptr(), &mut db, cfg, &mut err) == 0);
        duckdb_connect(db, &mut con);
        for s in a[2].split(';').filter(|s| !s.trim().is_empty()) {
            q(con, s);
        }
        reg(con, "zc_noop", noop_update);
        reg(con, "zc_touch", touch_update);
        reg(con, "zc_cnt3", cnt3_update);
        ZERO.store(duckdb_create_int32(0), std::sync::atomic::Ordering::Relaxed);
        reg_scalar2(con, "z2_noop", s2_noop);
        reg_scalar2(con, "z2_fold", s2_fold);
        reg_scalar2(con, "z2_fold64", s2_fold_i64);
        reg_scalar(con, "zs_noop", scalar_noop);
        reg_scalar(con, "zs_noop_ref", scalar_noop_ref);
        reg_scalar(con, "zs_cnt3_ref", scalar_cnt3_ref);
        reg_scalar(con, "zs_cnt3", scalar_cnt3);
        reg(con, "zc_cnt3_s", cnt3_s_update);
        reg(con, "zc_cnt3_sc", cnt3_sc_update);
        // interleaved: round r runs every query once, so slow drift hits all of them alike
        let specs: Vec<(&str, &str)> = a[3..].iter().map(|x| x.split_once('=').unwrap()).collect();
        let mut times: Vec<Vec<u128>> = vec![vec![]; specs.len()];
        let mut firsts = vec![0u128; specs.len()];
        let mut results = vec![String::new(); specs.len()];
        for (i, (_l, sql)) in specs.iter().enumerate() {
            let t = Instant::now();
            results[i] = q(con, sql);
            firsts[i] = t.elapsed().as_micros();
            q(con, sql);
        }
        for _ in 0..11 {
            for (i, (_l, sql)) in specs.iter().enumerate() {
                let t = Instant::now();
                q(con, sql);
                times[i].push(t.elapsed().as_micros());
            }
        }
        for (i, (label, _)) in specs.iter().enumerate() {
            let mut ts = times[i].clone();
            ts.sort();
            println!("{:44} first {:>8} us  median {:>8} us  min {:>8} us  result {}", label, firsts[i], ts[5], ts[0], results[i]);
        }
    }
}
