"""Host TRUSTED HAVING post-filter helpers (exec HashMap retain vs apply_having_filter)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from research_loop.trusted_ret_bridge import RetBridge, get_bridge

_HAVING_MAP_PEEL_INC = Path(__file__).resolve().parent / "having_map_peel.rs.inc"

_APPLY_HAVING_RE = re.compile(r"apply_having_filter\s*\(")
_IDENT_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\b")
_RUST_KEYWORDS = frozenset(
    {
        "as",
        "bool",
        "break",
        "continue",
        "else",
        "false",
        "if",
        "in",
        "int",
        "let",
        "match",
        "return",
        "true",
        "u32",
        "u64",
        "while",
    }
)


@dataclass(frozen=True)
class HavingFilterLayout:
    closure_params: str
    closure_body: str
    full_closure: str


def _extract_balanced_parens(text: str, open_pos: int) -> tuple[str, int] | None:
    if open_pos >= len(text) or text[open_pos] != "(":
        return None
    depth = 0
    for i in range(open_pos, len(text)):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_pos + 1 : i], i + 1
    return None


def _parse_closure(closure: str) -> tuple[str, str] | None:
    closure = closure.strip()
    if not closure.startswith("|"):
        return None
    pipe2 = closure.find("|", 1)
    if pipe2 == -1:
        return None
    params = closure[1:pipe2].strip()
    body_and_rest = closure[pipe2 + 1 :]
    depth = 0
    body_end: int | None = None
    for i, ch in enumerate(body_and_rest):
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                body_end = i
                break
            depth -= 1
    body = body_and_rest if body_end is None else body_and_rest[:body_end]
    body = body.strip()
    if not body:
        return None
    return params, body


def _find_having_call_closure(spec_rs: str) -> str | None:
    """Return the closure argument of ``apply_having_filter(m, CLOSURE)`` in MethodSpec."""
    for m in _APPLY_HAVING_RE.finditer(spec_rs):
        inner = _extract_balanced_parens(spec_rs, m.end() - 1)
        if inner is None:
            continue
        args_text = inner[0].lstrip()
        if not re.match(r"m\s*,", args_text):
            continue
        rest = re.sub(r"^m\s*,\s*", "", args_text, count=1)
        if not rest.startswith("|"):
            continue
        return rest
    return None


def parse_having_filter_layout(spec_rs: str) -> HavingFilterLayout | None:
    """Parse ``apply_having_filter(m, |k, v| ...)`` from MethodSpec, or None."""
    closure = _find_having_call_closure(spec_rs)
    if closure is None:
        return None
    parsed = _parse_closure(closure)
    if parsed is None:
        return None
    params, body = parsed
    return HavingFilterLayout(
        closure_params=params,
        closure_body=body,
        full_closure=closure.strip(),
    )


def _value_param_type(closure_params: str) -> str | None:
    for part in closure_params.split(","):
        part = part.strip()
        if ":" not in part:
            continue
        name, typ = part.split(":", 1)
        if name.strip() == "v":
            return typ.strip()
    return None


def _is_scalar_value_type(typ: str) -> bool:
    typ = typ.strip()
    return bool(typ) and not typ.startswith("(")


_SCALAR_V_RE = re.compile(r"(?<!\*)\bv(?![.\w])")


def _deref_scalar_v_in_body(body: str) -> str:
    """Rewrite bare ``v`` to ``*v`` for exec ``HashMap::filter`` (value is ``&V``)."""
    return _SCALAR_V_RE.sub("*v", body)


def _exec_filter_body(layout: HavingFilterLayout) -> str:
    """Spec HAVING body rewritten for exec HashMap filter when value type is scalar."""
    body = layout.closure_body
    v_type = _value_param_type(layout.closure_params)
    if v_type and _is_scalar_value_type(v_type):
        body = _deref_scalar_v_in_body(body)
    return body


def _valid_cols_predicate(struct_name: str, param: str) -> str:
    if struct_name == "Cols":
        return f"valid_cols({param})"
    if struct_name.startswith("Cols_"):
        table = struct_name[len("Cols_") :]
        return f"valid_cols_{table}({param})"
    raise ValueError(f"unsupported Cols struct name in method_spec: {struct_name}")


def _closure_param_names(closure_params: str) -> set[str]:
    names: set[str] = set()
    for part in closure_params.split(","):
        part = part.strip()
        if not part:
            continue
        names.add(part.split(":")[0].strip())
    return names


def referenced_table_params(
    body: str,
    closure_params: str,
    method_params: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """``method_spec`` table params referenced in the HAVING closure body."""
    locals_ = _closure_param_names(closure_params)
    out: list[tuple[str, str]] = []
    for param, struct in method_params:
        if param in locals_:
            continue
        if re.search(rf"\b{re.escape(param)}\b", body):
            out.append((param, struct))
    return out


_SPEC_PARAM_RE = re.compile(r"(\w+)\s*:\s*&(\w+)")
_SPEC_INDEX_PARAM_RE = re.compile(r"(\w+)\s*:\s*int\b")


def _split_top_level_commas(text: str) -> list[str]:
    from research_loop.method_spec_ret_type import _split_top_level_commas as split

    return split(text)


def _parse_spec_fn_params(spec_rs: str, fn_name: str) -> list[tuple[str, str]] | None:
    m = re.search(rf"pub\s+open\s+spec\s+fn\s+{re.escape(fn_name)}\s*\(", spec_rs)
    if not m:
        return None
    inner = _extract_balanced_parens(spec_rs, m.end() - 1)
    if inner is None:
        return None
    params: list[tuple[str, str]] = []
    for chunk in _split_top_level_commas(inner[0]):
        chunk = chunk.strip()
        if not chunk:
            continue
        pm = _SPEC_PARAM_RE.fullmatch(chunk)
        if not pm:
            return None
        params.append((pm.group(1), pm.group(2)))
    return params


def _calls_in_body(body: str) -> list[tuple[str, list[str]]]:
    calls: list[tuple[str, list[str]]] = []
    for m in re.finditer(r"(\w+)\s*\(", body):
        fn_name = m.group(1)
        inner = _extract_balanced_parens(body, m.end() - 1)
        if inner is None:
            continue
        args = [a.strip() for a in _split_top_level_commas(inner[0]) if a.strip()]
        if not args:
            calls.append((fn_name, []))
            continue
        if all(re.fullmatch(r"[a-z_][a-z0-9_]*", a) for a in args):
            calls.append((fn_name, args))
    return calls


def table_params_for_having(
    body: str,
    closure_params: str,
    spec_rs: str,
    method_params: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Table params the HAVING exec helper must take (method_spec + spec helper calls)."""
    locals_ = _closure_param_names(closure_params)
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    def add(param: str, struct: str) -> None:
        if param in locals_ or param in seen:
            return
        seen.add(param)
        out.append((param, struct))

    for param, struct in referenced_table_params(body, closure_params, method_params):
        add(param, struct)

    for fn_name, args in _calls_in_body(body):
        sig_params = _parse_spec_fn_params(spec_rs, fn_name)
        if not sig_params:
            continue
        for arg, (pname, struct) in zip(args, sig_params, strict=False):
            if arg != pname:
                add(arg, struct)
            else:
                add(pname, struct)

    return out


