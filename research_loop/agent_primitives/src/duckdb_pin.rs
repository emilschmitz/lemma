//! Zero-copy **pin/lease** so **Lemma** can execute on DuckDB `SELECT` result chunk
//! buffers (TRUSTED layout host). DuckDB is not the query engine on this path.
//!
//! Links prebuilt `libduckdb.so` + `lemma_pin_ffi` (no bundled DuckDB compile).
//! Writers must not mutate the pinned table until [`DuckTablePin::unpin`].

#![cfg(feature = "duckdb_pin")]

use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_void};
use std::ptr;

use crate::duckdb_export::checksum_u64;
use crate::zone_map::{may_satisfy_range_u32, ZoneSegmentU32};

/// Sub-zones within pinned DuckDB chunks (same row budget as holdout `ZONE_ROWS`).
pub const PIN_ZONE_ROWS: usize = 8192;

/// Min/max over a date sub-slice inside one chunk; row indices are chunk-local.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PinZoneSegmentU32 {
    pub chunk_index: usize,
    pub min: u32,
    pub max: u32,
    pub start: usize,
    pub end: usize,
}

impl PinZoneSegmentU32 {
    #[inline]
    pub fn may_satisfy(&self, lo: u32, hi: u32) -> bool {
        may_satisfy_range_u32(
            &ZoneSegmentU32 {
                min: self.min,
                max: self.max,
                start: self.start,
                end: self.end,
            },
            lo,
            hi,
        )
    }
}

// Minimal DuckDB C API (from prebuilt duckdb.h) — avoid libduckdb-sys bundled build.
type DuckDBState = u32;
const DUCKDB_SUCCESS: DuckDBState = 0;
type DuckDBType = u32;
const DUCKDB_TYPE_INTEGER: DuckDBType = 4;
const DUCKDB_TYPE_BIGINT: DuckDBType = 5;
const DUCKDB_TYPE_UINTEGER: DuckDBType = 16;
const DUCKDB_TYPE_UBIGINT: DuckDBType = 17;
const DUCKDB_TYPE_HUGEINT: DuckDBType = 14;
const DUCKDB_TYPE_UHUGEINT: DuckDBType = 32;

#[repr(C)]
struct DuckDBDatabase {
    _private: [u8; 0],
}
#[repr(C)]
struct DuckDBConnection {
    _private: [u8; 0],
}
type DuckDBDatabasePtr = *mut DuckDBDatabase;
type DuckDBConnectionPtr = *mut DuckDBConnection;

extern "C" {
    fn duckdb_open(path: *const c_char, out: *mut DuckDBDatabasePtr) -> DuckDBState;
    fn duckdb_close(db: *mut DuckDBDatabasePtr);
    fn duckdb_connect(db: DuckDBDatabasePtr, out: *mut DuckDBConnectionPtr) -> DuckDBState;
    fn duckdb_disconnect(conn: *mut DuckDBConnectionPtr);
    fn duckdb_query(
        conn: DuckDBConnectionPtr,
        query: *const c_char,
        out: *mut c_void,
    ) -> DuckDBState;
    fn duckdb_destroy_result(result: *mut c_void);
    fn duckdb_result_error(result: *mut c_void) -> *const c_char;
    fn duckdb_value_int64(result: *mut c_void, col: u64, row: u64) -> i64;

    fn lemma_pin_table(
        conn: *mut c_void,
        table: *const c_char,
        columns: *const *const c_char,
        n_columns: usize,
        error_out: *mut c_char,
        error_len: usize,
    ) -> i64;
    fn lemma_unpin(pin: i64);
    fn lemma_pin_row_count(pin: i64) -> u64;
    fn lemma_pin_column_count(pin: i64) -> u64;
    fn lemma_pin_column_name(pin: i64, col: u64) -> *const c_char;
    fn lemma_pin_column_type(pin: i64, col: u64) -> DuckDBType;
    fn lemma_pin_chunk_count(pin: i64) -> u64;
    fn lemma_pin_chunk_len(pin: i64, chunk_index: u64) -> u64;
    fn lemma_pin_vector_data(pin: i64, chunk_index: u64, col: u64) -> *mut c_void;
    fn lemma_pin_vector_type(pin: i64, chunk_index: u64, col: u64) -> DuckDBType;
}

