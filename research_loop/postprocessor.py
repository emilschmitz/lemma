"""Minimal Python post-processor for Dafny→Rust output.

Only:
  - Row-path: empty mock → load_dataset + Loadable impl
  - Column-path: benchmark harness (load_cols_from_tbl + main) via inject_hot_loop_main
  - RunQuery: hoist cols ref + usize reverse loop + _usize column accessors (read-only; safe)
  - NativeAggMap: stack-local agg + AddStrKey (skip Dafny string alloc on group keys)
  - RunQuery: strip MaybePlacebo return wrapper (same value returned)

No query-specific rewrites. Column storage is schema-generated ColsNative (single Object).
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TBL = "ssb-dbgen/lineorder_flat.tbl"
DEFAULT_LIMIT = 50000
NATIVE_BRIDGE = Path(__file__).resolve().parent / "native_bridge" / "src"


@dataclass
class RowField:
    name: str
    rust_type: str  # u32, u64, or String


@dataclass
class PostProcessState:
    tbl_path: str = DEFAULT_TBL
    row_limit: int = DEFAULT_LIMIT
    row_fields: list[RowField] = field(default_factory=list)
    needs_dataset: bool = False


def postprocess(
    file_path: str,
    tbl_path: str = DEFAULT_TBL,
    row_limit: int = DEFAULT_LIMIT,
    *,
    allow_fast_native_agg: bool = True,
) -> None:
    if not os.path.exists(file_path):
        return
    with open(file_path) as f:
        content = f.read()
    if "fn RunQuery" not in content:
        return
    state = PostProcessState(tbl_path=tbl_path, row_limit=row_limit)
    out = _transform(content, state, allow_fast_native_agg=allow_fast_native_agg, file_path=file_path)
    with open(file_path, "w") as f:
        f.write(out)


def _transform(content: str, state: PostProcessState, *, allow_fast_native_agg: bool = True, file_path: str = "") -> str:
    _extract_row_schema(content, state)
    content = _inject_dataset_loader(content, state)
    content = _inject_native_extern_imports(content)
    content = _inject_native_ops_delegates(content)
    content = _ensure_native_bridge_modules(content, os.path.dirname(file_path) if file_path else ".")
    content = _optimize_runquery_hot_loop(content)
    if allow_fast_native_agg:
        content = _fix_native_agg_local(content)
        content = _optimize_native_agg_calls(content)
    content = _strip_maybe_placebo_return(content)
    if state.needs_dataset:
        content = _ensure_mod_dataset(content)
        content = _inject_loadable_impl(content, state)
    return content


def _inject_native_extern_imports(content: str) -> str:
    """Import native_bridge types into generated _module."""
    if "pub mod _module" not in content:
        return content
    imports = []
    if "ColsNative" in content:
        imports.append("ColsNative")
    if "NativeAggMap" in content:
        imports.append("NativeAggMap")
    if not imports:
        return content
    use_line = f"use crate::_dafny_externs::{{{', '.join(imports)}}};"
    if use_line in content:
        return content
    return re.sub(r"(pub mod _module\s*\{)", r"\1\n    " + use_line, content, count=1)


def _inject_native_ops_delegates(content: str) -> str:
    """Dafny codegen calls _default::_native_* for {:extern} functions."""
    if "_default::_native_" not in content or "fn _native_add_u64" in content:
        return content
    delegates = """
        pub fn _native_add_u64(a: u64, b: u64) -> u64 {
            crate::native_ops::native_add_u64(a, b)
        }
        pub fn _native_mul_u64_u32(ep: u64, d: u32) -> u64 {
            crate::native_ops::native_mul_u64_u32(ep, d)
        }
        pub fn _native_sub_u64_i64(a: u64, b: u64) -> i64 {
            crate::native_ops::native_sub_u64_i64(a, b)
        }
        pub fn _native_add_i64(a: i64, b: i64) -> i64 {
            crate::native_ops::native_add_i64(a, b)
        }
