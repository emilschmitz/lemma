"""LEMMA_COLD_STREAM=1 (default off, never chosen silently, no fallback): the streaming chunk fold.

The column is never materialized. The generated program registers ONE DuckDB C-API aggregate function `f` and runs ``SELECT f(c1, ..., ck) FROM t``: DuckDB
drives its own multi-threaded scan and calls the proved fold once per vector (``cold_update``), merges thread-local states (``cold_combine``) and finalizes once
(``cold_finish``). Every filter lives inside the proved fold: the SQL handed to DuckDB has no WHERE, so DuckDB's filter evaluation is not part of the claim.

What is verified (Verus, ``cold_lib.rs`` + a worked fixture per query): the fold is correct for EVERY arrival order and grouping of the chunks, because the
aggregate is a sum of a per-row term and a sum is invariant under permutation; the caps of ``valid_cols`` are checked per cell inside the verified update; the final
function has the unchanged declarative ``ensures`` of ``run_query``. What is trusted: ZC-2 (research_loop/menus/cold_path_feasibility.md): DuckDB delivers each row
of ``t`` to exactly one ``update`` call whose state is combined exactly once into the state ``finalize`` sees, the vectors of one call are row-aligned, flat and of the
declared native type. The glue that registers the callbacks and reads the vectors is plain untrusted Rust, like ``main`` in the copy path.

Supported: one input table, every column a fixed-width signed integer / DECIMAL / DATE at its stored width (the zero-copy resolution), no NULL (the aggregate
asks for special NULL handling and the glue aborts on a NULL), the sequential spec, an ``OutRow`` of one field ``Option<i128>`` or ``u64``. Everything else raises
``ColdStreamUnsupported`` at assemble time.
"""

from __future__ import annotations

import lemma_config
import re
from pathlib import Path

from declarative_spec import assemble as asm
from declarative_spec import parallel, zero_copy
from declarative_spec.schema_types import DeclarativeUnsupported, SchemaModel

_HERE = Path(__file__).resolve().parent


class ColdStreamUnsupported(DeclarativeUnsupported):
    """The query is outside what the streaming fold handles (or the flag is off)."""


def enabled() -> bool:
    # WIP/parked: lemma.toml [wip] cold_stream (default false), see research_loop/menus/pin_path_archive.md
    return bool(lemma_config.get("cold_stream"))


def lib_rs() -> str:
    return (_HERE / "cold_lib.rs").read_text()


COLD_FOLD_START = "// COLD_FOLD_START"
COLD_FOLD_END = "// COLD_FOLD_END"


def split_fixture(text: str) -> tuple[str, str]:
    """(the fold region: spec fns, lemmas, cold_init/cold_update/cold_combine; the body of cold_finish)."""
    from declarative_spec.regions import extract_agent_edit

    a, b = text.find(COLD_FOLD_START), text.find(COLD_FOLD_END)
    if a == -1 or b == -1 or b < a:
        raise ValueError("COLD_FOLD markers missing")
    return text[a + len(COLD_FOLD_START) : b], extract_agent_edit(text)


def _row_ty(fields: list[tuple[str, str]]) -> str:
    return fields[0][1] if len(fields) == 1 else "(" + ", ".join(t for _f, t in fields) + ")"


def _rewrite(spec_rs: str, suffix: str, fields: list[tuple[str, str]]) -> tuple[str, str]:
    """(the spec with spec-only columns and without run_query, the `ensures` text of run_query)."""
    m = re.search(r"pub fn run_query\([^)]*\) -> \(res: Vec<OutRow>\)\n    requires\n(?:        [^\n]*\n)+?    ensures\n        (.*?),\n\{\n", spec_rs, re.S)
    if m is None:
        raise ColdStreamUnsupported("the spec has no `run_query(...) -> (res: Vec<OutRow>)` with requires/ensures")
    ensures = m.group(1)
    head = spec_rs[: spec_rs.index("// AGENT_HELPERS_START")]
    out = head
    struct = re.search(rf"pub struct Cols_{suffix}\s*\{{[^}}]+\}}", out)
    body = struct.group(0)
    new = body
    for fname, fty in fields:
        new = new.replace(f"pub {fname}: Vec<{fty}>", f"pub {fname}: ColSeq<{fty}>")
    out = out.replace(body, new)
    return out, ensures