const LEMMA_PIN_INVALID: i64 = -1;

// duckdb_result is a large struct by value in C API — allocate on heap via MaybeUninit bytes.
// Use the official size from duckdb.h: we'll query with a byte buffer.
// From duckdb 1.2 duckdb.h, duckdb_result is typedef struct { ... } — use opaque heap via
// duckdb_query writing into allocated memory. Size: typically ~80-200 bytes; use 512.
const DUCKDB_RESULT_BYTES: usize = 512;

#[derive(Debug)]
pub enum PinError {
    Open(String),
    Pin(String),
    ColumnNotFound(String),
    UnsupportedType(String),
}

impl std::fmt::Display for PinError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PinError::Open(s) => write!(f, "open: {s}"),
            PinError::Pin(s) => write!(f, "pin: {s}"),
            PinError::ColumnNotFound(s) => write!(f, "column: {s}"),
            PinError::UnsupportedType(s) => write!(f, "type: {s}"),
        }
    }
}

impl std::error::Error for PinError {}

pub struct DuckDb {
    db: DuckDBDatabasePtr,
    conn: DuckDBConnectionPtr,
}

impl DuckDb {
    pub fn open(path: &str) -> Result<Self, PinError> {
        let c_path = CString::new(path).map_err(|e| PinError::Open(e.to_string()))?;
        let mut db: DuckDBDatabasePtr = ptr::null_mut();
        let mut conn: DuckDBConnectionPtr = ptr::null_mut();
        unsafe {
            if duckdb_open(c_path.as_ptr(), &mut db) != DUCKDB_SUCCESS {
                return Err(PinError::Open("duckdb_open failed".into()));
            }
            if duckdb_connect(db, &mut conn) != DUCKDB_SUCCESS {
                duckdb_close(&mut db);
                return Err(PinError::Open("duckdb_connect failed".into()));
            }
        }
        Ok(Self { db, conn })
    }

    pub fn connection_ptr(&self) -> *mut c_void {
        self.conn as *mut c_void
    }

    pub fn pin_table(&self, table: &str, columns: &[&str]) -> Result<DuckTablePin, PinError> {
        DuckTablePin::pin(self.conn as *mut c_void, table, columns)
    }

    pub fn exec(&self, sql: &str) -> Result<(), PinError> {
        let c_sql = CString::new(sql).map_err(|e| PinError::Open(e.to_string()))?;
        let mut result = vec![0u8; DUCKDB_RESULT_BYTES];
        unsafe {
            let status = duckdb_query(
                self.conn,
                c_sql.as_ptr(),
                result.as_mut_ptr() as *mut c_void,
            );
            if status != DUCKDB_SUCCESS {
                let err = duckdb_result_error(result.as_mut_ptr() as *mut c_void);
                let msg = if err.is_null() {
                    "query failed".to_string()
                } else {
                    CStr::from_ptr(err).to_string_lossy().into_owned()
                };
                duckdb_destroy_result(result.as_mut_ptr() as *mut c_void);
                return Err(PinError::Open(msg));
            }
            duckdb_destroy_result(result.as_mut_ptr() as *mut c_void);
        }
        Ok(())
    }

    /// Run SQL that returns a single INT64/BIGINT cell (DuckDB engine path for e2e baselines).
    pub fn query_i64(&self, sql: &str) -> Result<i64, PinError> {
        let c_sql = CString::new(sql).map_err(|e| PinError::Open(e.to_string()))?;
        let mut result = vec![0u8; DUCKDB_RESULT_BYTES];
        unsafe {
            let status = duckdb_query(
                self.conn,
                c_sql.as_ptr(),
                result.as_mut_ptr() as *mut c_void,
            );
            if status != DUCKDB_SUCCESS {
                let err = duckdb_result_error(result.as_mut_ptr() as *mut c_void);
                let msg = if err.is_null() {
                    "query failed".to_string()
                } else {
                    CStr::from_ptr(err).to_string_lossy().into_owned()
                };
                duckdb_destroy_result(result.as_mut_ptr() as *mut c_void);
                return Err(PinError::Open(msg));
            }
            let v = duckdb_value_int64(result.as_mut_ptr() as *mut c_void, 0, 0);
            duckdb_destroy_result(result.as_mut_ptr() as *mut c_void);
            Ok(v)
        }
    }
}

