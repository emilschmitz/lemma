//! Single-pass streaming scan over DuckDB vector chunks (no retain-all materialize).
//!
//! Lemma executes on chunk buffers as they arrive; DuckDB supplies layout only.

#![cfg(feature = "duckdb_pin")]

use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_void};
use std::ptr;

use crate::duckdb_pin::{DuckDb, PinError};
use crate::zone_map::may_satisfy_range_u32;

type DuckDBType = u32;
const DUCKDB_TYPE_INTEGER: DuckDBType = 4;
const DUCKDB_TYPE_BIGINT: DuckDBType = 5;
const DUCKDB_TYPE_UINTEGER: DuckDBType = 16;
const DUCKDB_TYPE_UBIGINT: DuckDBType = 17;

const LEMMA_STREAM_INVALID: i64 = -1;

extern "C" {
    fn lemma_stream_start(
        conn: *mut c_void,
        table: *const c_char,
        columns: *const *const c_char,
        n_columns: usize,
        error_out: *mut c_char,
        error_len: usize,
    ) -> i64;
    fn lemma_stream_start_pushdown(
        conn: *mut c_void,
        table: *const c_char,
        amount_column: *const c_char,
        date_column: *const c_char,
        date_lo: i64,
        date_hi: i64,
        error_out: *mut c_char,
        error_len: usize,
    ) -> i64;
    fn lemma_stream_h1_sum_optimized(
        conn: *mut c_void,
        matched_out: *mut u64,
        sum_out: *mut u64,
        error_out: *mut c_char,
        error_len: usize,
    ) -> i32;
    fn lemma_stream_h1_sum_lemma_filter(
        conn: *mut c_void,
        matched_out: *mut u64,
        sum_out: *mut u64,
        error_out: *mut c_char,
        error_len: usize,
    ) -> i32;
    fn lemma_stream_fetch_next(stream: i64) -> i32;
    fn lemma_stream_chunk_len(stream: i64) -> u64;
    fn lemma_stream_column_count(stream: i64) -> u64;
    fn lemma_stream_column_name(stream: i64, col: u64) -> *const c_char;
    fn lemma_stream_vector_data(stream: i64, col: u64) -> *mut c_void;
    fn lemma_stream_vector_type(stream: i64, col: u64) -> DuckDBType;
    fn lemma_stream_close(stream: i64);
}

pub struct DuckStream {
    stream_id: i64,
    date_col: usize,
    amount_col: usize,
    pushdown: bool,
}

impl DuckStream {
    pub fn open(db: &DuckDb, table: &str, columns: &[&str]) -> Result<Self, PinError> {
        let c_table = CString::new(table).map_err(|e| PinError::Pin(e.to_string()))?;
        let c_cols: Vec<CString> = columns
            .iter()
            .map(|c| CString::new(*c))
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| PinError::Pin(e.to_string()))?;
        let col_ptrs: Vec<*const c_char> = c_cols.iter().map(|c| c.as_ptr()).collect();

        let mut err_buf = vec![0i8; 512];
        let stream_id = unsafe {
            lemma_stream_start(
                db.connection_ptr(),
                c_table.as_ptr(),
                if col_ptrs.is_empty() {
                    ptr::null()
                } else {
                    col_ptrs.as_ptr()
                },
                col_ptrs.len(),
                err_buf.as_mut_ptr(),
                err_buf.len(),
            )
        };
        if stream_id == LEMMA_STREAM_INVALID {
            let msg = unsafe { CStr::from_ptr(err_buf.as_ptr()) }
                .to_string_lossy()
                .into_owned();
            return Err(PinError::Pin(msg));
        }