def unsupported_having_predicate_reason(
    layout: HavingFilterLayout,
    spec_rs: str,
    method_params: list[tuple[str, str]],
) -> str | None:
    """Return a skip reason when the predicate needs bindings we cannot emit."""
    locals_ = _closure_param_names(layout.closure_params)
    bound = locals_ | {p for p, _ in table_params_for_having(
        layout.closure_body,
        layout.closure_params,
        spec_rs,
        method_params,
    )}
    body = layout.closure_body
    for m in _IDENT_RE.finditer(body):
        name = m.group(1)
        if name in bound or name in _RUST_KEYWORDS:
            continue
        rest = body[m.end() :].lstrip()
        if rest.startswith("("):
            continue
        return (
            f"predicate references unbound identifier {name!r} "
            "(not a method_spec table param or spec helper argument)"
        )
    return None


def emit_having_map_peel_structs(rust_ret: str | None = None) -> str:
    """Layout structs for inline peel inside ``apply_having_filter_exec_*`` only."""
    full = _HAVING_MAP_PEEL_INC.read_text(encoding="utf-8")
    if rust_ret is None:
        return full
    if rust_ret.startswith(("HashMapWithView", "StringHashMap")):
        return full.rstrip() + "\n"
    return ""


def emit_having_map_peel_trusted(rust_ret: str | None = None) -> str:
    """Deprecated alias: peel is private inside HAVING exec; structs only."""
    return emit_having_map_peel_structs(rust_ret)


