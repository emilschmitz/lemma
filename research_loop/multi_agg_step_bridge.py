"""Host TRUSTED multi-agg group step helpers (exec inner state + projected map)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from research_loop.trusted_ret_bridge import (
    RetBridge,
    TypeAtom,
    TypeExpr,
    TypeMap,
    TypeTuple,
    _exec_key_expr,
    _key_param_specs,
    _spec_key_expr,
    parse_verus_type,
    spec_to_exec_type,
)

_HELPER_NAMES = (
    "method_spec_helper",
    "multi_agg_helper",
    "join_anti_multi_agg_helper",
    "join_multi_agg_helper",
)

_HELPER_FN_RE = re.compile(
    r"pub open spec fn (\w*(?:multi_agg_helper|method_spec_helper))\(",
)

_COL_REF_RE = re.compile(
    r"cols\.(?:get_)?(\w+)\((?:k|\w+)\)(?:@)?"
    r"|cols\.(\w+)\[(?:k|\w+) as int\](?:@)?"
    r"|\w+\.\w+\[(?:\w+) as int\](?:@)?"
)

_UPDATE_LET_RE = re.compile(
    r"let\s+((?:s|t)\d+)\s*=\s*(.+?);",
    re.DOTALL,
)

_NUMERIC_CAST_RE = re.compile(
    r"\(\(\(cols\.(?:get_)?(\w+)\((?:k|\w+)\)(?:@)? as int\)\) as u64 as int\)"
)


@dataclass(frozen=True)
class RowParam:
    name: str
    rust_ty: str
    spec_ty: str


@dataclass
class MultiAggLayout:
    helper_name: str
    key_type: TypeExpr
    state_type: TypeExpr
    default_state: str
    rebuild_state: str
    project_body: str
    project_bind_ty: str
    apply_body: str
    row_params: list[RowParam] = field(default_factory=list)


def _type_to_str(t: TypeExpr) -> str:
    if isinstance(t, TypeAtom):
        return t.name
    if isinstance(t, TypeTuple):
        return f"({', '.join(_type_to_str(e) for e in t.elems)})"
    if isinstance(t, TypeMap):
        return f"Map<{_type_to_str(t.key)}, {_type_to_str(t.value)}>"
    raise ValueError(f"unsupported type: {t!r}")


def _extract_balanced_fn_body(spec_rs: str, start: int) -> tuple[str, int]:
    depth = 0
    i = start
    n = len(spec_rs)
    body_start = start
    while i < n:
        ch = spec_rs[i]
        if ch == "{":
            depth += 1
            if depth == 1:
                body_start = i + 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return spec_rs[body_start:i], i + 1
        i += 1
    raise ValueError("unbalanced braces in helper body")


def _split_map_type_args(inner: str) -> tuple[str, str]:
    """Split ``K, V`` inside ``Map<K, V>`` at the top-level comma."""
    depth = 0
    for i, ch in enumerate(inner):
        if ch in "<(":
            depth += 1
        elif ch in ">)":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            return inner[:i].strip(), inner[i + 1 :].strip()
    raise ValueError(f"could not split Map type args: {inner!r}")


def _find_helper(spec_rs: str) -> tuple[str, str, str, str] | None:
    """Locate the multi-agg fold helper (single-table, join, or anti-join)."""
    candidates: list[str] = []
    for name in _HELPER_NAMES:
        if f"pub open spec fn {name}(" in spec_rs:
            candidates.append(name)
    for m in _HELPER_FN_RE.finditer(spec_rs):
        name = m.group(1)
        if name not in candidates:
            candidates.append(name)
    # Prefer the longest/most specific name (anti-join before generic).
    candidates.sort(key=len, reverse=True)

    for name in candidates:
        marker = f"pub open spec fn {name}("
        pos = spec_rs.find(marker)
        if pos == -1:
            continue
        head = spec_rs[pos:]
        ret_m = re.search(
            rf"pub open spec fn {re.escape(name)}\([^)]+\)\s*->\s*(?:\(res:\s*)?Map<",
            head,
        )
        if not ret_m:
            continue
        start = ret_m.end()
        depth = 1
        i = start
        while i < len(head) and depth > 0:
            if head[i] == "<":
                depth += 1
            elif head[i] == ">":
                depth -= 1
            i += 1
        if depth != 0:
            continue
        inner = head[start : i - 1]
        key_ty_s, val_ty_s = _split_map_type_args(inner)
        brace = head.find("{", i)
        body, _ = _extract_balanced_fn_body(head, brace)
        return name, key_ty_s, val_ty_s, body
    return None


def _extract_method_spec_projection(spec_rs: str) -> tuple[str, str] | None:
    m = re.search(r"raw\.map_values\(\|v:\s*([^|]+)\|\s*", spec_rs)
    if not m:
        return None
    bind_ty = m.group(1).strip()
    start = m.end()
    depth = 0
    i = start
    while i < len(spec_rs):
        ch = spec_rs[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                return None
            depth -= 1
            if depth == 0:
                body = spec_rs[start : i + 1].strip()
                return bind_ty, body
        i += 1
    return None


def _parse_default_state(body: str) -> str:
    m = re.search(
        r"let prev = if tail\.contains_key\(key\) \{ tail\[key\] \} else \{ ([^}]+) \};",
        body,
    )
    if not m:
        raise ValueError("could not parse multi-agg default state")
    return m.group(1).strip()


def _parse_update_block(body: str) -> tuple[list[str], str]:
    m = re.search(
        r"let prev = if tail\.contains_key\(key\) \{ tail\[key\] \} else \{ [^}]+\};\s*"
        r"(.*?)\s*tail\.insert\(key,\s*",
        body,
        re.DOTALL,
    )
    if not m:
        raise ValueError("could not parse multi-agg update block")
    updates_raw = m.group(1).strip()
    start = m.end()
    depth = 0
    i = start
    while i < len(body):
        ch = body[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                rebuild = body[start:i].strip()
                updates: list[str] = []
                for um in _UPDATE_LET_RE.finditer(updates_raw):
                    updates.append(f"let {um.group(1)} = {um.group(2).strip()};")
                if not updates:
                    raise ValueError("no let sN/tN = updates in multi-agg helper")
                return updates, rebuild
            depth -= 1
        i += 1
    raise ValueError("could not parse multi-agg rebuild tuple")


def _state_slots(state_type: TypeExpr) -> list[TypeExpr]:
    if isinstance(state_type, TypeTuple):
        return list(state_type.elems)
    return [state_type]


def _distinct_atom_from_map_type(ty: str) -> str | None:
    ty = ty.strip()
    if ty == "Map<Seq<char>, bool>":
        return "str"
    if ty == "Map<u32, bool>":
        return "u32"
    return None



def _col_ref_usage(line: str, expr: str) -> str:
    if ".contains_key" in line or ".insert" in line:
        return "distinct"
    return "numeric"


def _is_str_distinct_expr(expr: str) -> bool:
    return expr.rstrip().endswith("@")


_MINMAX_S_LINE_RE = re.compile(
    r"let s(\d+) = if t\1 [<>] prev(?:\.\d+)?",
)


def _minmax_t_indices(update_lines: list[str]) -> set[int]:
    """Slot indices whose ``tN`` bind MIN/MAX row values (u64, not int)."""
    indices: set[int] = set()
    for line in update_lines:
        m = _MINMAX_S_LINE_RE.search(line)
        if m:
            indices.add(int(m.group(1)))
    return indices


def _rewrite_updates_for_apply(
    update_lines: list[str],
) -> tuple[list[str], list[RowParam]]:
    params: list[RowParam] = []
    seen_cols: dict[str, str] = {}
    minmax_slots = _minmax_t_indices(update_lines)

    def col_param(expr: str, usage: str) -> str:
        if expr in seen_cols:
            return seen_cols[expr]
        if usage == "distinct":
            n = len([p for p in params if p.name.startswith("distinct_")])
            pname = f"distinct_{n}"
            if _is_str_distinct_expr(expr):
                params.append(RowParam(pname, "&str", "Seq<char>"))
            else:
                params.append(RowParam(pname, "u32", "u32"))
        else:
            n = len([p for p in params if p.name.startswith("row_u64_")])
            pname = f"row_u64_{n}"
            params.append(RowParam(pname, "u64", "u64"))
        seen_cols[expr] = params[-1].name
        return params[-1].name

    def spec_ref_for(pname: str, usage: str, *, minmax: bool) -> str:
        if usage == "distinct":
            return pname
        if minmax:
            return pname
        return f"({pname} as int)"

    rewritten: list[str] = []
    for line in update_lines:
        t_slot_m = re.match(r"\s*let t(\d+) =", line)
        minmax = bool(t_slot_m and int(t_slot_m.group(1)) in minmax_slots)
        out = line
        out = _NUMERIC_CAST_RE.sub(
            lambda m, minmax=minmax: (
                col_param(m.group(0), "numeric")
                if minmax
                else f"({col_param(m.group(0), 'numeric')} as int)"
            ),
            out,
        )
        for m in _COL_REF_RE.finditer(line):
            expr = m.group(0)
            if expr not in out:
                continue
            usage = _col_ref_usage(line, expr)
            pname = col_param(expr, usage)
            out = out.replace(expr, spec_ref_for(pname, usage, minmax=minmax))
        rewritten.append(out)
    return rewritten, params


def _inner_exec_type(state_type: TypeExpr, *, ghost: bool = False) -> str:
    if isinstance(state_type, TypeAtom):
        return spec_to_exec_type(state_type)
    if isinstance(state_type, TypeTuple):
        parts = [_inner_exec_slot_type(e, ghost=ghost) for e in state_type.elems]
        if len(parts) == 1:
            return parts[0]
        return f"({', '.join(parts)})"
    raise ValueError(f"unsupported state type: {state_type!r}")


def _inner_exec_slot_type(slot: TypeExpr, *, ghost: bool = False) -> str:
    if isinstance(slot, TypeAtom):
        return spec_to_exec_type(slot)
    if isinstance(slot, TypeMap):
        key = slot.key
        if isinstance(key, TypeAtom) and key.name == "Seq<char>":
            return "std::collections::HashSet<String>"
        if isinstance(key, TypeAtom) and key.name == "u32":
            return "std::collections::HashSet<u32>"
    raise ValueError(f"unsupported inner slot: {slot!r}")


def _default_inner_exec(default_state: str, slots: list[TypeExpr]) -> str:
    if len(slots) == 1:
        slot = slots[0]
        if isinstance(slot, TypeMap):
            return "std::collections::HashSet::new()"
        return default_state
    parts: list[str] = []
    frag = default_state.strip()
    inner_parts = (
        [p.strip() for p in frag[1:-1].split(",")]
        if frag.startswith("(") and frag.endswith(")")
        else [default_state]
    )
    for i, slot in enumerate(slots):
        if isinstance(slot, TypeMap):
            parts.append("std::collections::HashSet::new()")
        else:
            parts.append(inner_parts[i] if i < len(inner_parts) else "0u64")
    return f"({', '.join(parts)})"


def _spec_param_list(params: list[RowParam]) -> str:
    if not params:
        return ""
    return ", " + ", ".join(f"{p.name}: {p.spec_ty}" for p in params)


def _exec_param_sig(params: list[RowParam]) -> str:
    if not params:
        return ""
    return ", " + ", ".join(f"{p.name}: {p.rust_ty}" for p in params)


def _projected_exec_expr(project_body: str, var: str, slots: list[TypeExpr]) -> str:
    out = project_body
    for i, slot in enumerate(slots):
        if isinstance(slot, TypeMap):
            out = out.replace(f"v.{i}.dom().len() as u64", f"{var}.{i}.len() as u64")
            out = out.replace(f"v.{i}.dom().len()", f"{var}.{i}.len() as u64")
    out = out.replace("v.", f"{var}.")
    if out.startswith("(") and out.endswith(")") and out.count("(") == 1:
        return out[1:-1]
    return out


def _minmax_src_from_t_line(t_line: str) -> str | None:
    m = re.search(r"let t\d+ = (.+);", t_line)
    if not m:
        return None
    expr = m.group(1).strip()
    m2 = re.search(r"(row_u64_\d+)", expr)
    if m2:
        return m2.group(1)
    return None


def _sum_delta_expr(s_line: str, slot_i: int, *, multi_slot: bool) -> str | None:
    prev_ref = f"prev.{slot_i}" if multi_slot else "prev"
    m = re.search(
        rf"let s{slot_i} = \({prev_ref} as int \+ (.+?)\) as u64",
        s_line,
    )
    return m.group(1).strip() if m else None


_ROW_U64_BARE_RE = re.compile(
    r"^\s*(?:\(\s*)*(?P<name>row_u64_\d+)(?:\s*\))*\s*$"
)

_ROW_U64_GHOST_INT_RE = re.compile(r"\(row_u64_(\d+) as int\)|row_u64_(\d+) as int")
_TRAILING_GHOST_INT_RE = re.compile(r"^(?P<inner>.+?) as int$")


def _strip_row_u64_ghost_int(expr: str) -> str:
    """Remove spec ``row_u64_N as int`` casts; leave bare u64 param names."""
    while True:
        prev = expr
        expr = _ROW_U64_GHOST_INT_RE.sub(
            lambda m: f"row_u64_{m.group(1) or m.group(2)}", expr
        )
        if expr == prev:
            return expr


def _spec_expr_to_exec(expr: str) -> str:
    """Convert a spec ghost-int addend into an exec u64 addend for wrapping_add."""
    out = _strip_row_u64_ghost_int(expr.strip())
    out = out.replace("case_when_u64(", "case_when_u64_exec(")
    while True:
        bare = _ROW_U64_BARE_RE.match(out)
        if bare:
            return bare.group("name")
        trailing = _TRAILING_GHOST_INT_RE.match(out)
        if trailing:
            out = trailing.group("inner").strip()
            continue
        return out


def _exec_update_inner(
    layout: MultiAggLayout,
    slots: list[TypeExpr],
    prev_var: str,
    params: list[RowParam],
) -> list[str]:
    """Emit exec statements that mirror spec apply_row on inner exec tuple."""
    lines: list[str] = []
    distinct_params = [p for p in params if p.name.startswith("distinct_")]
    numeric_params = [p for p in params if p.name.startswith("row_u64_")]
    distinct_i = 0
    numeric_i = 0

    if len(slots) == 1:
        slot = slots[0]
        if isinstance(slot, TypeMap):
            atom = _distinct_atom_from_map_type(
                f"Map<{_type_to_str(slot.key)}, {_type_to_str(slot.value)}>"
            )
            dp = distinct_params[distinct_i]
            lines.append(f"let mut new_inner = {prev_var}.clone();")
            if atom == "str":
                lines.append(f"set_insert_{atom}(&mut new_inner, {dp.name});")
            else:
                lines.append(f"set_insert_{atom}(&mut new_inner, {dp.name});")
            return lines

    apply_lines = [ln.strip() for ln in layout.apply_body.split("\n") if ln.strip()]

    slot_vals: list[str] = []
    for i, slot in enumerate(slots):
        if isinstance(slot, TypeMap):
            atom = _distinct_atom_from_map_type(
                f"Map<{_type_to_str(slot.key)}, {_type_to_str(slot.value)}>"
            )
            dp = distinct_params[distinct_i]
            distinct_i += 1
            lines.append(f"let mut v{i} = {prev_var}.{i}.clone();")
            if atom == "str":
                lines.append(f"set_insert_{atom}(&mut v{i}, {dp.name});")
            else:
                lines.append(f"set_insert_{atom}(&mut v{i}, {dp.name});")
            slot_vals.append(f"v{i}")
        elif isinstance(slot, TypeAtom) and slot.name == "u64":
            s_line = next(
                (ln for ln in apply_lines if ln.startswith(f"let s{i} =")),
                "",
            )
            t_line = next(
                (ln for ln in apply_lines if ln.startswith(f"let t{i} =")),
                "",
            )
            is_min = re.search(rf"let s{i} = if t{i} <", s_line) is not None
            is_max = re.search(rf"let s{i} = if t{i} >", s_line) is not None
            if is_min or is_max:
                src = _minmax_src_from_t_line(t_line)
                if src is None:
                    if numeric_i >= len(numeric_params):
                        raise ValueError(
                            f"missing numeric param for {'MIN' if is_min else 'MAX'} slot {i}"
                        )
                    src = numeric_params[numeric_i].name
                    numeric_i += 1
                op = "<" if is_min else ">"
                lines.append(
                    f"let v{i} = if {src} {op} {prev_var}.{i} "
                    f"{{ {src} }} else {{ {prev_var}.{i} }};"
                )
            elif "as int + 1) as u64" in s_line:
                lines.append(f"let v{i} = {prev_var}.{i}.wrapping_add(1);")
            else:
                delta = _sum_delta_expr(s_line, i, multi_slot=len(slots) > 1)
                if delta is not None:
                    lines.append(
                        f"let v{i} = {prev_var}.{i}.wrapping_add({_spec_expr_to_exec(delta)});"
                    )
                elif numeric_i < len(numeric_params):
                    np = numeric_params[numeric_i]
                    numeric_i += 1
                    lines.append(f"let v{i} = {prev_var}.{i}.wrapping_add({np.name});")
                else:
                    lines.append(f"let v{i} = {prev_var}.{i}.wrapping_add(1);")
            slot_vals.append(f"v{i}")

    lines.append(f"let new_inner = ({', '.join(slot_vals)});")
    return lines


def parse_multi_agg_layout(spec_rs: str) -> MultiAggLayout | None:
    """Parse multi-agg fold + projection from transpiled MethodSpec, or None."""
    found = _find_helper(spec_rs)
    if not found:
        return None
    _name, key_ty_s, val_ty_s, body = found
    projection = _extract_method_spec_projection(spec_rs)
    if not projection:
        return None
    bind_ty, project_body = projection
    try:
        key_type = parse_verus_type(key_ty_s)
        state_type = parse_verus_type(val_ty_s)
        default_state = _parse_default_state(body)
        update_lines, rebuild_state = _parse_update_block(body)
        rewritten, row_params = _rewrite_updates_for_apply(update_lines)
        apply_body = "\n    ".join(rewritten) + f"\n    {rebuild_state}"
    except (ValueError, IndexError):
        return None

    return MultiAggLayout(
        helper_name=_name,
        key_type=key_type,
        state_type=state_type,
        default_state=default_state,
        rebuild_state=rebuild_state,
        project_body=project_body,
        project_bind_ty=bind_ty,
        apply_body=apply_body,
        row_params=row_params,
    )


def emit_multi_agg_step_trusted(layout: MultiAggLayout, bridge: RetBridge) -> str:
    """Emit open-spec apply/project + TRUSTED agg_step state/step for one multi-agg query."""
    suffix = bridge.agg_suffix or bridge.key.removeprefix("map_")
    view_proj = bridge.view_spec
    if not view_proj:
        raise ValueError("multi-agg step requires projected map view")

    state_type = layout.state_type
    inner_spec = _type_to_str(state_type)
    inner_exec = _inner_exec_type(state_type, ghost=False)
    key_hm = spec_to_exec_type(layout.key_type)
    key_spec = _type_to_str(layout.key_type)
    spec_map_inner = f"Map<{key_spec}, {inner_spec}>"
    hm_inner = f"HashMap<{key_hm}, {inner_exec}>"
    inner_hm_ghost = f"Map<{key_hm}, {_inner_exec_type(state_type, ghost=True)}>"
    hm_proj = bridge.rust_ret
    slots = _state_slots(state_type)
    default_inner_exec = _default_inner_exec(layout.default_state, slots)
    default_inner_spec = layout.default_state

    key_params = _key_param_specs(layout.key_type)
    key_sig = ", ".join(f"{n}: {t}" for n, t, _ in key_params)
    spec_key = _spec_key_expr(layout.key_type)
    exec_key = _exec_key_expr(layout.key_type)

    inner_view = f"agg_step_inner_{suffix}_view"
    project_fn = f"agg_step_project_{suffix}"
    apply_fn = f"agg_step_apply_row_{suffix}"
    state_ty = f"AggStepState_{suffix}"

    spec_params = _spec_param_list(layout.row_params)
    exec_params = _exec_param_sig(layout.row_params)
    ghost_apply = ", ".join(
        f"{p.name}@" if p.rust_ty == "&str" else p.name for p in layout.row_params
    )
    if ghost_apply:
        ghost_apply = ", " + ghost_apply

    parsed_map = parse_verus_type(bridge.spec_map or "")
    if not isinstance(parsed_map, TypeMap):
        raise TypeError("expected Map spec_map for multi-agg step")
    proj_ret = _type_to_str(parsed_map.value)

    exec_update = _exec_update_inner(layout, slots, "prev", layout.row_params)
    exec_update_block = "\n    ".join(exec_update)
    projected_expr = _projected_exec_expr(layout.project_body, "new_inner", slots)

    head = (
        f"""