def assemble_cold_program(
    spec_rs: str,
    fixture: str,
    *,
    db_path: str,
    schema: SchemaModel,
    stored_types: dict[str, str],
    reference_sql: str | None = None,
    mode: str | None = None,
    sql: str | None = None,
) -> str:
    """The verified program plus the plain-Rust glue that runs it inside DuckDB. ``fixture``: see ``split_fixture``."""
    if not enabled():
        raise ColdStreamUnsupported("[wip] cold_stream (LEMMA_COLD_STREAM=1) is not set: the streaming fold is opt-in, there is no fallback to or from it")
    mode = mode or lemma_config.get("cold_stream_mode")
    if mode not in ("aggregate", "scalar"):
        raise ColdStreamUnsupported(f"cold_stream_mode={mode!r}: one of aggregate, scalar")
    refuse_unsupported_sql(sql if sql is not None else reference_sql)
    if re.search(r"distinct", re.sub(r"//[^\n]*", "", spec_rs), re.I):
        raise ColdStreamUnsupported("the spec talks about DISTINCT values: the streaming fold cannot see them (DuckDB dedups before the aggregate callbacks)")
    if parallel.is_parallel(spec_rs):
        raise ColdStreamUnsupported("the spec is the parallel variant (Arc parameters): DuckDB parallelizes the scan itself, emit the sequential spec")
    try:
        res = zero_copy.resolve(spec_rs, schema, stored_types)
    except zero_copy.ZeroCopyUnsupported as exc:
        raise ColdStreamUnsupported(str(exc)) from exc
    suffix, fields = zero_copy._single_table(spec_rs)
    out_row = re.search(r"pub struct OutRow\s*\{\s*pub (\w+):\s*([^,\n]+),\s*\}", spec_rs)
    if out_row is None or out_row.group(2).strip() not in ("Option<i128>", "u64"):
        raise ColdStreamUnsupported("the result must be an OutRow with one field of type Option<i128> or u64")
    out_ty = out_row.group(2).strip()
    fold, finish_body = split_fixture(fixture)
    spec_cold, ensures = _rewrite(spec_rs, suffix, fields)
    row_ty = _row_ty(fields)
    pname = re.search(r"pub fn run_query\((\w+): &Cols_", spec_rs).group(1)
    if len(fields) == 1:
        rows_spec = f"{pname}.{fields[0][0]}@"
    else:
        cells = ", ".join(f"{pname}.{f}@[i]" for f, _t in fields)
        rows_spec = f"Seq::new({pname}.n as nat, |i: int| ({cells}))"
    lens = "".join(f"        {pname}.{f}@.len() == {pname}.n as int,\n" for f, _t in fields)
    verus_part = (
        spec_cold.rstrip()
        + "\n\n"
        + lib_rs()
        + f"\npub type ColdRow = {row_ty};\n\n"
        + f"pub open spec fn cold_rows({pname}: &Cols_{suffix}) -> Seq<ColdRow> {{\n    {rows_spec}\n}}\n"
        + fold
        + f"\npub fn cold_finish(st: &ColdState, Ghost({pname}): Ghost<&Cols_{suffix}>, Ghost(seen): Ghost<Seq<ColdRow>>) -> (res: Vec<OutRow>)\n"
        + f"    requires\n        st_rel(*st, seen),\n        seen.to_multiset() =~= cold_rows({pname}).to_multiset(),\n{lens}"
        + f"    ensures\n        {ensures},\n{{\n{finish_body.rstrip()}\n}}\n}}\n"
    )
    if "verus!" not in verus_part:
        raise ValueError("verus! block missing")
    return verus_part + "\n" + _glue(res, fields, out_ty, db_path, spec_rs, reference_sql, mode)


# Query constructs DuckDB handles BEFORE or AROUND the aggregate callbacks: the proved fold would see a different set of rows than the spec talks about
# (DISTINCT dedups before `update`: zc_cold(DISTINCT x) silently returned 1 where DuckDB gives 199,374; GROUP BY / OVER / FILTER / HAVING / ORDER BY / LIMIT / JOIN change the row set or the grouping).
_UNSUPPORTED_SQL = re.compile(r"\b(distinct|group\s+by|over|filter|having|order\s+by|limit|offset|join|union|intersect|except|with|window|qualify|sample)\b", re.I)


