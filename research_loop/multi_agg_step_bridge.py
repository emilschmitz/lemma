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
    map_new_expr,
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


def _slot_spec_from_exec(expr: str, slot: TypeExpr) -> str:
    if isinstance(slot, TypeMap):
        return f"{expr}@"
    return expr


def _tuple_spec_from_exec_var(var: str, state_type: TypeExpr) -> str:
    if isinstance(state_type, TypeAtom):
        return var
    if isinstance(state_type, TypeTuple):
        parts = [_slot_spec_from_exec(f"{var}.{i}", e) for i, e in enumerate(state_type.elems)]
        return f"({', '.join(parts)})"
    raise ValueError(f"unsupported state type for spec view: {state_type!r}")


def _emit_inner_spec_map_fn(
    *,
    suffix: str,
    key_spec: str,
    state_type: TypeExpr,
    inner_exec: str,
    inner_spec: str,
) -> str:
    spec_val = _tuple_spec_from_exec_var("v", state_type)
    return f"""
pub open spec fn agg_step_inner_{suffix}_spec(
    m: Map<{key_spec}, {inner_exec}>,
) -> Map<{key_spec}, {inner_spec}> {{
    m.map_values(|v: {inner_exec}| {spec_val})
}}
"""


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
            return "HashMapWithView<String, bool>"
        if isinstance(key, TypeAtom) and key.name == "u32":
            return "HashMapWithView<u32, bool>"
    raise ValueError(f"unsupported inner slot: {slot!r}")


def _default_inner_exec(default_state: str, slots: list[TypeExpr]) -> str:
    if len(slots) == 1:
        slot = slots[0]
        if isinstance(slot, TypeMap):
            return "HashMapWithView::new()"
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
            parts.append("HashMapWithView::new()")
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
    """Convert a spec ghost-int addend into an exec u64 addend for checked_add."""
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


def _checked_u64_add(prev_expr: str, delta_expr: str) -> str:
    return (
        f"{prev_expr}.checked_add({delta_expr})"
        '.expect("Trusted overflow: ValidCols/requires violated")'
    )


def _prev_slot_ref(n_slots: int, slot_i: int) -> str:
    return "prev" if n_slots == 1 else f"prev.{slot_i}"


_ROW_U64_PARAM_RE = re.compile(r"row_u64_\d+")


def _row_u64_param_in_delta(delta: str) -> str | None:
    m = _ROW_U64_PARAM_RE.search(delta)
    return m.group(0) if m else None


def _emit_agg_step_requires(
    layout: MultiAggLayout,
    slots: list[TypeExpr],
    *,
    spec_key: str,
) -> str:
    """Fit-in-width requires: cell caps + prev-fit from old(st).inner@."""
    apply_lines = [ln.strip() for ln in layout.apply_body.split("\n") if ln.strip()]
    n_slots = len(slots)
    seen_params: set[str] = set()
    clauses: list[str] = []
    for i, slot in enumerate(slots):
        if not isinstance(slot, TypeAtom) or slot.name != "u64":
            continue
        s_line = next((ln for ln in apply_lines if ln.startswith(f"let s{i} =")), "")
        kind = _classify_u64_slot(s_line, i, multi_slot=n_slots > 1)
        if kind is None:
            continue
        if n_slots == 1:
            prev_ref = (
                f"if old(st).inner@.contains_key({spec_key}) "
                f"{{ old(st).inner@[{spec_key}] }} else {{ 0u64 }}"
            )
        else:
            prev_ref = (
                f"(if old(st).inner@.contains_key({spec_key}) "
                f"{{ old(st).inner@[{spec_key}].{i} }} else {{ 0u64 }})"
            )
        if kind == "count":
            clauses.append(_u64_add_bound_requires(prev_ref, "1"))
            continue
        delta = _sum_delta_expr(s_line, i, multi_slot=n_slots > 1)
        if delta is None:
            continue
        row_param = _row_u64_param_in_delta(delta)
        if row_param is not None and row_param not in seen_params:
            seen_params.add(row_param)
            clauses.append(f"{row_param} < LEMMA_MAX_MONEY_U64")
        exec_delta = _spec_expr_to_exec(delta)
        clauses.append(_u64_add_bound_requires(prev_ref, f"({exec_delta} as int)"))
    if not clauses:
        return ""
    joined = " &&\n        ".join(clauses)
    return f"""    requires
        {joined},
"""


