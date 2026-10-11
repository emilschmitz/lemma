"""LEMMA_ZERO_COPY=1 (default off, never chosen silently): run `run_query` on slices borrowed from pinned DuckDB result chunks instead of Vecs
copied out of them.

OPTIONAL PATH. One input table; every column a fixed-width signed integer / DECIMAL / DATE loaded at exactly DuckDB's storage width,
no NULL cells; the sequential and the ``Arc`` parallel shape. Anything else raises ``ZeroCopyUnsupported`` at assemble time, loudly, with the
reason: there is no fallback to the copy path (and the copy path never falls back to this one).
The design, the trusted statement ZC-1 and what is not covered: research_loop/menus/zero_copy_lease_PROPOSAL.md; the switch-on criteria:
research_loop/menus/zero_copy_gate.md.

What changes against ``assemble_declarative_program``:

* the struct field ``pub v: Vec<T>`` becomes ``pub v: PinnedCol<T>`` (``zero_copy_lib.rs``: verified, its view is the concatenation of the
  chunks, so every emitted spec statement ``t.v@[i]`` is unchanged) and ``valid_cols`` gains ``t.v.wf()`` and, for every column after the first,
  ``t.v.offs@ == t.first.offs@`` (all columns of one pin have the same chunk boundaries);
* the loader fn takes the borrowed columns instead of Vecs (verified: ``requires`` restates ``valid_cols``, ``ensures valid_cols``);
* ``main`` pins the SELECT through the C API (``zero_copy_ffi.rs``), leaks the pin (the slices are ``'static``), checks the exact declared
  type of every column (type id, DECIMAL precision and scale) and the other loader facts, runs the SAME runtime checks of the ``valid_cols`` caps
  over the borrowed memory, then calls ``run_query``.

The assembler is given the schema model (the declared types, the real table and column names) and the stored types of the database that will be
pinned, and refuses any mismatch at assemble time (``_resolve``). The generated ``main`` checks the stored types again when it runs.

``mode="copy"`` is a measurement control, not a product path: the same pin, then a memcpy into one ``Vec`` (the native-loader alternative:
no Python, no file, but a copy), run on the unchanged spec.
"""

from __future__ import annotations

import json
import lemma_config
import re
from dataclasses import dataclass
from pathlib import Path

from declarative_spec import assemble as asm
from declarative_spec import parallel
from declarative_spec.schema_types import (
    ColumnTypeInfo,
    DeclarativeUnsupported,
    SchemaModel,
    classify_sql_type,
    rust_ident,
)

_HERE = Path(__file__).resolve().parent
_NATIVE = {"i8", "i16", "i32", "i64", "i128"}
_BYTES = {"i8": 1, "i16": 2, "i32": 4, "i64": 8, "i128": 16}
# duckdb_type ids (duckdb.h)
_TYPE_ID = {"i8": 2, "i16": 3, "i32": 4, "i64": 5, "i128": 16}
_DATE_ID = 13
_DECIMAL_ID = 19
# spellings of one type (`DESCRIBE` says INTEGER, the schema model may say int)
_SYNONYM = {"int": "integer", "int4": "integer", "int8": "bigint", "int64": "bigint"}


class ZeroCopyUnsupported(DeclarativeUnsupported):
    """The query is outside what the zero-copy path handles (or the flag is off)."""


def enabled() -> bool:
    # WIP/parked: lemma.toml [wip] zero_copy (default false), see research_loop/menus/pin_path_archive.md
    return bool(lemma_config.get("zero_copy"))


def lib_rs() -> str:
    return (_HERE / "zero_copy_lib.rs").read_text()


def ffi_rs() -> str:
    return (_HERE / "zero_copy_ffi.rs").read_text()


def _single_table(spec_rs: str) -> tuple[str, list[tuple[str, str]]]:
    structs = re.findall(r"pub struct Cols_([A-Za-z0-9_]+)\s*\{([^}]+)\}", spec_rs)
    if len(structs) != 1:
        raise ZeroCopyUnsupported(f"zero-copy handles one input table, the spec has {len(structs)}")
    suffix, body = structs[0]
    fields = re.findall(r"pub\s+((?:r#)?[A-Za-z_][A-Za-z0-9_]*):\s+Vec<([^>]+)>", body)
    if not fields:
        raise ZeroCopyUnsupported("no Vec column in the input struct")
    for fname, fty in fields:
        if fname.endswith("__dict"):
            raise ZeroCopyUnsupported(f"column {fname}: dictionary codes need an encode pass, they are not zero-copy")
        if fname.endswith("__valid"):
            raise ZeroCopyUnsupported(
                f"column {fname}: a nullable column has a validity mask; DuckDB's bit-mask layout is not borrowed (refused, see the proposal section 5)"
            )
        if fty not in _NATIVE:
            raise ZeroCopyUnsupported(f"column {fname} is loaded as {fty}: only native fixed-width signed integers are zero-copy")
    declared = len(re.findall(r"pub\s+(?:r#)?[A-Za-z_][A-Za-z0-9_]*:\s+", body)) - 1  # minus `n`
    if declared != len(fields):
        raise ZeroCopyUnsupported("the input struct has a column that is not a Vec")
    return suffix, fields