"""
    return re.sub(r"(impl _default \{)", r"\1" + delegates, content, count=1)


def _ensure_native_bridge_modules(content: str, src_dir: str) -> str:
    """Copy native_bridge Rust modules and declare them when postprocessor uses them."""
    needs_ops = "crate::native_ops::" in content
    needs_agg = "NativeAggMap" in content and "crate::native_agg::" in content
    if not needs_ops and not needs_agg:
        return content
    src = Path(src_dir)
    src.mkdir(parents=True, exist_ok=True)
    mods: list[str] = []
    if needs_ops:
        shutil.copy2(NATIVE_BRIDGE / "native_ops.rs", src / "native_ops.rs")
        mods.append("native_ops")
    if needs_agg:
        shutil.copy2(NATIVE_BRIDGE / "native_agg.rs", src / "native_agg.rs")
        mods.append("native_agg")
    if "pub mod _dafny_externs" not in content and needs_agg:
        externs = "pub mod _dafny_externs {\n"
        if "ColsNative" in content:
            externs += "    pub use crate::cols_native::*;\n"
        externs += "    pub use crate::native_agg::*;\n    pub use crate::native_ops::*;\n}\n\n"
        content = externs + content
    for mod_name in mods:
        decl = f"pub mod {mod_name};"
        if decl not in content:
            anchor = content.find("pub mod _module")
            if anchor == -1:
                content = decl + "\n" + content
            else:
                content = content[:anchor] + decl + "\n" + content[anchor:]
    return content


def _runquery_span(content: str) -> tuple[int, int] | None:
    m = re.search(r"pub fn RunQuery\(cols: &Object<ColsNative>\)[^{]+\{", content)
    if not m:
        return None
    start = m.end()
    depth, i = 1, start
    while i < len(content) and depth:
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
        i += 1
    return (m.start(), i) if depth == 0 else None


def _optimize_runquery_hot_loop(content: str) -> str:
    """Safe RunQuery opts: one cols borrow, usize loop, native slice accessors."""
    span = _runquery_span(content)
    if not span:
        return content
    rs, re_ = span
    chunk = content[rs:re_]
    if "cols_ref" in chunk:
        body = chunk
    else:
        body = chunk.replace(
            "{",
            "{\n            let cols_ref = rd!(cols);",
            1,
        )
        body = re.sub(r"rd!\(\s*cols\s*\)\.", "cols_ref.", body)
    body = re.sub(
        r"let mut i: DafnyInt = cols_ref\.n\(\);\s*"
        r"while int!\(0\) < i\.clone\(\) \{\s*"
        r"i = i\.clone\(\) - int!\(1\);",
        "let mut i: usize = cols_ref.n;\n            while i > 0 {\n                i -= 1;",
        body,
        count=1,
    )
    body = re.sub(
        r"cols_ref\.Get([A-Z0-9_]+)\(&i\)",
        r"cols_ref.Get\1_usize(i)",
        body,
    )
    body = re.sub(
        r'cols_ref\.EqAt([A-Z0-9_]+)\(&i, &string_of\("([^"]*)"\)\)',
        r'cols_ref.EqAt\1_usize(i, "\2")',
        body,
    )
    return content[:rs] + body + content[re_:]


def _fix_native_agg_local(content: str) -> str:
    """Dafny `new NativeAggMap()` → Object; local agg can be stack NativeAggMap."""
    if "NativeAggMap" not in content:
        return content
    m = re.search(r"pub fn RunQuery\(cols: &Object<ColsNative>\)[^{]+\{", content)
    if not m:
        m = re.search(r"pub fn RunQuery\(cols: &Rc<Cols>\)[^{]+\{", content)
    if not m:
        return content
    end = content.find("\n        /// ", m.end())
    if end == -1:
        end = content.find("\n    /// ", m.end())
    if end == -1:
        return content
    chunk = content[m.start() : end]
    if "Object<NativeAggMap>" not in chunk:
        return content
    chunk = re.sub(
        r"let mut agg: Object<NativeAggMap>;\s*"
        r"let mut _nw\d+: Object<NativeAggMap> = NativeAggMap::_allocate_object\(\);\s*"
        r"agg = _nw\d+\.clone\(\);\s*",
        "let mut agg = NativeAggMap::default();\n            ",
        chunk,
        count=1,
    )
    chunk = re.sub(r"(?:md|rd)!\(\s*agg\s*\)\.(Add|ToMap|ToU64Map|Snapshot)\(", r"agg.\1(", chunk)
    return content[: m.start()] + chunk + content[end:]


def _optimize_native_agg_calls(content: str) -> str:
    """Native agg hot path: AddStrKey + str_ref instead of Dafny Sequence keys."""
    span = _runquery_span(content)
    if not span:
        return content
    rs, re_ = span
    body = content[rs:re_]
    # yr + nation locals + optional key tuple + agg.Add(&nation) — drop Dafny string allocs.
    body = re.sub(
        r"let mut ([a-zA-Z_]+): u32 = cols_ref\.Get([A-Z0-9_]+)_usize\(i\);\s*"
        r"let mut ([a-zA-Z_]+): Sequence<DafnyChar> = cols_ref\.Get([A-Z0-9_]+)_usize\(i\);\s*"
        r"let mut key: \(u32, Sequence<DafnyChar>\) = \(\s*\1,\s*\3\.clone\(\)\s*\);\s*"
        r"(let mut term: [^;]+;)\s*"
        r"agg\.Add\(\1, &\3(?:\.clone\(\))?, term\)",
        r"let mut \1: u32 = cols_ref.Get\2_usize(i);\n                    \5\n                    agg.AddStrKey(\1, cols_ref.Get\4_str_ref(i), term)",
        body,
        count=1,
    )
    # Tuple key built from two Get*_usize → Add(key.0, key.1).
    body = re.sub(
        r"let mut key: \(u32, Sequence<DafnyChar>\) = \(\s*"
        r"cols_ref\.Get([A-Z0-9_]+)_usize\(i\),\s*"
        r"cols_ref\.Get([A-Z0-9_]+)_usize\(i\)\s*\);\s*"
        r"(let mut term: [^;]+;)\s*"
        r"agg\.Add\(key\.0(?:\.clone\(\))?, &key\.1(?:\.clone\(\))?, term\)",
        r"\3\n                    agg.AddStrKey(cols_ref.Get\1_usize(i), cols_ref.Get\2_str_ref(i), term)",
        body,
        count=1,
    )
    body = re.sub(
        r"agg\.Add\(([^,]+),\s*&cols_ref\.Get([A-Z0-9_]+)_usize\(i\),\s*([^)]+)\)",
        r"agg.AddStrKey(\1, cols_ref.Get\2_str_ref(i), \3)",
        body,
    )
    body = re.sub(
        r"let mut ([a-zA-Z_][a-zA-Z0-9_]*): Sequence<DafnyChar> = "
        r"cols_ref\.Get([A-Z0-9_]+)_usize\(i\);\s*"
        r"(?:let mut [^;]+;\s*)?"
        r"agg\.Add\(([^,]+), &\1(?:\.clone\(\))?, ([^)]+)\)",
        r"agg.AddStrKey(\3, cols_ref.Get\2_str_ref(i), \4)",
        body,
    )
    return content[:rs] + body + content[re_:]


def _strip_maybe_placebo_return(content: str) -> str:
    """Dafny emits MaybePlacebo + clone on return; direct return is equivalent."""
    span = _runquery_span(content)
    if not span:
        return content
    rs, re_ = span
    body = content[rs:re_]
    if "MaybePlacebo" not in body:
        return content
    body = re.sub(
        r"let mut _out0: ([^=]+) = agg\.ToMap\(\);\s*"
        r"res = MaybePlacebo::from\(_out0\.clone\(\)\);\s*"
        r"return res\.read\(\);",
        r"return agg.ToMap();",
        body,
        count=1,
    )
    body = re.sub(
        r"let mut _out0: ([^=]+) = agg\.ToU64Map\(\);\s*"
        r"res = MaybePlacebo::from\(_out0\.clone\(\)\);\s*"
        r"return res\.read\(\);",
        r"return agg.ToU64Map();",
        body,
        count=1,
    )
    body = re.sub(
        r"res = MaybePlacebo::from\(([^;]+)\.clone\(\)\);\s*return res\.read\(\);",
        r"return \1;",
        body,
        count=1,
    )
    body = re.sub(r"let mut res = MaybePlacebo::<[^;]+>::new\(\);\s*", "", body, count=1)
    return content[:rs] + body + content[re_:]


def _extract_row_schema(content: str, state: PostProcessState) -> None:
    m = re.search(r"pub enum Row\s*\{\s*Row\s*\{([^}]+)\}", content, re.DOTALL)
    if not m:
        return
    for part in m.group(1).split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        name, ty = part.split(":", 1)
        name, ty = name.strip(), ty.strip()
        if "Sequence" in ty:
            rust_ty = "String"
        elif "u64" in ty:
            rust_ty = "u64"
        else:
            rust_ty = "u32"
        state.row_fields.append(RowField(name, rust_ty))


def _inject_dataset_loader(content: str, state: PostProcessState) -> None:
    pat = re.compile(
        r"let mut data\s*:\s*Sequence\s*<\s*Rc\s*<\s*Row\s*>\s*>\s*=\s*(?:\[\s*\]|seq!\[\s*\])\s*;",
    )
    tbl_lit = json.dumps(state.tbl_path)
    repl = (
        f"let mut data: Sequence<Rc<Row>> = "
        f"crate::dataset::load_dataset::<Row>({tbl_lit}, {state.row_limit});"
    )
    if pat.search(content):
        state.needs_dataset = True
        content = pat.sub(repl, content, count=1)
    return content


def _ensure_mod_dataset(content: str) -> str:
    if "mod dataset;" in content:
        return content
    pos = content.find("pub mod _module")
    return content[:pos] + "mod dataset; " + content[pos:] if pos != -1 else "mod dataset;\n" + content


def _build_loadable_impl(state: PostProcessState) -> str:
    lines = []
    for fld in state.row_fields:
        col = fld.name.upper()
        access = f'f[ci["{col}"]]'
        if fld.rust_type == "String":
            lines.append(f"            {fld.name}: ::dafny_runtime::string_of({access}),")
        else:
            lines.append(f"            {fld.name}: {access}.parse::<{fld.rust_type}>().unwrap(),")
    body = "\n".join(lines)
    return f"""
    impl crate::dataset::Loadable for crate::_module::Row {{
        fn from_fields(f: &[&str], ci: &std::collections::HashMap<String, usize>) -> Self {{
            crate::_module::Row::Row {{
{body}
            }}
        }}
    }}