def _u64_add_bound_requires(prev_expr: str, delta_expr: str) -> str:
    return f"({prev_expr} as int) + {delta_expr} <= u64::MAX as int"


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
            lines.append(f"let mut new_inner = {prev_var};")
            if atom == "str":
                lines.append(f"new_inner.insert({dp.name}.to_string(), true);")
            else:
                lines.append(f"new_inner.insert({dp.name}, true);")
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
            lines.append(f"let mut v{i} = {prev_var}.{i};")
            if atom == "str":
                lines.append(f"v{i}.insert({dp.name}.to_string(), true);")
            else:
                lines.append(f"v{i}.insert({dp.name}, true);")
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
                lines.append(
                    f"let v{i} = {_checked_u64_add(f'{prev_var}.{i}' if len(slots) > 1 else prev_var, '1')};"
                )
            else:
                delta = _sum_delta_expr(s_line, i, multi_slot=len(slots) > 1)
                if delta is not None:
                    prev_ref = f"{prev_var}.{i}" if len(slots) > 1 else prev_var
                    exec_delta = _spec_expr_to_exec(delta)
                    lines.append(
                        f"let v{i} = {_checked_u64_add(prev_ref, exec_delta)};"
                    )
                elif numeric_i < len(numeric_params):
                    np = numeric_params[numeric_i]
                    numeric_i += 1
                    prev_ref = f"{prev_var}.{i}" if len(slots) > 1 else prev_var
                    lines.append(
                        f"let v{i} = {_checked_u64_add(prev_ref, np.name)};"
                    )
                else:
                    prev_ref = f"{prev_var}.{i}" if len(slots) > 1 else prev_var
                    lines.append(f"let v{i} = {_checked_u64_add(prev_ref, '1')};")
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


def _classify_u64_slot(s_line: str, slot_i: int, *, multi_slot: bool) -> str | None:
    """Return count / sum_native / sum_money for a numeric slot, or None (MIN/MAX / skip)."""
    prev_ref = f"prev.{slot_i}" if multi_slot else "prev"
    if re.search(rf"let s{slot_i} = if t{slot_i} [<>] {re.escape(prev_ref)}", s_line):
        return None
    if "as int + 1) as u64" in s_line:
        return "count"
    delta = _sum_delta_expr(s_line, slot_i, multi_slot=multi_slot)
    if delta is None:
        return None
    if "case_when_u64" in delta:
        return "count"
    if re.fullmatch(r"row_u64_\d+", delta.strip()):
        return "sum_money"
    if "as int)" in delta or " as int" in delta:
        return "sum_native"
    return "sum_money"


def _parse_helper_params(spec_rs: str, helper_name: str) -> str | None:
    m = re.search(
        rf"pub open spec fn {re.escape(helper_name)}\(([^)]*)\)",
        spec_rs,
    )
    return m.group(1).strip() if m else None


