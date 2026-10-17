// LEMMA_ZERO_COPY host reader: the C-API calls the generated `main` makes to pin DuckDB result chunks. Plain Rust, outside `verus!`:
// this is the trusted bridge (docs: research_loop/menus/zero_copy_lease_PROPOSAL.md). Nothing here is verified.
mod zc_duck {
    use std::ffi::{c_char, c_void, CStr, CString};

    #[repr(C)]
    #[derive(Clone, Copy)]
    pub struct DResult {
        a: u64,
        b: u64,
        c: u64,
        d: *mut c_void,
        e: *mut c_char,
        internal: *mut c_void,
    }

    #[link(name = "duckdb")]
    extern "C" {
        fn duckdb_library_version() -> *const c_char;
        fn duckdb_create_config(out: *mut *mut c_void) -> i32;
        fn duckdb_set_config(c: *mut c_void, n: *const c_char, o: *const c_char) -> i32;
        fn duckdb_open_ext(path: *const c_char, out: *mut *mut c_void, cfg: *mut c_void, err: *mut *mut c_char) -> i32;
        fn duckdb_connect(db: *mut c_void, out: *mut *mut c_void) -> i32;
        fn duckdb_query(con: *mut c_void, q: *const c_char, out: *mut DResult) -> i32;
        fn duckdb_result_error(r: *mut DResult) -> *const c_char;
        fn duckdb_column_count(r: *mut DResult) -> u64;
        fn duckdb_column_type(r: *mut DResult, col: u64) -> u32;
        fn duckdb_column_logical_type(r: *mut DResult, col: u64) -> *mut c_void;
        fn duckdb_decimal_internal_type(t: *mut c_void) -> u32;
        fn duckdb_decimal_width(t: *mut c_void) -> u8;
        fn duckdb_decimal_scale(t: *mut c_void) -> u8;
        fn duckdb_destroy_logical_type(t: *mut *mut c_void);
        fn duckdb_result_chunk_count(r: DResult) -> u64;
        fn duckdb_result_get_chunk(r: DResult, i: u64) -> *mut c_void;
        fn duckdb_data_chunk_get_size(c: *mut c_void) -> u64;
        fn duckdb_data_chunk_get_vector(c: *mut c_void, col: u64) -> *mut c_void;
        fn duckdb_vector_get_data(v: *mut c_void) -> *mut c_void;
        fn duckdb_vector_get_validity(v: *mut c_void) -> *mut u64;
        fn duckdb_destroy_data_chunk(c: *mut *mut c_void);
        fn duckdb_destroy_result(r: *mut DResult);
        fn duckdb_value_int64(r: *mut DResult, col: u64, row: u64) -> i64;
    }

    pub struct Db {
        db: *mut c_void,
        pub con: *mut c_void,
    }

    /// ZC-1 was validated against these library versions only (`duckdb_result_get_chunk` is a deprecated API whose chunk ownership is version dependent).
    const TESTED_VERSIONS: &[&str] = &["v1.5.6"];

    pub fn open(path: &str, read_only: bool) -> Db {
        unsafe {
            let version = CStr::from_ptr(duckdb_library_version()).to_str().unwrap();
            assert!(TESTED_VERSIONS.contains(&version), "zero-copy: linked DuckDB is {}, ZC-1 was validated on {:?} only", version, TESTED_VERSIONS);
            let mut cfg: *mut c_void = std::ptr::null_mut();
            assert!(duckdb_create_config(&mut cfg) == 0);
            if read_only {
                let (n, o) = (CString::new("access_mode").unwrap(), CString::new("READ_ONLY").unwrap());
                assert!(duckdb_set_config(cfg, n.as_ptr(), o.as_ptr()) == 0);
            }
            let (mut db, mut con): (*mut c_void, *mut c_void) = (std::ptr::null_mut(), std::ptr::null_mut());
            let mut err: *mut c_char = std::ptr::null_mut();
            let p = CString::new(path).unwrap();
            assert!(duckdb_open_ext(p.as_ptr(), &mut db, cfg, &mut err) == 0, "open {}: {:?}", path, if err.is_null() { None } else { Some(CStr::from_ptr(err)) });
            assert!(duckdb_connect(db, &mut con) == 0);
            Db { db, con }
        }
    }

    pub fn exec(db: &Db, sql: &str) {
        unsafe {
            let mut r: DResult = std::mem::zeroed();
            let q = CString::new(sql).unwrap();
            let st = duckdb_query(db.con, q.as_ptr(), &mut r);
            assert!(st == 0, "{}: {:?}", sql, CStr::from_ptr(duckdb_result_error(&mut r)));
            duckdb_destroy_result(&mut r);
        }
    }

    /// `SELECT COUNT(*) FROM "table"` answered by the engine itself (an independent row count for the pin).
    pub fn count(db: &Db, table: &str) -> usize {
        unsafe {
            let mut r: DResult = std::mem::zeroed();
            let q = CString::new(format!("SELECT COUNT(*) FROM \"{}\"", table.replace('"', "\"\""))).unwrap();
            assert!(duckdb_query(db.con, q.as_ptr(), &mut r) == 0);
            let n = duckdb_value_int64(&mut r, 0, 0);
            duckdb_destroy_result(&mut r);
            n as usize
        }
    }