"""


def _inject_loadable_impl(content: str, state: PostProcessState) -> str:
    if "impl crate::dataset::Loadable" in content:
        return content
    impl = _build_loadable_impl(state)
    pos = content.find("pub enum Row")
    if pos == -1:
        return content + impl
    end = content.find("} }", pos)
    return content[: end + 3] + impl + content[end + 3 :] if end != -1 else content + impl


def _extract_cols_schema_from_native_rs(native_rs_path: str, state: PostProcessState) -> None:
    """Parse schema-specific cols_native.rs generated alongside the Dafny program."""
    with open(native_rs_path) as f:
        content = f.read()
    state.row_fields.clear()
    for m in re.finditer(r"pub fn Get([A-Z0-9_]+)\(", content):
        col = m.group(1)
        field_m = re.search(rf"pub {re.escape(col.lower())}: Arc<Vec<(\w+)>>", content)
        if not field_m:
            continue
        rust_ty = field_m.group(1)
        if rust_ty == "String":
            ty = "String"
        elif rust_ty == "u64":
            ty = "u64"
        else:
            ty = "u32"
        state.row_fields.append(RowField(col.lower(), ty))


def _build_load_cols_fn(state: PostProcessState, tbl_lit: str) -> str:
    """Load tbl → ColsNative (Arc<Vec> columns) wrapped in Object<ColsNative>."""
    vec_decls, field_inits, parse_lines = [], [], []
    for fld in state.row_fields:
        vname = f"v_{fld.name}"
        col = fld.name.upper()
        if fld.rust_type == "String":
            vec_decls.append(f"    let mut {vname}: Vec<String> = Vec::new();")
            parse_lines.append(
                f'        {vname}.push(f[ci["{col}"]].trim_matches(\'"\').to_string());'
            )
        else:
            vec_decls.append(f"    let mut {vname}: Vec<{fld.rust_type}> = Vec::new();")
            parse_lines.append(
                f'        {vname}.push(f[ci["{col}"]].parse::<{fld.rust_type}>().unwrap());'
            )
        field_inits.append(f"        {fld.name}: Arc::new({vname}),")
    return f"""