@dataclass(frozen=True)
class Resolved:
    """What the pin needs to know about the one table: its real names and the exact DuckDB type every loaded field must have."""

    suffix: str
    table: str  # the real table name (not the sanitized identifier)
    columns: list[str]  # real column names, in struct order
    expect: list[tuple[int, int, int]]  # per column: duckdb type id, decimal width, decimal scale
    dates: list[bool]  # per column: a DATE (its infinity values are not day numbers)
    sql_types: list[str]  # per column: the canonical upper-case type name as DuckDB's DESCRIBE spells it


def _native(table: str, column: str, info: ColumnTypeInfo, loaded: str) -> tuple[int, int, int]:
    """The (type id, decimal width, decimal scale) DuckDB stores `info` as, after checking that the spec loads exactly that width."""
    if info.is_float or info.exec_rust == "String" or not info.signed:
        raise ZeroCopyUnsupported(f"{table}.{column}: {info.sql_type} is not a signed fixed-width integer, DECIMAL or DATE column")
    if info.is_date:
        native, ident = "i32", (_DATE_ID, 0, 0)
    elif info.precision is not None:
        p = info.precision
        native = "i16" if p <= 4 else "i32" if p <= 9 else "i64" if p <= 18 else "i128"
        ident = (_DECIMAL_ID, p, info.scale)
    else:
        by_sql = {"tinyint": "i8", "smallint": "i16", "int": "i32", "integer": "i32", "int4": "i32", "bigint": "i64", "int8": "i64", "int64": "i64", "hugeint": "i128"}
        if info.sql_type not in by_sql:
            raise ZeroCopyUnsupported(f"{table}.{column}: {info.sql_type} is not a type the zero-copy path knows the storage of")
        native = by_sql[info.sql_type]
        ident = (_TYPE_ID[native], 0, 0)
    if loaded != native:
        hint = (
            " (LEMMA_NARROW_CELLS narrowed this column below its stored width: a narrow cell needs a pass over the data, i.e. a copy)"
            if _BYTES[loaded] < _BYTES[native]
            else " (the spec loads this column wider than DuckDB stores it: set LEMMA_NARROW_CELLS=1 for INTEGER, SMALLINT, TINYINT columns)"
        )
        raise ZeroCopyUnsupported(
            f"{table}.{column}: DuckDB stores {info.sql_type} as {native} ({_BYTES[native]} bytes), the spec loads {loaded} ({_BYTES[loaded]} bytes){hint}"
        )
    return ident