    /// One pinned column of a result: each chunk's data pointer and row count (the chunk handles stay alive in `Pin`).
    pub struct PinCol {
        pub ptrs: Vec<(*const u8, usize)>,
        pub elem_bytes: usize,
        /// duckdb_type id of the column; for DECIMAL (19) also its declared precision and scale.
        pub type_id: u32,
        pub dec_width: u8,
        pub dec_scale: u8,
    }

    /// A materialized `SELECT cols FROM table`: the result and its data chunks are retained until `Pin` is dropped.
    pub struct Pin {
        result: DResult,
        chunks: Vec<*mut c_void>,
        pub cols: Vec<PinCol>,
        pub rows: usize,
    }

    /// Storage width in bytes of a signed-integer-like duckdb type (TINYINT 2, SMALLINT 3, INTEGER 4, BIGINT 5, DATE 13, HUGEINT 16),
    /// or of a DECIMAL's internal type. Anything else (strings, floats, unsigned, ...) is refused.
    fn int_width(t: u32) -> usize {
        match t {
            2 => 1,
            3 => 2,
            4 | 13 => 4,
            5 => 8,
            16 => 16,
            other => panic!("zero-copy: duckdb type id {} is not a fixed-width signed integer column", other),
        }
    }

    /// Pin `sql` (one fixed-width signed integer / DECIMAL / DATE column per selected expression, no NULLs).
    /// `Pin::cols[c].ptrs` holds each chunk's native buffer. Aborts loudly if a vector carries NULLs.
    pub fn pin(db: &Db, sql: &str) -> Pin {
        unsafe {
            let mut r: DResult = std::mem::zeroed();
            let q = CString::new(sql).unwrap();
            let st = duckdb_query(db.con, q.as_ptr(), &mut r);
            assert!(st == 0, "{}: {:?}", sql, CStr::from_ptr(duckdb_result_error(&mut r)));
            let ncols = duckdb_column_count(&mut r) as usize;
            let mut widths = Vec::new();
            for c in 0..ncols {
                let t = duckdb_column_type(&mut r, c as u64);
                if t == 19 {
                    let mut lt = duckdb_column_logical_type(&mut r, c as u64);
                    widths.push((int_width(duckdb_decimal_internal_type(lt)), t, duckdb_decimal_width(lt), duckdb_decimal_scale(lt)));
                    duckdb_destroy_logical_type(&mut lt);
                } else {
                    widths.push((int_width(t), t, 0, 0));
                }
            }
            let nchunks = duckdb_result_chunk_count(r) as usize;
            let mut chunks = Vec::with_capacity(nchunks);
            let mut cols: Vec<PinCol> = widths.iter().map(|w| PinCol { ptrs: Vec::with_capacity(nchunks), elem_bytes: w.0, type_id: w.1, dec_width: w.2, dec_scale: w.3 }).collect();
            let mut rows = 0usize;
            for k in 0..nchunks {
                let ch = duckdb_result_get_chunk(r, k as u64);
                assert!(!ch.is_null());
                let len = duckdb_data_chunk_get_size(ch) as usize;
                for (c, col) in cols.iter_mut().enumerate() {
                    let v = duckdb_data_chunk_get_vector(ch, c as u64);
                    let validity = duckdb_vector_get_validity(v);
                    if !validity.is_null() {
                        for w in 0..len / 64 {
                            assert!(*validity.add(w) == u64::MAX, "zero-copy: column {} has NULLs", c);
                        }
                        if len % 64 != 0 {
                            let mask = (1u64 << (len % 64)) - 1;
                            assert!(*validity.add(len / 64) & mask == mask, "zero-copy: column {} has NULLs", c);
                        }
                    }
                    col.ptrs.push((duckdb_vector_get_data(v) as *const u8, len));
                }
                chunks.push(ch);
                rows += len;
            }
            Pin { result: r, chunks, cols, rows }
        }
    }

    impl Pin {
        /// The declared type of column `c` must be exactly `type_id` (and, for DECIMAL, `width`/`scale`): the storage width alone
        /// is not enough (DECIMAL(38,2) and DECIMAL(38,4) share it, as do INTEGER and DATE).
        pub fn expect_type(&self, c: usize, name: &str, type_id: u32, width: u8, scale: u8) {
            let col = &self.cols[c];
            assert!(
                col.type_id == type_id && col.dec_width == width && col.dec_scale == scale,
                "zero-copy: column {} is stored as duckdb type {} (decimal width {}, scale {}) but the spec declares type {} (decimal width {}, scale {})",
                name, col.type_id, col.dec_width, col.dec_scale, type_id, width, scale
            );
        }
    }

    impl Drop for Pin {
        fn drop(&mut self) {
            unsafe {
                for ch in self.chunks.iter_mut() {
                    duckdb_destroy_data_chunk(ch);
                }
                duckdb_destroy_result(&mut self.result);
            }
        }
    }
}