fn load_cols_from_tbl(tbl_path: &str, limit: usize) -> ::dafny_runtime::Object<crate::_dafny_externs::ColsNative> {{
    use std::collections::HashMap;
    use std::fs::File;
    use std::io::{{BufRead, BufReader}};
    use std::sync::Arc;
    use crate::_dafny_externs::ColsNative;
    let mut base = std::env::current_dir().unwrap();
    let mut p = base.join(tbl_path);
    while !p.exists() {{
        match base.parent() {{ Some(par) => {{ base = par.to_path_buf(); p = base.join(tbl_path); }} None => break }}
    }}
    let mut rdr = BufReader::new(File::open(&p).unwrap());
    let mut hdr = String::new();
    rdr.read_line(&mut hdr).unwrap();
    let mut ci: HashMap<String, usize> = HashMap::new();
    for (i, c) in hdr.split('|').enumerate() {{ ci.insert(c.trim().to_uppercase(), i); }}
{chr(10).join(vec_decls)}
    let mut n = 0usize;
    for ln in rdr.lines().take(limit) {{
        let line = ln.unwrap();
        let f: Vec<&str> = line.split('|').collect();
        if f.is_empty() {{ continue; }}
{chr(10).join(parse_lines)}
        n += 1;
    }}
    ::dafny_runtime::Object::new(ColsNative {{
        n,
{chr(10).join(field_inits)}
    }})
}}
"""


def inject_hot_loop_main(file_path: str, tbl_path: str, row_limit: int) -> None:
    with open(file_path) as f:
        content = f.read()
    content = re.sub(r"\nfn main\s*\(\)\s*\{[\s\S]*\}\s*$", "\n", content)
    tbl_lit = json.dumps(tbl_path)
    state = PostProcessState(tbl_path=tbl_path, row_limit=row_limit)
    native_rs = os.path.join(os.path.dirname(file_path), "cols_native.rs")
    uses_cols = "ColsNative" in content and re.search(r"fn RunQuery\s*\(\s*cols:", content)
    if uses_cols and os.path.exists(native_rs):
        _extract_cols_schema_from_native_rs(native_rs, state)
        harness = f"""
{_build_load_cols_fn(state, tbl_lit)}
fn main() {{
    use std::time::Instant;
    let cols = load_cols_from_tbl({tbl_lit}, {row_limit});
    for run in 0..3 {{
        let t0 = Instant::now();
        let _ = crate::_module::_default::RunQuery(&cols);
        let dt = t0.elapsed().as_micros();
        if run == 2 {{
            println!("QUERY_LATENCY_US: {{}}", dt);
        }}
    }}
}}
"""
    else:
        _extract_row_schema(content, state)
        if "mod dataset;" not in content:
            pos = content.find("pub mod _module")
            if pos != -1:
                content = content[:pos] + "mod dataset; " + content[pos:]
        if "impl crate::dataset::Loadable" not in content:
            content = _inject_loadable_impl(content, state)
        harness = f"""
fn main() {{
    use std::time::Instant;
    let data = crate::dataset::load_dataset::<crate::_module::Row>({tbl_lit}, {row_limit});
    for run in 0..3 {{
        let t0 = Instant::now();
        let _ = crate::_module::_default::RunQuery(&data);
        let dt = t0.elapsed().as_micros();
        if run == 2 {{
            println!("QUERY_LATENCY_US: {{}}", dt);
        }}
    }}
}}
"""
    with open(file_path, "w") as f:
        f.write(content + harness)