def _needs_having_map_peel(rust_ret: str) -> bool:
    return rust_ret.startswith(("HashMapWithView", "StringHashMap"))


def _having_filter_exec_body(rust_ret: str, filter_expr: str) -> str:
    """Runtime filter via inline peel (transmute scoped to HAVING exec Trusted)."""
    if rust_ret.startswith("StringHashMap"):
        val_ty = rust_ret[len("StringHashMap<") : -1]
        return f"""{{
    let peeled: StringHashMapPeel<{val_ty}> = unsafe {{ std::mem::transmute(hm) }};
    let std_hm = peeled.m;
    let std_res: std::collections::HashMap<String, {val_ty}> = std_hm
        .into_iter()
        .filter(|(_k, v)| {filter_expr})
        .collect();
    let wrapped = StringHashMapPeel {{ m: std_res }};
    unsafe {{ std::mem::transmute(wrapped) }}
}}"""
    if rust_ret.startswith("HashMapWithView"):
        inner = rust_ret[len("HashMapWithView<") : -1]
        key_ty, val_ty = inner.split(", ", 1)
        return f"""{{
    let peeled: HashMapWithViewPeel<{key_ty}, {val_ty}> = unsafe {{ std::mem::transmute(hm) }};
    let std_hm = peeled.m;
    let std_res: std::collections::HashMap<{key_ty}, {val_ty}> = std_hm
        .into_iter()
        .filter(|(_k, v)| {filter_expr})
        .collect();
    let wrapped = HashMapWithViewPeel {{ m: std_res }};
    unsafe {{ std::mem::transmute(wrapped) }}
}}"""
    return f"""hm.into_iter().filter(|(_k, v)| {filter_expr}).collect()"""


def _having_skip_comment(reason: str) -> str:
    return f"\n// === HAVING exec skipped: {reason} ===\n"


def _extract_balanced_braces(text: str, open_pos: int) -> tuple[str, int] | None:
    if open_pos >= len(text) or text[open_pos] != "{":
        return None
    depth = 0
    for i in range(open_pos, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_pos + 1 : i], i + 1
    return None


def _extract_open_spec_fn(spec_rs: str, fn_name: str) -> dict[str, object] | None:
    """Return params, ret_type, body for ``pub open spec fn {fn_name}``."""
    m = re.search(rf"pub\s+open\s+spec\s+fn\s+{re.escape(fn_name)}\s*\(", spec_rs)
    if not m:
        return None
    inner = _extract_balanced_parens(spec_rs, m.end() - 1)
    if inner is None:
        return None
    params: list[tuple[str, str]] = []
    for chunk in _split_top_level_commas(inner[0]):
        chunk = chunk.strip()
        if not chunk:
            continue
        pm = _SPEC_PARAM_RE.fullmatch(chunk)
        if pm:
            params.append((pm.group(1), pm.group(2)))
            continue
        im = _SPEC_INDEX_PARAM_RE.fullmatch(chunk)
        if im:
            params.append((im.group(1), "int"))
            continue
        return None
    rest = spec_rs[inner[1] :].lstrip()
    ret_m = re.match(r"->\s*([^\n{]+)", rest)
    if not ret_m:
        return None
    ret_type = ret_m.group(1).strip()
    named_ret = re.fullmatch(r"\(\s*res\s*:\s*(.+)\)", ret_type)
    if named_ret:
        ret_type = named_ret.group(1).strip()
    brace_pos = rest.find("{", ret_m.end())
    if brace_pos == -1:
        return None
    body_wrap = _extract_balanced_braces(rest, brace_pos)
    if body_wrap is None:
        return None
    return {"params": params, "ret_type": ret_type, "body": body_wrap[0].strip()}


