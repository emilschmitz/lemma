"""Host TRUSTED multi-agg group step helpers (exec inner state + projected map)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from research_loop.table_assumptions import CatalogAssumptions, resolve_bounds
from research_loop.trusted_ret_bridge import (
    RetBridge,
    TypeAtom,
    TypeExpr,
    TypeMap,
    TypeTuple,
    _exec_key_expr,
    _key_param_specs,
    _spec_key_expr,
    map_new_expr,
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
            clauses.append(f"{row_param} < LEMMA_MAX_CELL_U64")
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
    """Return count / sum_native / sum_cell_u64 for a numeric slot, or None (MIN/MAX / skip)."""
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
        return "sum_cell_u64"
    if "as int)" in delta or " as int" in delta:
        return "sum_native"
    return "sum_cell_u64"


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

    def suffix_start_requires(self) -> str:
        """Indices are a nested-loop suffix start (same gate as rem ≤ ROWS^k lemmas).

        For depth d: either still inside some outer row (i_j < n_j for the first
        incomplete level), or all remaining inner indices are 0 when an outer index
        is exhausted. Compact form used by rem lemmas: for each prefix, if outer
        indices are at end then inners are 0 — equivalently for 2-table
        ``i0 < n0 || i1 == 0``.
        """
        d = len(self.table_params)
        if d <= 1:
            return ""
        if d == 2:
            (p0, _), (p1, _) = self.table_params
            i0, i1 = self.index_params
            return f"{i0} < {p0}.n as int || {i1} == 0"
        # General: for each outer level j < d-1, if i_j >= n_j then all i_k==0 for k>j
        # — equivalent nested form matching rem_join_* callers.
        clauses: list[str] = []
        for j in range(d - 1):
            pj, _ = self.table_params[j]
            ij = self.index_params[j]
            inner_zeros = " && ".join(
                f"{self.index_params[k]} == 0" for k in range(j + 1, d)
            )
            clauses.append(f"{ij} < {pj}.n as int || ({inner_zeros})")
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
                parts.append(f"({n} as int - {idx})")
            else:
                tail_prod = " * ".join(
                    f"{tables[k][0]}.n as int" for k in range(j + 1, d)
                )
                parts.append(f"({n} as int - {idx} - 1) * ({tail_prod})")
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


@dataclass(frozen=True)
class _HelperHitBranch:
    filter_expr: str
    key_expr: str
    default_state: str
    scalar_map: bool


def _parse_helper_decreases(spec_rs: str, helper_name: str) -> str:
    m = re.search(
        rf"pub open spec fn {re.escape(helper_name)}\([\s\S]*?\)\s*->[\s\S]*?\n\s*decreases\s+([^,\n{{]+(?:,\s*[^,\n{{]+)*)",
        spec_rs,
    )
    return m.group(1).strip() if m else ""


def _extract_paren_group(text: str, open_pos: int) -> tuple[str, int]:
    """Return inner text between balanced parens starting at open_pos, and index after ')'."""
    if open_pos >= len(text) or text[open_pos] != "(":
        raise ValueError("expected '('")
    depth = 0
    body_start = open_pos + 1
    i = open_pos
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[body_start:i], i + 1
        i += 1
    raise ValueError("unbalanced parens")


def _parse_helper_fold_step(spec_rs: str, helper_name: str) -> str | None:
    """Extract ``if filter {{ ... }} else {{ tail }}`` after innermost ``let tail``."""
    found = _find_helper(spec_rs)
    if not found or found[0] != helper_name:
        return None
    body = found[3]
    tail_m = re.search(
        rf"let tail = {re.escape(helper_name)}\([^;]+\;",
        body,
        re.DOTALL,
    )
    if not tail_m:
        return None
    if_m = re.search(r"\sif\s+", body[tail_m.end() :])
    if not if_m:
        return None
    start = tail_m.end() + if_m.start()
    cond_start = tail_m.end() + if_m.end()
    brace = body.find("{", cond_start)
    if brace == -1:
        return None
    depth = 0
    i = brace
    while i < len(body):
        ch = body[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                after_if = i + 1
                break
        i += 1
    else:
        return None
    else_m = re.match(r"\s*else\s*\{", body[after_if:])
    if not else_m:
        return None
    else_brace = after_if + else_m.end() - 1
    depth = 0
    j = else_brace
    while j < len(body):
        ch = body[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return body[start : j + 1].strip()
        j += 1
    return None


def _parse_helper_hit_branch(spec_rs: str, helper_name: str) -> _HelperHitBranch | None:
    found = _find_helper(spec_rs)
    if not found or found[0] != helper_name:
        return None
    _name, _key_ty, _val_ty, body = found
    scalar_map = _val_ty.strip() == "u64"
    tail_m = re.search(
        rf"let tail = {re.escape(helper_name)}\([^;]+\;",
        body,
        re.DOTALL,
    )
    if not tail_m:
        return None
    if_m = re.search(r"\sif\s+", body[tail_m.end() :])
    if not if_m:
        return None
    cond_start = tail_m.end() + if_m.end()
    brace = body.find("{", cond_start)
    if brace == -1:
        return None
    filter_expr = body[cond_start:brace].strip()
    key_m = re.search(
        r"let key = (.+?);\s*let (?:prev|val) = if tail\.contains_key\(key\) \{ tail\[key\] \} else \{ ([^}]+) \};",
        body[brace:],
        re.DOTALL,
    )
    if not key_m:
        return None
    return _HelperHitBranch(
        filter_expr=filter_expr.strip(),
        key_expr=key_m.group(1).strip(),
        default_state=key_m.group(2).strip(),
        scalar_map=scalar_map,
    )


def _helper_call_args(
    ctx: FoldBoundContext,
    idx_overrides: dict[str, str] | None = None,
) -> str:
    parts = [p for p, _ in ctx.table_params]
    for idx in ctx.index_params:
        parts.append(idx_overrides[idx] if idx_overrides and idx in idx_overrides else idx)
    return ", ".join(parts)


def _helper_call(ctx: FoldBoundContext, idx_overrides: dict[str, str] | None = None) -> str:
    return f"{ctx.helper}({_helper_call_args(ctx, idx_overrides)})"


def _slot_bound_expr(
    helper_call: str,
    key: str,
    val_access: str,
    *,
    scalar_map: bool,
) -> str:
    if scalar_map:
        inner = f"{helper_call}[{key}]"
    else:
        inner = f"{helper_call}[{key}]{val_access}"
    return f"(if {helper_call}.contains_key({key}) {{ {inner} }} else {{ 0u64 }})"


def _rem_int_expr(ctx: FoldBoundContext, idx_overrides: dict[str, str] | None = None) -> str:
    depth = len(ctx.table_params)
    if depth == 1:
        t0, _ = ctx.table_params[0]
        i0 = (
            idx_overrides[ctx.index_params[0]]
            if idx_overrides and ctx.index_params[0] in idx_overrides
            else ctx.index_params[0]
        )
        i0_expr = f"({i0})" if idx_overrides and ctx.index_params[0] in idx_overrides else i0
        return f"({t0}.n as int - {i0_expr})"
    ns = ", ".join(f"{p}.n" for p, _ in ctx.table_params)
    is_parts: list[str] = []
    for i in ctx.index_params:
        if idx_overrides and i in idx_overrides:
            is_parts.append(idx_overrides[i])
        else:
            is_parts.append(i)
    is_ = ", ".join(is_parts)
    if depth == 2:
        return f"rem_join_sq({ns}, {is_})"
    if depth == 3:
        return f"rem_join_cube({ns}, {is_})"
    if depth == 4:
        return f"rem_join_4({ns}, {is_})"
    return ctx.suffix_remaining_u64().replace(" as u64", "")


def _index_bounds_requires_list(ctx: FoldBoundContext) -> list[str]:
    clauses: list[str] = []
    for param, _struct in ctx.table_params:
        clauses.append(f"0 <= {param}.n as int")
    for idx, (param, _) in zip(ctx.index_params, ctx.table_params):
        clauses.append(f"0 <= {idx} <= {param}.n as int")
    return clauses


def _parse_slot_sum_delta_line(line: str, slot_i: int) -> str | None:
    m = re.search(rf"let s{slot_i} = ", line)
    if not m:
        return None
    i = m.end()
    if i >= len(line) or line[i] != "(":
        return None
    depth = 0
    body_start = i + 1
    j = i
    while j < len(line):
        ch = line[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                inner = line[body_start:j]
                plus_m = re.search(r"\+ ", inner)
                if not plus_m:
                    return None
                return inner[plus_m.end() :].strip()
        j += 1
    return None


def _parse_slot_sum_delta(spec_rs: str, helper_name: str, slot_i: int) -> str | None:
    found = _find_helper(spec_rs)
    if not found or found[0] != helper_name:
        return None
    _name, _key_ty, val_ty, body = found
    scalar_map = val_ty.strip() == "u64"
    if scalar_map:
        m = re.search(
            r"tail\.insert\(key,\s*\(val as int \+ (.+)\) as u64\)",
            body,
            re.DOTALL,
        )
        raw = m.group(1).strip() if m else None
    else:
        raw = None
        for line in body.split("\n"):
            raw = _parse_slot_sum_delta_line(line.strip(), slot_i)
            if raw is not None:
                break
    if raw is None:
        return None
    return _normalize_sum_delta_for_proof(raw)


def _normalize_sum_delta_for_proof(delta: str) -> str:
    """Strip rebuild casts; return a balanced ghost-int cell for proof asserts."""
    out = delta.strip()
    if out.endswith(" as u64 as int"):
        out = out[: -len(" as u64 as int")].strip()
    while out.startswith("(") and out.endswith(")"):
        inner = out[1:-1].strip()
        if inner.count("(") == inner.count(")"):
            out = inner
        else:
            break
    if out.endswith(" as int"):
        return f"({out})"
    return f"({out} as int)"


def _sum_cap_const(kind: str) -> str:
    return "LEMMA_MAX_NATIVE_U32" if kind == "sum_native" else "LEMMA_MAX_CELL_U64"


def _sanitize_fold_step_for_proof(fold_step: str) -> str:
    """Rename MethodSpec ``let key =`` binder so it does not shadow the lemma ``key`` param."""
    s = fold_step
    s = re.sub(r"\blet key =", "let row_key =", s)
    s = re.sub(r"\bcontains_key\(key\)", "contains_key(row_key)", s)
    s = re.sub(r"\btail\[key\]", "tail[row_key]", s)
    s = re.sub(r"\.insert\(key,", ".insert(row_key,", s)
    return s


@dataclass(frozen=True)
class _FoldHitSlotUpdates:
    prev_default: str
    slot_lets: tuple[tuple[str, str], ...]
    insert_value: str


def _extract_brace_block(text: str, open_pos: int) -> tuple[str, int]:
    if open_pos >= len(text) or text[open_pos] != "{":
        raise ValueError("expected '{'")
    depth = 0
    body_start = open_pos + 1
    i = open_pos
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[body_start:i], i + 1
        i += 1
    raise ValueError("unbalanced braces")


def _strip_rust_line_comment(expr: str) -> str:
    return re.sub(r"\s*//.*$", "", expr.strip(), flags=re.MULTILINE).strip()


def _subst_prev_identifier(expr: str, prev_replacement: str) -> str:
    return re.sub(r"\bprev\b", prev_replacement, expr)


def _parse_fold_hit_slot_updates(fold_step: str) -> _FoldHitSlotUpdates | None:
    """Parse ``let prev`` / ``let sN`` / ``tail.insert(row_key, …)`` from sanitized fold_step."""
    s = fold_step.strip()
    if not s.startswith("if "):
        return None
    brace = s.find("{")
    if brace < 0:
        return None
    try:
        hit_body, _ = _extract_brace_block(s, brace)
    except ValueError:
        return None
    prev_m = re.search(
        r"let prev = if tail\.contains_key\(row_key\) \{ tail\[row_key\] \} else \{",
        hit_body,
    )
    if not prev_m:
        return None
    else_brace = hit_body.index("{", prev_m.end() - 1)
    try:
        prev_default, after_default = _extract_brace_block(hit_body, else_brace)
    except ValueError:
        return None
    rest = hit_body[after_default :].lstrip()
    if not rest.startswith(";"):
        return None
    rest = rest[1:].lstrip()
    slot_lets: list[tuple[str, str]] = []
    while True:
        m = re.match(r"let (s\d+) = (.+?);", rest, re.DOTALL)
        if not m:
            break
        slot_lets.append((m.group(1), m.group(2).strip()))
        rest = rest[m.end() :].lstrip()
    insert_m = re.match(r"tail\.insert\(row_key,\s*(.+?)\)\s*$", rest.strip(), re.DOTALL)
    if not insert_m:
        return None
    return _FoldHitSlotUpdates(
        prev_default=prev_default.strip(),
        slot_lets=tuple(slot_lets),
        insert_value=_strip_rust_line_comment(insert_m.group(1)),
    )


def _emit_reconstructed_insert_value(
    *,
    indent: str,
    prev_var: str,
    prev_expr: str,
    updates: _FoldHitSlotUpdates,
    result_var: str = "inserted_val",
) -> list[str]:
    lines = [f"{indent}let ghost {prev_var} = {prev_expr};"]
    for sname, rhs in updates.slot_lets:
        sub_rhs = _subst_prev_identifier(rhs, prev_var)
        lines.append(f"{indent}let ghost {sname} = {sub_rhs};")
    insert_val = _subst_prev_identifier(updates.insert_value, prev_var)
    lines.append(f"{indent}let ghost {result_var} = {insert_val};")
    return lines


def _emit_count_add_one_fit_steps(
    ctx: FoldBoundContext,
    indent: str,
    *,
    rem_tail_int: str,
) -> list[str]:
    """Prove ``prev_slot as int + 1`` fits in u64 so MethodSpec COUNT cast is math +1."""
    depth = len(ctx.table_params)
    lines: list[str] = []
    ns = [p for p, _ in ctx.table_params]
    idxs = list(ctx.index_params)
    if depth == 1:
        lines.append(f"{indent}assert(0 <= {rem_tail_int});")
        lines.append(f"{indent}assert({rem_tail_int} <= {ns[0]}.n as int);")
        lines.append(f"{indent}assert({ns[0]}.n <= LEMMA_MAX_ROWS);")
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
        lines.append(
            f"{indent}assert(rem_tail_u64 <= LEMMA_MAX_ROWS as u64);"
        )
        lines.append(f"{indent}lemma_rem_cap_one_add_fits_rows(rem_tail_u64);")
    elif depth == 2:
        lines.append(
            f"{indent}lemma_join_nested_rem_leq_rows_sq("
            f"{ns[0]}.n, {ns[1]}.n, {idxs[0]}, {idxs[1]} + 1);"
        )
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
        lines.append(
            f"{indent}assert(rem_tail_u64 <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64));"
        )
        lines.append(f"{indent}lemma_rem_cap_one_add_fits(rem_tail_u64);")
    elif depth == 3:
        lines.append(
            f"{indent}lemma_join_nested_rem_leq_rows_cube("
            f"{ns[0]}.n, {ns[1]}.n, {ns[2]}.n, {idxs[0]}, {idxs[1]}, {idxs[2]} + 1);"
        )
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
        lines.append(f"{indent}lemma_rem_cap_one_add_fits_cube(rem_tail_u64);")
    elif depth == 4:
        lines.append(
            f"{indent}lemma_join_nested_rem_leq_rows_4("
            f"{ns[0]}.n, {ns[1]}.n, {ns[2]}.n, {ns[3]}.n, "
            f"{idxs[0]}, {idxs[1]}, {idxs[2]}, {idxs[3]} + 1);"
        )
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
        lines.append(f"{indent}lemma_rem_cap_one_add_fits_4(rem_tail_u64);")
    else:
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
        lines.append(
            f"{indent}assert((rem_tail_u64 as int) + 1 <= u64::MAX as int);"
        )
    lines.append(f"{indent}assert(prev_slot <= rem_tail_u64);")
    lines.append(f"{indent}lemma_u64_add_one_prev_le(prev_slot, rem_tail_u64);")
    lines.append(f"{indent}assert((prev_slot as int) + 1 <= u64::MAX as int);")
    return lines


def _emit_inductive_hit_branch(
    *,
    ctx: FoldBoundContext,
    fname: str,
    key: str,
    val_access: str,
    hit: _HelperHitBranch,
    kind: str,
    sum_delta: str | None,
    indent: str,
    cur_call: str,
    rem_here_int: str,
    rem_tail_int: str,
    tail_call: str,
    tail_rec_args: str,
    spec_rs: str,
) -> list[str]:
    cap = _sum_cap_const(kind)
    helper = ctx.helper
    fold_step = _parse_helper_fold_step(spec_rs, helper)
    slot_updates: _FoldHitSlotUpdates | None = None
    if fold_step is not None:
        fold_step = _sanitize_fold_step_for_proof(fold_step)
        slot_updates = _parse_fold_hit_slot_updates(fold_step)
    lines: list[str] = []
    if hit.scalar_map:
        prev_slot = f"if tail.contains_key({key}) {{ tail[{key}] }} else {{ 0u64 }}"
        slot_expr = lambda call: f"{call}[{key}]"
    elif val_access:
        prev_slot = (
            f"if tail.contains_key({key}) {{ tail[{key}]{val_access} }} else {{ 0u64 }}"
        )
        slot_expr = lambda call: f"{call}[{key}]{val_access}"
    else:
        prev_slot = (
            f"if tail.contains_key({key}) {{ tail[{key}] }} else {{ {hit.default_state} }}"
        )
        slot_expr = lambda call: f"{call}[{key}]"

    lines.append(f"{indent}{fname}({tail_rec_args}, {key});")
    lines.append(f"{indent}let ghost tail = {tail_call};")
    lines.append(f"{indent}let ghost rem_here_int = {rem_here_int};")
    lines.append(f"{indent}let ghost rem_tail_int = {rem_tail_int};")
    lines.append(f"{indent}let ghost prev_slot = {prev_slot};")
    # One inner step: rem_here = rem_tail + 1 (proved lemma when 2-table rem_join_sq).
    if len(ctx.table_params) == 2:
        n0, _ = ctx.table_params[0]
        n1, _ = ctx.table_params[1]
        i0 = ctx.index_params[0]
        i1 = ctx.index_params[1]
        lines.append(
            f"{indent}lemma_rem_join_sq_inner_step({n0}.n, {n1}.n, {i0}, {i1});"
        )
    else:
        lines.append(
            f"{indent}assert(rem_here_int == rem_tail_int + 1) by (nonlinear_arith);"
        )
    lines.append(f"{indent}assert(prev_slot as int <= rem_tail_int);")
    lines.append(f"{indent}assert(prev_slot as int <= rem_here_int - 1);")
    if kind != "count":
        assert sum_delta is not None
        lines.append(
            f"{indent}assert(prev_slot as int <= (rem_here_int - 1) * ({cap} as int));"
        )
        lines.append(f"{indent}assert({sum_delta} < ({cap} as int));")
    # COUNT MethodSpec uses `(prev as int + 1) as u64`; discharge cast = math +1 via rem·ROWS fit.
    if kind == "count":
        lines.extend(_emit_count_add_one_fit_steps(ctx, indent, rem_tail_int=rem_tail_int))

    if fold_step is not None:
        # Unfold one recursive step of the open helper (no key-shadowing in copied body).
        lines.append(f"{indent}reveal_with_fuel({helper}, 1);")
        lines.append(f"{indent}assert({cur_call} =~= {{")
        lines.append(f"{indent}    let tail = {tail_call};")
        for step_line in fold_step.splitlines():
            lines.append(f"{indent}    {step_line}")
        lines.append(f"{indent}}});")
    else:
        lines.append(f"{indent}reveal_with_fuel({helper}, 1);")

    if kind == "count":
        # Bind the one-step map explicitly so indexing facts are local.
        lines.append(f"{indent}let ghost next_map = {{")
        lines.append(f"{indent}    let tail = {tail_call};")
        if fold_step is not None:
            for step_line in fold_step.splitlines():
                lines.append(f"{indent}    {step_line}")
        else:
            lines.append(
                f"{indent}    if ({hit.filter_expr}) {{"
            )
            lines.append(f"{indent}        let row_key = {hit.key_expr};")
            lines.append(
                f"{indent}        let prev = if tail.contains_key(row_key) {{ tail[row_key] }} else {{ {hit.default_state} }};"
            )
            if hit.scalar_map:
                lines.append(f"{indent}        let s0 = (prev as int + 1) as u64;")
                lines.append(f"{indent}        tail.insert(row_key, s0)")
            else:
                lines.append(f"{indent}        let s0 = (prev.0 as int + 1) as u64;")
                lines.append(
                    f"{indent}        tail.insert(row_key, (s0, prev.1)) // slot0 count; other slots unchanged in this stub"
                )
            lines.append(f"{indent}    }} else {{")
            lines.append(f"{indent}        tail")
            lines.append(f"{indent}    }}")
        lines.append(f"{indent}}};")
        lines.append(f"{indent}assert({cur_call} == next_map);")
        lines.append(f"{indent}if ({hit.filter_expr}) {{")
        lines.append(f"{indent}    let ghost row_key = {hit.key_expr};")
        lines.append(f"{indent}    if row_key == {key} {{")
        lines.append(f"{indent}        assert(next_map.contains_key({key}));")
        prev_default = (
            slot_updates.prev_default if slot_updates is not None else hit.default_state
        )
        hit_indent = indent + "        "
        if hit.scalar_map:
            lines.append(
                f"{indent}        let ghost prev_full = if tail.contains_key({key}) {{ tail[{key}] }} else {{ {prev_default} }};"
            )
            lines.append(f"{indent}        assert(prev_full == prev_slot);")
            lines.append(
                f"{indent}        let ghost s0 = (prev_full as int + 1) as u64;"
            )
            lines.append(f"{indent}        assert(s0 as int == prev_full as int + 1);")
            lines.append(f"{indent}        assert(next_map == tail.insert({key}, s0));")
            lines.append(f"{indent}        lemma_map_insert_get(tail, {key}, s0);")
            lines.append(f"{indent}        assert(next_map[{key}] == s0);")
            lines.append(f"{indent}        assert(s0 as int == prev_slot as int + 1);")
        elif slot_updates is not None:
            lines.extend(
                _emit_reconstructed_insert_value(
                    indent=hit_indent,
                    prev_var="prev_full",
                    prev_expr=(
                        f"if tail.contains_key({key}) {{ tail[{key}] }} "
                        f"else {{ {prev_default} }}"
                    ),
                    updates=slot_updates,
                )
            )
            if val_access:
                lines.append(f"{hit_indent}assert(prev_full{val_access} == prev_slot);")
            else:
                lines.append(f"{hit_indent}assert(prev_full.0 == prev_slot);")
            # s0 is always MethodSpec COUNT step: (prev.0 as int + 1) as u64
            lines.append(f"{hit_indent}assert(s0 as int == prev_full.0 as int + 1);")
            lines.append(
                f"{hit_indent}assert(next_map == tail.insert({key}, inserted_val));"
            )
            lines.append(
                f"{hit_indent}lemma_map_insert_get(tail, {key}, inserted_val);"
            )
            if val_access:
                lines.append(
                    f"{hit_indent}assert(next_map[{key}]{val_access} == inserted_val{val_access});"
                )
                lines.append(
                    f"{hit_indent}assert(inserted_val{val_access} as int == prev_slot as int + 1);"
                )
            else:
                lines.append(f"{hit_indent}assert(next_map[{key}] == inserted_val);")
                lines.append(
                    f"{hit_indent}assert(inserted_val.0 as int == prev_slot as int + 1);"
                )
        else:
            lines.append(
                f"{indent}        let ghost prev_full = if tail.contains_key({key}) {{ tail[{key}] }} else {{ {hit.default_state} }};"
            )
            lines.append(f"{indent}        assert(prev_full.0 == prev_slot);")
            lines.append(
                f"{indent}        let ghost s0 = (prev_full.0 as int + 1) as u64;"
            )
            lines.append(
                f"{indent}        assert(s0 as int == prev_full.0 as int + 1);"
            )
            lines.append(
                f"{indent}        let ghost inserted_val = (s0, prev_full.1);"
            )
            lines.append(
                f"{indent}        assert(next_map == tail.insert({key}, inserted_val));"
            )
            lines.append(
                f"{indent}        lemma_map_insert_get(tail, {key}, inserted_val);"
            )
            lines.append(f"{indent}        assert(next_map[{key}].0 == s0);")
            lines.append(f"{indent}        assert(s0 as int == prev_slot as int + 1);")
        lines.append(
            f"{indent}        assert(prev_slot as int + 1 <= rem_here_int);"
        )
        lines.append(f"{indent}    }} else {{")
        other_indent = indent + "        "
        if slot_updates is not None:
            lines.extend(
                _emit_reconstructed_insert_value(
                    indent=other_indent,
                    prev_var="prev_row",
                    prev_expr=(
                        f"if tail.contains_key(row_key) {{ tail[row_key] }} "
                        f"else {{ {prev_default} }}"
                    ),
                    updates=slot_updates,
                )
            )
            lines.append(
                f"{other_indent}assert(next_map == tail.insert(row_key, inserted_val));"
            )
            lines.append(
                f"{other_indent}lemma_map_insert_preserves_other_key(tail, row_key, {key}, inserted_val);"
            )
        elif hit.scalar_map:
            lines.append(
                f"{indent}        lemma_map_insert_preserves_other_key(tail, row_key, {key}, next_map[row_key]);"
            )
        else:
            lines.append(
                f"{other_indent}let ghost prev_row = if tail.contains_key(row_key) {{ tail[row_key] }} else {{ {hit.default_state} }};"
            )
            lines.append(
                f"{other_indent}let ghost s0 = (prev_row.0 as int + 1) as u64;"
            )
            lines.append(
                f"{other_indent}let ghost inserted_val = (s0, prev_row.1);"
            )
            lines.append(
                f"{other_indent}lemma_map_insert_preserves_other_key(tail, row_key, {key}, inserted_val);"
            )
        lines.append(
            f"{indent}        assert(next_map.contains_key({key}) == tail.contains_key({key}));"
        )
        lines.append(f"{indent}        if tail.contains_key({key}) {{")
        if hit.scalar_map:
            lines.append(f"{indent}            assert(next_map[{key}] == prev_slot);")
        else:
            lines.append(
                f"{indent}            assert(next_map[{key}]{val_access} == prev_slot);"
            )
        lines.append(f"{indent}        }} else {{")
        lines.append(f"{indent}            assert(!next_map.contains_key({key}));")
        lines.append(f"{indent}        }}")
        lines.append(f"{indent}    }}")
        lines.append(f"{indent}}} else {{")
        lines.append(f"{indent}    assert(next_map == tail);")
        lines.append(f"{indent}}}")
        lines.append(
            f"{indent}assert({_slot_bound_expr('next_map', key, val_access, scalar_map=hit.scalar_map)} as int <= rem_here_int);"
        )
        lines.append(
            f"{indent}assert({_slot_bound_expr(cur_call, key, val_access, scalar_map=hit.scalar_map)} as int <= rem_here_int);"
        )
    else:
        assert sum_delta is not None
        lines.append(f"{indent}if ({hit.filter_expr}) {{")
        lines.append(f"{indent}    let ghost row_key = {hit.key_expr};")
        lines.append(f"{indent}    if row_key == {key} {{")
        lines.append(
            f"{indent}        assert({slot_expr(cur_call)} as int == prev_slot as int + ({sum_delta}));"
        )
        lines.append(
            f"{indent}        assert(prev_slot as int + ({sum_delta}) <= rem_here_int * ({cap} as int));"
        )
        lines.append(f"{indent}    }} else {{")
        lines.append(f"{indent}        assert({cur_call}.contains_key(row_key));")
        lines.append(
            f"{indent}        lemma_map_insert_preserves_other_key(tail, row_key, {key}, {cur_call}[row_key]);"
        )
        lines.append(
            f"{indent}        assert({cur_call}.contains_key({key}) == tail.contains_key({key}));"
        )
        lines.append(f"{indent}        if tail.contains_key({key}) {{")
        lines.append(
            f"{indent}            assert({slot_expr(cur_call)} == prev_slot);"
        )
        lines.append(f"{indent}        }} else {{")
        lines.append(f"{indent}            assert(!{cur_call}.contains_key({key}));")
        lines.append(f"{indent}        }}")
        lines.append(f"{indent}    }}")
        lines.append(f"{indent}}} else {{")
        lines.append(f"{indent}    assert({cur_call} == tail);")
        lines.append(f"{indent}}}")
        lines.append(
            f"{indent}assert({_slot_bound_expr(cur_call, key, val_access, scalar_map=hit.scalar_map)} as int <= rem_here_int * ({cap} as int));"
        )
    return lines


def _emit_nested_count_or_sum_body(
    *,
    ctx: FoldBoundContext,
    fname: str,
    key: str,
    val_access: str,
    hit: _HelperHitBranch,
    kind: str,
    sum_delta: str | None,
    level: int,
    indent: str,
    spec_rs: str,
) -> list[str]:
    depth = len(ctx.table_params)
    if level >= depth:
        cur_call = _helper_call(ctx)
        rem_here_int = _rem_int_expr(ctx)
        lines = [
            f"{indent}assert({cur_call} =~= Map::empty());",
            f"{indent}assert({_slot_bound_expr(cur_call, key, val_access, scalar_map=hit.scalar_map)} == 0u64);",
        ]
        if len(ctx.table_params) == 2:
            n0, _ = ctx.table_params[0]
            n1, _ = ctx.table_params[1]
            i0, i1 = ctx.index_params
            lines.append(f"{indent}assert({i0} == {n0}.n as int);")
            lines.append(f"{indent}assert({i1} == 0);")
            lines.append(
                f"{indent}lemma_rem_join_sq_nonneg_boundary({n0}.n, {n1}.n);"
            )
            lines.append(f"{indent}assert({rem_here_int} == 0);")
        else:
            lines.append(f"{indent}assert(0 <= {rem_here_int});")
            lines.append(
                f"{indent}assert({rem_here_int} == 0) by (nonlinear_arith);"
            )
        lines.append(
            f"{indent}assert({_slot_bound_expr(cur_call, key, val_access, scalar_map=hit.scalar_map)} as int <= {rem_here_int});"
        )
        return lines

    tab_param, _tab_struct = ctx.table_params[level]
    idx = ctx.index_params[level]
    rem_here_int = _rem_int_expr(ctx)

    if level == depth - 1:
        overrides_tail = {idx: f"{idx} + 1"}
        tail_call = _helper_call(ctx, overrides_tail)
        tail_rec_args = _helper_call_args(ctx, overrides_tail)
        rem_tail_int = _rem_int_expr(ctx, overrides_tail)
        cur_call = _helper_call(ctx)
        lines = [f"{indent}if {idx} < {tab_param}.n as int {{"]
        lines.extend(
            _emit_inductive_hit_branch(
                ctx=ctx,
                fname=fname,
                key=key,
                val_access=val_access,
                hit=hit,
                kind=kind,
                sum_delta=sum_delta,
                indent=indent + "    ",
                cur_call=cur_call,
                rem_here_int=rem_here_int,
                rem_tail_int=rem_tail_int,
                tail_call=tail_call,
                tail_rec_args=tail_rec_args,
                spec_rs=spec_rs,
            )
        )
        lines.append(f"{indent}}} else {{")
        if depth == 1:
            lines.append(f"{indent}    assert({cur_call} =~= Map::empty());")
            lines.append(
                f"{indent}    assert({_slot_bound_expr(cur_call, key, val_access, scalar_map=hit.scalar_map)} == 0u64);"
            )
            lines.append(f"{indent}    assert({idx} == {tab_param}.n as int);")
            lines.append(
                f"{indent}    assert({rem_here_int} == 0) by (nonlinear_arith);"
            )
            lines.append(
                f"{indent}    assert({_slot_bound_expr(cur_call, key, val_access, scalar_map=hit.scalar_map)} as int <= {rem_here_int});"
            )
        else:
            parent_idx = ctx.index_params[level - 1]
            boundary_overrides = {idx: "0", parent_idx: f"{parent_idx} + 1"}
            boundary_args = _helper_call_args(ctx, boundary_overrides)
            boundary_call = _helper_call(ctx, boundary_overrides)
            rem_boundary_int = _rem_int_expr(ctx, boundary_overrides)
            lines.append(f"{indent}    {fname}({boundary_args}, {key});")
            # When innermost index is at n, MethodSpec rolls to (parent+1, 0, …);
            # rem geometry matches that boundary call.
            lines.append(f"{indent}    reveal_with_fuel({ctx.helper}, 1);")
            lines.append(f"{indent}    assert({idx} == {tab_param}.n as int);")
            lines.append(f"{indent}    assert({cur_call} == {boundary_call});")
            if depth == 2:
                parent_tab, _ = ctx.table_params[level - 1]
                lines.append(
                    f"{indent}    lemma_rem_join_sq_outer_roll("
                    f"{parent_tab}.n, {tab_param}.n, {parent_idx}, {idx});"
                )
            else:
                lines.append(
                    f"{indent}    assert({rem_here_int} == {rem_boundary_int}) by (nonlinear_arith);"
                )
            lines.append(
                f"{indent}    assert({_slot_bound_expr(cur_call, key, val_access, scalar_map=hit.scalar_map)} as int "
                f"<= {rem_here_int});"
            )
        lines.append(f"{indent}}}")
        return lines

    lines = [f"{indent}if {idx} < {tab_param}.n as int {{"]
    lines.extend(
        _emit_nested_count_or_sum_body(
            ctx=ctx,
            fname=fname,
            key=key,
            val_access=val_access,
            hit=hit,
            kind=kind,
            sum_delta=sum_delta,
            level=level + 1,
            indent=indent + "    ",
            spec_rs=spec_rs,
        )
    )
    boundary_overrides: dict[str, str] = {idx: f"{idx} + 1"}
    for inner in ctx.index_params[level + 1 :]:
        boundary_overrides[inner] = "0"
    boundary_args = _helper_call_args(ctx, boundary_overrides)
    lines.append(f"{indent}}} else {{")
    if level == 0:
        lines.extend(
            _emit_nested_count_or_sum_body(
                ctx=ctx,
                fname=fname,
                key=key,
                val_access=val_access,
                hit=hit,
                kind=kind,
                sum_delta=sum_delta,
                level=depth,
                indent=indent + "    ",
                spec_rs=spec_rs,
            )
        )
    else:
        lines.append(f"{indent}    {fname}({boundary_args}, {key});")
    lines.append(f"{indent}}}")
    return lines


_FOLD_LEMMA_HEADER = (
    "// Fold slot bound: inductive proof mirroring the open-spec fold helper — "
    "each filter hit adds ≤1 (COUNT) or one capped cell (SUM)."
)

_FOLD_AXIOM_HEADER = (
    "// ASSUMPTION (catalog/user): under valid_cols + open-spec fold, partial agg ≤ rem·cap.\n"
    "// Honest empty external_body — not a proved lemma. Set LEMMA_FOLD_SLOT_INDUCTIVE=1\n"
    "// for experimental inductive `lemma_*` bodies (COUNT/SUM)."
)


def _fold_slot_inductive_enabled() -> bool:
    return os.environ.get("LEMMA_FOLD_SLOT_INDUCTIVE", "") == "1"


def _fold_bounds_allow_cell_cap(
    spec_rs: str,
    catalog: CatalogAssumptions | None,
) -> bool:
    if catalog is not None:
        return resolve_bounds(catalog).has_tight_cell_u64
    return "LEMMA_MAX_CELL_U64" in spec_rs


def _emit_axiomatic_slot_bound_lemma(
    *,
    ctx: FoldBoundContext,
    suffix: str,
    key_spec: str,
    slot_i: int,
    kind: str,
    val_access: str,
    hit: _HelperHitBranch,
) -> str:
    helper = ctx.helper
    rem = ctx.suffix_remaining_u64()
    fname = f"assume_{helper}_slot{slot_i}_{kind}_leq_{suffix}"
    if kind == "count":
        detail = f"COUNT slot {slot_i}: ≤{rem} filtered rows add ≤1 each."
        cap = rem
    elif kind == "sum_native":
        detail = (
            f"SUM(native) slot {slot_i}: ≤{rem} cells each < LEMMA_MAX_NATIVE_U32."
        )
        cap = f"{rem} * (LEMMA_MAX_NATIVE_U32 as u64)"
    else:
        detail = (
            f"SUM(u64 cell) slot {slot_i}: ≤{rem} cells each < LEMMA_MAX_CELL_U64."
        )
        cap = f"{rem} * (LEMMA_MAX_CELL_U64 as u64)"
    comment = f"{_FOLD_AXIOM_HEADER}\n// {detail}"
    ensures = (
        f"{_slot_bound_expr(_helper_call(ctx), 'key', val_access, scalar_map=hit.scalar_map)} <= {cap},"
    )
    sig_params = ",\n    ".join(f"{p}: &{s}" for p, s in ctx.table_params)
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


def _emit_inductive_slot_bound_lemma(
    *,
    ctx: FoldBoundContext,
    suffix: str,
    key_spec: str,
    slot_i: int,
    kind: str,
    val_access: str,
    spec_rs: str,
    hit: _HelperHitBranch,
    sum_delta: str | None,
) -> str:
    helper = ctx.helper
    rem = ctx.suffix_remaining_u64()
    fname = f"lemma_{helper}_slot{slot_i}_{kind}_leq_{suffix}"
    if kind == "count":
        detail = f"COUNT slot {slot_i}: ≤{rem} filtered rows add ≤1 each."
        cap = rem
    elif kind == "sum_native":
        detail = (
            f"SUM(native) slot {slot_i}: ≤{rem} cells each < LEMMA_MAX_NATIVE_U32."
        )
        cap = f"{rem} * (LEMMA_MAX_NATIVE_U32 as u64)"
    else:
        detail = (
            f"SUM(u64 cell) slot {slot_i}: ≤{rem} cells each < LEMMA_MAX_CELL_U64."
        )
        cap = f"{rem} * (LEMMA_MAX_CELL_U64 as u64)"
    comment = f"{_FOLD_LEMMA_HEADER}\n// {detail}"
    cur_call = _helper_call(ctx)
    rem_int = _rem_int_expr(ctx)
    slot_e = _slot_bound_expr(cur_call, "key", val_access, scalar_map=hit.scalar_map)
    if kind == "count":
        ensures = f"({slot_e} as int) <= ({rem_int}),"
    else:
        ensures = f"({slot_e} as int) <= ({rem_int}) * ({_sum_cap_const(kind)} as int),"
    sig_params = ",\n    ".join(f"{p}: &{s}" for p, s in ctx.table_params)
    sig_params += ",\n    " + ",\n    ".join(f"{i}: int" for i in ctx.index_params)
    sig_params += f",\n    key: {key_spec}"
    decreases = _parse_helper_decreases(spec_rs, helper)
    decreases_clause = f"\n    decreases {decreases}," if decreases else ""
    proof_body = _emit_nested_count_or_sum_body(
        ctx=ctx,
        fname=fname,
        key="key",
        val_access=val_access,
        hit=hit,
        kind=kind,
        sum_delta=sum_delta,
        level=0,
        indent="    ",
        spec_rs=spec_rs,
    )
    body = "\n".join(proof_body)
    suffix_req = ctx.suffix_start_requires()
    requires_extra = f",\n        {suffix_req}" if suffix_req else ""
    lemma_block = f"""{comment}