def resolve(spec_rs: str, schema: SchemaModel, stored_types: dict[str, str]) -> Resolved:
    """Map the spec's one input struct to its real table and columns, and refuse every declared-vs-stored mismatch.

    ``stored_types``: the type DuckDB reports (``DESCRIBE``) for each column of the table that will be pinned, by real column name.
    Refused with the exact reason: a struct that names no table or two, a field that names no column or two (sanitized identifiers collide),
    a column whose declared SQL type, precision or scale differs from the stored one, and any loaded width that is not the stored width."""
    suffix, fields = _single_table(spec_rs)
    tables = [orig for orig in schema.original_table_names.values() if rust_ident(orig) == suffix]
    if len(tables) != 1:
        raise ZeroCopyUnsupported(f"the struct Cols_{suffix} matches {len(tables)} tables of the schema {tables}, it must match exactly one")
    table = tables[0]
    _orig, cols = schema.lookup_table(table)
    stored = {k.casefold(): v for k, v in stored_types.items()}
    # the spec must carry the declared input types it was emitted from (emitted only under LEMMA_ZERO_COPY=1), and they must be the model's:
    # the scaled literals and caps inside the spec were computed from them (round 2 finding 1)
    m = re.search(r"^// IN_TYPES: (\{.*\})$", spec_rs, re.M)
    if m is None:
        raise ZeroCopyUnsupported("the spec carries no `// IN_TYPES:` line: emit it with LEMMA_ZERO_COPY=1 so the declared input types are bound to the spec")
    spec_types = json.loads(m.group(1)).get(table, {})
    names: list[str] = []
    expect: list[tuple[int, int, int]] = []
    dates: list[bool] = []
    sql_types: list[str] = []
    for fname, fty in fields:
        ident = fname.removeprefix("r#")
        keys = [c for c in cols if rust_ident(c).removeprefix("r#") == ident]
        if len(keys) != 1:
            raise ZeroCopyUnsupported(f"{table}.{ident}: the field matches {len(keys)} columns {keys}: sanitized identifiers must map to exactly one column")
        key = keys[0]
        real = schema.original_column_names[(table.casefold(), key)]
        info = cols[key]
        if real.casefold() not in stored:
            raise ZeroCopyUnsupported(f"{table}.{real}: the database that will be pinned has no such column")
        stored_info = classify_sql_type(stored[real.casefold()])
        canon = lambda t: _SYNONYM.get(t, t)  # noqa: E731
        if (canon(stored_info.sql_type), stored_info.is_date) != (canon(info.sql_type), info.is_date):
            raise ZeroCopyUnsupported(
                f"{table}.{real}: the spec declares {info.sql_type}, the database stores {stored_info.sql_type}"
            )
        declared_in_spec = spec_types.get(real)
        if declared_in_spec is None or canon(classify_sql_type(declared_in_spec).sql_type) != canon(info.sql_type):
            raise ZeroCopyUnsupported(
                f"{table}.{real}: the spec was emitted for {declared_in_spec}, the schema model declares {info.sql_type}: the spec's scaled literals do not match"
            )
        names.append(real)
        expect.append(_native(table, real, info, fty))
        dates.append(info.is_date)
        sql_types.append(_SYNONYM.get(info.sql_type, info.sql_type).upper())
    return Resolved(suffix, table, names, expect, dates, sql_types)


def rewrite_spec(spec_rs: str) -> tuple[str, str, list[tuple[str, str]]]:
    """The spec with ``PinnedCol`` columns, plus (table suffix, fields)."""
    suffix, fields = _single_table(spec_rs)
    struct = re.search(rf"pub struct Cols_{suffix}\s*\{{[^}}]+\}}", spec_rs)
    assert struct is not None
    body = struct.group(0)
    new = body
    for fname, fty in fields:
        new = new.replace(f"pub {fname}: Vec<{fty}>", f"pub {fname}: PinnedCol<{fty}>")
    out = spec_rs.replace(body, new)
    head = re.search(rf"pub open spec fn valid_cols_{suffix}\((\w+): &Cols_{suffix}\) -> bool \{{\n", out)
    if head is None:
        raise ZeroCopyUnsupported(f"valid_cols_{suffix} not found")
    param = head.group(1)
    first = fields[0][0]
    conj = "".join(f"    &&& {param}.{f}.wf()\n" for f, _ in fields)
    conj += "".join(f"    &&& {param}.{f}.offs@ == {param}.{first}.offs@\n" for f, _ in fields[1:])
    out = out[: head.end()] + conj + out[head.end() :]
    m = re.search(r"verus!\s*\{\n", out)
    assert m is not None
    return out[: m.end()] + lib_rs() + "\n" + out[m.end() :], suffix, fields


def _rust_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _sql(res: Resolved) -> str:
    q = lambda n: '"' + n.replace('"', '""') + '"'  # noqa: E731
    return f"SELECT {', '.join(q(c) for c in res.columns)} FROM {q(res.table)}"


