"""Library mode of the assembler: the proved ``run_query`` as a shared library with one fixed C entry point instead of ``main``.

The ``verus!`` part is exactly what :func:`declarative_spec.assemble.assemble_declarative_program` emits (spec, agent body, host lemmas,
verified ``load_cols_*``). Only the unverified host code after it differs. ``main`` reads column files; the library takes the same
columns as caller buffers through ``lemma_run``. That entry point is a FIXED TEMPLATE, the same text for every query apart from
the per-field decode lines generated from the spec's column structs: no agent code is in it. Its caller in research_loop
(the in-engine executor cache) emits it only when the feature flag of lemma.toml is on.

C ABI (version 2; the C header is ``lemma_abi.h`` of the database extension):

    struct LemmaCol   { const uint8_t *data; uint64_t len; uint64_t n; };     // len bytes at data; n values
    struct LemmaParam { uint32_t kind; const uint8_t *data; uint64_t len; };  // one query-template parameter value
    struct LemmaOut   { uint8_t *ptr; uint64_t len; uint64_t cap; };          // owned by the library: release with lemma_free_out

    uint32_t    lemma_abi_version(void);       // 2
    const char *lemma_query_sql(void);         // the SQL the spec was emitted from (NUL-terminated)
    const char *lemma_input_layout(void);      // one line per LemmaCol, in order: "rows <table>" or "<table>.<field> <rust type>"
    const char *lemma_output_layout(void);     // one line per result column: "<field> <rust type>"
    const char *lemma_param_layout(void);      // one line per LemmaParam, in run_query's order: "<name> <rust type> <lo> <hi>" (- = none)
    int32_t     lemma_run(const LemmaCol *cols, uint64_t ncols, const LemmaParam *params, uint64_t nparams, LemmaOut *out);
    void        lemma_free_out(LemmaOut *out);

Inputs, per column struct of the spec in order: one ``rows`` entry (``n`` = the table's row count, no data), then one entry per
field in struct order, in the bytes of the column-file format of ``main`` (little-endian cells; a string is a u32 byte length and
its UTF-8 bytes; a ``__dict`` entry has ``n`` = its entry count). ``lemma_run`` decodes them into the ``Vec``s the verified loaders
take, checks EVERY data assumption ``main`` checks (the same generated checks: lengths, catalog row/value caps, dictionary codes,
unique keys, join caps), and only then calls the proved loaders and ``run_query``. A violated assumption is a nonzero return with the
message in ``out``; ``run_query`` never runs on unchecked data. A panic never crosses the C boundary (``catch_unwind``).

Parameters (a query template, ``declarative_spec/templates.py``; new in version 2): one ``LemmaParam`` per ``// PARAM`` line of
the spec, in ``run_query``'s order. ``kind`` 1 = an integer, ``data`` its 8 bytes as a little-endian i64 (BIGINT as is, DATE the day
number since 1970-01-01, DECIMAL the value * 10**scale: what ``run_query`` takes); ``kind`` 4 = a VARCHAR, ``data`` its UTF-8 bytes.
The fixed template checks the count, each kind and length, that the value fits the parameter's Rust type and lies in the range
``run_query`` ``requires`` (the check the command line of ``main`` gets), before any column is decoded; a violation is a nonzero
return like a violated data assumption. A spec without parameters takes ``nparams == 0``.

A stateful spec (lemma.toml ``stateful``) is refused: its runtime needs the caller's data version (``docs/STATEFUL.md``), which this
ABI does not carry yet.

Result (``out`` on return 0): ``LMR1``, u64 load_us, u64 run_us, u64 rows, u32 columns, one kind byte per column
(1 integer as i128, 2 f64, 3 bool, 4 string), then column-major per column: one validity byte per row (0 = NULL), then the cells
(i128 16 bytes, f64 8 bytes, bool 1 byte, string u32 length + bytes; a NULL cell holds the zero value).
"""

