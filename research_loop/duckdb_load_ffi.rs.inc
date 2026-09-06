// Layer A DuckDB → owned Vec Cols (libduckdb C API). Included once in assembled programs.
#[allow(dead_code, non_snake_case, non_camel_case_types)]
mod lemma_duckdb_load {
    use std::ffi::{CStr, CString};
    use std::os::raw::{c_char, c_void};
    use std::ptr;

    type DuckDBState = u32;
    const DUCKDB_SUCCESS: DuckDBState = 0;
    type DuckDBType = u32;
    const DUCKDB_TYPE_BOOLEAN: DuckDBType = 1;
    const DUCKDB_TYPE_TINYINT: DuckDBType = 2;
    const DUCKDB_TYPE_SMALLINT: DuckDBType = 3;
    const DUCKDB_TYPE_INTEGER: DuckDBType = 4;
    const DUCKDB_TYPE_BIGINT: DuckDBType = 5;
    const DUCKDB_TYPE_UTINYINT: DuckDBType = 6;
    const DUCKDB_TYPE_USMALLINT: DuckDBType = 7;
    const DUCKDB_TYPE_UINTEGER: DuckDBType = 8;
    const DUCKDB_TYPE_UBIGINT: DuckDBType = 9;
    const DUCKDB_TYPE_FLOAT: DuckDBType = 10;
    const DUCKDB_TYPE_DOUBLE: DuckDBType = 11;
    const DUCKDB_TYPE_DATE: DuckDBType = 13;
    const DUCKDB_TYPE_VARCHAR: DuckDBType = 17;

    type idx_t = u64;

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
    type DuckDBConfigPtr = *mut c_void;

    #[repr(C)]
    #[derive(Copy, Clone)]
    struct DuckdbResult {
        deprecated_column_count: idx_t,
        deprecated_row_count: idx_t,
        deprecated_rows_changed: idx_t,
        deprecated_columns: *mut c_void,
        deprecated_error_message: *mut c_char,
        internal_data: *mut c_void,
    }

    type DuckDBDataChunk = *mut c_void;
    type DuckDBVector = *mut c_void;

    extern "C" {
        fn duckdb_open_ext(
            path: *const c_char,
            out: *mut DuckDBDatabasePtr,
            config: DuckDBConfigPtr,
            out_error: *mut *mut c_char,
        ) -> DuckDBState;
        fn duckdb_create_config(out: *mut DuckDBConfigPtr) -> DuckDBState;
        fn duckdb_set_config(
            config: DuckDBConfigPtr,
            name: *const c_char,
            option: *const c_char,
        ) -> DuckDBState;
        fn duckdb_destroy_config(config: *mut DuckDBConfigPtr);
        fn duckdb_free(ptr: *mut c_void);
        fn duckdb_close(db: *mut DuckDBDatabasePtr);
        fn duckdb_connect(db: DuckDBDatabasePtr, out: *mut DuckDBConnectionPtr) -> DuckDBState;
        fn duckdb_disconnect(conn: *mut DuckDBConnectionPtr);
        fn duckdb_query(
            conn: DuckDBConnectionPtr,
            query: *const c_char,
            out: *mut DuckdbResult,
        ) -> DuckDBState;
        fn duckdb_destroy_result(result: *mut DuckdbResult);
        fn duckdb_result_error(result: *mut DuckdbResult) -> *const c_char;
        fn duckdb_column_type(result: *mut DuckdbResult, col: idx_t) -> DuckDBType;
        fn duckdb_result_chunk_count(result: DuckdbResult) -> idx_t;
        fn duckdb_result_get_chunk(result: DuckdbResult, chunk_index: idx_t) -> DuckDBDataChunk;
        fn duckdb_destroy_data_chunk(chunk: *mut DuckDBDataChunk);
        fn duckdb_data_chunk_get_size(chunk: DuckDBDataChunk) -> idx_t;
        fn duckdb_data_chunk_get_vector(chunk: DuckDBDataChunk, col_idx: idx_t) -> DuckDBVector;
        fn duckdb_vector_get_data(vector: DuckDBVector) -> *mut c_void;
        fn duckdb_vector_get_validity(vector: DuckDBVector) -> *mut u64;
        fn duckdb_validity_row_is_valid(validity: *mut u64, row: idx_t) -> bool;
    }

    /// duckdb_string_t is 16 bytes; parse without a Rust union (layout host).
    unsafe fn read_varchar_at(ptr: *const u8) -> String {
        let len = *(ptr as *const u32) as usize;
        if len == 0 {
            return String::new();
        }
        if len <= 12 {
            let bytes = std::slice::from_raw_parts(ptr.add(4), len);
            String::from_utf8_lossy(bytes).into_owned()
        } else {
            let data_ptr = *(ptr.add(8) as *const *const u8);
            if data_ptr.is_null() {
                return String::new();
            }
            let bytes = std::slice::from_raw_parts(data_ptr, len);
            String::from_utf8_lossy(bytes).into_owned()
        }
    }