@dataclass(frozen=True)
class FoldBoundContext:
    helper: str
    table_params: tuple[tuple[str, str], ...]
    index_params: tuple[str, ...]

    @property
    def call_args(self) -> str:
        parts = [p for p, _ in self.table_params]
        parts.extend(self.index_params)
        return ", ".join(parts)

    @property
    def valid_requires(self) -> str:
        clauses: list[str] = []
        for param, struct in self.table_params:
            if struct == "Cols":
                clauses.append(f"valid_cols({param})")
            else:
                suffix = struct.removeprefix("Cols_")
                clauses.append(f"valid_cols_{suffix}({param})")
        return ",\n        ".join(clauses)

    def index_bounds_requires(self) -> str:
        clauses: list[str] = []
        for param, struct in self.table_params:
            n = f"{param}.n as int"
            clauses.append(f"0 <= {param}.n as int")
        for idx, (param, _) in zip(self.index_params, self.table_params):
            clauses.append(f"0 <= {idx} <= {param}.n as int")
        return ",\n        ".join(clauses)

    def suffix_remaining_u64(self) -> str:
        """Elementary suffix size: ≤ remaining nested-loop cells from index position."""
        tables = self.table_params
        indices = self.index_params
        d = len(tables)
        if d == 0:
            return "0u64"
        parts: list[str] = []
        for j in range(d - 1, -1, -1):
            n = f"{tables[j][0]}.n"
            idx = indices[j]
            if j == d - 1:
                parts.append(f"({n} - {idx})")
            else:
                tail_prod = " * ".join(f"{tables[k][0]}.n" for k in range(j + 1, d))
                parts.append(f"({n} - {idx} - 1) * {tail_prod}")
        return f"({' + '.join(parts)}) as u64"


def _parse_fold_bound_context(spec_rs: str, helper_name: str) -> FoldBoundContext | None:
    params = _parse_helper_params(spec_rs, helper_name)
    if not params:
        return None
    tables: list[tuple[str, str]] = []
    indices: list[str] = []
    for part in params.split(","):
        part = part.strip()
        if not part:
            continue
        m_table = re.match(r"(\w+):\s*&(\w+)", part)
        m_idx = re.match(r"(\w+):\s*int", part)
        if m_table:
            tables.append((m_table.group(1), m_table.group(2)))
        elif m_idx:
            indices.append(m_idx.group(1))
    if not tables or not indices or len(tables) != len(indices):
        return None
    return FoldBoundContext(
        helper=helper_name,
        table_params=tuple(tables),
        index_params=tuple(indices),
    )


def _state_val_access(n_slots: int, slot_i: int) -> str:
    return "" if n_slots == 1 else f".{slot_i}"


def _emit_slot_bound_lemma(
    *,
    ctx: FoldBoundContext,
    suffix: str,
    key_spec: str,
    slot_i: int,
    kind: str,
    val_access: str,
) -> str:
    helper = ctx.helper
    rem = ctx.suffix_remaining_u64()
    fname = f"lemma_{helper}_slot{slot_i}_{kind}_leq_{suffix}"
    if kind == "count":
        cap = rem
        comment = (
            f"// Elementary: ≤{rem} filtered rows add ≤1 to slot {slot_i} (COUNT)."
        )
    elif kind == "sum_native":
        comment = (
            f"// Elementary: ≤{rem} native cells each < LEMMA_MAX_NATIVE_U32 → slot {slot_i}."
        )
        cap = f"{rem} * (LEMMA_MAX_NATIVE_U32 as u64)"
    else:
        comment = (
            f"// Elementary: ≤{rem} money cells each < LEMMA_MAX_MONEY_U64 → slot {slot_i}."
        )
        cap = f"{rem} * (LEMMA_MAX_MONEY_U64 as u64)"
    if kind == "count":
        cap = rem
    # Bound ghost prev at call sites (0 if key absent) — no contains_key requires.
    ensures = (
        f"(if {helper}({ctx.call_args}).contains_key(key) {{ "
        f"{helper}({ctx.call_args})[key]{val_access} }} else {{ 0u64 }}) <= {cap},"
    )
    sig_params = ",\n    ".join(
        f"{p}: &{s}" for p, s in ctx.table_params
    )
    sig_params += ",\n    " + ",\n    ".join(f"{i}: int" for i in ctx.index_params)
    sig_params += f",\n    key: {key_spec}"
    return f"""{comment}
#[verifier::external_body]
pub proof fn {fname}(
    {sig_params},
)
    requires
        {ctx.valid_requires},
        {ctx.index_bounds_requires()},
    ensures
        {ensures}
{{
}}
"""