from __future__ import annotations

import re

from declarative_spec.assemble import (
    _WIDTH,
    _join_cap_checks,
    _loader_fn,
    _local_ident,
    _out_row_fields,
    _run_call,
    _runtime_checks,
    _stitch_verus,
)

ABI_VERSION = 2
KIND_INT, KIND_F64, KIND_BOOL, KIND_STR = 1, 2, 3, 4
_INT_TYPES = ("u8", "u16", "u32", "u64", "usize", "i8", "i16", "i32", "i64", "i128")


def input_layout(verus_part: str) -> list[str]:
    """The ``LemmaCol`` order: ``rows <table>``, then ``<table>.<field> <type>`` per field, per column struct in spec order."""
    out: list[str] = []
    for struct_name, body in re.findall(r"pub struct (Cols_[A-Za-z0-9_]+)\s*\{([^}]+)\}", verus_part, re.DOTALL):
        suffix = struct_name.removeprefix("Cols_")
        out.append(f"rows {suffix}")
        for fname, fty in re.findall(r"pub\s+((?:r#)?[A-Za-z_][A-Za-z0-9_]*):\s+Vec<([^>]+)>", body):
            out.append(f"{suffix}.{_local_ident(fname)} {fty}")
    return out


def output_layout(verus_part: str) -> list[tuple[str, str]]:
    """``(field, rust type)`` of each result column; refuses a result that is not ``Vec<OutRow>``."""
    if not re.search(r"pub fn run_query\([^)]*\)\s*->\s*\(res: Vec<OutRow>\)", verus_part):
        result = re.search(r"pub fn run_query\([^)]*\)\s*->\s*\(res: ([^)]+)\)", verus_part)
        raise ValueError(
            f"library mode returns OutRow rows; this run_query returns {result.group(1) if result else 'nothing'}"
        )
    fields = [(_local_ident(f), t.strip()) for f, t in _out_row_fields(verus_part)]
    for name, ty in fields:
        _kind(ty, name)
    return fields


def _kind(ty: str, name: str) -> int:
    inner = ty[len("Option<") : -1] if ty.startswith("Option<") else ty
    if inner in _INT_TYPES:
        return KIND_INT
    if inner == "f64":
        return KIND_F64
    if inner == "bool":
        return KIND_BOOL
    if inner == "String":
        return KIND_STR
    raise ValueError(f"library mode cannot return OutRow field {name}: {ty}")


def _static(name: str, text: str) -> str:
    """A NUL-terminated byte array, so the C side reads it as a string with no unsafe code here."""
    data = text.encode("utf-8")
    if b"\x00" in data:
        raise ValueError("a NUL byte in an embedded string")
    body, size = f"[{', '.join(str(b) for b in data + bytes(1))}]", len(data) + 1
    return f"static {name}: [u8; {size}] = {body};\n"


def _decode_field(index: int, suffix: str, fname: str, fty: str) -> str:
    var = f"{suffix}_{_local_ident(fname)}"
    label = f"{suffix}.{_local_ident(fname)}"
    if fty == "String":
        return f'    let {var}: Vec<String> = lemma_strings(&cols[{index}], "{label}");\n'
    if fty == "bool":
        return f'    let {var}: Vec<bool> = lemma_fixed(&cols[{index}], "{label}", |b: [u8; 1]| b[0] != 0);\n'
    if fty in _WIDTH:
        return f'    let {var}: Vec<{fty}> = lemma_fixed(&cols[{index}], "{label}", {fty}::from_le_bytes);\n'
    raise ValueError(f"library mode cannot load column type {fty}")