def _spec_expr_to_exec(expr: str) -> str:
    """Rewrite spec accessors in a predicate/key/term for exec pin getters."""
    out = expr.strip()
    out = re.sub(
        r"(\w+)\.(\w+)\[(\w+) as int\]@\s*==\s*(\w+)\.(\w+)\[(\w+) as int\]@",
        r"\1.get_\2_exec(\3 as usize) == \4.get_\5_exec(\6 as usize)",
        out,
    )
    out = re.sub(
        r'(\w+)\.(\w+)\[(\w+) as int\]@\s*==\s*"([^"]*)"@',
        r'\1.eq_at_\2(\3 as usize, "\4")',
        out,
    )
    out = re.sub(
        r'(\w+)\.get_(\w+)\((\w+)\)\s*==\s*"([^"]*)"@',
        r'\1.eq_at_\2(\3 as usize, "\4")',
        out,
    )
    out = re.sub(
        r"(\w+)\.(\w+)\[(\w+) as int\]\s*==\s*(\d+)",
        r"\1.get_\2_exec(\3 as usize) == \4",
        out,
    )
    out = re.sub(r"\s*&&\s*true\b", "", out)
    out = re.sub(
        r"(\w+)\.(\w+)\[(\w+) as int\]@",
        r"\1.get_\2_exec(\3 as usize)",
        out,
    )
    out = re.sub(
        r"\((\w+)\.(\w+)\[(\w+) as int\]\)",
        r"\1.get_\2_exec(\3 as usize)",
        out,
    )

    def _field_access(m: re.Match[str]) -> str:
        if m.group(2) == "n":
            return m.group(0)
        return f"{m.group(1)}.get_{m.group(2)}_exec({m.group(3)} as usize)"

    out = re.sub(r"(\w+)\.(\w+)\[(\w+) as int\]", _field_access, out)
    out = re.sub(
        r"(\w+)\.get_(\w+)\((\w+)\)",
        r"\1.get_\2_exec(\3 as usize)",
        out,
    )
    return out


def _bind_loop_index(expr: str, idx: str, loop_var: str) -> str:
    out = expr.replace(f"{idx} as usize", loop_var)
    return re.sub(rf"\b{re.escape(idx)}\b", loop_var, out)


def _spec_term_to_exec(term: str) -> str:
    term = term.strip()
    if term in ("1", "1 as int"):
        return "1u64"
    term = _spec_expr_to_exec(term)
    term = re.sub(r" as int\)", ")", term)
    term = re.sub(r" as int", "", term)
    if term.isdigit():
        return f"{term}u64"
    if not term.endswith("u64"):
        return f"({term} as u64)"
    return term


def _exec_hashmap_type_from_map_ret(ret_type: str) -> str | None:
    m = re.fullmatch(r"Map<(.+),\s*(.+?)>", ret_type.strip())
    if not m:
        return None
    key_ty, val_ty = m.group(1).strip(), m.group(2).strip()
    exec_key = "String" if key_ty == "Seq<char>" else key_ty
    return f"std::collections::HashMap<{exec_key}, {val_ty}>"