pub proof fn {fname}(
    {sig_params},
)
    requires
        {ctx.valid_requires},
        {ctx.index_bounds_requires()}{requires_extra},
    ensures
        {ensures}{decreases_clause}
{{
{body}
}}
"""
    # Compat alias: old agent bodies call assume_*; body is one call to the proved lemma.
    alias = f"assume_{helper}_slot{slot_i}_{kind}_leq_{suffix}"
    call_args = ", ".join(
        [p for p, _ in ctx.table_params] + list(ctx.index_params) + ["key"]
    )
    lemma_block += f"""
// Compat alias — prefer `{fname}`; body is the proved lemma (not an axiom).
pub proof fn {alias}(
    {sig_params},
)
    requires
        {ctx.valid_requires},
        {ctx.index_bounds_requires()}{requires_extra},
    ensures
        {ensures}
{{
    {fname}({call_args});
}}
"""
    return lemma_block


def _emit_slot_bound_lemma(
    *,
    ctx: FoldBoundContext,
    suffix: str,
    key_spec: str,
    slot_i: int,
    kind: str,
    val_access: str,
    spec_rs: str,
) -> str:
    helper = ctx.helper
    hit = _parse_helper_hit_branch(spec_rs, helper)
    if hit is None:
        return ""
    sum_delta = _parse_slot_sum_delta(spec_rs, helper, slot_i) if kind != "count" else None
    if kind != "count" and sum_delta is None:
        return ""
    # Inductive COUNT/SUM behind LEMMA_FOLD_SLOT_INDUCTIVE=1 until Verus closes
    # Map-fold unfold (rocketship goal). Default: honest assume_* (not fake lemma_*).
    use_inductive = _fold_slot_inductive_enabled()
    if use_inductive:
        return _emit_inductive_slot_bound_lemma(
            ctx=ctx,
            suffix=suffix,
            key_spec=key_spec,
            slot_i=slot_i,
            kind=kind,
            val_access=val_access,
            spec_rs=spec_rs,
            hit=hit,
            sum_delta=sum_delta,
        )
    return _emit_axiomatic_slot_bound_lemma(
        ctx=ctx,
        suffix=suffix,
        key_spec=key_spec,
        slot_i=slot_i,
        kind=kind,
        val_access=val_access,
        hit=hit,
    )


def emit_multi_agg_bound_lemmas(
    layout: MultiAggLayout,
    bridge: RetBridge,
    *,
    spec_rs: str,
    catalog_assumptions: CatalogAssumptions | None = None,
) -> str:
    """Auditable fold-bound assumptions: helper slot caps discharge agg_step requires."""
    ctx = _parse_fold_bound_context(spec_rs, layout.helper_name)
    if ctx is None:
        return ""

    allow_cell = _fold_bounds_allow_cell_cap(spec_rs, catalog_assumptions)
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
        if kind == "sum_cell_u64" and not allow_cell:
            continue
        val_access = _state_val_access(n_slots, i)
        block = _emit_slot_bound_lemma(
            ctx=ctx,
            suffix=suffix,
            key_spec=key_spec,
            slot_i=i,
            kind=kind,
            val_access=val_access,
            spec_rs=spec_rs,
        )
        if block:
            blocks.append(block)

    return "\n".join(blocks) if len(blocks) > 1 else ""


def _classify_scalar_map_u64(body: str) -> str | None:
    """COUNT vs SUM for Map<K, u64> scalar fold helpers."""
    if re.search(r"prev as int \+ 1", body) or re.search(r"\+ 1u64", body):
        return "count"
    if ".value[" in body or "get_value(" in body:
        return "sum_cell_u64"
    return None


def emit_scalar_fold_bound_lemmas(
    spec_rs: str,
    bridge: RetBridge,
    *,
    catalog_assumptions: CatalogAssumptions | None = None,
) -> str:
    """Fold-bound assumptions for scalar Map<K,u64> fold helpers (single-table or join agg_add)."""
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
        if kind == "sum_cell_u64" and not _fold_bounds_allow_cell_cap(
            spec_rs, catalog_assumptions
        ):
            return ""
        key_ty_s, _ = _split_map_type_args(inner)
        key_spec = key_ty_s.strip()
        suffix = bridge.agg_suffix or bridge.key.removeprefix("map_")
        rem = ctx.suffix_remaining_u64()
        hit = _parse_helper_hit_branch(spec_rs, name)
        if hit is None:
            return ""
        sum_delta = _parse_slot_sum_delta(spec_rs, name, 0) if kind != "count" else None
        if kind != "count" and sum_delta is None:
            return ""
        if kind == "count":
            fname = f"lemma_{name}_count_leq_{suffix}"
            detail = f"COUNT: ≤{rem} filtered rows in fold suffix."
            bound = rem
        else:
            cap = _sum_cap_const(kind)
            fname = f"lemma_{name}_sum_cell_u64_leq_{suffix}"
            detail = f"SUM(u64 cell): ≤{rem} cells each < {cap}."
            bound = f"{rem} * ({cap} as u64)"
        sig_params = ",\n    ".join(f"{p}: &{s}" for p, s in ctx.table_params)
        sig_params += ",\n    " + ",\n    ".join(f"{idx}: int" for idx in ctx.index_params)
        sig_params += f",\n    key: {key_spec}"
        cur_call = _helper_call(ctx)
        ensures = (
            f"{_slot_bound_expr(cur_call, 'key', '', scalar_map=True)} <= {bound},"
        )
        if not _fold_slot_inductive_enabled():
            comment = f"{_FOLD_AXIOM_HEADER}\n// {detail}"
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
        comment = f"{_FOLD_LEMMA_HEADER}\n// {detail}"
        decreases = _parse_helper_decreases(spec_rs, name)
        decreases_clause = f"\n    decreases {decreases}," if decreases else ""
        proof_body = _emit_nested_count_or_sum_body(
            ctx=ctx,
            fname=fname,
            key="key",
            val_access="",
            hit=hit,
            kind=kind,
            sum_delta=sum_delta,
            level=0,
            indent="    ",
            spec_rs=spec_rs,
        )
        body = "\n".join(proof_body)
        return f"""
// === Scalar map fold bound lemmas ({suffix}) ===
{comment}
pub proof fn {fname}(
    {sig_params},
)
    requires
        {ctx.valid_requires},
        {ctx.index_bounds_requires()},
    ensures
        {ensures}{decreases_clause}
{{
{body}
}}
"""
    return ""


def emit_multi_agg_step_trusted(
    layout: MultiAggLayout,
    bridge: RetBridge,
    *,
    spec_rs: str = "",
    catalog_assumptions: CatalogAssumptions | None = None,
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
    bound = emit_multi_agg_bound_lemmas(
        layout,
        bridge,
        spec_rs=spec_rs,
        catalog_assumptions=catalog_assumptions,
    )
    return head + bound


def multi_agg_step_trusted_rs(
    spec_rs: str,
    ret_type: str,
    *,
    catalog_assumptions: CatalogAssumptions | None = None,
) -> str:
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
        return emit_multi_agg_step_trusted(
            layout,
            bridge,
            spec_rs=spec_rs,
            catalog_assumptions=catalog_assumptions,
        )
    except (ValueError, KeyError, AttributeError, IndexError):
        return ""