def _encode_column(fname: str, fty: str) -> str:
    access = f"r.{fname}"
    option = fty.startswith("Option<")
    kind = _kind(fty, fname)
    if kind == KIND_INT:
        put = "out.extend_from_slice(&(({v}) as i128).to_le_bytes());"
        zero = "out.extend_from_slice(&0i128.to_le_bytes());"
    elif kind == KIND_F64:
        put = "out.extend_from_slice(&({v}).to_le_bytes());"
        zero = "out.extend_from_slice(&0f64.to_le_bytes());"
    elif kind == KIND_BOOL:
        put = "out.push(if {v} { 1u8 } else { 0u8 });"
        zero = "out.push(0u8);"
    else:
        put = "lemma_put_str(&mut out, {v});"
        zero = "lemma_put_str(&mut out, \"\");"
    if option:
        valid = f"        out.push(if {access}.is_some() {{ 1u8 }} else {{ 0u8 }});\n"
        deref = "v" if kind == KIND_STR else "*v"
        cell = f"        match &{access} {{ Some(v) => {{ {put.format(v=deref)} }} None => {{ {zero} }} }}\n"
    else:
        valid = "        out.push(1u8);\n"
        value = f"&{access}" if kind == KIND_STR else access
        cell = f"        {put.format(v=value)}\n"
    return f"    for r in res.iter() {{\n{valid}    }}\n    for r in res.iter() {{\n{cell}    }}\n"