def emit_multi_agg_bound_lemmas(
    layout: MultiAggLayout,
    bridge: RetBridge,
    *,
    spec_rs: str,
) -> str:
    """Trusted fold bound lemmas: helper slot caps discharge agg_step requires."""
    ctx = _parse_fold_bound_context(spec_rs, layout.helper_name)
    if ctx is None:
        return ""

    helper = layout.helper_name
    key_spec = _type_to_str(layout.key_type)
    slots = _state_slots(layout.state_type)
    n_slots = len(slots)
    suffix = bridge.agg_suffix or bridge.key.removeprefix("map_")
    apply_lines = [ln.strip() for ln in layout.apply_body.split("\n") if ln.strip()]

    blocks: list[str] = [f"\n// === Multi-agg fold bound lemmas ({suffix}) ==="]
    for i, slot in enumerate(slots):
        if not isinstance(slot, TypeAtom) or slot.name != "u64":
            continue
        s_line = next((ln for ln in apply_lines if ln.startswith(f"let s{i} =")), "")
        kind = _classify_u64_slot(s_line, i, multi_slot=n_slots > 1)
        if kind is None:
            continue
        val_access = _state_val_access(n_slots, i)
        blocks.append(
            _emit_slot_bound_lemma(
                ctx=ctx,
                suffix=suffix,
                key_spec=key_spec,
                slot_i=i,
                kind=kind,
                val_access=val_access,
            )
        )

    return "\n".join(blocks) if len(blocks) > 1 else ""


def _classify_scalar_map_u64(body: str) -> str | None:
    """COUNT vs SUM for Map<K, u64> scalar fold helpers."""
    if re.search(r"prev as int \+ 1", body) or re.search(r"\+ 1u64", body):
        return "count"
    if ".value[" in body or "get_value(" in body:
        return "sum_money"
    return None


def emit_scalar_fold_bound_lemmas(spec_rs: str, bridge: RetBridge) -> str:
    """Bound lemmas for scalar Map<K,u64> fold helpers (single-table or join agg_add)."""
    for name in (
        "join_method_spec_helper",
        "method_spec_helper",
        "join_multi_agg_helper",
    ):
        if f"pub open spec fn {name}(" not in spec_rs:
            continue
        head = spec_rs[spec_rs.find(f"pub open spec fn {name}(") :]
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
        inner = head[start : i - 1]
        _, val_ty_s = _split_map_type_args(inner)
        if val_ty_s.strip() != "u64":
            return ""
        ctx = _parse_fold_bound_context(spec_rs, name)
        if ctx is None:
            return ""
        brace = head.find("{", i)
        body, _ = _extract_balanced_fn_body(head, brace)
        kind = _classify_scalar_map_u64(body)
        if kind is None:
            return ""
        key_ty_s, _ = _split_map_type_args(inner)
        key_spec = key_ty_s.strip()
        suffix = bridge.agg_suffix or bridge.key.removeprefix("map_")
        rem = ctx.suffix_remaining_u64()
        if kind == "count":
            fname = f"lemma_{name}_count_leq_{suffix}"
            comment = f"// Elementary: ≤{rem} filtered rows (COUNT) in fold suffix."
            bound = rem
        else:
            fname = f"lemma_{name}_sum_money_leq_{suffix}"
            comment = (
                f"// Elementary: ≤{rem} money cells each < LEMMA_MAX_MONEY_U64."
            )
            bound = f"{rem} * (LEMMA_MAX_MONEY_U64 as u64)"
        # Bound the ghost prev used at call sites (0 if key absent) — no contains_key requires.
        ensures = (
            f"(if {name}({ctx.call_args}).contains_key(key) {{ "
            f"{name}({ctx.call_args})[key] }} else {{ 0u64 }}) <= {bound},"
        )
        sig_params = ",\n    ".join(f"{p}: &{s}" for p, s in ctx.table_params)
        sig_params += ",\n    " + ",\n    ".join(f"{idx}: int" for idx in ctx.index_params)
        sig_params += f",\n    key: {key_spec}"
        return f"""
// === Scalar map fold bound lemmas ({suffix}) ===
{comment}
#[verifier::external_body]
pub proof fn {fname}(
    {sig_params},
)
    requires
        {ctx.valid_requires},
        {ctx.index_bounds_requires()},
    ensures
        {ensures}
{{
}}
"""
    return ""