def _lower_map_helper_to_exec(helper_name: str, spec_rs: str) -> str | None:
    """Lower grouped map spec helper (single-table scan) to exec HashMap loop."""
    info = _extract_open_spec_fn(spec_rs, helper_name)
    if info is None:
        return None
    params: list[tuple[str, str]] = info["params"]  # type: ignore[assignment]
    body: str = info["body"]  # type: ignore[assignment]
    ret_type: str = info["ret_type"]  # type: ignore[assignment]
    hm_ty = _exec_hashmap_type_from_map_ret(ret_type)
    if hm_ty is None or len(params) != 2:
        return None
    table_param, idx_param = params[0][0], params[1][0]
    if idx_param != "k" and not re.fullmatch(r"i\d+", idx_param):
        return None
    idx = idx_param
    loop_var = f"{idx}_loop"
    m = re.search(
        rf"if\s+{re.escape(idx)}\s+<\s+{re.escape(table_param)}\.n\s+\{{"
        rf"\s*let tail = {re.escape(helper_name)}\([^)]+\);\s*"
        rf"if\s+(.+?)\s+\{{\s*"
        rf"let key = ([^;]+);\s*"
        rf"let prev = if tail\.contains_key\(key\) \{{ tail\[key\] \}} else \{{ ([^}}]+) \}};\s*"
        rf"tail\.insert\(key, \(prev as int \+ ([^)]+)\) as \w+\)",
        body,
        re.DOTALL,
    )
    if m is None:
        return None
    where_exec = _bind_loop_index(_spec_expr_to_exec(m.group(1)), idx, loop_var)
    key_exec = _bind_loop_index(_spec_expr_to_exec(m.group(2)), idx, loop_var)
    term_exec = _spec_term_to_exec(_table_param_ref(m.group(4), table_param))
    zero = m.group(3).strip()
    return f"""let mut groups: {hm_ty} = {hm_ty}::new();
    let mut {loop_var} = 0usize;
    while {loop_var} < {table_param}.n {{
        if {where_exec} {{
            let key = {key_exec};
            let prev = groups.get(&key).copied().unwrap_or({zero});
            groups.insert(key, prev + {term_exec});
        }}
        {loop_var} += 1;
    }}
    groups"""


def _lower_join_map_helper_to_exec(helper_name: str, spec_rs: str) -> str | None:
    """Lower join nested-loop grouped map spec helper to exec double loop."""
    info = _extract_open_spec_fn(spec_rs, helper_name)
    if info is None:
        return None
    params: list[tuple[str, str]] = info["params"]  # type: ignore[assignment]
    body: str = info["body"]  # type: ignore[assignment]
    ret_type: str = info["ret_type"]  # type: ignore[assignment]
    hm_ty = _exec_hashmap_type_from_map_ret(ret_type)
    if hm_ty is None or len(params) != 4:
        return None
    p0, i0, p1, i1 = params[0][0], params[1][0], params[2][0], params[3][0]
    where_m = re.search(
        rf"let tail = {re.escape(helper_name)}\([^)]+\);\s*if\s+(.+?)\s+\{{",
        body,
        re.DOTALL,
    )
    key_m = re.search(r"let key = ([^;]+);", body)
    zero_m = re.search(
        r"let val = if tail\.contains_key\(key\) \{ tail\[key\] \} else \{ ([^}]+) \};",
        body,
    )
    term_m = re.search(r"tail\.insert\(key, \(val as int \+ (.+\)) as u64\)", body, re.DOTALL)
    if where_m is None or key_m is None or zero_m is None or term_m is None:
        return None
    i0_loop, i1_loop = f"{i0}_loop", f"{i1}_loop"
    where_exec = _bind_loop_index(
        _bind_loop_index(_spec_expr_to_exec(where_m.group(1)), i0, i0_loop),
        i1,
        i1_loop,
    )
    key_exec = _bind_loop_index(
        _bind_loop_index(_spec_expr_to_exec(key_m.group(1)), i0, i0_loop),
        i1,
        i1_loop,
    )
    term_exec = _spec_term_to_exec(
        _bind_loop_index(
            _bind_loop_index(term_m.group(1), i0, i0_loop),
            i1,
            i1_loop,
        )
    )
    zero = zero_m.group(1).strip()
    return f"""let mut groups: {hm_ty} = {hm_ty}::new();
    let mut {i0_loop} = 0usize;
    while {i0_loop} < {p0}.n {{
        let mut {i1_loop} = 0usize;
        while {i1_loop} < {p1}.n {{
            if {where_exec} {{
                let key = {key_exec};
                let prev = groups.get(&key).copied().unwrap_or({zero});
                groups.insert(key, prev + {term_exec});
            }}
            {i1_loop} += 1;
        }}
        {i0_loop} += 1;
    }}
    groups"""