// === Multi-agg group step ({suffix}): inner HashMap + projected map ===
pub struct {state_ty} {{
    pub projected: {hm_proj},
    pub inner: {hm_inner},
}}

#[verifier::external_body]
pub open spec fn {inner_view}(hm: {inner_hm_ghost}) -> {spec_map_inner} {{
    arbitrary()
}}

pub open spec fn {project_fn}(v: {inner_spec}) -> {proj_ret} {{
    """
        + layout.project_body
        + f"""
}}

pub open spec fn {apply_fn}(prev: {inner_spec}{spec_params}) -> {inner_spec} {{
    """
        + layout.apply_body
        + f"""
}}

#[verifier::external_body]
pub exec fn agg_step_state_new_{suffix}() -> (st: {state_ty})
    ensures
        {view_proj}(st.projected@) == Map::empty(),
        {inner_view}(st.inner@) == Map::empty(),
{{
    {state_ty} {{ projected: HashMap::new(), inner: HashMap::new() }}
}}

#[verifier::external_body]
pub exec fn agg_step_{suffix}(
    st: &mut {state_ty},
    {key_sig}{exec_params},
)
    ensures
        ({{
            let spec_key = {spec_key};
            let old_inner = {inner_view}(old(st).inner@);
            let prev_inner = if old_inner.contains_key(spec_key) {{
                old_inner[spec_key]
            }} else {{
                {default_inner_spec}
            }};
            let new_inner = {apply_fn}(prev_inner{ghost_apply});
            &&& {inner_view}(final(st).inner@) == old_inner.insert(spec_key, new_inner)
            &&& {view_proj}(final(st).projected@) == {view_proj}(old(st).projected@).insert(
                spec_key,
                {project_fn}(new_inner),
            )
        }}),
{{
    let key = {exec_key};
    let prev = st.inner.get(&key).cloned().unwrap_or({default_inner_exec});
    {exec_update_block}
    st.inner.insert(key.clone(), new_inner.clone());
    st.projected.insert(key, ({projected_expr}));
}}
"""
    )
    return head


def multi_agg_step_trusted_rs(spec_rs: str, ret_type: str) -> str:
    """Return TRUSTED agg_step helpers for this spec/ret_type, or empty string."""
    from research_loop.trusted_ret_bridge import get_bridge, multi_agg_ret_type

    if not multi_agg_ret_type(ret_type):
        return ""
    layout = parse_multi_agg_layout(spec_rs)
    if layout is None:
        return ""
    bridge = get_bridge(ret_type)
    if bridge is None:
        return ""
    try:
        return emit_multi_agg_step_trusted(layout, bridge)
    except (ValueError, KeyError, AttributeError, IndexError):
        return ""