        let date_col = resolve_column(stream_id, "event_date")?;
        let amount_col = resolve_column(stream_id, "amount")?;
        Ok(Self {
            stream_id,
            date_col,
            amount_col,
            pushdown: false,
        })
    }

    /// Predicate pushdown at scan: project `amount_col` only; DuckDB filters on `date_col`.
    pub fn open_range(
        db: &DuckDb,
        table: &str,
        amount_col: &str,
        date_col: &str,
        lo: u32,
        hi: u32,
    ) -> Result<Self, PinError> {
        let c_table = CString::new(table).map_err(|e| PinError::Pin(e.to_string()))?;
        let c_amount = CString::new(amount_col).map_err(|e| PinError::Pin(e.to_string()))?;
        let c_date = CString::new(date_col).map_err(|e| PinError::Pin(e.to_string()))?;
        let mut err_buf = vec![0i8; 512];
        let stream_id = unsafe {
            lemma_stream_start_pushdown(
                db.connection_ptr(),
                c_table.as_ptr(),
                c_amount.as_ptr(),
                c_date.as_ptr(),
                lo as i64,
                hi as i64,
                err_buf.as_mut_ptr(),
                err_buf.len(),
            )
        };
        if stream_id == LEMMA_STREAM_INVALID {
            let msg = unsafe { CStr::from_ptr(err_buf.as_ptr()) }
                .to_string_lossy()
                .into_owned();
            return Err(PinError::Pin(msg));
        }
        Ok(Self {
            stream_id,
            date_col: 0,
            amount_col: 0,
            pushdown: true,
        })
    }

    /// Chunk-path H1 default: stream raw columns; Lemma zone-prune + filter + sum in C++.
    pub fn h1_sum_lemma_filter(db: &DuckDb) -> Result<(u64, u64), PinError> {
        let mut matched = 0u64;
        let mut sum = 0u64;
        let mut err_buf = vec![0i8; 512];
        let rc = unsafe {
            lemma_stream_h1_sum_lemma_filter(
                db.connection_ptr(),
                &mut matched,
                &mut sum,
                err_buf.as_mut_ptr(),
                err_buf.len(),
            )
        };
        if rc != 0 {
            let msg = unsafe { CStr::from_ptr(err_buf.as_ptr()) }
                .to_string_lossy()
                .into_owned();
            return Err(PinError::Pin(msg));
        }
        Ok((matched, sum))
    }

    /// Legacy: SQL WHERE pushdown + amount sum (DuckDB filters; not chunk default).
    pub fn h1_sum_optimized(db: &DuckDb) -> Result<(u64, u64), PinError> {
        let mut matched = 0u64;
        let mut sum = 0u64;
        let mut err_buf = vec![0i8; 512];
        let rc = unsafe {
            lemma_stream_h1_sum_optimized(
                db.connection_ptr(),
                &mut matched,
                &mut sum,
                err_buf.as_mut_ptr(),
                err_buf.len(),
            )
        };
        if rc != 0 {
            let msg = unsafe { CStr::from_ptr(err_buf.as_ptr()) }
                .to_string_lossy()
                .into_owned();
            return Err(PinError::Pin(msg));
        }
        Ok((matched, sum))
    }

    /// Sum pre-filtered amount column after [`Self::open_range`] (one column per chunk).
    pub fn sum_amounts_only(&mut self) -> Result<(u64, u64), PinError> {
        if !self.pushdown {
            return Err(PinError::Pin(
                "sum_amounts_only requires open_range pushdown stream".into(),
            ));
        }
        let mut matched = 0u64;
        let mut sum = 0u64;
        loop {
            let rc = unsafe { lemma_stream_fetch_next(self.stream_id) };
            if rc < 0 {
                return Err(PinError::Pin("lemma_stream_fetch_next failed".into()));
            }
            if rc == 0 {
                break;
            }
            let n = unsafe { lemma_stream_chunk_len(self.stream_id) as usize };
            if n == 0 {
                continue;
            }
            matched += n as u64;
            sum = sum.wrapping_add(chunk_sum_amounts(self.stream_id, 0, n)?);
        }
        Ok((matched, sum))
    }

    /// Ingest all rows from a two-column stream into owned `u32` dates + `u64` amounts.
    pub fn ingest_u32_dates_u64_amounts(&mut self) -> Result<(Vec<u32>, Vec<u64>), PinError> {
        let mut dates = Vec::new();
        let mut amounts = Vec::new();
        loop {
            let rc = unsafe { lemma_stream_fetch_next(self.stream_id) };
            if rc < 0 {
                return Err(PinError::Pin("lemma_stream_fetch_next failed".into()));
            }
            if rc == 0 {
                break;
            }
            let n = unsafe { lemma_stream_chunk_len(self.stream_id) as usize };
            if n == 0 {
                continue;
            }
            append_chunk_u32_u64(self.stream_id, self.date_col, self.amount_col, n, &mut dates, &mut amounts)?;
        }
        Ok((dates, amounts))
    }

    /// Legacy two-column scan + Rust-side filter (prefer [`Self::h1_sum_optimized`]).
    pub fn stream_h1_sum_filtered(&mut self, lo: u32, hi: u32) -> Result<(u64, u64), PinError> {
        let mut matched = 0u64;
        let mut sum = 0u64;
        loop {
            let rc = unsafe { lemma_stream_fetch_next(self.stream_id) };
            if rc < 0 {
                return Err(PinError::Pin("lemma_stream_fetch_next failed".into()));
            }
            if rc == 0 {
                break;
            }
            let n = unsafe { lemma_stream_chunk_len(self.stream_id) as usize };
            if n == 0 {
                continue;
            }
            if chunk_may_satisfy(self.stream_id, self.date_col, lo, hi, n)? {
                let (m, s) = chunk_sum_filtered(self.stream_id, self.date_col, self.amount_col, lo, hi, n)?;
                matched += m;
                sum = sum.wrapping_add(s);
            }
        }
        Ok((matched, sum))
    }
}

