"""Assemble a single verified Verus program: transpiled spec + proved run_query + load + main."""

from __future__ import annotations

import re
from pathlib import Path

from verus_transpiler.rust_ident import rust_ident

from research_loop.agent_primitives.emit_externs import maybe_emit_agent_externs
from research_loop.exec_cols import _rust_vec_type
from research_loop.lemma_flags import lemma_load_format
from research_loop.table_assumptions import CatalogAssumptions

_DUCKDB_FFI_INC = Path(__file__).resolve().parent / "duckdb_load_ffi.rs.inc"

RUNQUERY_SKELETON_MARKER = "// === RunQuery skeleton"

# Per return-type metadata for group-by boundary helpers and RESULT formatting.
RET_TYPE_CONFIG: dict[str, dict[str, str]] = {
    "u64": {
        "rust_ret": "u64",
        "format_result": 'format!("RESULT: {}", res)',
    },
    "i64": {
        "rust_ret": "i64",
        "format_result": 'format!("RESULT: {}", res)',
    },
    "map_u32_str_u64": {
        "rust_ret": "HashMapWithView<(u32, String), u64>",
        "spec_map": "Map<(u32, Seq<char>), u64>",
        "agg_suffix": "u32_str_u64",
        "format_result": 'format!("RESULT: map_len={}", res.len())',
    },
    "map_str_u32_u64": {
        "rust_ret": "HashMapWithView<(String, u32), u64>",
        "spec_map": "Map<(Seq<char>, u32), u64>",
        "agg_suffix": "str_u32_u64",
        "format_result": 'format!("RESULT: map_len={}", res.len())',
    },
    "map_str_str_u64": {
        "rust_ret": "HashMapWithView<(String, String), u64>",
        "spec_map": "Map<(Seq<char>, Seq<char>), u64>",
        "agg_suffix": "str_str_u64",
        "format_result": 'format!("RESULT: map_len={}", res.len())',
    },
    "map_str_str_u32_u64": {
        "rust_ret": "HashMapWithView<(String, String, u32), u64>",
        "spec_map": "Map<(Seq<char>, Seq<char>, u32), u64>",
        "agg_suffix": "str_str_u32_u64",
        "format_result": 'format!("RESULT: map_len={}", res.len())',
    },
    "map_u32_str_i64": {
        "rust_ret": "HashMapWithView<(u32, String), i64>",
        "spec_map": "Map<(u32, Seq<char>), i64>",
        "agg_suffix": "u32_str_i64",
        "format_result": 'format!("RESULT: map_len={}", res.len())',
    },
    "map_u32_str_str_i64": {
        "rust_ret": "HashMapWithView<(u32, String, String), i64>",
        "spec_map": "Map<(u32, Seq<char>, Seq<char>), i64>",
        "agg_suffix": "u32_str_str_i64",
        "format_result": 'format!("RESULT: map_len={}", res.len())',
    },
    "map_u32_str_str_u64": {
        "rust_ret": "HashMapWithView<(u32, String, String), u64>",
        "spec_map": "Map<(u32, Seq<char>, Seq<char>), u64>",
        "agg_suffix": "u32_str_str_u64",
        "format_result": 'format!("RESULT: map_len={}", res.len())',
    },
    "map_u32_u64": {
        "rust_ret": "HashMapWithView<u32, u64>",
        "spec_map": "Map<u32, u64>",
        "agg_suffix": "u32_u64",
        "format_result": 'format!("RESULT: map_len={}", res.len())',
    },
    "map_str_u64": {
        "rust_ret": "StringHashMap<u64>",
        "spec_map": "Map<Seq<char>, u64>",
        "agg_suffix": "str_u64",
        "format_result": 'format!("RESULT: map_len={}", res.len())',
    },
    "seq_u64": {
        "rust_ret": "Vec<u64>",
        "format_result": (
            "{\n"
            "        let checksum: u64 = res.iter().copied().fold(0u64, |a, v| a.wrapping_add(v));\n"
            '        format!("RESULT: seq_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
    "set_u32": {
        "rust_ret": "Vec<u32>",
        "format_result": (
            "{\n"
            "        let checksum: u64 = res.iter().map(|v| *v as u64).fold(0u64, |a, v| a.wrapping_add(v));\n"
            '        format!("RESULT: set_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
    "seq_u32": {
        "rust_ret": "Vec<u32>",
        "format_result": (
            "{\n"
            "        let checksum: u64 = res.iter().map(|v| *v as u64).fold(0u64, |a, v| a.wrapping_add(v));\n"
            '        format!("RESULT: seq_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
    "seq_u32_u32": {
        "rust_ret": "Vec<(u32, u32)>",
        "format_result": (
            "{\n"
            "        let checksum: u64 = res.iter().fold(0u64, |a, (k, v)| {\n"
            "            a.wrapping_add(*k as u64).wrapping_add(*v as u64)\n"
            "        });\n"
            '        format!("RESULT: seq_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
    "seq_u32_u64": {
        "rust_ret": "Vec<(u32, u64)>",
        "format_result": (
            "{\n"
            "        let checksum: u64 = res.iter().fold(0u64, |a, (k, v)| {\n"
            "            a.wrapping_add(*k as u64).wrapping_add(*v)\n"
            "        });\n"
            '        format!("RESULT: seq_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
}


_AGG_HELPER_SPECS: dict[str, dict[str, str]] = {
    "map_u32_str_u64": {
        "add_params": "k0: u32, k1: &str, delta: u64",
        "spec_key": "(k0, k1@)",
        "value_ty": "u64",
        "exec_body": """
    let key = (k0, k1.to_string());
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, prev.wrapping_add(delta));
""",
    },
    "map_str_u32_u64": {
        "add_params": "k0: &str, k1: u32, delta: u64",
        "spec_key": "(k0@, k1)",
        "value_ty": "u64",
        "exec_body": """
    let key = (k0.to_string(), k1);
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, prev.wrapping_add(delta));
""",
    },
    "map_str_str_u64": {
        "add_params": "k0: &str, k1: &str, delta: u64",
        "spec_key": "(k0@, k1@)",
        "value_ty": "u64",
        "exec_body": """
    let key = (k0.to_string(), k1.to_string());
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, prev.wrapping_add(delta));
""",
    },
    "map_str_str_u32_u64": {
        "add_params": "k0: &str, k1: &str, k2: u32, delta: u64",
        "spec_key": "(k0@, k1@, k2)",
        "value_ty": "u64",
        "exec_body": """
    let key = (k0.to_string(), k1.to_string(), k2);
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, prev.wrapping_add(delta));
""",
    },
    "map_u32_str_i64": {
        "add_params": "k0: u32, k1: &str, delta: i64",
        "spec_key": "(k0, k1@)",
        "value_ty": "i64",
        "exec_body": """
    let key = (k0, k1.to_string());
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, prev.wrapping_add(delta));
""",
    },
    "map_u32_str_str_i64": {
        "add_params": "k0: u32, k1: &str, k2: &str, delta: i64",
        "spec_key": "(k0, k1@, k2@)",
        "value_ty": "i64",
        "exec_body": """
    let key = (k0, k1.to_string(), k2.to_string());
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, prev.wrapping_add(delta));
""",
    },
    "map_u32_str_str_u64": {
        "add_params": "k0: u32, k1: &str, k2: &str, delta: u64",
        "spec_key": "(k0, k1@, k2@)",
        "value_ty": "u64",
        "exec_body": """
    let key = (k0, k1.to_string(), k2.to_string());
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, prev.wrapping_add(delta));
""",
    },
    "map_u32_u64": {
        "add_params": "k0: u32, delta: u64",
        "spec_key": "k0",
        "value_ty": "u64",
        "exec_body": """
    let prev = hm.get(&k0).copied().unwrap_or(0);
    hm.insert(k0, prev.wrapping_add(delta));
""",
    },
    "map_str_u64": {
        "add_params": "k0: &str, delta: u64",
        "spec_key": "k0@",
        "value_ty": "u64",
        "exec_body": """
    let key = k0.to_string();
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, prev.wrapping_add(delta));
""",
    },
}


def _emit_agg_helpers(ret_type: str) -> str:
    cfg = RET_TYPE_CONFIG.get(ret_type, {})
    spec_map = cfg.get("spec_map")
    suffix = cfg.get("agg_suffix")
    if not spec_map or not suffix:
        return ""
    from research_loop.trusted_ret_bridge import structural_bridge_for_spec_type

    return structural_bridge_for_spec_type(spec_map).trusted_rs


def _cfg(ret_type: str) -> dict[str, str]:
    if ret_type in RET_TYPE_CONFIG:
        return RET_TYPE_CONFIG[ret_type]
    from research_loop.trusted_ret_bridge import dynamic_ret_type_config

    dyn = dynamic_ret_type_config()
    if ret_type in dyn:
        return dyn[ret_type]
    raise ValueError(
        f"unsupported MethodSpec return type key (no Trusted/shell wiring): {ret_type}"
    )


def _ret_type_supported(ret_type: str) -> bool:
    if ret_type in RET_TYPE_CONFIG:
        return True
    from research_loop.trusted_ret_bridge import dynamic_ret_type_config

    return ret_type in dynamic_ret_type_config()


_VSTD_CONTAINER_USE = (
    "use vstd::hash_map::{HashMapWithView, StringHashMap};\n"
    "use vstd::hash_set::HashSetWithView;\n\n"
)


def _boundary_helpers(
    ret_type: str,
    verus_spec: str | None = None,
    *,
    catalog_assumptions: CatalogAssumptions | None = None,
) -> str:
    from research_loop.having_filter_bridge import having_filter_trusted_rs
    from research_loop.multi_agg_step_bridge import (
        emit_scalar_fold_bound_lemmas,
        multi_agg_step_trusted_rs,
    )
    from research_loop.trusted_ret_bridge import (
        distinct_set_trusted_rs,
        get_bridge,
        multi_agg_ret_type,
    )

    boundary = _emit_agg_helpers(ret_type)
    if not boundary:
        b = get_bridge(ret_type)
        if b and b.trusted_rs:
            boundary = b.trusted_rs
    if verus_spec and not multi_agg_ret_type(ret_type):
        from research_loop.method_spec_ret_type import parse_method_spec_return_type
        from research_loop.trusted_ret_bridge import bridge_from_method_spec_type

        b = get_bridge(ret_type)
        if b is None:
            try:
                b = bridge_from_method_spec_type(parse_method_spec_return_type(verus_spec))
            except ValueError:
                b = None
        if b is not None:
            scalar_bounds = emit_scalar_fold_bound_lemmas(
                verus_spec, b, catalog_assumptions=catalog_assumptions
            )
            if scalar_bounds:
                boundary = f"{boundary}{scalar_bounds}" if boundary else scalar_bounds
    if multi_agg_ret_type(ret_type):
        distinct = distinct_set_trusted_rs()
        boundary = f"{boundary}{distinct}" if boundary else distinct
        if verus_spec:
            step = multi_agg_step_trusted_rs(
                verus_spec, ret_type, catalog_assumptions=catalog_assumptions
            )
            if step:
                boundary = f"{boundary}{step}" if boundary else step
    if verus_spec:
        having = having_filter_trusted_rs(verus_spec, ret_type)
        if having:
            boundary = f"{boundary}{having}" if boundary else having
    if boundary and (
        "HashMapWithView" in boundary
        or "StringHashMap" in boundary
        or "HashSetWithView" in boundary
    ):
        # Join specs already import StringHashMap with the proved equijoin slice.
        if verus_spec and "use vstd::hash_map::StringHashMap;" in verus_spec:
            boundary = (
                "use vstd::hash_map::HashMapWithView;\n"
                "use vstd::hash_set::HashSetWithView;\n\n" + boundary
            )
        else:
            boundary = _VSTD_CONTAINER_USE + boundary
    return boundary


def _strip_skeleton(spec_rs: str) -> str:
    """Remove the commented run_query skeleton.

    Items after the skeleton stay. The join prelude is emitted after the
    query contract, so dropping everything past the marker would drop
    ``rem_join_sq`` and the index proofs.
    """
    if RUNQUERY_SKELETON_MARKER not in spec_rs:
        return spec_rs
    head, rest = spec_rs.split(RUNQUERY_SKELETON_MARKER, 1)
    if not re.search(r"\n\} // verus!\s*$", spec_rs, re.MULTILINE):
        raise ValueError("transpiled spec missing closing verus! brace")
    # The marker is a prefix of its comment line. Drop that line, then the
    # commented skeleton, and keep real items that follow.
    rest = rest.split("\n", 1)[1] if "\n" in rest else ""
    lines = rest.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == "" or stripped.startswith("//"):
            i += 1
            continue
        break
    after = _trim_verus_close("".join(lines[i:]))
    return head.rstrip() + "\n" + after


_VERUS_CLOSE_RE = re.compile(r"\n\} // verus!\s*$", re.MULTILINE)


def _trim_verus_close(spec_rs: str) -> str:
    """Drop trailing ``} // verus!`` so callers can append boundary helpers."""
    m = _VERUS_CLOSE_RE.search(spec_rs)
    if m:
        return spec_rs[: m.start()].rstrip() + "\n"
    return spec_rs.rstrip() + "\n"


def _next_code(text: str, i: int) -> tuple[str, int]:
    """Next code character at or after ``i``, skipping comments and strings."""
    n = len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            nl = text.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        if c == "/" and nxt == "*":
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\":
                    i += 2
                else:
                    i += 1
            i = min(i + 1, n)
            continue
        return c, i + 1
    return "", n


def _function_body_span(text: str, sig_at: int) -> tuple[int, int]:
    """``(open_brace, index_past_close)`` for the function that starts at ``sig_at``.

    A ``{`` inside ``ensures`` / ``requires`` (``match hit {``, ``assert forall``)
    is not the function body. The body brace is the first ``{`` at parenthesis
    depth 0 that starts its line, or that sits on the signature line itself.
    """
    i = sig_at
    paren = 0
    open_at = -1
    while open_at < 0:
        c, nxt = _next_code(text, i)
        if not c:
            raise ValueError("function signature has no body")
        if c == "(":
            paren += 1
        elif c == ")":
            paren = max(0, paren - 1)
        elif c == "{" and paren == 0:
            brace_at = nxt - 1
            line_start = text.rfind("\n", 0, brace_at) + 1
            starts_line = text[line_start:brace_at].strip() == ""
            on_sig_line = "\n" not in text[sig_at:brace_at]
            if starts_line or on_sig_line:
                open_at = brace_at
        i = nxt
    depth = 0
    i = open_at
    while True:
        c, nxt = _next_code(text, i)
        if not c:
            raise ValueError("unclosed function body")
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return open_at, nxt
        i = nxt


def _collapse_proved_bodies(core: str) -> str:
    """Drop proof bodies and equijoin exec bodies from the copy the agent reads.

    Signatures, ensures, and spec functions stay. Verus re-transpiles the real
    bodies from SQL; this file is not what it checks. ``assert forall { } by { }``
    is inside the body, so the span runs to the function's own closing brace.
    """
    begin = core.find("// EQ_JOIN_PROVED_BEGIN")
    out: list[str] = []
    i = 0
    n = len(core)
    while i < n:
        at_line = i == 0 or core[i - 1] == "\n"
        collapse = at_line and core.startswith("pub proof fn ", i)
        if (
            not collapse
            and at_line
            and begin >= 0
            and i >= begin
            and core.startswith("pub fn ", i)
        ):
            collapse = True
        if collapse:
            open_at, close_end = _function_body_span(core, i)
            out.append(core[i:open_at])
            out.append("{\n}\n")
            i = close_end
            if i < n and core[i] == "\n":
                i += 1
            continue
        out.append(core[i])
        i += 1
    return "".join(out)


def prepare_agent_visible_spec(
    verus_spec: str,
    ret_type: str,
    *,
    catalog_assumptions: CatalogAssumptions | None = None,
) -> str:
    """Spec the sandbox agent may read: MethodSpec + TRUSTED agg API for ret_type; no RunQuery skeleton."""
    core = _collapse_proved_bodies(_trim_verus_close(_strip_skeleton(verus_spec)))
    boundary = _boundary_helpers(
        ret_type, verus_spec, catalog_assumptions=catalog_assumptions
    )
    if boundary:
        agent_note = (
            "// === Agent: use TRUSTED helpers below (vstd map/set @ views).\n"
            "// Maps: agg_new_* / agg_add_* / agg_put_*; ensures res@ == method_spec.\n"
            "// Multi-agg steps: agg_step_state_new_* / agg_step_* (+ agg_step_apply_row_* spec).\n"
            "// HAVING: host post-filter exec helper (ensures vs apply_having_filter).\n"
            "// Distinct sets: hashset_*_as_map + set_new_* / set_insert_* (COUNT_DISTINCT state).\n"
            "// Seqs: seq_new_* / seq_push_* when present; else Vec@ directly.\n"
        )
        boundary = agent_note + boundary.lstrip("\n")
    return f"{core}{boundary}}} // verus!\n"


def _inject_duckdb_like_cols_fields(spec_rs: str, schema_dict: dict[str, str]) -> str:
    """Append duckdb_like metadata fields to transpiled Cols struct."""
    extras: list[str] = []
    for col, col_type in schema_dict.items():
        base = col.lower()
        if _rust_vec_type(col_type) == "String":
            extras.append(f"    pub {base}_codes: Vec<u32>,")
            extras.append(f"    pub {base}_dict: Vec<String>,")
        else:
            extras.append(f"    pub {base}_zones: Vec<(u32, u32, usize, usize)>,")
    if not extras:
        return spec_rs
    injection = "\n".join(extras)
    marker = "\n}\n\nimpl Cols"
    if marker not in spec_rs:
        return spec_rs
    return spec_rs.replace(marker, f"\n{injection}\n}}\n\nimpl Cols", 1)


def _prepare_spec_rs(spec_rs: str, schema_dict: dict[str, str] | None = None) -> str:
    core = _strip_skeleton(spec_rs)
    if lemma_load_format() == "duckdb_like" and schema_dict is not None:
        core = _inject_duckdb_like_cols_fields(core, schema_dict)
    return core


def duckdb_ffi_prelude() -> str:
    """FFI + chunk loader module (included once outside ``verus!``)."""
    return _DUCKDB_FFI_INC.read_text(encoding="utf-8")


def _col_kind_for_schema_type(col_type: str) -> str:
    rust_ty = _rust_vec_type(col_type)
    if rust_ty == "String":
        return "String"
    if rust_ty == "bool":
        return "Bool"
    if rust_ty == "u32":
        return "U32"
    return "U64"


def _impl_span(src: str, struct_name: str) -> tuple[int, int] | None:
    needle = f"impl {struct_name} {{"
    start = src.find(needle)
    if start < 0:
        return None
    brace = src.find("{", start)
    depth = 0
    for j in range(brace, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return start, j + 1
    return None


def rewrite_cols_getters_for_pin(
    spec_rs: str,
    *,
    table_name: str,
    schema_dict: dict[str, str],
    struct_name: str = "Cols",
) -> str:
    """Point exec getters at pinned DuckDB vectors (spec still uses Vec model)."""
    span = _impl_span(spec_rs, struct_name)
    if span is None:
        return spec_rs
    lo, hi = span
    impl = spec_rs[lo:hi]
    for i, (col, col_type) in enumerate(schema_dict.items()):
        field = rust_ident(col)
        kind = _col_kind_for_schema_type(col_type)
        if kind == "String":
            impl = impl.replace(
                f"        self.{field}[i].clone()",
                f'        lemma_duckdb_load::read_string("{table_name}", {i}usize, i)',
            )
            impl = impl.replace(
                f"        self.{field}[i] == lit",
                f'        lemma_duckdb_load::eq_str("{table_name}", {i}usize, i, lit)',
            )
        elif kind == "Bool":
            impl = impl.replace(
                f"        self.{field}[i]",
                f'        lemma_duckdb_load::read_bool("{table_name}", {i}usize, i)',
            )
        elif kind == "U32":
            impl = impl.replace(
                f"        self.{field}[i]",
                f'        lemma_duckdb_load::read_u32("{table_name}", {i}usize, i)',
            )
        else:
            impl = impl.replace(
                f"        self.{field}[i]",
                f'        lemma_duckdb_load::read_u64("{table_name}", {i}usize, i)',
            )
    return spec_rs[:lo] + impl + spec_rs[hi:]


def _select_load_generator(
    load_format: str | None = None,
    *,
    load_mode: str = "tbl",
):
    if load_mode == "duckdb":
        return generate_load_cols_duckdb_verus
    fmt = load_format or lemma_load_format()
    if fmt == "duckdb_like":
        return generate_load_cols_duckdb_like_verus
    return generate_load_cols_verus


def generate_load_cols_verus(
    schema_dict: dict[str, str],
    *,
    struct_name: str = "Cols",
    valid_fn: str = "valid_cols",
    load_fn: str = "load_cols",
) -> str:
    """Trusted tbl loader with ensures valid_cols (I/O boundary)."""
    fields = ["    pub n: usize,"]
    col_indices: list[str] = []
    load_pushes: list[str] = []
    vec_decls: list[str] = []

    for col, col_type in schema_dict.items():
        base = col.lower()
        field = rust_ident(col)
        rust_ty = _rust_vec_type(col_type)
        fields.append(f"    pub {field}: Vec<{rust_ty}>,")
        col_indices.append(
            f'    let {base}_i = *name_to_idx.get("{col.upper()}").expect("missing col {col}");'
        )
        vec_decls.append(f"        let mut {field}: Vec<{rust_ty}> = Vec::new();")
        if rust_ty == "String":
            load_pushes.append(
                f"        {field}.push(strip_quotes(f[{base}_i]).to_string());"
            )
        else:
            load_pushes.append(
                f"        {field}.push(f[{base}_i].parse::<{rust_ty}>().unwrap());"
            )

    first_col = next(iter(schema_dict.keys()))
    first_field = rust_ident(first_col)
    field_inits = "\n".join(f"            {rust_ident(col)}," for col in schema_dict)

    return f"""
#[verifier::external_body]
pub exec fn {load_fn}(path: &str, limit: usize) -> (cols: {struct_name})
    ensures {valid_fn}(&cols),
{{
    use std::collections::HashMap;
    use std::fs::File;
    use std::io::{{BufRead, BufReader}};

    fn strip_quotes(s: &str) -> &str {{
        s.trim_matches('"')
    }}

    let f = File::open(path).expect("open .tbl");
    let mut rdr = BufReader::new(f);
    let mut hdr = String::new();
    rdr.read_line(&mut hdr).unwrap();
    let mut name_to_idx: HashMap<String, usize> = HashMap::new();
    for (i, c) in hdr.split('|').enumerate() {{
        name_to_idx.insert(c.trim().to_uppercase(), i);
    }}
{chr(10).join('    ' + line for line in col_indices)}

{chr(10).join(vec_decls)}

    for raw_line in rdr.lines().take(limit) {{
        let raw_line = raw_line.unwrap();
        let f: Vec<&str> = raw_line.split('|').collect();
        if f.is_empty() {{
            continue;
        }}
{chr(10).join(load_pushes)}
    }}

    let n = {first_field}.len();
    {struct_name} {{
        n,
{field_inits}
    }}
}}
"""


def generate_load_cols_duckdb_verus(
    schema_dict: dict[str, str],
    *,
    table_name: str,
    struct_name: str = "Cols",
    valid_fn: str = "valid_cols",
    load_fn: str = "load_cols",
    catalog_multi: dict[str, dict[str, str]] | None = None,
) -> str:
    """Trusted DuckDB loader: pin result vectors; Cols getters read pointers (no memcpy)."""
    from verus_transpiler.column_projection import pin_schema_for_table

    pinned = pin_schema_for_table(table_name, schema_dict, catalog_multi)
    col_specs: list[str] = []
    field_inits: list[str] = []

    for col, col_type in pinned.items():
        field = rust_ident(col)
        kind = _col_kind_for_schema_type(col_type)
        col_specs.append(f'            ("{col}", lemma_duckdb_load::ColKind::{kind}),')
        rust_ty = _rust_vec_type(col_type)
        field_inits.append(f"            {field}: Vec::<{rust_ty}>::new(),")

    return f"""
#[verifier::external_body]
pub exec fn {load_fn}(db_path: &str, limit: usize) -> (cols: {struct_name})
    ensures {valid_fn}(&cols),
{{
    let n = lemma_duckdb_load::pin_table(
        "{table_name}",
        db_path,
        "{table_name}",
        limit,
        &[
{chr(10).join(col_specs)}
        ],
    );
    {struct_name} {{
        n,
{chr(10).join(field_inits)}
    }}
}}
"""


def generate_load_cols_duckdb_like_verus(
    schema_dict: dict[str, str],
    *,
    struct_name: str = "Cols",
    valid_fn: str = "valid_cols",
    load_fn: str = "load_cols",
    zone_rows: int = 65536,
) -> str:
    """duckdb_like: dictionary-encoded strings + precomputed zone maps for numerics."""
    fields = ["    pub n: usize,"]
    col_indices: list[str] = []
    load_pushes: list[str] = []
    vec_decls: list[str] = []
    zone_build: list[str] = []

    for col, col_type in schema_dict.items():
        base = col.lower()
        field = rust_ident(col)
        rust_ty = _rust_vec_type(col_type)
        col_indices.append(
            f'    let {base}_i = *name_to_idx.get("{col.upper()}").expect("missing col {col}");'
        )
        if rust_ty == "String":
            fields.append(f"    pub {field}: Vec<String>,")
            fields.append(f"    pub {base}_codes: Vec<u32>,")
            fields.append(f"    pub {base}_dict: Vec<String>,")
            vec_decls.append(f"        let mut {field}: Vec<String> = Vec::new();")
            vec_decls.append(f"        let mut {base}_codes: Vec<u32> = Vec::new();")
            vec_decls.append(f"        let mut {base}_dict: Vec<String> = Vec::new();")
            vec_decls.append(
                f"        let mut {base}_rev: std::collections::HashMap<String, u32> = "
                "std::collections::HashMap::new();"
            )
            load_pushes.append(
                f"""        {{
            let raw = strip_quotes(f[{base}_i]).to_string();
            let code = match {base}_rev.get(&raw) {{
                Some(&c) => c,
                None => {{
                    let c = {base}_dict.len() as u32;
                    {base}_dict.push(raw.clone());
                    {base}_rev.insert(raw.clone(), c);
                    c
                }},
            }};
            {base}_codes.push(code);
            {field}.push(raw);
        }}"""
            )
        else:
            fields.append(f"    pub {field}: Vec<{rust_ty}>,")
            fields.append(f"    pub {base}_zones: Vec<(u32, u32, usize, usize)>,")
            vec_decls.append(f"        let mut {field}: Vec<{rust_ty}> = Vec::new();")
            load_pushes.append(
                f"        {field}.push(f[{base}_i].parse::<{rust_ty}>().unwrap());"
            )
            zone_build.append(
                f"""    let mut {base}_zones: Vec<(u32, u32, usize, usize)> = Vec::new();
    {{
        let zr = {zone_rows};
        let mut start: usize = 0;
        while start < {field}.len() {{
            let end = if start + zr < {field}.len() {{ start + zr }} else {{ {field}.len() }};
            let mut min_v = {field}[start];
            let mut max_v = {field}[start];
            let mut j = start + 1;
            while j < end {{
                if {field}[j] < min_v {{ min_v = {field}[j]; }}
                if {field}[j] > max_v {{ max_v = {field}[j]; }}
                j = j + 1;
            }}
            {base}_zones.push((min_v as u32, max_v as u32, start, end));
            start = end;
        }}
    }}"""
            )

    first_field = rust_ident(next(iter(schema_dict.keys())))
    field_inits: list[str] = []
    for col, col_type in schema_dict.items():
        base = col.lower()
        field = rust_ident(col)
        rust_ty = _rust_vec_type(col_type)
        field_inits.append(f"            {field},")
        if rust_ty == "String":
            field_inits.append(f"            {base}_codes,")
            field_inits.append(f"            {base}_dict,")
        else:
            field_inits.append(f"            {base}_zones,")

    return f"""
#[verifier::external_body]
pub exec fn {load_fn}(path: &str, limit: usize) -> (cols: {struct_name})
    ensures {valid_fn}(&cols),
{{
    use std::collections::HashMap;
    use std::fs::File;
    use std::io::{{BufRead, BufReader}};

    fn strip_quotes(s: &str) -> &str {{
        s.trim_matches('"')
    }}

    let f = File::open(path).expect("open .tbl");
    let mut rdr = BufReader::new(f);
    let mut hdr = String::new();
    rdr.read_line(&mut hdr).unwrap();
    let mut name_to_idx: HashMap<String, usize> = HashMap::new();
    for (i, c) in hdr.split('|').enumerate() {{
        name_to_idx.insert(c.trim().to_uppercase(), i);
    }}
{chr(10).join('    ' + line for line in col_indices)}

{chr(10).join(vec_decls)}

    for raw_line in rdr.lines().take(limit) {{
        let raw_line = raw_line.unwrap();
        let f: Vec<&str> = raw_line.split('|').collect();
        if f.is_empty() {{
            continue;
        }}
{chr(10).join(load_pushes)}
    }}

    let n = {first_field}.len();
{chr(10).join(zone_build)}
    {struct_name} {{
        n,
{chr(10).join(field_inits)}
    }}
}}
"""


_BENCH_ITERS = 5


def _bench_black_box(ret_type: str) -> str:
    if ret_type == "u64":
        return "std::hint::black_box(res);"
    return "std::hint::black_box(res.len());"


def _median_bench_loop(
    *,
    fmt: str,
    ret_type: str = "u64",
    bench_call: str = "",
    bench_timing_body: str = "",
    bench_post_timing: str = "",
) -> str:
    """Five timed iterations; print median QUERY_LATENCY_US; keep RESULT from last run."""
    black_box = _bench_black_box(ret_type)
    if bench_timing_body:
        exec_block = f"""let t0 = Instant::now();
        {bench_timing_body}
        *t = t0.elapsed().as_micros();
        {bench_post_timing}"""
    else:
        exec_block = f"""let t0 = Instant::now();
        let res = {bench_call};
        {black_box}
        *t = t0.elapsed().as_micros();"""
    return f"""let mut times = [0u128; {_BENCH_ITERS}];
    let mut last = String::new();
    for t in &mut times {{
        {exec_block}
        last = {fmt};
    }}
    times.sort();
    println!("QUERY_LATENCY_US: {{}}", times[times.len() / 2]);"""


def _emit_table_cols_and_loader(
    table: str,
    cols: dict[str, str],
    *,
    load_mode: str = "tbl",
    catalog_multi: dict[str, dict[str, str]] | None = None,
) -> tuple[str, str]:
    """Emit ``Cols_<table>`` struct, ``valid_cols_<table>``, and ``load_cols_<table>``."""
    from verus_transpiler.value_bounds import emit_valid_cols_predicate

    from verus_transpiler import generate_cols_rs

    struct_name = f"Cols_{table}"
    valid_fn = f"valid_cols_{table}"
    load_fn = f"load_cols_{table}"

    cols_block = generate_cols_rs(cols, struct_name=struct_name)
    valid_block = emit_valid_cols_predicate(
        cols, struct_name=struct_name
    ).replace("valid_cols", valid_fn)
    combined = f"{cols_block}\n\n{valid_block}"
    if load_mode == "duckdb":
        combined = rewrite_cols_getters_for_pin(
            combined,
            table_name=table,
            schema_dict=cols,
            struct_name=struct_name,
        )

    load_gen = _select_load_generator(load_mode=load_mode)
    duckdb_kwargs: dict[str, object] = {}
    if load_mode == "duckdb":
        duckdb_kwargs = {
            "table_name": table,
            "catalog_multi": catalog_multi,
        }
    loader = load_gen(
        cols,
        struct_name=struct_name,
        valid_fn=valid_fn,
        load_fn=load_fn,
        **duckdb_kwargs,
    )
    return combined, loader


def _support_table_defs_in_spec(spec_rs: str, table: str) -> bool:
    """True when transpiled spec already defines ``Cols_<table>`` (IN/EXISTS wiring)."""
    return re.search(rf"pub struct Cols_{re.escape(table)}\b", spec_rs) is not None


def _inject_support_table_defs(spec_rs: str, support_defs: str) -> str:
    """Insert support-table Cols/valid_cols before spec helpers that may reference them."""
    if not support_defs.strip():
        return spec_rs
    for marker in (
        "pub open spec fn method_spec_helper",
        "pub open spec fn exists_corr",
        "pub open spec fn scalar_subquery",
        "pub open spec fn in_subquery",
    ):
        if marker in spec_rs:
            return spec_rs.replace(marker, f"{support_defs}\n\n{marker}", 1)
    return f"{spec_rs.rstrip()}\n\n{support_defs}\n"


def generate_main_rs(
    *,
    default_tbl: str,
    ret_type: str,
    bench_exec: str = "",
    bench_timing_body: str = "",
    bench_post_timing: str = "",
    bench_main_prefix: str = "",
    rust_ret: str | None = None,
    load_mode: str = "tbl",
    default_db: str = "",
    support_tables: tuple[str, ...] | None = None,
) -> str:
    if rust_ret is not None:
        from research_loop.format_result_from_type import format_result_for_exec_type

        fmt = format_result_for_exec_type(rust_ret)
    else:
        cfg = _cfg(ret_type)
        fmt = cfg["format_result"]
    support = support_tables or ()
    if bench_exec:
        bench_call = bench_exec
    elif support:
        args = ", ".join(["&cols", *[f"&{t}" for t in support]])
        bench_call = f"run_query({args})"
    else:
        bench_call = "run_query(&cols)"
    timing = _median_bench_loop(
        fmt=fmt,
        ret_type=ret_type,
        bench_call=bench_call,
        bench_timing_body=bench_timing_body,
        bench_post_timing=bench_post_timing,
    )
    if load_mode == "duckdb":
        path_arg = f'        .unwrap_or("{default_db}");'
        load_line = "    let cols = load_cols(db_path, limit);"
        support_loads = "\n".join(
            f"    let {table} = load_cols_{table}(db_path, limit);" for table in support
        )
        path_decl = """    let db_path = args
        .get(1)
        .map(|s| s.as_str())"""
        timing += '\n    println!("SESSION_HOT_US: {}", times[times.len() / 2]);'
        epilogue = "    lemma_duckdb_load::unpin_all();\n"
    else:
        path_arg = f'        .unwrap_or("{default_tbl}");'
        load_line = "    let cols = load_cols(tbl_path, limit);"
        support_loads = "\n".join(
            f"    let {table} = load_cols_{table}(tbl_path, limit);" for table in support
        )
        path_decl = """    let tbl_path = args
        .get(1)
        .map(|s| s.as_str())"""
        epilogue = ""
    if support_loads:
        support_loads = f"\n{support_loads}"

    return f"""
fn main() {{
    use std::env;
    use std::time::Instant;

    let args: Vec<String> = env::args().collect();
{path_decl}
{path_arg}
    let limit: usize = args
        .get(2)
        .and_then(|s| s.parse().ok())
        .unwrap_or(50_000);

{load_line}{support_loads}
{bench_main_prefix}

    {timing}
    println!("{{}}", last);
{epilogue}}}
"""


def generate_main_join_rs(
    *,
    left_table: str,
    right_table: str,
    default_left_tbl: str,
    default_right_tbl: str,
    ret_type: str,
    bench_exec: str = "run_query(&left, &right)",
    load_mode: str = "tbl",
    default_db: str = "",
) -> str:
    cfg = _cfg(ret_type)
    fmt = cfg["format_result"]
    load_left = f"load_cols_{left_table}"
    load_right = f"load_cols_{right_table}"
    if load_mode == "duckdb":
        path_setup = f"""    let db_path = args
        .get(1)
        .map(|s| s.as_str())
        .unwrap_or("{default_db}");
    let limit: usize = args
        .get(2)
        .and_then(|s| s.parse().ok())
        .unwrap_or(50_000);

    let left = {load_left}(db_path, limit);
    let right = {load_right}(db_path, limit);"""
    else:
        path_setup = f"""    let left_path = args
        .get(1)
        .map(|s| s.as_str())
        .unwrap_or("{default_left_tbl}");
    let right_path = args
        .get(2)
        .map(|s| s.as_str())
        .unwrap_or("{default_right_tbl}");
    let limit: usize = args
        .get(3)
        .and_then(|s| s.parse().ok())
        .unwrap_or(50_000);

    let left = {load_left}(left_path, limit);
    let right = {load_right}(right_path, limit);"""
    timing = _median_bench_loop(fmt=fmt, ret_type=ret_type, bench_call=bench_exec)
    if load_mode == "duckdb":
        timing += '\n    println!("SESSION_HOT_US: {}", times[times.len() / 2]);'
        epilogue = "    lemma_duckdb_load::unpin_all();\n"
    else:
        epilogue = ""
    return f"""
fn main() {{
    use std::env;
    use std::time::Instant;

    let args: Vec<String> = env::args().collect();
{path_setup}

    {timing}
    println!("{{}}", last);
{epilogue}}}
"""


def assemble_verified_join_program(
    *,
    spec_rs: str,
    run_query_body: str,
    multi_schema: dict[str, dict[str, str]],
    table_order: tuple[str, str],
    ret_type: str,
    default_tbls: dict[str, str],
    hot_path_rs: str = "",
    bench_exec: str = "",
    load_mode: str = "tbl",
    default_db: str = "",
    catalog_assumptions: CatalogAssumptions | None = None,
) -> str:
    """Build one `.rs` file for a two-table join query."""
    if not _ret_type_supported(ret_type):
        raise ValueError(
            f"unsupported MethodSpec return type key (no Trusted/shell wiring): {ret_type}"
        )

    left_table, right_table = table_order
    if left_table not in multi_schema or right_table not in multi_schema:
        raise ValueError(f"table_order {table_order} not in multi_schema keys")

    core = _prepare_spec_rs(spec_rs, None)
    if load_mode == "duckdb":
        for table, cols in multi_schema.items():
            core = rewrite_cols_getters_for_pin(
                core,
                table_name=table,
                schema_dict=cols,
                struct_name=f"Cols_{table}",
            )
    boundary = _boundary_helpers(
        ret_type, spec_rs, catalog_assumptions=catalog_assumptions
    )
    agent_externs = maybe_emit_agent_externs(run_query_body, context=boundary)
    load_gen = _select_load_generator(load_mode=load_mode)
    loaders = "\n".join(
        load_gen(
            cols,
            struct_name=f"Cols_{table}",
            valid_fn=f"valid_cols_{table}",
            load_fn=f"load_cols_{table}",
            **(
                {"table_name": table}
                if load_mode == "duckdb"
                else {}
            ),
        ).strip()
        for table, cols in multi_schema.items()
    )
    main_rs = generate_main_join_rs(
        left_table=left_table,
        right_table=right_table,
        default_left_tbl=default_tbls[left_table],
        default_right_tbl=default_tbls[right_table],
        ret_type=ret_type,
        bench_exec=bench_exec or "run_query(&left, &right)",
        load_mode=load_mode,
        default_db=default_db,
    )

    hot = f"{hot_path_rs.rstrip()}\n\n" if hot_path_rs else ""
    duckdb_prelude = f"{duckdb_ffi_prelude()}\n\n" if load_mode == "duckdb" else ""
    return (
        f"{duckdb_prelude}"
        f"{core}\n"
        f"{boundary}\n"
        f"{agent_externs.rstrip()}\n\n"
        f"{run_query_body.rstrip()}\n\n"
        f"{loaders}\n"
        f"}} // verus!\n"
        f"{hot}"
        f"{main_rs}"
    )


def generate_main_nway_rs(
    *,
    table_order: tuple[str, ...],
    default_tbls: dict[str, str],
    ret_type: str,
    bench_exec: str = "",
    load_mode: str = "tbl",
    default_db: str = "",
) -> str:
    cfg = _cfg(ret_type)
    fmt = cfg["format_result"]
    load_lines = []
    arg_names = []
    if load_mode == "duckdb":
        load_lines.append(f"""    let db_path = args
        .get(1)
        .map(|s| s.as_str())
        .unwrap_or("{default_db}");""")
        load_lines.append("""    let limit: usize = args
        .get(2)
        .and_then(|s| s.parse().ok())
        .unwrap_or(50_000);""")
        for table in table_order:
            load_lines.append(f"    let {table} = load_cols_{table}(db_path, limit);")
            arg_names.append(f"&{table}")
    else:
        load_lines.append("""    let limit: usize = args
        .get(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(50_000);""")
        for i, table in enumerate(table_order):
            idx = i + 2
            default = default_tbls[table]
            load_lines.append(
                f"    let {table}_path = args.get({idx}).map(|s| s.as_str()).unwrap_or(\"{default}\");"
            )
            load_lines.append(
                f"    let {table} = load_cols_{table}({table}_path, limit);"
            )
            arg_names.append(f"&{table}")
    bench_call = bench_exec or f"run_query({', '.join(arg_names)})"
    timing = _median_bench_loop(fmt=fmt, ret_type=ret_type, bench_call=bench_call)
    if load_mode == "duckdb":
        timing += '\n    println!("SESSION_HOT_US: {}", times[times.len() / 2]);'
        epilogue = "    lemma_duckdb_load::unpin_all();\n"
    else:
        epilogue = ""
    return f"""
fn main() {{
    use std::env;
    use std::time::Instant;

    let args: Vec<String> = env::args().collect();

{chr(10).join(load_lines)}

    {timing}
    println!("{{}}", last);
{epilogue}}}
"""


def assemble_verified_nway_program(
    *,
    spec_rs: str,
    run_query_body: str,
    multi_schema: dict[str, dict[str, str]],
    table_order: tuple[str, ...],
    ret_type: str,
    default_tbls: dict[str, str],
    hot_path_rs: str = "",
    bench_exec: str = "",
    load_mode: str = "tbl",
    default_db: str = "",
    catalog_assumptions: CatalogAssumptions | None = None,
) -> str:
    """Build one `.rs` file for an N-table (3+) join query."""
    if not _ret_type_supported(ret_type):
        raise ValueError(
            f"unsupported MethodSpec return type key (no Trusted/shell wiring): {ret_type}"
        )

    for table in table_order:
        if table not in multi_schema:
            raise ValueError(f"table {table!r} not in multi_schema")

    core = _prepare_spec_rs(spec_rs, None)
    if load_mode == "duckdb":
        for table, cols in multi_schema.items():
            core = rewrite_cols_getters_for_pin(
                core,
                table_name=table,
                schema_dict=cols,
                struct_name=f"Cols_{table}",
            )
    boundary = _boundary_helpers(
        ret_type, spec_rs, catalog_assumptions=catalog_assumptions
    )
    agent_externs = maybe_emit_agent_externs(run_query_body, context=boundary)
    load_gen = _select_load_generator(load_mode=load_mode)
    loaders = "\n".join(
        load_gen(
            cols,
            struct_name=f"Cols_{table}",
            valid_fn=f"valid_cols_{table}",
            load_fn=f"load_cols_{table}",
            **(
                {"table_name": table}
                if load_mode == "duckdb"
                else {}
            ),
        ).strip()
        for table, cols in multi_schema.items()
    )
    main_rs = generate_main_nway_rs(
        table_order=table_order,
        default_tbls=default_tbls,
        ret_type=ret_type,
        bench_exec=bench_exec,
        load_mode=load_mode,
        default_db=default_db,
    )
    hot = f"{hot_path_rs.rstrip()}\n\n" if hot_path_rs else ""
    duckdb_prelude = f"{duckdb_ffi_prelude()}\n\n" if load_mode == "duckdb" else ""
    return (
        f"{duckdb_prelude}"
        f"{core}\n"
        f"{boundary}\n"
        f"{agent_externs.rstrip()}\n\n"
        f"{run_query_body.rstrip()}\n\n"
        f"{loaders}\n"
        f"}} // verus!\n"
        f"{hot}"
        f"{main_rs}"
    )


def assemble_verified_program(
    *,
    spec_rs: str,
    run_query_body: str,
    schema_dict: dict[str, str],
    ret_type: str,
    default_tbl: str,
    hot_path_rs: str = "",
    bench_exec: str = "",
    bench_timing_body: str = "",
    bench_post_timing: str = "",
    bench_main_prefix: str = "",
    rust_ret: str | None = None,
    load_mode: str = "tbl",
    table_name: str = "t",
    default_db: str = "",
    catalog_multi: dict[str, dict[str, str]] | None = None,
    support_tables: dict[str, dict[str, str]] | None = None,
    catalog_assumptions: CatalogAssumptions | None = None,
) -> str:
    """Build one `.rs` file: spec + proved run_query + load_cols + main."""
    if not _ret_type_supported(ret_type):
        raise ValueError(
            f"unsupported MethodSpec return type key (no Trusted/shell wiring): {ret_type}"
        )

    effective_catalog: dict[str, dict[str, str]] = dict(catalog_multi or {})
    effective_catalog.setdefault(table_name, schema_dict)
    support = support_tables or {}
    if support:
        effective_catalog.update(support)

    core = _prepare_spec_rs(spec_rs, schema_dict)
    support_defs = ""
    support_loaders = ""
    if support:
        defs: list[str] = []
        loaders: list[str] = []
        for st, cols in support.items():
            cols_block, loader = _emit_table_cols_and_loader(
                st,
                cols,
                load_mode=load_mode,
                catalog_multi=effective_catalog,
            )
            if _support_table_defs_in_spec(spec_rs, st):
                loaders.append(loader.strip())
            else:
                defs.append(cols_block.strip())
                loaders.append(loader.strip())
        support_defs = "\n\n".join(defs)
        support_loaders = "\n".join(loaders)
        core = _inject_support_table_defs(core, support_defs)
    if load_mode == "duckdb":
        core = rewrite_cols_getters_for_pin(
            core,
            table_name=table_name,
            schema_dict=schema_dict,
            struct_name="Cols",
        )
        for st, cols in support.items():
            core = rewrite_cols_getters_for_pin(
                core,
                table_name=st,
                schema_dict=cols,
                struct_name=f"Cols_{st}",
            )
    boundary = _boundary_helpers(
        ret_type, spec_rs, catalog_assumptions=catalog_assumptions
    )
    agent_externs = maybe_emit_agent_externs(run_query_body, context=boundary)
    load_gen = _select_load_generator(load_mode=load_mode)
    duckdb_kwargs: dict[str, object] = {}
    if load_mode == "duckdb":
        duckdb_kwargs = {
            "table_name": table_name,
            "catalog_multi": effective_catalog,
        }
    load_cols = load_gen(
        schema_dict,
        **duckdb_kwargs,
    )
    all_loaders = load_cols.rstrip()
    if support_loaders:
        all_loaders = f"{all_loaders}\n\n{support_loaders}"
    main_rs = generate_main_rs(
        default_tbl=default_tbl,
        ret_type=ret_type,
        bench_exec=bench_exec,
        bench_timing_body=bench_timing_body,
        bench_post_timing=bench_post_timing,
        bench_main_prefix=bench_main_prefix,
        rust_ret=rust_ret,
        load_mode=load_mode,
        default_db=default_db,
        support_tables=tuple(support.keys()),
    )
    hot = f"{hot_path_rs.rstrip()}\n\n" if hot_path_rs else ""
    duckdb_prelude = f"{duckdb_ffi_prelude()}\n\n" if load_mode == "duckdb" else ""

    return (
        f"{duckdb_prelude}"
        f"{core}\n"
        f"{boundary}\n"
        f"{agent_externs.rstrip()}\n\n"
        f"{run_query_body.rstrip()}\n\n"
        f"{all_loaders}\n"
        f"}} // verus!\n"
        f"{hot}"
        f"{main_rs}"
    )


def rust_ret_from_run_query_fn(fn_text: str) -> str | None:
    """Parse admitted ``pub exec fn run_query`` return type for format_result wiring."""
    from research_loop.admit_agent_runquery import _parse_return_type

    try:
        return _parse_return_type(fn_text)
    except ValueError:
        return None