def refuse_unsupported_sql(sql: str | None) -> None:
    """Loud refusal of an original query that uses a construct the streaming fold does not model (see ``_UNSUPPORTED_SQL``)."""
    if sql is None:
        return
    # `SELECT DISTINCT ...` and `COUNT(DISTINCT ...)` both match; the string literals are blanked first so a quoted word is not a construct
    bare = re.sub(r"'(?:[^']|'')*'", "''", sql)
    m = _UNSUPPORTED_SQL.search(bare)
    if m:
        raise ColdStreamUnsupported(f"the query uses {m.group(1).upper()}: the streaming fold models an ungrouped aggregate over every row of one table with no other operator")


def zero_copy_var(f: str) -> str:
    return f.removeprefix("r#")


def _glue(res: zero_copy.Resolved, fields: list[tuple[str, str]], out_ty: str, db_path: str, spec_rs: str, reference_sql: str | None, mode: str = "aggregate") -> str:
    rn = zero_copy._rust_str
    cap = asm._const_literal(spec_rs, f"ROW_CAP_{res.suffix}")
    reg_params = []
    for (tid, dw, ds), (_f, _t) in zip(res.expect, fields):
        mk = f"zc_cold::decimal({dw}, {ds})" if tid == 19 else f"zc_cold::ltype({tid})"
        reg_params.append(f"        zc_cold::add_param(f, {mk});")
    cols_sql = ", ".join('"' + c.replace('"', '""') + '"' for c in res.columns)
    table_sql = '"' + res.table.replace('"', '""') + '"'
    query = f"SELECT zc_cold({cols_sql}) FROM {table_sql}"
    count_sql = f"SELECT COUNT(*) FROM {table_sql}"
    expected = ", ".join(f"({rn(c)}, {rn(t)})" for c, t in zip(res.columns, res.sql_types))
    slices = []
    for j, (_f, t) in enumerate(fields):
        slices.append(
            f"        let (d{j}, ok{j}) = zc_cold::column(input, {j}, n, std::mem::align_of::<{t}>());\n"
            f"        if !ok{j} {{ zc_cold::fail(info, \"a column vector is not flat, aligned and NULL-free\"); return; }}\n"
            f"        let c{j}: &[{t}] = std::slice::from_raw_parts(d{j} as *const {t}, n);"
        )
    call_args = ", ".join(f"c{j}" for j in range(len(fields)))
    if out_ty == "u64":
        ret_id, write_final = 9, "*(data as *mut u64).add(idx) = res[0].%s;"
    else:
        ret_id, write_final = 16, "match res[0].%s { Some(v) => std::ptr::write_unaligned((data as *mut i128).add(idx), v), None => zc_cold::set_null(result, idx as u64) }"
    # the reference (DuckDB's own answer to the original SQL, same connection) is timed INTERLEAVED with the fold, run for run: a sequential phase would pick up drift
    ref_decl = f"    let rsql = {rn(reference_sql)};\n    let ref_first = query(&db, rsql).expect(\"ref\"); println!(\"REFERENCE_ROW\\x1f{{}}\", ref_first[0][0].clone().unwrap_or(\"NULL\".to_string()));\n    query(&db, rsql).expect(\"ref\");\n    let mut rs = vec![];\n" if reference_sql else ""
    ref_run = "        let t = std::time::Instant::now(); query(&db, rsql).expect(\"ref\"); rs.push(t.elapsed().as_micros());\n" if reference_sql else ""
    ref_report = "    rs.sort();\n    println!(\"REFERENCE_INPLACE_US: {}\", rs[4]);\n" if reference_sql else ""
    field = re.search(r"pub struct OutRow\s*\{\s*pub (\w+):", spec_rs).group(1)
    write_final = write_final % field
    if out_ty == "u64":
        fmt = f"res[0].{field}.to_string()"
    else:
        fmt = f'match res[0].{field} {{ Some(v) => v.to_string(), None => "NULL".to_string() }}'
    if mode == "scalar":
        query = f"SELECT COALESCE(MAX(zc_cold({cols_sql})), 0) FROM {table_sql}"  # MAX over zero rows is NULL; the rows-seen check catches a fold that was never called
        scalar_cb = SCALAR_CB.replace("@@SLICES@@", chr(10).join(slices).replace("zc_cold::fail(info", "zc_cold::fail_scalar(info")).replace("@@CALLARGS@@", call_args).replace("@@FMT@@", fmt)
        scalar_params = "\n".join(r.replace("add_param(", "add_param_scalar(") for r in reg_params)
        register_block = (
            "    ZC_ZERO.store(zc_cold::make_zero(), std::sync::atomic::Ordering::Relaxed);\n"
            "    register_scalar(&db, zc_scalar, |f| {\n" + scalar_params + "\n    });"
        )
        run_body = (
            "        let r = query(&db, sql).expect(\"query\");\n"
            "        assert!(r[0][0].as_deref() == Some(\"0\"), \"cold-stream: the carrier query returned {:?}, not 0\", r[0][0]);\n"
            "        zc_drain_and_finish()"
        )
    else:
        scalar_cb = ""
        register_block = (
            "    register(&db, zc_size, zc_init, zc_update, zc_combine, zc_final, |f| {\n" + "\n".join(reg_params) + "\n    });"
        )
        run_body = (
            "        let r = query(&db, sql).expect(\"query\");\n"
            "        match &r[0][0] { Some(v) => v.clone(), None => \"NULL\".to_string() }"
        )
    return f"""
// ---- plain-Rust glue (untrusted): registers the callbacks, reads DuckDB's vectors, runs the query. ZC-2 is the statement it relies on. ----
mod zc_cold {{
    use std::ffi::{{c_char, c_void, CStr, CString}};

    #[repr(C)]
    #[derive(Clone, Copy)]
    pub struct DResult {{ a: u64, b: u64, c: u64, d: *mut c_void, e: *mut c_char, internal: *mut c_void }}

    #[link(name = "duckdb")]
    extern "C" {{
        fn duckdb_library_version() -> *const c_char;
        fn duckdb_create_config(out: *mut *mut c_void) -> i32;
        fn duckdb_set_config(c: *mut c_void, n: *const c_char, o: *const c_char) -> i32;
        fn duckdb_open_ext(path: *const c_char, out: *mut *mut c_void, cfg: *mut c_void, err: *mut *mut c_char) -> i32;
        fn duckdb_connect(db: *mut c_void, out: *mut *mut c_void) -> i32;
        fn duckdb_query(con: *mut c_void, q: *const c_char, out: *mut DResult) -> i32;
        fn duckdb_result_error(r: *mut DResult) -> *const c_char;
        fn duckdb_destroy_result(r: *mut DResult);
        fn duckdb_row_count(r: *mut DResult) -> u64;
        fn duckdb_value_varchar(r: *mut DResult, col: u64, row: u64) -> *mut c_char;
        fn duckdb_free(p: *mut c_void);
        fn duckdb_data_chunk_get_size(c: *mut c_void) -> u64;
        fn duckdb_data_chunk_get_vector(c: *mut c_void, col: u64) -> *mut c_void;
        fn duckdb_vector_get_data(v: *mut c_void) -> *mut c_void;
        fn duckdb_vector_get_validity(v: *mut c_void) -> *mut u64;
        fn duckdb_vector_ensure_validity_writable(v: *mut c_void);
        fn duckdb_validity_set_row_invalid(v: *mut u64, row: u64);
        fn duckdb_create_logical_type(t: u32) -> *mut c_void;
        fn duckdb_create_decimal_type(w: u8, s: u8) -> *mut c_void;
        fn duckdb_destroy_logical_type(t: *mut *mut c_void);
        fn duckdb_create_aggregate_function() -> *mut c_void;
        fn duckdb_aggregate_function_set_name(f: *mut c_void, n: *const c_char);
        fn duckdb_aggregate_function_add_parameter(f: *mut c_void, t: *mut c_void);
        fn duckdb_aggregate_function_set_return_type(f: *mut c_void, t: *mut c_void);
        fn duckdb_aggregate_function_set_special_handling(f: *mut c_void);
        fn duckdb_aggregate_function_set_error(info: *mut c_void, msg: *const c_char);
        pub fn duckdb_aggregate_function_set_functions(
            f: *mut c_void,
            size: extern "C" fn(*mut c_void) -> u64,
            init: extern "C" fn(*mut c_void, *mut c_void),
            update: extern "C" fn(*mut c_void, *mut c_void, *mut *mut c_void),
            combine: extern "C" fn(*mut c_void, *mut *mut c_void, *mut *mut c_void, u64),
            fin: extern "C" fn(*mut c_void, *mut *mut c_void, *mut c_void, u64, u64),
        );
        fn duckdb_register_aggregate_function(con: *mut c_void, f: *mut c_void) -> i32;
        fn duckdb_create_scalar_function() -> *mut c_void;
        fn duckdb_scalar_function_set_name(f: *mut c_void, n: *const c_char);
        fn duckdb_scalar_function_add_parameter(f: *mut c_void, t: *mut c_void);
        fn duckdb_scalar_function_set_return_type(f: *mut c_void, t: *mut c_void);
        fn duckdb_scalar_function_set_special_handling(f: *mut c_void);
        fn duckdb_scalar_function_set_error(info: *mut c_void, msg: *const c_char);
        fn duckdb_scalar_function_set_function(f: *mut c_void, func: extern "C" fn(*mut c_void, *mut c_void, *mut c_void));
        fn duckdb_register_scalar_function(con: *mut c_void, f: *mut c_void) -> i32;
        fn duckdb_create_int32(v: i32) -> *mut c_void;
        fn duckdb_vector_reference_value(v: *mut c_void, val: *mut c_void);
    }}

    /// ZC-2 was validated against these library versions only.
    const TESTED_VERSIONS: &[&str] = &["v1.5.4"];

    pub struct Db {{ pub con: *mut c_void }}

    pub fn open(path: &str) -> Db {{
        unsafe {{
            let version = CStr::from_ptr(duckdb_library_version()).to_str().unwrap();
            assert!(TESTED_VERSIONS.contains(&version), "cold-stream: linked DuckDB is {{}}, ZC-2 was validated on {{:?}} only", version, TESTED_VERSIONS);
            let mut cfg: *mut c_void = std::ptr::null_mut();
            assert!(duckdb_create_config(&mut cfg) == 0);
            let (n, o) = (CString::new("access_mode").unwrap(), CString::new("READ_ONLY").unwrap());
            assert!(duckdb_set_config(cfg, n.as_ptr(), o.as_ptr()) == 0);
            let (mut db, mut con): (*mut c_void, *mut c_void) = (std::ptr::null_mut(), std::ptr::null_mut());
            let mut err: *mut c_char = std::ptr::null_mut();
            let p = CString::new(path).unwrap();
            assert!(duckdb_open_ext(p.as_ptr(), &mut db, cfg, &mut err) == 0, "open {{}}", path);
            assert!(duckdb_connect(db, &mut con) == 0);
            Db {{ con }}
        }}
    }}

    pub fn query(db: &Db, sql: &str) -> Result<Vec<Vec<Option<String>>>, String> {{
        unsafe {{
            let mut r: DResult = std::mem::zeroed();
            let q = CString::new(sql).unwrap();
            if duckdb_query(db.con, q.as_ptr(), &mut r) != 0 {{
                let m = CStr::from_ptr(duckdb_result_error(&mut r)).to_string_lossy().into_owned();
                duckdb_destroy_result(&mut r);
                return Err(m);
            }}
            let ncols = r.a as usize;
            let nrows = duckdb_row_count(&mut r) as usize;
            let mut out = vec![];
            for row in 0..nrows {{
                let mut line = vec![];
                for c in 0..ncols {{
                    let p = duckdb_value_varchar(&mut r, c as u64, row as u64);
                    if p.is_null() {{ line.push(None); }} else {{ line.push(Some(CStr::from_ptr(p).to_string_lossy().into_owned())); duckdb_free(p as *mut c_void); }}
                }}
                out.push(line);
            }}
            duckdb_destroy_result(&mut r);
            Ok(out)
        }}
    }}

    pub fn decimal(w: u8, s: u8) -> *mut c_void {{ unsafe {{ duckdb_create_decimal_type(w, s) }} }}
    pub fn ltype(t: u32) -> *mut c_void {{ unsafe {{ duckdb_create_logical_type(t) }} }}
    pub fn add_param(f: *mut c_void, mut t: *mut c_void) {{ unsafe {{ duckdb_aggregate_function_add_parameter(f, t); duckdb_destroy_logical_type(&mut t); }} }}
    pub fn fail(info: *mut c_void, msg: &str) {{ unsafe {{ let m = CString::new(msg).unwrap(); duckdb_aggregate_function_set_error(info, m.as_ptr()); }} }}
    pub fn set_null(result: *mut c_void, row: u64) {{ unsafe {{ duckdb_vector_ensure_validity_writable(result); duckdb_validity_set_row_invalid(duckdb_vector_get_validity(result), row); }} }}
    pub fn fail_scalar(info: *mut c_void, msg: &str) {{ unsafe {{ let m = CString::new(msg).unwrap(); duckdb_scalar_function_set_error(info, m.as_ptr()); }} }}
    pub fn constant_zero(out: *mut c_void, zero: *mut c_void) {{ unsafe {{ duckdb_vector_reference_value(out, zero); }} }}
    pub fn make_zero() -> *mut c_void {{ unsafe {{ duckdb_create_int32(0) }} }}
    pub fn register_scalar(db: &Db, f: extern "C" fn(*mut c_void, *mut c_void, *mut c_void), params: impl FnOnce(*mut c_void)) {{
        unsafe {{
            let s = duckdb_create_scalar_function();
            duckdb_scalar_function_set_name(s, CString::new("zc_cold").unwrap().as_ptr());
            params(s);
            let mut r = duckdb_create_logical_type(4);
            duckdb_scalar_function_set_return_type(s, r);
            duckdb_destroy_logical_type(&mut r);
            duckdb_scalar_function_set_special_handling(s);
            duckdb_scalar_function_set_function(s, f);
            assert!(duckdb_register_scalar_function(db.con, s) == 0);
        }}
    }}
    pub fn add_param_scalar(f: *mut c_void, mut t: *mut c_void) {{ unsafe {{ duckdb_scalar_function_add_parameter(f, t); duckdb_destroy_logical_type(&mut t); }} }}
    pub fn result_data(result: *mut c_void) -> *mut c_void {{ unsafe {{ duckdb_vector_get_data(result) }} }}

    /// Data pointer of column `j` of an input chunk after checking: aligned and every row valid (no NULL cell). A constant or dictionary vector would have
    /// no per-row data at this pointer; DuckDB's C aggregate wrapper hands flat vectors (ZC-2 item 1, tested on constant and dictionary-compressed data).
    pub fn column(input: *mut c_void, j: u64, n: usize, align: usize) -> (*mut c_void, bool) {{
        unsafe {{
            let v = duckdb_data_chunk_get_vector(input, j);
            let p = duckdb_vector_get_data(v);
            let validity = duckdb_vector_get_validity(v);
            let mut ok = !p.is_null() && (p as usize) % align == 0;
            if !validity.is_null() {{
                for w in 0..n / 64 {{ ok &= *validity.add(w) == u64::MAX; }}
                if n % 64 != 0 {{ let mask = (1u64 << (n % 64)) - 1; ok &= *validity.add(n / 64) & mask == mask; }}
            }}
            (p, ok)
        }}
    }}

    pub fn register(db: &Db, size: extern "C" fn(*mut c_void) -> u64, init: extern "C" fn(*mut c_void, *mut c_void), update: extern "C" fn(*mut c_void, *mut c_void, *mut *mut c_void), combine: extern "C" fn(*mut c_void, *mut *mut c_void, *mut *mut c_void, u64), fin: extern "C" fn(*mut c_void, *mut *mut c_void, *mut c_void, u64, u64), params: impl FnOnce(*mut c_void)) {{
        unsafe {{
            let f = duckdb_create_aggregate_function();
            duckdb_aggregate_function_set_name(f, CString::new("zc_cold").unwrap().as_ptr());
            params(f);
            let mut r = duckdb_create_logical_type({ret_id});
            duckdb_aggregate_function_set_return_type(f, r);
            duckdb_destroy_logical_type(&mut r);
            duckdb_aggregate_function_set_special_handling(f);
            duckdb_aggregate_function_set_functions(f, size, init, update, combine, fin);
            assert!(duckdb_register_aggregate_function(db.con, f) == 0);
        }}
    }}
}}

use zc_cold::*;

const ZC_ROW_CAP: u64 = {cap};
static ZC_ROWS_SEEN: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(u64::MAX);

/// The `duckdb_aggregate_state` the callbacks receive is the state memory itself (checked: init and update see the same address).
unsafe fn mem(p: *mut std::ffi::c_void) -> *mut std::ffi::c_void {{
    p
}}

unsafe fn load(p: *mut std::ffi::c_void) -> ColdState {{
    let w = mem(p) as *const u64;
    let lo = std::ptr::read_unaligned(w);
    let hi = std::ptr::read_unaligned(w.add(1));
    ColdState {{ acc: (((hi as u128) << 64) | lo as u128) as i128, cnt: std::ptr::read_unaligned(w.add(2)), rows: std::ptr::read_unaligned(w.add(3)) }}
}}

unsafe fn store(p: *mut std::ffi::c_void, s: &ColdState) {{
    let w = mem(p) as *mut u64;
    let a = s.acc as u128;
    std::ptr::write_unaligned(w, a as u64);
    std::ptr::write_unaligned(w.add(1), (a >> 64) as u64);
    std::ptr::write_unaligned(w.add(2), s.cnt);
    std::ptr::write_unaligned(w.add(3), s.rows);
}}

extern "C" fn zc_size(_i: *mut std::ffi::c_void) -> u64 {{ 32 }}

extern "C" fn zc_init(_i: *mut std::ffi::c_void, s: *mut std::ffi::c_void) {{
    unsafe {{ store(s, &cold_init()); }}
}}

extern "C" fn zc_update(info: *mut std::ffi::c_void, input: *mut std::ffi::c_void, states: *mut *mut std::ffi::c_void) {{
    unsafe {{
        let n = duckdb_data_chunk_get_size_pub(input) as usize;
        if n == 0 {{ return; }}
        let p0 = *states;
        // all rows of the chunk must belong to one state (an ungrouped aggregate); a branch-free XOR reduction, not an early-exit loop (2 us per vector otherwise)
        let mut diff = 0usize;
        for i in 1..n {{ diff |= (mem(*states.add(i)) as usize) ^ (mem(p0) as usize); }}
        if diff != 0 {{ fail(info, "the chunk's rows belong to different aggregate states (grouped aggregation)"); return; }}
{chr(10).join(slices)}
        let mut st = load(p0);
        if st.rows + n as u64 > ZC_ROW_CAP {{ fail(info, "more rows than the catalog row cap"); return; }}
        if !cold_update(&mut st, {call_args}, Ghost::assume_new()) {{ fail(info, "a cell is outside the catalog cap"); return; }}
        store(p0, &st);
    }}
}}

extern "C" fn zc_combine(info: *mut std::ffi::c_void, src: *mut *mut std::ffi::c_void, tgt: *mut *mut std::ffi::c_void, n: u64) {{
    unsafe {{
        for i in 0..n as usize {{
            let s = load(*src.add(i));
            let mut t = load(*tgt.add(i));
            if t.rows + s.rows > ZC_ROW_CAP {{ fail(info, "more rows than the catalog row cap"); return; }}
            cold_combine(&mut t, &s, Ghost::assume_new(), Ghost::assume_new());
            store(*tgt.add(i), &t);
        }}
    }}
}}

extern "C" fn zc_final(_i: *mut std::ffi::c_void, src: *mut *mut std::ffi::c_void, result: *mut std::ffi::c_void, n: u64, off: u64) {{
    unsafe {{
        let data = result_data(result);
        for k in 0..n as usize {{
            let st = load(*src.add(k));
            ZC_ROWS_SEEN.store(st.rows, std::sync::atomic::Ordering::SeqCst);
            let res = cold_finish(&st, Ghost::assume_new(), Ghost::assume_new());
            let idx = off as usize + k;
            {write_final}
        }}
    }}
}}

{scalar_cb}
extern "C" {{
    #[link_name = "duckdb_data_chunk_get_size"]
    fn duckdb_data_chunk_get_size_pub(c: *mut std::ffi::c_void) -> u64;
}}

fn main() {{
    let db = open({rn(db_path)});
    // the same settings for the fold and for the in-place reference (one connection): a bounded buffer pool (DuckDB defaults to 80% of RAM), 8 threads, spill under the run dir
    let tmp = std::env::var("LEMMA_ZC_TEMP_DIR").unwrap_or_else(|_| ".zc_duck_tmp".to_string());
    let mem = std::env::var("LEMMA_ZC_MEMORY_LIMIT").unwrap_or_else(|_| "3GB".to_string());
    for set in [format!("PRAGMA memory_limit='{{}}'", mem), "PRAGMA threads=8".to_string(), format!("PRAGMA temp_directory='{{}}'", tmp)] {{ query(&db, &set).expect("pragma"); }}
    println!("DUCKDB_SETTINGS: memory_limit={{}} threads=8 temp_directory={{}}", mem, tmp);
    // the stored types of the pinned table must be the declared ones (the spec's scaled literals depend on them): checked again when it runs
    let described = query(&db, {rn(f"SELECT column_name, column_type FROM (DESCRIBE {table_sql})")}).expect("describe");
    for (col, ty) in [{expected}] {{
        let found = described.iter().find(|r| r[0].as_deref().map_or(false, |n| n.eq_ignore_ascii_case(col))).unwrap_or_else(|| panic!("cold-stream: column {{}} is not in the table", col));
        assert!(found[1].as_deref() == Some(ty), "cold-stream: column {{}} is stored as {{:?}}, the spec declares {{}}", col, found[1], ty);
    }}
{register_block}
    let sql = {rn(query)};
    // ZC-2 item 3 (every row exactly once): the rows the final state saw must be the rows the engine counts for the table, after EVERY execution
    let table_rows: u64 = query(&db, {rn(count_sql)}).expect("count")[0][0].as_ref().unwrap().parse().unwrap();
    let check_rows = || assert!(ZC_ROWS_SEEN.load(std::sync::atomic::Ordering::SeqCst) == table_rows, "cold-stream: the fold saw {{}} rows, the table has {{}}", ZC_ROWS_SEEN.load(std::sync::atomic::Ordering::SeqCst), table_rows);
    let run_once = || -> String {{
{run_body}
    }};
    let t0 = std::time::Instant::now();
    let shown = run_once();
    println!("COLD_FIRST_US: {{}}", t0.elapsed().as_micros());
    check_rows();
    let mut samples = vec![];
    for _ in 0..2 {{ run_once(); }}
{ref_decl}    for _ in 0..9 {{
        let t = std::time::Instant::now();
        let r = run_once();
        samples.push(t.elapsed().as_micros());
        assert!(r == shown, "the result changed between runs");
        check_rows();
{ref_run}    }}
    samples.sort();
    println!("QUERY_LATENCY_US: {{}}", samples[4]);
    println!("QUERY_LATENCY_BEST_US: {{}}", samples[0]);
    println!("ROW\\x1f{{}}", shown);
{ref_report}}}

"""