def assemble_zero_copy_program(
    spec_rs: str,
    agent_body: str,
    *,
    db_path: str,
    schema: SchemaModel,
    stored_types: dict[str, str],
    helpers: str = "",
    mode: str = "zero_copy",
) -> str:
    """Verified program + `main` that pins `db_path` through the C API (read only). ``mode``: ``zero_copy`` or ``copy`` (the control)."""
    if not enabled():
        raise ZeroCopyUnsupported("[wip] zero_copy (LEMMA_ZERO_COPY=1) is not set: the zero-copy path is opt-in, there is no fallback to or from it")
    if mode not in ("zero_copy", "copy"):
        raise ValueError(mode)
    res = resolve(spec_rs, schema, stored_types)
    suffix, fields = res.suffix, _single_table(spec_rs)[1]
    if parallel.is_parallel(spec_rs) and not re.search(r"-> \(res: Vec<OutRow>\)", spec_rs):
        raise ZeroCopyUnsupported("the parallel zero-copy shape returns Vec<OutRow>")
    spec_work = rewrite_spec(spec_rs)[0] if mode == "zero_copy" else spec_rs
    # Stitch the body exactly as the pipeline does (markers, helpers, host lemmas).
    from declarative_spec.regions import EDIT_END, EDIT_START
    from declarative_spec.trusted_sets import current

    start, end = spec_work.find(EDIT_START), spec_work.find(EDIT_END)
    if start == -1 or end == -1 or end < start:
        raise ValueError("AGENT_EDIT markers missing from spec")
    stitched = spec_work[: start + len(EDIT_START)] + f"\n{agent_body.rstrip()}\n" + spec_work[end:]
    stitched = asm._insert_helpers(stitched, helpers)
    hs, he = stitched.find("// HOST_LEMMAS_START"), stitched.find("// HOST_LEMMAS_END")
    if hs == -1 or he == -1:
        raise ValueError("HOST_LEMMAS markers missing from spec")
    stitched = stitched[: hs + len("// HOST_LEMMAS_START")] + "\n" + current().lemmas_rs(stitched) + "\n" + stitched[he:]
    m = re.search(r"verus!\s*\{", stitched)
    depth, verus_end = 0, None
    for i in range(m.end() - 1, len(stitched)):
        depth += {"{": 1, "}": -1}.get(stitched[i], 0)
        if depth == 0:
            verus_end = i + 1
            break
    verus_part = stitched[:verus_end]

    # Loader (verified). Its requires are the ORIGINAL valid_cols conjuncts restated over the parameters, plus well-formedness.
    orig_part = spec_rs  # valid_cols without the wf conjuncts: the restating regexes know its shape
    requires = asm._loader_requires(orig_part, suffix, fields)
    var = lambda f: f"{suffix}_{asm._local_ident(f)}"  # noqa: E731
    if mode == "zero_copy":
        params = ", ".join([f"n_{suffix}: usize"] + [f"{var(f)}: PinnedCol<{t}>" for f, t in fields])
        wf_req = "".join(f"        {var(f)}.wf(),\n" for f, _ in fields)
        wf_req += "".join(f"        {var(f)}.offs@ == {var(fields[0][0])}.offs@,\n" for f, _ in fields[1:])
    else:
        params = ", ".join([f"n_{suffix}: usize"] + [f"{var(f)}: Vec<{t}>" for f, t in fields])
        wf_req = ""
    init = ", ".join([f"n: n_{suffix}"] + [f"{f}: {var(f)}" for f, _ in fields])
    loader = (
        f"fn load_cols_{suffix}({params}) -> (cols: Cols_{suffix})\n    requires\n{wf_req}{requires}\n"
        f"    ensures\n        valid_cols_{suffix}(&cols),\n{{\n    Cols_{suffix} {{ {init} }}\n}}"
    )
    closed = verus_part.rstrip()
    verus_with_loader = closed[:-1] + "\n" + loader + "\n}\n"

    checks = "\n".join(asm._runtime_checks(orig_part, suffix, fields))
    if mode == "zero_copy" and re.search(r"_\w+\[(?:i|j)\]", checks):
        raise ZeroCopyUnsupported("a valid_cols conjunct (unique key) needs random access over the borrowed column")
    is_par = parallel.is_parallel(verus_part)
    if is_par:
        run_call = f"run_query(&*arc_{suffix}, &arc_{suffix})"
    else:
        run_call = f"run_query(&cols_{suffix})"
    timed, hex_fn = asm._timed_runs(run_call, verus_part)

    lines = [
        f"    let db = zc_duck::open({_rust_str(db_path)}, true);",
        "    let t_pin = std::time::Instant::now();",
        f"    let pin: &'static zc_duck::Pin = Box::leak(Box::new(zc_duck::pin(&db, {_rust_str(_sql(res))})));",
        '    println!("PIN_US: {}", t_pin.elapsed().as_micros());',
        f"    let n_{suffix}: usize = pin.rows;",
        f'    assert!(n_{suffix} == zc_duck::count(&db, {_rust_str(res.table)}), "{{}}: the pinned chunks hold {{}} rows, the engine counts a different number", {_rust_str(res.table)}, n_{suffix});',
        "    let t_wrap = std::time::Instant::now();",
    ]
    for ci, ((f, t), real, (tid, dw, ds)) in enumerate(zip(fields, res.columns, res.expect)):
        v = var(f)
        lines.append(f"    pin.expect_type({ci}, {_rust_str(real)}, {tid}, {dw}, {ds});")
        rn = _rust_str(real)
        lines.append(f'    assert!(pin.cols[{ci}].elem_bytes == std::mem::size_of::<{t}>(), "{{}}: pinned width differs from {t}", {rn});')
        lines.append(
            f"    for (p, _) in pin.cols[{ci}].ptrs.iter() {{ assert!(!p.is_null() && (*p as usize) % std::mem::align_of::<{t}>() == 0, "
            f'"{{}}: pinned buffer is null or not aligned for {t}", {rn}); }}'
        )
        if ci > 0:
            lines.append(
                f'    assert!(pin.cols[{ci}].ptrs.iter().map(|x| x.1).eq(pin.cols[0].ptrs.iter().map(|x| x.1)), "{{}}: chunk boundaries differ from the first column", {rn});'
            )
        if mode == "zero_copy":
            lines.append(
                f"    let chunks_{v}: Vec<&'static [{t}]> = pin.cols[{ci}].ptrs.iter().filter(|x| x.1 > 0)"
                f".map(|(p, l)| unsafe {{ std::slice::from_raw_parts(*p as *const {t}, *l) }}).collect();"
            )
            lines.append(f"    let {v} = ZcFlat(&chunks_{v});")
            if res.dates[ci]:
                lines.append(f'    assert!({v}.iter().all(|c| *c != i32::MAX && *c != -i32::MAX), "{{}}: a DATE cell is infinity (+-2147483647), not a day number", {rn});')
        else:
            lines.append(f"    let mut {v}: Vec<{t}> = Vec::with_capacity(n_{suffix});")
            lines.append(
                f"    for (p, l) in pin.cols[{ci}].ptrs.iter() {{ {v}.extend_from_slice(unsafe {{ std::slice::from_raw_parts(*p as *const {t}, *l) }}); }}"
            )
            if res.dates[ci]:
                lines.append(f'    assert!({v}.iter().all(|c| *c != i32::MAX && *c != -i32::MAX), "{{}}: a DATE cell is infinity (+-2147483647), not a day number", {rn});')
    lines.append('    println!("WRAP_US: {}", t_wrap.elapsed().as_micros());')
    lines.append("    let t_check = std::time::Instant::now();")
    lines.append(checks)
    lines.append('    println!("CHECK_US: {}", t_check.elapsed().as_micros());')
    args = []
    for f, t in fields:
        v = var(f)
        if mode == "zero_copy":
            lines.append(f"    let offs_{v}: Vec<usize> = zc_offsets(&chunks_{v});")
            lines.append(f'    assert!(offs_{v}.last() == Some(&n_{suffix}), "{{}}: the chunk lengths do not add up to the row count", {_rust_str(f)});')
            lines.append(f"    let {v} = PinnedCol {{ n: n_{suffix}, chunks: chunks_{v}, offs: offs_{v} }};")
        args.append(v)
    lines.append(f"    let cols_{suffix} = load_cols_{suffix}(n_{suffix}, {', '.join(args)});")
    if is_par:
        lines.append(f"    let arc_{suffix} = std::sync::Arc::new(cols_{suffix});")
    main_fn = "fn main() {\n" + "\n".join(lines) + "\n" + timed + "}\n"

    helpers_rs = """
struct ZcFlat<'b, T: 'static>(&'b Vec<&'static [T]>);
struct ZcIter<'b, T: 'static>(&'b [&'static [T]]);
impl<'b, T: 'static> ZcFlat<'b, T> {
    fn iter(&self) -> ZcIter<'b, T> { ZcIter(self.0.as_slice()) }
}
impl<'b, T: 'static> ZcIter<'b, T> {
    fn all(self, mut f: impl FnMut(&T) -> bool) -> bool { self.0.iter().all(|c| c.iter().all(|v| f(v))) }
}
fn zc_offsets<T: 'static>(chunks: &Vec<&'static [T]>) -> Vec<usize> {
    let mut offs = Vec::with_capacity(chunks.len() + 1);
    let mut acc = 0usize;
    offs.push(0);
    for c in chunks { acc += c.len(); offs.push(acc); }
    offs
}
"""
    return verus_with_loader + "\n" + ffi_rs() + helpers_rs + hex_fn + main_fn