# The fixed host template. `unsafe` appears ONLY here, in four small functions, each commented with the caller's contract.
_TEMPLATE_HEAD = r"""
// ===== HOST C ABI (fixed template, not agent code; outside verus!, unverified, reviewed) =====
#[repr(C)]
pub struct LemmaCol {
    pub data: *const u8,
    pub len: u64,
    pub n: u64,
}

#[repr(C)]
pub struct LemmaParam {
    pub kind: u32,
    pub data: *const u8,
    pub len: u64,
}

const LEMMA_PARAM_INT: u32 = 1;
const LEMMA_PARAM_STR: u32 = 4;

#[repr(C)]
pub struct LemmaOut {
    pub ptr: *mut u8,
    pub len: u64,
    pub cap: u64,
}

#[no_mangle]
pub extern "C" fn lemma_abi_version() -> u32 {
    __ABI__
}

#[no_mangle]
pub extern "C" fn lemma_query_sql() -> *const u8 {
    LEMMA_SQL.as_ptr()
}

#[no_mangle]
pub extern "C" fn lemma_input_layout() -> *const u8 {
    LEMMA_INPUT_LAYOUT.as_ptr()
}

#[no_mangle]
pub extern "C" fn lemma_output_layout() -> *const u8 {
    LEMMA_OUTPUT_LAYOUT.as_ptr()
}

#[no_mangle]
pub extern "C" fn lemma_param_layout() -> *const u8 {
    LEMMA_PARAM_LAYOUT.as_ptr()
}

// UNSAFE 1/4. Contract: `ptr` points to `n` initialized T (the caller's LemmaCol or LemmaParam array) that outlive the call.
fn lemma_slice<'a, T>(ptr: *const T, n: u64, what: &str) -> &'a [T] {
    if n == 0 {
        return &[];
    }
    assert!(!ptr.is_null(), "lemma_run: {} is null", what);
    unsafe { std::slice::from_raw_parts(ptr, n as usize) }
}

// UNSAFE 2/4. Contract: `data` points to `len` readable bytes (a LemmaCol or LemmaParam buffer) that outlive the call and are
// not written during it.
fn lemma_bytes<'a>(data: *const u8, len: u64, what: &str) -> &'a [u8] {
    if len == 0 {
        return &[];
    }
    assert!(!data.is_null(), "lemma_run: {} buffer is null", what);
    unsafe { std::slice::from_raw_parts(data, len as usize) }
}

fn lemma_col_bytes<'a>(col: &LemmaCol) -> &'a [u8] {
    lemma_bytes(col.data, col.len, "a column")
}

fn lemma_param_int(p: &LemmaParam, name: &str) -> i64 {
    assert!(p.kind == LEMMA_PARAM_INT, "parameter {}: kind {}, expected {} (an integer)", name, p.kind, LEMMA_PARAM_INT);
    let bytes = lemma_bytes(p.data, p.len, "a parameter");
    assert!(bytes.len() == 8, "parameter {}: {} bytes, an integer is 8", name, bytes.len());
    i64::from_le_bytes(bytes.try_into().unwrap())
}

fn lemma_param_str(p: &LemmaParam, name: &str) -> String {
    assert!(p.kind == LEMMA_PARAM_STR, "parameter {}: kind {}, expected {} (a string)", name, p.kind, LEMMA_PARAM_STR);
    String::from_utf8(lemma_bytes(p.data, p.len, "a parameter").to_vec()).expect("a string parameter is not UTF-8")
}

// UNSAFE 3/4. Contract: `out` points to a writable LemmaOut. The bytes move to the caller, who returns them with lemma_free_out.
fn lemma_write_out(out: *mut LemmaOut, bytes: Vec<u8>) {
    let mut bytes = std::mem::ManuallyDrop::new(bytes);
    let value = LemmaOut { ptr: bytes.as_mut_ptr(), len: bytes.len() as u64, cap: bytes.capacity() as u64 };
    unsafe { out.write(value) };
}

// UNSAFE 4/4. Contract: `out` was filled by lemma_run of this library and not freed before; it is reset to empty.
#[no_mangle]
pub extern "C" fn lemma_free_out(out: *mut LemmaOut) {
    if out.is_null() {
        return;
    }
    unsafe {
        let o = &mut *out;
        if !o.ptr.is_null() {
            drop(Vec::from_raw_parts(o.ptr, o.len as usize, o.cap as usize));
        }
        o.ptr = std::ptr::null_mut();
        o.len = 0;
        o.cap = 0;
    }
}

fn lemma_fixed<T, const W: usize>(col: &LemmaCol, label: &str, conv: fn([u8; W]) -> T) -> Vec<T> {
    let bytes = lemma_col_bytes(col);
    let n = col.n as usize;
    assert!(n.checked_mul(W) == Some(bytes.len()), "{}: {} bytes for {} values of {} bytes", label, bytes.len(), n, W);
    bytes.chunks_exact(W).map(|c| conv(c.try_into().unwrap())).collect()
}

fn lemma_strings(col: &LemmaCol, label: &str) -> Vec<String> {
    let bytes = lemma_col_bytes(col);
    let n = col.n as usize;
    let mut out: Vec<String> = Vec::with_capacity(n);
    let mut off: usize = 0;
    while out.len() < n {
        assert!(off + 4 <= bytes.len(), "{}: string buffer ends early", label);
        let len = u32::from_le_bytes(bytes[off..off + 4].try_into().unwrap()) as usize;
        off += 4;
        assert!(off + len <= bytes.len(), "{}: string buffer ends early", label);
        out.push(String::from_utf8(bytes[off..off + len].to_vec()).expect("a string cell is not UTF-8"));
        off += len;
    }
    assert!(off == bytes.len(), "{}: string buffer has trailing bytes", label);
    out
}

fn lemma_put_str(out: &mut Vec<u8>, s: &str) {
    out.extend_from_slice(&(s.len() as u32).to_le_bytes());
    out.extend_from_slice(s.as_bytes());
}

fn lemma_panic_message(payload: Box<dyn std::any::Any + Send>) -> String {
    if let Some(s) = payload.downcast_ref::<String>() {
        s.clone()
    } else if let Some(s) = payload.downcast_ref::<&str>() {
        s.to_string()
    } else {
        "lemma_run: panic without a message".to_string()
    }
}

#[no_mangle]
pub extern "C" fn lemma_run(
    cols: *const LemmaCol,
    ncols: u64,
    params: *const LemmaParam,
    nparams: u64,
    out: *mut LemmaOut,
) -> i32 {
    if out.is_null() {
        return 2;
    }
    std::panic::set_hook(Box::new(|_| {})); // the message goes back through `out`, not to the host's stderr
    let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        assert!(ncols == __NCOLS__, "lemma_run: {} column buffers, the layout has __NCOLS__", ncols);
        assert!(nparams == __NPARAMS__, "lemma_run: {} parameters, this query takes __NPARAMS__", nparams);
        lemma_execute(lemma_slice(cols, ncols, "cols"), lemma_slice(params, nparams, "params"))
    }));
    match outcome {
        Ok(bytes) => {
            lemma_write_out(out, bytes);
            0
        }
        Err(payload) => {
            lemma_write_out(out, lemma_panic_message(payload).into_bytes());
            1
        }
    }
}
"""