def _table_param_ref(expr: str, table_param: str) -> str:
    return expr.replace("cols.", f"{table_param}.")


def _lower_recursive_u64_helper_to_exec(helper_name: str, spec_rs: str) -> str | None:
    """Lower single-table recursive sum/count spec helper to exec scan loop."""
    info = _extract_open_spec_fn(spec_rs, helper_name)
    if info is None:
        return None
    params: list[tuple[str, str]] = info["params"]  # type: ignore[assignment]
    body: str = info["body"]  # type: ignore[assignment]
    if len(params) != 2:
        return None
    table_param, idx_param = params[0][0], params[1][0]
    idx = idx_param
    loop_var = f"{idx}_loop"
    where_m = re.search(
        rf"let tail = {re.escape(helper_name)}\([^)]+\);\s*if\s+(.+?)\s+\{{",
        body,
        re.DOTALL,
    )
    term_m = re.search(r"\(tail as int \+ (.+)\) as u64", body, re.DOTALL)
    if where_m and term_m:
        where_exec = _bind_loop_index(
            _spec_expr_to_exec(_table_param_ref(where_m.group(1), table_param)),
            idx,
            loop_var,
        )
        term_exec = _spec_term_to_exec(
            _bind_loop_index(
                _table_param_ref(term_m.group(1), table_param),
                idx,
                loop_var,
            ),
        )
        return f"""let mut acc = 0u64;
    let mut {loop_var} = 0usize;
    while {loop_var} < {table_param}.n {{
        if {where_exec} {{
            acc = acc + {term_exec};
        }}
        {loop_var} += 1;
    }}
    acc"""
    term_m2 = re.search(
        rf"\({re.escape(helper_name)}\([^)]+\) as int \+ (.+\)) as u64",
        body,
        re.DOTALL,
    )
    if term_m2:
        term_exec = _spec_term_to_exec(
            _bind_loop_index(
                _table_param_ref(term_m2.group(1), table_param),
                idx,
                loop_var,
            )
        )
        return f"""let mut acc = 0u64;
    let mut {loop_var} = 0usize;
    while {loop_var} < {table_param}.n {{
        acc = acc + {term_exec};
        {loop_var} += 1;
    }}
    acc"""
    return None


def _avg_over_map_exec(map_expr: str) -> str:
    return f"""{{
    let m = {map_expr};
    let s: u64 = m.values().sum();
    let c = m.len() as u64;
    if c == 0 {{ 0u64 }} else {{ s / c }}
}}"""


def _lower_subquery_having_spec_body(fn_name: str, spec_rs: str) -> str | None:
    """Return exec Rust expression computing the scalar threshold (no spec calls)."""
    info = _extract_open_spec_fn(spec_rs, fn_name)
    if info is None:
        return None
    body: str = info["body"]  # type: ignore[assignment]

    m_map = re.search(
        r"let m = (\w+)\(([^)]*)\);\s*"
        r"let s = m\.values\(\)\.fold\(0u64, \|acc, v\| \(acc as int \+ v as int\) as u64\);\s*"
        r"let c = m\.len\(\) as u64;\s*"
        r"if c == 0 \{ 0 \} else \{ s / c \}",
        body,
        re.DOTALL,
    )
    if m_map:
        map_spec_fn = m_map.group(1)
        helper_name = map_spec_fn.replace("_spec", "_helper")
        map_exec = _lower_join_map_helper_to_exec(helper_name, spec_rs)
        if map_exec is None:
            map_exec = _lower_map_helper_to_exec(helper_name, spec_rs)
        if map_exec is None:
            return None
        return _avg_over_map_exec(map_exec)

    m_avg = re.search(
        r"let s = (\w+)\(([^)]*)\);\s*"
        r"let c = (\w+)\(([^)]*)\);\s*"
        r"if c == 0 \{ 0 \} else \{ s / c \}",
        body,
        re.DOTALL,
    )
    if m_avg:
        sum_fn, count_fn = m_avg.group(1), m_avg.group(3)
        sum_exec = _lower_recursive_u64_helper_to_exec(sum_fn, spec_rs)
        count_exec = _lower_recursive_u64_helper_to_exec(count_fn, spec_rs)
        if sum_exec is None or count_exec is None:
            return None
        return f"""{{
    let s = {sum_exec};
    let c = {count_exec};
    if c == 0 {{ 0u64 }} else {{ s / c }}
}}"""

    return None