impl Drop for DuckDb {
    fn drop(&mut self) {
        unsafe {
            if !self.conn.is_null() {
                duckdb_disconnect(&mut self.conn);
            }
            if !self.db.is_null() {
                duckdb_close(&mut self.db);
            }
        }
    }
}

pub struct DuckTablePin {
    pin_id: i64,
    row_count: usize,
}

impl DuckTablePin {
    pub fn pin(conn: *mut c_void, table: &str, columns: &[&str]) -> Result<Self, PinError> {
        let c_table = CString::new(table).map_err(|e| PinError::Pin(e.to_string()))?;
        let c_cols: Vec<CString> = columns
            .iter()
            .map(|c| CString::new(*c))
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| PinError::Pin(e.to_string()))?;
        let col_ptrs: Vec<*const c_char> = c_cols.iter().map(|c| c.as_ptr()).collect();

        let mut err_buf = vec![0i8; 512];
        let pin_id = unsafe {
            lemma_pin_table(
                conn,
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
        if pin_id == LEMMA_PIN_INVALID {
            let msg = unsafe { CStr::from_ptr(err_buf.as_ptr()) }
                .to_string_lossy()
                .into_owned();
            return Err(PinError::Pin(msg));
        }
        let row_count = unsafe { lemma_pin_row_count(pin_id) as usize };
        Ok(Self { pin_id, row_count })
    }

    fn resolve_column(pin_id: i64, column: &str) -> Result<usize, PinError> {
        let ncol = unsafe { lemma_pin_column_count(pin_id) as usize };
        for c in 0..ncol {
            let name = unsafe {
                let p = lemma_pin_column_name(pin_id, c as u64);
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

    pub fn row_count(&self) -> usize {
        self.row_count
    }

    pub fn chunk_count(&self) -> usize {
        unsafe { lemma_pin_chunk_count(self.pin_id) as usize }
    }

    pub fn chunks(&self) -> DuckChunkIter<'_> {
        DuckChunkIter {
            pin: self,
            next: 0,
        }
    }

    pub fn column_index(&self, name: &str) -> Result<usize, PinError> {
        Self::resolve_column(self.pin_id, name)
    }

    pub fn chunk(&self, index: usize) -> DuckChunk<'_> {
        DuckChunk {
            pin: self,
            index,
        }
    }

    pub fn unpin(self) {
        unsafe { lemma_unpin(self.pin_id) };
        std::mem::forget(self);
    }
}

impl Drop for DuckTablePin {
    fn drop(&mut self) {
        unsafe { lemma_unpin(self.pin_id) };
    }
}

pub struct DuckChunkIter<'a> {
    pin: &'a DuckTablePin,
    next: usize,
}

impl<'a> Iterator for DuckChunkIter<'a> {
    type Item = DuckChunk<'a>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.next >= self.pin.chunk_count() {
            return None;
        }
        let chunk = DuckChunk {
            pin: self.pin,
            index: self.next,
        };
        self.next += 1;
        Some(chunk)
    }
}

pub struct DuckChunk<'a> {
    pin: &'a DuckTablePin,
    index: usize,
}