impl Drop for DuckStream {
    fn drop(&mut self) {
        unsafe { lemma_stream_close(self.stream_id) };
    }
}

fn resolve_column(stream_id: i64, column: &str) -> Result<usize, PinError> {
    let ncol = unsafe { lemma_stream_column_count(stream_id) as usize };
    for c in 0..ncol {
        let name = unsafe {
            let p = lemma_stream_column_name(stream_id, c as u64);
            if p.is_null() {
                continue;
            }
            CStr::from_ptr(p).to_string_lossy().into_owned()
        };
        if name.eq_ignore_ascii_case(column) {
            return Ok(c);
        }
    }
    Err(PinError::ColumnNotFound(column.to_string()))
}

fn chunk_may_satisfy(
    stream_id: i64,
    date_col: usize,
    lo: u32,
    hi: u32,
    n: usize,
) -> Result<bool, PinError> {
    let date_ty = unsafe { lemma_stream_vector_type(stream_id, date_col as u64) };
    let date_ptr = unsafe { lemma_stream_vector_data(stream_id, date_col as u64) };
    if date_ptr.is_null() {
        return Err(PinError::ColumnNotFound("date vector".into()));
    }
    let (min, max) = min_max_dates(date_ptr, date_ty, n)?;
    Ok(may_satisfy_range_u32(
        &crate::zone_map::ZoneSegmentU32 {
            min,
            max,
            start: 0,
            end: n,
        },
        lo,
        hi,
    ))
}

fn min_max_dates(date_ptr: *mut c_void, date_ty: DuckDBType, n: usize) -> Result<(u32, u32), PinError> {
    match date_ty {
        DUCKDB_TYPE_INTEGER | DUCKDB_TYPE_UINTEGER => {
            let slice = unsafe { std::slice::from_raw_parts(date_ptr as *const i32, n) };
            let min = *slice.iter().min().unwrap_or(&0) as u32;
            let max = *slice.iter().max().unwrap_or(&0) as u32;
            Ok((min, max))
        }
        DUCKDB_TYPE_BIGINT | DUCKDB_TYPE_UBIGINT => {
            let slice = unsafe { std::slice::from_raw_parts(date_ptr as *const i64, n) };
            let min = *slice.iter().min().unwrap_or(&0) as u32;
            let max = *slice.iter().max().unwrap_or(&0) as u32;
            Ok((min, max))
        }
        _ => Err(PinError::UnsupportedType(format!(
            "stream date col type {date_ty}"
        ))),
    }
}

fn chunk_sum_amounts(stream_id: i64, amount_col: usize, n: usize) -> Result<u64, PinError> {
    let amount_ty = unsafe { lemma_stream_vector_type(stream_id, amount_col as u64) };
    let amount_ptr = unsafe { lemma_stream_vector_data(stream_id, amount_col as u64) };
    if amount_ptr.is_null() {
        return Err(PinError::ColumnNotFound("amount vector".into()));
    }

    let mut sum = 0u64;
    match amount_ty {
        DUCKDB_TYPE_BIGINT | DUCKDB_TYPE_UBIGINT => {
            let p = amount_ptr as *const i64;
            let end = unsafe { p.add(n) };
            let mut cur = p;
            while cur < end {
                sum = sum.wrapping_add(unsafe { *cur } as u64);
                cur = unsafe { cur.add(1) };
            }
        }
        DUCKDB_TYPE_INTEGER | DUCKDB_TYPE_UINTEGER => {
            let p = amount_ptr as *const i32;
            let end = unsafe { p.add(n) };
            let mut cur = p;
            while cur < end {
                sum = sum.wrapping_add(unsafe { *cur } as u64);
                cur = unsafe { cur.add(1) };
            }
        }
        _ => {
            return Err(PinError::UnsupportedType(format!(
                "amount col type {amount_ty}"
            )));
        }
    }
    Ok(sum)
}