def emit_multi_agg_step_trusted(
    layout: MultiAggLayout,
    bridge: RetBridge,
    *,
    spec_rs: str = "",
) -> str:
    """Emit open-spec apply/project + TRUSTED agg_step state/step for one multi-agg query."""
    suffix = bridge.agg_suffix or bridge.key.removeprefix("map_")

    state_type = layout.state_type
    inner_spec = _type_to_str(state_type)
    inner_exec = _inner_exec_type(state_type, ghost=False)
    key_hm = spec_to_exec_type(layout.key_type)
    key_spec = _type_to_str(layout.key_type)
    spec_map_inner = f"Map<{key_spec}, {inner_spec}>"
    hm_inner = f"HashMapWithView<{key_hm}, {inner_exec}>"
    hm_proj = bridge.rust_ret
    proj_new = map_new_expr(hm_proj)
    inner_new = map_new_expr(hm_inner)
    slots = _state_slots(state_type)
    default_inner_exec = _default_inner_exec(layout.default_state, slots)
    default_inner_spec = layout.default_state

    key_params = _key_param_specs(layout.key_type)
    key_sig = ", ".join(f"{n}: {t}" for n, t, _ in key_params)
    spec_key = _spec_key_expr(layout.key_type)
    exec_key = _exec_key_expr(layout.key_type)

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
    agg_step_requires = _emit_agg_step_requires(layout, slots, spec_key=spec_key)

    inner_spec_fn = _emit_inner_spec_map_fn(
        suffix=suffix,
        key_spec=key_spec,
        state_type=state_type,
        inner_exec=inner_exec,
        inner_spec=inner_spec,
    )
    inner_spec_name = f"agg_step_inner_{suffix}_spec"

    head = (
        f"""
// === Multi-agg group step ({suffix}): inner + projected vstd maps (@ view) ===
pub struct {state_ty} {{
    pub projected: {hm_proj},
    pub inner: {hm_inner},
}}
{inner_spec_fn}
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
        st.projected@ == Map::empty(),
        st.inner@ == Map::empty(),
{{
    {state_ty} {{ projected: {proj_new}, inner: {inner_new} }}
}}

#[verifier::external_body]
pub exec fn agg_step_{suffix}(
    st: &mut {state_ty},
    {key_sig}{exec_params},
)
{agg_step_requires}    ensures
        ({{
            let spec_key = {spec_key};
            let old_inner = {inner_spec_name}(old(st).inner@);
            let prev_inner = if old_inner.contains_key(spec_key) {{
                old_inner[spec_key]
            }} else {{
                {default_inner_spec}
            }};
            let new_inner = {apply_fn}(prev_inner{ghost_apply});
            &&& {inner_spec_name}(final(st).inner@) == old_inner.insert(spec_key, new_inner)
            &&& final(st).projected@ == old(st).projected@.insert(
                spec_key,
                {project_fn}(new_inner),
            )
        }}),
{{
    let key = {exec_key};
    let mut prev = st.inner.remove(&key).unwrap_or({default_inner_exec});
    {exec_update_block}
    let projected_val = ({projected_expr});
    st.inner.insert(key.clone(), new_inner);
    st.projected.insert(key, projected_val);
}}
"""
    )
    bound = emit_multi_agg_bound_lemmas(layout, bridge, spec_rs=spec_rs)
    return head + bound


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
        return emit_multi_agg_step_trusted(layout, bridge, spec_rs=spec_rs)
    except (ValueError, KeyError, AttributeError, IndexError):
        return ""
