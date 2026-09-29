// Layer A DuckDB pin/lease: keep result chunks alive; getters read vector pointers (no column memcpy).
#[allow(dead_code, non_snake_case, non_camel_case_types)]
mod lemma_duckdb_load {
    use std::collections::HashMap;
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

    #[derive(Clone, Copy, Debug)]
    pub enum ColKind {
        U32,
        U64,
        String,
        Bool,
    }

    #[derive(Clone, Copy)]
    struct ChunkVec {
        data: *mut c_void,
        validity: *mut u64,
        duck_ty: DuckDBType,
    }

    struct PinnedTable {
        db: DuckDBDatabasePtr,
        conn: DuckDBConnectionPtr,
        result: DuckdbResult,
        chunks: Vec<DuckDBDataChunk>,
        chunk_starts: Vec<usize>,
        chunk_lens: Vec<usize>,
        n: usize,
        kinds: Vec<ColKind>,
        // [chunk][col]
        vecs: Vec<Vec<ChunkVec>>,
    }

    struct PinWorld {
        tables: HashMap<String, PinnedTable>,
    }

    fn world() -> &'static mut PinWorld {
        static mut WORLD: *mut PinWorld = ptr::null_mut();
        unsafe {
            if WORLD.is_null() {
                WORLD = Box::into_raw(Box::new(PinWorld {
                    tables: HashMap::new(),
                }));
            }
            &mut *WORLD
        }
    }

    unsafe fn varchar_bytes_at(ptr: *const u8) -> &'static [u8] {
        let len = *(ptr as *const u32) as usize;
        if len == 0 {
            return b"";
        }
        if len <= 12 {
            std::slice::from_raw_parts(ptr.add(4), len)
        } else {
            let data_ptr = *(ptr.add(8) as *const *const u8);
            if data_ptr.is_null() {
                b""
            } else {
                std::slice::from_raw_parts(data_ptr, len)
            }
        }
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

    fn open_readonly(path: &str) -> (DuckDBDatabasePtr, DuckDBConnectionPtr) {
        let c_path = CString::new(path).expect("db path");
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
        (db, conn)
    }

    fn locate_row(pin: &PinnedTable, row: usize) -> (usize, usize) {
        if row >= pin.n {
            panic!("row {row} out of pin n={}", pin.n);
        }
        let mut lo = 0usize;
        let mut hi = pin.chunk_starts.len();
        while lo + 1 < hi {
            let mid = (lo + hi) / 2;
            if pin.chunk_starts[mid] <= row {
                lo = mid;
            } else {
                hi = mid;
            }
        }
        (lo, row - pin.chunk_starts[lo])
    }

    fn vec_at(pin: &PinnedTable, col: usize, row: usize) -> (ChunkVec, usize) {
        let (ci, local) = locate_row(pin, row);
        (pin.vecs[ci][col], local)
    }

    /// Pin `SELECT cols FROM table LIMIT n` and retain DuckDB vector buffers (lease).
    pub fn pin_table(
        key: &str,
        db_path: &str,
        table: &str,
        limit: usize,
        columns: &[(&str, ColKind)],
    ) -> usize {
        if columns.is_empty() {
            return 0;
        }
        let (mut db, mut conn) = open_readonly(db_path);
        let col_sql: Vec<String> = columns
            .iter()
            .map(|(n, kind)| match kind {
                // Dataset INTEGER columns are < 2^31. Cast a wider file column
                // to that width. A value outside signed 32-bit fails the cast.
                ColKind::U32 => format!("CAST({} AS INTEGER)", quote_ident(n)),
                // A catalog u64 cell may be stored as a narrower integer.
                // Widen those. Leave DOUBLE/FLOAT alone: CAST to BIGINT rounds.
                ColKind::U64 => {
                    let ident = quote_ident(n);
                    format!(
                        "CASE WHEN typeof({ident}) IN ('TINYINT', 'SMALLINT', 'INTEGER', 'UTINYINT', 'USMALLINT', 'UINTEGER') THEN CAST({ident} AS BIGINT) ELSE {ident} END"
                    )
                }
                _ => quote_ident(n),
            })
            .collect();
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

        let kinds: Vec<ColKind> = columns.iter().map(|(_, k)| *k).collect();
        let n_chunks = unsafe { duckdb_result_chunk_count(result) };
        let mut chunks: Vec<DuckDBDataChunk> = Vec::new();
        let mut chunk_starts: Vec<usize> = Vec::new();
        let mut chunk_lens: Vec<usize> = Vec::new();
        let mut vecs: Vec<Vec<ChunkVec>> = Vec::new();
        let mut total_rows: usize = 0;
        for ci in 0..n_chunks {
            let chunk = unsafe { duckdb_result_get_chunk(result, ci) };
            if chunk.is_null() {
                continue;
            }
            let chunk_size = unsafe { duckdb_data_chunk_get_size(chunk) } as usize;
            let mut col_vecs: Vec<ChunkVec> = Vec::with_capacity(columns.len());
            for (col_idx, (col_name, kind)) in columns.iter().enumerate() {
                let duck_ty = unsafe { duckdb_column_type(&mut result, col_idx as idx_t) };
                check_duck_type(*kind, duck_ty, col_name);
                let vector = unsafe { duckdb_data_chunk_get_vector(chunk, col_idx as idx_t) };
                let data = unsafe { duckdb_vector_get_data(vector) };
                let validity = unsafe { duckdb_vector_get_validity(vector) };
                col_vecs.push(ChunkVec {
                    data,
                    validity,
                    duck_ty,
                });
            }
            chunk_starts.push(total_rows);
            chunk_lens.push(chunk_size);
            total_rows += chunk_size;
            chunks.push(chunk);
            vecs.push(col_vecs);
        }

        let pin = PinnedTable {
            db,
            conn,
            result,
            chunks,
            chunk_starts,
            chunk_lens,
            n: total_rows,
            kinds,
            vecs,
        };
        world().tables.insert(key.to_string(), pin);
        total_rows
    }

    fn pin_ref(key: &str) -> &'static PinnedTable {
        world()
            .tables
            .get(key)
            .unwrap_or_else(|| panic!("no pin for table {key}"))
    }

    pub fn read_u32(key: &str, col: usize, row: usize) -> u32 {
        let pin = pin_ref(key);
        let (v, local) = vec_at(pin, col, row);
        if !row_valid(v.validity, local as idx_t) {
            return 0;
        }
        unsafe { *(v.data as *const i32).add(local) as u32 }
    }

    pub fn read_u64(key: &str, col: usize, row: usize) -> u64 {
        let pin = pin_ref(key);
        let (v, local) = vec_at(pin, col, row);
        if !row_valid(v.validity, local as idx_t) {
            return 0;
        }
        unsafe {
            match v.duck_ty {
                DUCKDB_TYPE_FLOAT | DUCKDB_TYPE_DOUBLE => {
                    *(v.data as *const f64).add(local) as u64
                }
                _ => *(v.data as *const i64).add(local) as u64,
            }
        }
    }

    pub fn read_bool(key: &str, col: usize, row: usize) -> bool {
        let pin = pin_ref(key);
        let (v, local) = vec_at(pin, col, row);
        if !row_valid(v.validity, local as idx_t) {
            return false;
        }
        unsafe { *(v.data as *const bool).add(local) }
    }

    pub fn read_string(key: &str, col: usize, row: usize) -> String {
        let pin = pin_ref(key);
        let (v, local) = vec_at(pin, col, row);
        if !row_valid(v.validity, local as idx_t) {
            return String::new();
        }
        const STRING_T_BYTES: usize = 16;
        unsafe {
            let st = (v.data as *const u8).add(local * STRING_T_BYTES);
            let bytes = varchar_bytes_at(st);
            String::from_utf8_lossy(bytes).into_owned()
        }
    }

    pub fn eq_str(key: &str, col: usize, row: usize, lit: &str) -> bool {
        let pin = pin_ref(key);
        let (v, local) = vec_at(pin, col, row);
        if !row_valid(v.validity, local as idx_t) {
            return lit.is_empty();
        }
        const STRING_T_BYTES: usize = 16;
        unsafe {
            let st = (v.data as *const u8).add(local * STRING_T_BYTES);
            varchar_bytes_at(st) == lit.as_bytes()
        }
    }

    pub fn unpin_all() {
        let w = world();
        let tables = std::mem::take(&mut w.tables);
        for mut pin in tables.into_values() {
            unsafe {
                for chunk in pin.chunks.drain(..) {
                    let mut destroy = chunk;
                    duckdb_destroy_data_chunk(&mut destroy);
                }
                duckdb_destroy_result(&mut pin.result);
                duckdb_disconnect(&mut pin.conn);
                duckdb_close(&mut pin.db);
            }
        }
    }
}