def _emit_subquery_having_exec_fn(fn_name: str, spec_rs: str) -> str | None:
    """Emit TRUSTED ``subquery_having_*_exec`` matching ``subquery_having_*_spec``."""
    info = _extract_open_spec_fn(spec_rs, fn_name)
    if info is None:
        return None
    params: list[tuple[str, str]] = info["params"]  # type: ignore[assignment]
    exec_body = _lower_subquery_having_spec_body(fn_name, spec_rs)
    if exec_body is None:
        return None
    exec_name = fn_name.replace("_spec", "_exec")
    sig = ",\n    ".join(f"{p}: &{s}" for p, s in params)
    spec_call = ", ".join(p for p, _ in params)
    requires = ",\n        ".join(
        _valid_cols_predicate(struct, param) for param, struct in params
    )
    return f"""
#[verifier::external_body]
pub exec fn {exec_name}(
    {sig},
) -> (r: u64)
    requires
        {requires},
    ensures
        r == {fn_name}({spec_call}),
{{
    {exec_body}
}}
"""


_SUBQUERY_HAVING_SPEC_CALL_RE = re.compile(r"(subquery_having_\w+_spec)\s*\(")


@dataclass(frozen=True)
class HavingSubqueryRewrite:
    filter_expr: str
    exec_fns: tuple[str, ...]
    precompute: tuple[str, ...]


def _rewrite_having_subquery_specs(
    filter_expr: str,
    spec_rs: str,
) -> HavingSubqueryRewrite | str:
    """Replace ``subquery_having_*_spec(...)`` in filter with precomputed thresholds."""
    calls: list[tuple[str, str, str]] = []
    for m in _SUBQUERY_HAVING_SPEC_CALL_RE.finditer(filter_expr):
        fn_name = m.group(1)
        inner = _extract_balanced_parens(filter_expr, m.end() - 1)
        if inner is None:
            return f"cannot parse {fn_name} call in HAVING filter"
        args = inner[0].strip()
        call_text = f"{fn_name}({args})"
        if call_text not in {c[0] for c in calls}:
            calls.append((call_text, fn_name, args))

    if not calls:
        return HavingSubqueryRewrite(filter_expr, (), ())

    exec_fns: list[str] = []
    precompute: list[str] = []
    new_filter = filter_expr
    for i, (call_text, fn_name, args) in enumerate(calls):
        exec_fn = _emit_subquery_having_exec_fn(fn_name, spec_rs)
        if exec_fn is None:
            return f"cannot lower {fn_name} to exec HAVING threshold"
        exec_fns.append(exec_fn)
        exec_name = fn_name.replace("_spec", "_exec")
        thresh = "having_thresh" if len(calls) == 1 else f"having_thresh_{i}"
        precompute.append(f"let {thresh} = {exec_name}({args});")
        new_filter = new_filter.replace(call_text, thresh)

    return HavingSubqueryRewrite(filter_expr=new_filter, exec_fns=tuple(exec_fns), precompute=tuple(precompute))