SCALAR_CB = '\n// ---- scalar mode: DuckDB calls zc_cold once per input vector inside a projection (in parallel); each worker thread folds into ITS OWN state with the verified\n// cold_update; the function returns a constant vector (no per-row write) that `MAX` consumes. After the query the per-thread states are merged with the verified\n// cold_combine and finished with cold_finish. ZC-2 (scalar form): every row of the table reaches exactly one call of zc_cold. ----\nstruct ZcSlot {\n    st: std::sync::Mutex<ColdState>,\n}\nstatic ZC_SLOTS: std::sync::Mutex<Vec<std::sync::Arc<ZcSlot>>> = std::sync::Mutex::new(Vec::new());\nstatic ZC_ZERO: std::sync::atomic::AtomicPtr<std::ffi::c_void> = std::sync::atomic::AtomicPtr::new(std::ptr::null_mut());\nthread_local! {\n    static ZC_MINE: std::sync::Arc<ZcSlot> = {\n        let slot = std::sync::Arc::new(ZcSlot { st: std::sync::Mutex::new(cold_init()) });\n        ZC_SLOTS.lock().unwrap().push(slot.clone());\n        slot\n    };\n}\n\nextern "C" fn zc_scalar(info: *mut std::ffi::c_void, input: *mut std::ffi::c_void, out: *mut std::ffi::c_void) {\n    unsafe {\n        let n = duckdb_data_chunk_get_size_pub(input) as usize;\n        if n == 0 { return; }\n@@SLICES@@\n        ZC_MINE.with(|slot| {\n            let mut st = slot.st.lock().unwrap();\n            if st.rows + n as u64 > ZC_ROW_CAP { fail_scalar(info, "more rows than the catalog row cap"); return; }\n            if !cold_update(&mut *st, @@CALLARGS@@, Ghost::assume_new()) { fail_scalar(info, "a cell is outside the catalog cap"); }\n        });\n        constant_zero(out, ZC_ZERO.load(std::sync::atomic::Ordering::Relaxed));\n    }\n}\n\n/// After a query: merge every thread\'s state (verified combine), reset them for the next execution, finish (verified), format the one result row.\nfn zc_drain_and_finish() -> String {\n    let parts: Vec<ColdState> = ZC_SLOTS.lock().unwrap().iter().map(|s| std::mem::replace(&mut *s.st.lock().unwrap(), cold_init())).collect();\n    let mut total = cold_init();\n    for p in parts {\n        assert!(total.rows + p.rows <= ZC_ROW_CAP, "cold-stream: more rows than the catalog row cap");\n        cold_combine(&mut total, &p, Ghost::assume_new(), Ghost::assume_new());\n    }\n    ZC_ROWS_SEEN.store(total.rows, std::sync::atomic::Ordering::SeqCst);\n    let res = cold_finish(&total, Ghost::assume_new(), Ghost::assume_new());\n    @@FMT@@\n}\n'