fn append_chunk_u32_u64(
    stream_id: i64,
    date_col: usize,
    amount_col: usize,
    n: usize,
    dates: &mut Vec<u32>,
    amounts: &mut Vec<u64>,
) -> Result<(), PinError> {
    let date_ty = unsafe { lemma_stream_vector_type(stream_id, date_col as u64) };
    let amount_ty = unsafe { lemma_stream_vector_type(stream_id, amount_col as u64) };
    let date_ptr = unsafe { lemma_stream_vector_data(stream_id, date_col as u64) };
    let amount_ptr = unsafe { lemma_stream_vector_data(stream_id, amount_col as u64) };
    if date_ptr.is_null() || amount_ptr.is_null() {
        return Err(PinError::ColumnNotFound("chunk vectors".into()));
    }

    dates.reserve(n);
    amounts.reserve(n);

    macro_rules! append {
        ($d:ty, $a:ty) => {{
            let dslice = unsafe { std::slice::from_raw_parts(date_ptr as *const $d, n) };
            let aslice = unsafe { std::slice::from_raw_parts(amount_ptr as *const $a, n) };
            for i in 0..n {
                dates.push(dslice[i] as u32);
                amounts.push(aslice[i] as u64);
            }
        }};
    }

    match (date_ty, amount_ty) {
        (DUCKDB_TYPE_BIGINT | DUCKDB_TYPE_UBIGINT, DUCKDB_TYPE_BIGINT | DUCKDB_TYPE_UBIGINT) => {
            append!(i64, i64)
        }
        (DUCKDB_TYPE_BIGINT | DUCKDB_TYPE_UBIGINT, DUCKDB_TYPE_INTEGER | DUCKDB_TYPE_UINTEGER) => {
            append!(i64, i32)
        }
        (DUCKDB_TYPE_INTEGER | DUCKDB_TYPE_UINTEGER, DUCKDB_TYPE_BIGINT | DUCKDB_TYPE_UBIGINT) => {
            append!(i32, i64)
        }
        (DUCKDB_TYPE_INTEGER | DUCKDB_TYPE_UINTEGER, DUCKDB_TYPE_INTEGER | DUCKDB_TYPE_UINTEGER) => {
            append!(i32, i32)
        }
        _ => {
            return Err(PinError::UnsupportedType(format!(
                "date_ty={date_ty} amount_ty={amount_ty}"
            )));
        }
    }
    Ok(())
}

fn chunk_sum_filtered(
    stream_id: i64,
    date_col: usize,
    amount_col: usize,
    lo: u32,
    hi: u32,
    n: usize,
) -> Result<(u64, u64), PinError> {
    let lo64 = lo as i64;
    let hi64 = hi as i64;
    let date_ty = unsafe { lemma_stream_vector_type(stream_id, date_col as u64) };
    let amount_ty = unsafe { lemma_stream_vector_type(stream_id, amount_col as u64) };
    let date_ptr = unsafe { lemma_stream_vector_data(stream_id, date_col as u64) };
    let amount_ptr = unsafe { lemma_stream_vector_data(stream_id, amount_col as u64) };
    if date_ptr.is_null() || amount_ptr.is_null() {
        return Err(PinError::ColumnNotFound("chunk vectors".into()));
    }

    let mut sum = 0u64;
    let mut matched = 0u64;

    macro_rules! scan {
        ($d:ty, $a:ty) => {{
            let dates = unsafe { std::slice::from_raw_parts(date_ptr as *const $d, n) };
            let amounts = unsafe { std::slice::from_raw_parts(amount_ptr as *const $a, n) };
            for i in 0..n {
                let d = dates[i] as i64;
                if d >= lo64 && d <= hi64 {
                    sum = sum.wrapping_add(amounts[i] as u64);
                    matched += 1;
                }
            }
        }};
    }

    match (date_ty, amount_ty) {
        (DUCKDB_TYPE_BIGINT | DUCKDB_TYPE_UBIGINT, DUCKDB_TYPE_BIGINT | DUCKDB_TYPE_UBIGINT) => {
            scan!(i64, i64)
        }
        (DUCKDB_TYPE_BIGINT | DUCKDB_TYPE_UBIGINT, DUCKDB_TYPE_INTEGER | DUCKDB_TYPE_UINTEGER) => {
            scan!(i64, i32)
        }
        (DUCKDB_TYPE_INTEGER | DUCKDB_TYPE_UINTEGER, DUCKDB_TYPE_BIGINT | DUCKDB_TYPE_UBIGINT) => {
            scan!(i32, i64)
        }
        (DUCKDB_TYPE_INTEGER | DUCKDB_TYPE_UINTEGER, DUCKDB_TYPE_INTEGER | DUCKDB_TYPE_UINTEGER) => {
            scan!(i32, i32)
        }
        _ => {
            return Err(PinError::UnsupportedType(format!(
                "date_ty={date_ty} amount_ty={amount_ty}"
            )));
        }
    }
    Ok((matched, sum))
}