impl<'a> DuckChunk<'a> {
    pub fn len(&self) -> usize {
        unsafe { lemma_pin_chunk_len(self.pin.pin_id, self.index as u64) as usize }
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    pub fn col_u32_slice(&self, col: usize) -> Result<&[u32], PinError> {
        let data = self.raw_data(col)?;
        let ty = unsafe { lemma_pin_vector_type(self.pin.pin_id, self.index as u64, col as u64) };
        if ty != DUCKDB_TYPE_INTEGER && ty != DUCKDB_TYPE_UINTEGER {
            return Err(PinError::UnsupportedType(format!(
                "col_u32_slice expected INTEGER, got {ty}"
            )));
        }
        Ok(unsafe { std::slice::from_raw_parts(data as *const u32, self.len()) })
    }

    pub fn col_u64_slice(&self, col: usize) -> Result<&[u64], PinError> {
        let data = self.raw_data(col)?;
        let ty = unsafe { lemma_pin_vector_type(self.pin.pin_id, self.index as u64, col as u64) };
        if ty != DUCKDB_TYPE_BIGINT
            && ty != DUCKDB_TYPE_UBIGINT
            && ty != DUCKDB_TYPE_HUGEINT
            && ty != DUCKDB_TYPE_UHUGEINT
        {
            // DuckDB often stores integers as INTEGER — accept as u32 widened below via error.
            if ty == DUCKDB_TYPE_INTEGER || ty == DUCKDB_TYPE_UINTEGER {
                // Caller should use col_u32; provide clear error.
                return Err(PinError::UnsupportedType(format!(
                    "col_u64_slice got INTEGER (use col_u32_slice); type={ty}"
                )));
            }
            return Err(PinError::UnsupportedType(format!(
                "col_u64_slice expected BIGINT family, got {ty}"
            )));
        }
        Ok(unsafe { std::slice::from_raw_parts(data as *const u64, self.len()) })
    }

    /// Date + amount may be INTEGER or BIGINT from CSV/DuckDB loads — sum as u64.
    pub fn col_i64_or_i32_sum_filtered(
        &self,
        date_col: usize,
        amount_col: usize,
        lo: u32,
        hi: u32,
    ) -> Result<(u64, u64), PinError> {
        self.col_i64_or_i32_sum_filtered_range(date_col, amount_col, lo, hi, 0, self.len())
    }

    /// Filtered sum over `[row_start, row_end)` within this chunk (chunk-local indices).
    pub fn col_i64_or_i32_sum_filtered_range(
        &self,
        date_col: usize,
        amount_col: usize,
        lo: u32,
        hi: u32,
        row_start: usize,
        row_end: usize,
    ) -> Result<(u64, u64), PinError> {
        let n = self.len();
        if row_start >= row_end || row_start >= n {
            return Ok((0, 0));
        }
        let row_end = row_end.min(n);
        let lo64 = lo as i64;
        let hi64 = hi as i64;
        let date_ty =
            unsafe { lemma_pin_vector_type(self.pin.pin_id, self.index as u64, date_col as u64) };
        let amount_ty =
            unsafe { lemma_pin_vector_type(self.pin.pin_id, self.index as u64, amount_col as u64) };
        let date_ptr = self.raw_data(date_col)?;
        let amount_ptr = self.raw_data(amount_col)?;

        let mut sum = 0u64;
        let mut matched = 0u64;

        macro_rules! scan {
            ($d:ty, $a:ty) => {{
                let dates = unsafe { std::slice::from_raw_parts(date_ptr as *const $d, n) };
                let amounts = unsafe { std::slice::from_raw_parts(amount_ptr as *const $a, n) };
                for i in row_start..row_end {
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

    fn raw_data(&self, col: usize) -> Result<*const u8, PinError> {
        let ptr =
            unsafe { lemma_pin_vector_data(self.pin.pin_id, self.index as u64, col as u64) };
        if ptr.is_null() {
            return Err(PinError::ColumnNotFound(format!("chunk col {col}")));
        }
        Ok(ptr as *const u8)
    }
}

pub fn pin_checksum_u64_column(pin: &DuckTablePin, col: usize) -> Result<u64, PinError> {
    let mut acc = 0u64;
    for chunk in pin.chunks() {
        // Prefer u64; fall back to summing i32 as u64
        let ty = unsafe { lemma_pin_column_type(pin.pin_id, col as u64) };
        if ty == DUCKDB_TYPE_INTEGER || ty == DUCKDB_TYPE_UINTEGER {
            let data = chunk.raw_data(col)?;
            let slice = unsafe { std::slice::from_raw_parts(data as *const i32, chunk.len()) };
            for &v in slice {
                acc = acc.wrapping_add(v as u64);
            }
        } else {
            let slice = chunk.col_u64_slice(col)?;
            acc = acc.wrapping_add(checksum_u64(slice));
        }
    }
    Ok(acc)
}

pub fn pin_and_checksum(
    db: &DuckDb,
    table: &str,
    column: &str,
) -> Result<(usize, u64), PinError> {
    let pin = DuckTablePin::pin(db.connection_ptr(), table, &[column])?;
    let col_idx = pin.column_index(column)?;
    let rows = pin.row_count();
    let cksum = pin_checksum_u64_column(&pin, col_idx)?;
    pin.unpin();
    Ok((rows, cksum))
}

fn min_max_dates_as_u32(
    date_ptr: *const u8,
    date_ty: DuckDBType,
    chunk_len: usize,
    start: usize,
    end: usize,
) -> Result<(u32, u32), PinError> {
    match date_ty {
        DUCKDB_TYPE_INTEGER | DUCKDB_TYPE_UINTEGER => {
            let all =
                unsafe { std::slice::from_raw_parts(date_ptr as *const i32, chunk_len) };
            let slice = &all[start..end];
            let min = *slice.iter().min().unwrap_or(&0) as u32;
            let max = *slice.iter().max().unwrap_or(&0) as u32;
            Ok((min, max))
        }
        DUCKDB_TYPE_BIGINT | DUCKDB_TYPE_UBIGINT => {
            let all =
                unsafe { std::slice::from_raw_parts(date_ptr as *const i64, chunk_len) };
            let slice = &all[start..end];
            let min = *slice.iter().min().unwrap_or(&0) as u32;
            let max = *slice.iter().max().unwrap_or(&0) as u32;
            Ok((min, max))
        }
        _ => Err(PinError::UnsupportedType(format!(
            "zone date col type {date_ty} (need INTEGER/BIGINT)"
        ))),
    }
}

/// Build sub-zones over pinned DuckDB date vectors (zero-copy; indices are chunk-local).
pub fn build_pin_zone_map_u32(
    pin: &DuckTablePin,
    date_col: usize,
    zone_rows: usize,
) -> Result<Vec<PinZoneSegmentU32>, PinError> {
    let zone_rows = zone_rows.max(1);
    let mut zones = Vec::new();
    for chunk_index in 0..pin.chunk_count() {
        let chunk = pin.chunk(chunk_index);
        let n = chunk.len();
        if n == 0 {
            continue;
        }
        let date_ty = unsafe { lemma_pin_column_type(pin.pin_id, date_col as u64) };
        let date_ptr = chunk.raw_data(date_col)?;
        let mut start = 0usize;
        while start < n {
            let end = (start + zone_rows).min(n);
            let (min, max) = min_max_dates_as_u32(date_ptr, date_ty, n, start, end)?;
            zones.push(PinZoneSegmentU32 {
                chunk_index,
                min,
                max,
                start,
                end,
            });
            start = end;
        }
    }
    Ok(zones)
}

/// H1-style date-range sum over pinned DuckDB buffers with zone-map prune (prep outside timer).
pub struct PinH1Prep<'a> {
    pin: &'a DuckTablePin,
    date_col: usize,
    amount_col: usize,
    zones: Vec<PinZoneSegmentU32>,
}

impl<'a> PinH1Prep<'a> {
    pub fn new(
        pin: &'a DuckTablePin,
        date_col: usize,
        amount_col: usize,
    ) -> Result<Self, PinError> {
        Ok(Self {
            pin,
            date_col,
            amount_col,
            zones: build_pin_zone_map_u32(pin, date_col, PIN_ZONE_ROWS)?,
        })
    }

    pub fn zone_count(&self) -> usize {
        self.zones.len()
    }

    pub fn zones(&self) -> &[PinZoneSegmentU32] {
        &self.zones
    }

    /// Returns `(matched_rows, sum, zones_kept, zones_total)`.
    pub fn run(&self, lo: u32, hi: u32) -> Result<(u64, u64, usize, usize), PinError> {
        let zones_total = self.zones.len();
        let mut zones_kept = 0usize;
        let mut matched = 0u64;
        let mut sum = 0u64;
        for z in &self.zones {
            if z.may_satisfy(lo, hi) {
                zones_kept += 1;
                let chunk = self.pin.chunk(z.chunk_index);
                let (m, s) = chunk.col_i64_or_i32_sum_filtered_range(
                    self.date_col,
                    self.amount_col,
                    lo,
                    hi,
                    z.start,
                    z.end,
                )?;
                matched += m;
                sum = sum.wrapping_add(s);
            }
        }
        Ok((matched, sum, zones_kept, zones_total))
    }
}