def param_layout(verus_part: str) -> list[str]:
    """The ``LemmaParam`` order: ``<name> <rust type> <lo> <hi>`` per ``// PARAM`` line of the spec (``-`` = no range)."""
    from declarative_spec.templates import spec_params

    return [f"{name} {ty} {'-' if lo is None else lo} {'-' if hi is None else hi}" for name, ty, lo, hi in spec_params(verus_part)]


def _param_decode(verus_part: str) -> tuple[str, list[str]]:
    """Decode and check every query-template parameter (the ``main`` command-line check of ``assemble._param_prelude``, from the
    ``LemmaParam`` array): kind, length, fits the Rust type, in the ``requires`` range. Returns the code and the run_query arguments."""
    from declarative_spec.templates import spec_params

    lines: list[str] = []
    args: list[str] = []
    for index, (name, ty, lo, hi) in enumerate(spec_params(verus_part)):
        var = f"param_{name}"
        if ty == "String":
            lines.append(f'    let {var}: String = lemma_param_str(&params[{index}], "{name}");\n')
            args.append(f"&{var}")
            continue
        if ty not in ("i64", "i32"):
            raise ValueError(f"library mode cannot pass parameter {name} of type {ty}")
        if ty == "i64":
            lines.append(f'    let {var}: i64 = lemma_param_int(&params[{index}], "{name}");\n')
        else:
            lines.append(f'    let {var}_i64: i64 = lemma_param_int(&params[{index}], "{name}");\n')
            lines.append(
                f'    let {var}: {ty} = <{ty}>::try_from({var}_i64).unwrap_or_else(|_| panic!("parameter {name} = {{}} does not fit {ty}", {var}_i64));\n'
            )
        if lo is not None and hi is not None:
            lines.append(
                f'    assert!(({var} as i128) >= {lo}i128 && ({var} as i128) <= {hi}i128, "parameter {name} = {{}} is outside its declared range [{lo}, {hi}]", {var});\n'
            )
        args.append(var)
    return "".join(lines), args