def emit_having_filter_trusted(
    layout: HavingFilterLayout,
    bridge: RetBridge,
    table_params: list[tuple[str, str]] | None = None,
    *,
    spec_rs: str | None = None,
) -> str:
    """Emit TRUSTED ``apply_having_filter_exec_{suffix}`` for one query."""
    suffix = bridge.agg_suffix or bridge.key.removeprefix("map_")
    fn = f"apply_having_filter_exec_{suffix}"
    pred = layout.full_closure
    filter_expr = _exec_filter_body(layout)
    subquery_exec_fns: tuple[str, ...] = ()
    thresh_precompute: tuple[str, ...] = ()
    if spec_rs and _SUBQUERY_HAVING_SPEC_CALL_RE.search(filter_expr):
        rewrite = _rewrite_having_subquery_specs(filter_expr, spec_rs)
        if isinstance(rewrite, str):
            raise ValueError(rewrite)
        filter_expr = rewrite.filter_expr
        subquery_exec_fns = rewrite.exec_fns
        thresh_precompute = rewrite.precompute

    exec_inner = _having_filter_exec_body(bridge.rust_ret, filter_expr)
    if thresh_precompute:
        pre = "\n    ".join(thresh_precompute)
        exec_body = f"""{pre}
    {exec_inner}"""
    else:
        exec_body = exec_inner
    table_params = table_params or []
    sig_parts = [f"hm: {bridge.rust_ret}"]
    sig_parts.extend(f"{p}: &{s}" for p, s in table_params)
    sig = ",\n    ".join(sig_parts)
    requires = ""
    if table_params:
        preds = ",\n        ".join(
            _valid_cols_predicate(struct, param) for param, struct in table_params
        )
        requires = f"\n    requires\n        {preds},"
    subquery_block = "".join(subquery_exec_fns)
    return f"""{subquery_block}
// === HAVING post-filter ({suffix}): exec map retain vs apply_having_filter ===
#[verifier::external_body]
pub exec fn {fn}(
    {sig},
) -> (res: {bridge.rust_ret}){requires}
    ensures
        res@
            == apply_having_filter(
                hm@,
                {pred},
            ),
{{
    {exec_body}
}}
"""


def _bridge_for_having(ret_type: str) -> RetBridge | None:
    bridge = get_bridge(ret_type)
    if bridge is not None and bridge.rust_ret.startswith(
        ("HashMapWithView", "StringHashMap", "HashMap")
    ):
        return bridge
    from research_loop.assemble_verified_program import _cfg

    cfg = _cfg(ret_type)
    rust_ret = cfg["rust_ret"]
    if not rust_ret.startswith(("HashMapWithView", "StringHashMap", "HashMap")):
        return None
    view = cfg.get("view_spec")
    ensures = "res@ == method_spec(cols),"
    if view:
        ensures = f"{view}(res@) == method_spec(cols),"
    return RetBridge(
        key=ret_type,
        rust_ret=rust_ret,
        ensures=ensures,
        trusted_rs="",
        default_stub="HashMapWithView::new()",
        format_result="",
        needs_hashmap=True,
        view_spec=view,
        spec_map=cfg.get("spec_map"),
        hm_map=cfg.get("hm_map"),
        agg_suffix=cfg.get("agg_suffix"),
    )


def having_filter_trusted_rs(spec_rs: str, ret_type: str) -> str:
    """Return TRUSTED HAVING exec helper for this spec/ret_type, or empty string."""
    layout = parse_having_filter_layout(spec_rs)
    if layout is None:
        return ""
    bridge = _bridge_for_having(ret_type)
    if bridge is None:
        return ""
    try:
        from research_loop.method_spec_ret_type import parse_method_spec_params

        method_params = parse_method_spec_params(spec_rs)
    except ValueError:
        return _having_skip_comment("cannot parse method_spec parameters for HAVING exec")
    skip = unsupported_having_predicate_reason(layout, spec_rs, method_params)
    if skip:
        return _having_skip_comment(skip)
    table_params = table_params_for_having(
        layout.closure_body,
        layout.closure_params,
        spec_rs,
        method_params,
    )
    try:
        body = emit_having_filter_trusted(
            layout, bridge, table_params, spec_rs=spec_rs,
        )
    except (ValueError, KeyError, AttributeError):
        return ""
    if _needs_having_map_peel(bridge.rust_ret):
        structs = emit_having_map_peel_structs(bridge.rust_ret).rstrip()
        return f"{structs}\n\n{body.lstrip()}"
    return body