    #[derive(Clone, Copy, Debug)]
    pub enum ColKind {
        U32,
        U64,
        String,
        Bool,
    }

    pub struct LoadedTable {
        pub n: usize,
        pub columns: Vec<ColVec>,
    }

    pub enum ColVec {
        U32(Vec<u32>),
        U64(Vec<u64>),
        String(Vec<String>),
        Bool(Vec<bool>),
    }

    fn quote_ident(name: &str) -> String {
        let escaped = name.replace('"', "\"\"");
        format!("\"{escaped}\"")
    }

    fn row_valid(validity: *mut u64, row: idx_t) -> bool {
        if validity.is_null() {
            return true;
        }
        unsafe { duckdb_validity_row_is_valid(validity, row) }
    }

    fn duck_type_label(t: DuckDBType) -> &'static str {
        match t {
            DUCKDB_TYPE_BOOLEAN => "BOOLEAN",
            DUCKDB_TYPE_TINYINT => "TINYINT",
            DUCKDB_TYPE_SMALLINT => "SMALLINT",
            DUCKDB_TYPE_INTEGER => "INTEGER",
            DUCKDB_TYPE_BIGINT => "BIGINT",
            DUCKDB_TYPE_UTINYINT => "UTINYINT",
            DUCKDB_TYPE_USMALLINT => "USMALLINT",
            DUCKDB_TYPE_UINTEGER => "UINTEGER",
            DUCKDB_TYPE_UBIGINT => "UBIGINT",
            DUCKDB_TYPE_FLOAT => "FLOAT",
            DUCKDB_TYPE_DOUBLE => "DOUBLE",
            DUCKDB_TYPE_DATE => "DATE",
            DUCKDB_TYPE_VARCHAR => "VARCHAR",
            _ => "UNKNOWN",
        }
    }

    fn check_duck_type(expected: ColKind, actual: DuckDBType, col: &str) {
        let ok = match expected {
            ColKind::U32 => matches!(
                actual,
                DUCKDB_TYPE_TINYINT
                    | DUCKDB_TYPE_SMALLINT
                    | DUCKDB_TYPE_INTEGER
                    | DUCKDB_TYPE_UTINYINT
                    | DUCKDB_TYPE_USMALLINT
                    | DUCKDB_TYPE_UINTEGER
                    | DUCKDB_TYPE_DATE
            ),
            ColKind::U64 => matches!(
                actual,
                DUCKDB_TYPE_BIGINT
                    | DUCKDB_TYPE_UBIGINT
                    | DUCKDB_TYPE_FLOAT
                    | DUCKDB_TYPE_DOUBLE
            ),
            ColKind::String => actual == DUCKDB_TYPE_VARCHAR,
            ColKind::Bool => actual == DUCKDB_TYPE_BOOLEAN,
        };
        if !ok {
            panic!(
                "unsupported DuckDB type {} for column {} (expected {:?})",
                duck_type_label(actual),
                col,
                expected
            );
        }
    }

    unsafe fn append_chunk_col(
        kind: ColKind,
        chunk: DuckDBDataChunk,
        col_idx: idx_t,
        duck_ty: DuckDBType,
        col_name: &str,
        out: &mut ColVec,
    ) {
        check_duck_type(kind, duck_ty, col_name);
        let chunk_size = duckdb_data_chunk_get_size(chunk);
        let vec = duckdb_data_chunk_get_vector(chunk, col_idx);
        let data = duckdb_vector_get_data(vec);
        let validity = duckdb_vector_get_validity(vec);
        match out {
            ColVec::U32(v) => {
                let ptr = data as *const i32;
                for row in 0..chunk_size {
                    if !row_valid(validity, row) {
                        v.push(0);
                    } else {
                        // DATE columns store days since epoch as i32; SEC int cols are plain INTEGER.
                        v.push(*ptr.add(row as usize) as u32);
                    }
                }
            }
            ColVec::U64(v) => {
                match duck_ty {
                    DUCKDB_TYPE_FLOAT | DUCKDB_TYPE_DOUBLE => {
                        let ptr = data as *const f64;
                        for row in 0..chunk_size {
                            if !row_valid(validity, row) {
                                v.push(0);
                            } else {
                                // Truncate toward zero (matches tbl parse for numeric money cols).
                                v.push(*ptr.add(row as usize) as u64);
                            }
                        }
                    }
                    _ => {
                        let ptr = data as *const i64;
                        for row in 0..chunk_size {
                            if !row_valid(validity, row) {
                                v.push(0);
                            } else {
                                v.push(*ptr.add(row as usize) as u64);
                            }
                        }
                    }
                }
            }
            ColVec::String(v) => {
                const STRING_T_BYTES: usize = 16;
                let base = data as *const u8;
                for row in 0..chunk_size {
                    if !row_valid(validity, row) {
                        v.push(String::new());
                    } else {
                        let st_ptr = base.add(row as usize * STRING_T_BYTES);
                        v.push(read_varchar_at(st_ptr));
                    }
                }
            }
            ColVec::Bool(v) => {
                let ptr = data as *const bool;
                for row in 0..chunk_size {
                    if !row_valid(validity, row) {
                        v.push(false);
                    } else {
                        v.push(*ptr.add(row as usize));
                    }
                }
            }
        }
    }

    pub fn load_table(
        db_path: &str,
        table: &str,
        limit: usize,
        columns: &[(&str, ColKind)],
    ) -> LoadedTable {
        if columns.is_empty() {
            return LoadedTable {
                n: 0,
                columns: Vec::new(),
            };
        }
        let c_path = CString::new(db_path).expect("db path");
        let mut db: DuckDBDatabasePtr = ptr::null_mut();
        let mut conn: DuckDBConnectionPtr = ptr::null_mut();
        unsafe {
            let mut cfg: DuckDBConfigPtr = ptr::null_mut();
            if duckdb_create_config(&mut cfg) != DUCKDB_SUCCESS {
                panic!("duckdb_create_config failed");
            }
            let cfg_key = CString::new("access_mode").unwrap();
            let cfg_val = CString::new("READ_ONLY").unwrap();
            if duckdb_set_config(cfg, cfg_key.as_ptr(), cfg_val.as_ptr()) != DUCKDB_SUCCESS {
                duckdb_destroy_config(&mut cfg);
                panic!("duckdb_set_config access_mode=READ_ONLY failed");
            }
            let mut err: *mut c_char = ptr::null_mut();
            let st = duckdb_open_ext(c_path.as_ptr(), &mut db, cfg, &mut err);
            duckdb_destroy_config(&mut cfg);
            if st != DUCKDB_SUCCESS {
                let msg = if err.is_null() {
                    "duckdb_open_ext failed".to_string()
                } else {
                    let s = CStr::from_ptr(err).to_string_lossy().into_owned();
                    duckdb_free(err as *mut c_void);
                    s
                };
                panic!("duckdb_open_ext failed: {msg}");
            }
            if duckdb_connect(db, &mut conn) != DUCKDB_SUCCESS {
                duckdb_close(&mut db);
                panic!("duckdb_connect failed");
            }
        }

        let col_sql: Vec<String> = columns.iter().map(|(n, _)| quote_ident(n)).collect();
        let sql = format!(
            "SELECT {} FROM {} LIMIT {}",
            col_sql.join(", "),
            quote_ident(table),
            limit
        );
        let c_sql = CString::new(sql).expect("sql");
        let mut result = DuckdbResult {
            deprecated_column_count: 0,
            deprecated_row_count: 0,
            deprecated_rows_changed: 0,
            deprecated_columns: ptr::null_mut(),
            deprecated_error_message: ptr::null_mut(),
            internal_data: ptr::null_mut(),
        };
        unsafe {
            if duckdb_query(conn, c_sql.as_ptr(), &mut result) != DUCKDB_SUCCESS {
                let err = duckdb_result_error(&mut result);
                let msg = if err.is_null() {
                    "duckdb_query failed".to_string()
                } else {
                    CStr::from_ptr(err).to_string_lossy().into_owned()
                };
                duckdb_destroy_result(&mut result);
                duckdb_disconnect(&mut conn);
                duckdb_close(&mut db);
                panic!("{msg}");
            }
        }

        let mut outs: Vec<ColVec> = columns
            .iter()
            .map(|(_, k)| match k {
                ColKind::U32 => ColVec::U32(Vec::new()),
                ColKind::U64 => ColVec::U64(Vec::new()),
                ColKind::String => ColVec::String(Vec::new()),
                ColKind::Bool => ColVec::Bool(Vec::new()),
            })
            .collect();

        let n_chunks = unsafe { duckdb_result_chunk_count(result) };
        let mut total_rows: usize = 0;
        for ci in 0..n_chunks {
            let chunk = unsafe { duckdb_result_get_chunk(result, ci) };
            if chunk.is_null() {
                continue;
            }
            let chunk_size = unsafe { duckdb_data_chunk_get_size(chunk) };
            for (col_idx, (col_name, kind)) in columns.iter().enumerate() {
                let duck_ty =
                    unsafe { duckdb_column_type(&mut result, col_idx as idx_t) };
                unsafe {
                    append_chunk_col(
                        *kind,
                        chunk,
                        col_idx as idx_t,
                        duck_ty,
                        col_name,
                        &mut outs[col_idx],
                    );
                }
            }
            total_rows += chunk_size as usize;
            unsafe {
                let mut destroy = chunk;
                duckdb_destroy_data_chunk(&mut destroy);
            }
        }

        unsafe {
            duckdb_destroy_result(&mut result);
            duckdb_disconnect(&mut conn);
            duckdb_close(&mut db);
        }

        LoadedTable {
            n: total_rows,
            columns: outs,
        }
    }
}