def assemble_library_program(spec_rs: str, agent_body: str, *, helpers: str = "", sql: str) -> str:
    """The library program: the verified part of :func:`assemble_declarative_program` plus the fixed C entry point (no ``main``)."""
    from declarative_spec import stateful

    if stateful.is_stateful(spec_rs):
        raise ValueError(
            "library mode does not take a stateful spec yet: its runtime needs the caller's data version (refresh/execute_at, "
            "docs/STATEFUL.md) and ABI version 2 carries none; run the query in-DuckDB with stateful = false"
        )
    verus_part = _stitch_verus(spec_rs, agent_body, helpers)
    param_code, param_args = _param_decode(verus_part)
    params = param_layout(verus_part)
    outputs = output_layout(verus_part)
    layout = input_layout(verus_part)
    structs = re.findall(r"pub struct (Cols_[A-Za-z0-9_]+)\s*\{([^}]+)\}", verus_part, re.DOTALL)
    loaders: list[str] = []
    load: list[str] = []
    args: list[str] = []
    index = 0
    for struct_name, body in structs:
        suffix = struct_name.removeprefix("Cols_")
        fields = re.findall(r"pub\s+((?:r#)?[A-Za-z_][A-Za-z0-9_]*):\s+Vec<([^>]+)>", body)
        lines = [
            f'    assert!(cols[{index}].len == 0, "{suffix}: the rows entry carries no data");\n',
            f"    let n_{suffix}: usize = cols[{index}].n as usize;\n",
        ]
        index += 1
        for fname, fty in fields:
            lines.append(_decode_field(index, suffix, fname, fty))
            index += 1
        for fname, _fty in fields:
            if fname.endswith("__dict"):
                continue
            var = f"{suffix}_{_local_ident(fname)}"
            lines.append(
                f'    assert!({var}.len() == n_{suffix}, "{suffix}.{_local_ident(fname)}: {{}} values for {{}} rows", {var}.len(), n_{suffix});\n'
            )
        # The same runtime checks `main` makes: every non-length `valid_cols` conjunct (catalog caps, codes, unique keys).
        lines.extend(c + "\n" for c in _runtime_checks(verus_part, suffix, fields))
        call = ", ".join([f"n_{suffix}"] + [f"{suffix}_{_local_ident(f)}" for f, _ in fields])
        lines.append(f"    let cols_{suffix} = load_cols_{suffix}({call});\n")
        load.append("".join(lines))
        loaders.append(_loader_fn(verus_part, struct_name, fields))
        args.append(f"&cols_{suffix}")
    run_call, arc_lets = _run_call(verus_part, args)
    if param_args:
        run_call = run_call[:-1] + (", " if run_call != "run_query()" else "") + ", ".join(param_args) + ")"

    kinds = ", ".join(str(_kind(ty, name)) for name, ty in outputs)
    execute = "fn lemma_execute(cols: &[LemmaCol], params: &[LemmaParam]) -> Vec<u8> {\n"
    execute += "    let _ = params;\n" if not params else ""
    execute += param_code  # every parameter is checked before a column is decoded
    execute += "    let load_start = std::time::Instant::now();\n"
    execute += "".join(load)
    execute += _join_cap_checks(verus_part)
    execute += arc_lets
    execute += "    let load_us = load_start.elapsed().as_micros() as u64;\n"
    execute += "    let run_start = std::time::Instant::now();\n"
    execute += f"    let res = {run_call};\n"
    execute += "    let run_us = run_start.elapsed().as_micros() as u64;\n"
    execute += "    let mut out: Vec<u8> = Vec::new();\n"
    execute += '    out.extend_from_slice(b"LMR1");\n'
    execute += "    out.extend_from_slice(&load_us.to_le_bytes());\n"
    execute += "    out.extend_from_slice(&run_us.to_le_bytes());\n"
    execute += "    out.extend_from_slice(&(res.len() as u64).to_le_bytes());\n"
    execute += f"    out.extend_from_slice(&({len(outputs)}u32).to_le_bytes());\n"
    execute += f"    out.extend_from_slice(&[{kinds}]);\n"
    for name, ty in outputs:
        execute += _encode_column(name, ty)
    execute += "    out\n}\n"

    closed = verus_part.rstrip()
    if not closed.endswith("}"):
        raise ValueError("verus block did not end at '}'")
    verus_with_loaders = closed[:-1] + "\n" + "\n\n".join(loaders) + "\n}\n"
    statics = (
        _static("LEMMA_SQL", sql)
        + _static("LEMMA_INPUT_LAYOUT", "\n".join(layout))
        + _static("LEMMA_OUTPUT_LAYOUT", "\n".join(f"{n} {t}" for n, t in outputs))
        + _static("LEMMA_PARAM_LAYOUT", "\n".join(params))
    )
    head = (
        _TEMPLATE_HEAD.replace("__ABI__", str(ABI_VERSION))
        .replace("__NCOLS__", str(len(layout)))
        .replace("__NPARAMS__", str(len(params)))
    )
    return verus_with_loaders + head + "\n" + statics + "\n" + execute
