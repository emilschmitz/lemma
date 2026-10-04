"""Host TRUSTED multi-agg group step helpers (exec inner state + projected map)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from verus_transpiler.col_exprs import (
    assert_case_when_u64_then_else_u64,
    coerce_case_when_u64_args,
)
from verus_transpiler.value_bounds import (
    _int_product_fits_i128,
    _int_product_fits_u64,
    rem_cap_add_fits_lemma_name,
    rem_cap_one_add_fits_lemma_name,
    skip_u64_product_lemma_names,
)

from research_loop.table_assumptions import (
    CatalogAssumptions,
    ResolvedBounds,
    column_abs_sum_const_name,
    column_abs_sum_exclusive,
    column_assumption_exclusive,
    column_cap_const_name,
    engine_default_catalog_assumptions,
    resolve_bounds,
    table_assumptions_for,
    with_catalog_assumptions,
)
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


class SumAddFitCodegenError(RuntimeError):
    """Host fold emitter cannot prove SUM slot add fits in u64 from catalog bounds."""


_SUM_DELTA_COL_RE = re.compile(r"(\w+)\.(\w+)\[")

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
    coerced = [coerce_case_when_u64_args(line) for line in rewritten]
    for line in coerced:
        assert_case_when_u64_then_else_u64(line)
    return coerced, params


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
    m_i128 = re.search(
        rf"let s{slot_i} = \({prev_ref} as int \+ (.+)\) as i128;",
        s_line,
    )
    if m_i128:
        return m_i128.group(1).strip()
    m = re.search(
        rf"let s{slot_i} = \({prev_ref} as int \+ (.+?)\) as u64",
        s_line,
    )
    return m.group(1).strip() if m else None


@dataclass(frozen=True)
class CountSlotAddend:
    """Per-step COUNT / CASE-WHEN increment parsed from MethodSpec ``let sN =``."""

    addend: str  # spec RHS of ``prev + …`` (may include trailing `` as int``)
    ub: int  # per-row upper bound on addend (max of CASE literals, or 1)


_INT_LITERAL_RE = re.compile(r"^(\d+)(?:u64)?(?: as int)?$")


def _parse_int_literal(expr: str) -> int | None:
    m = _INT_LITERAL_RE.match(expr.strip())
    return int(m.group(1)) if m else None


def _split_comma_args(s: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(s[start:i].strip())
            start = i + 1
    parts.append(s[start:].strip())
    return parts


def _parse_case_when_u64_addend(delta: str) -> CountSlotAddend | None:
    """Parse ``case_when_u64(_, THEN, ELSE)`` when THEN/ELSE are int literals."""
    expr = delta.strip()
    inner = expr
    if inner.endswith(" as int"):
        inner = inner[: -len(" as int")].strip()
    marker = "case_when_u64("
    idx = inner.find(marker)
    if idx < 0:
        return None
    open_pos = idx + len(marker) - 1
    try:
        args_inner, _ = _extract_paren_group(inner, open_pos)
    except ValueError:
        return None
    args = _split_comma_args(args_inner)
    if len(args) != 3:
        return None
    then_lit = _parse_int_literal(args[1])
    else_lit = _parse_int_literal(args[2])
    if then_lit is None or else_lit is None:
        return None
    return CountSlotAddend(expr, max(then_lit, else_lit))


_COUNT_PLUS_ONE_LINE_RE = re.compile(
    r"as int \+ (?:1(?:u64 as int|\))|\d+u64 as int|\d+\))"
)


def _is_literal_one_delta(delta: str) -> bool:
    return _parse_int_literal(delta.strip()) == 1


def _parse_count_slot_addend(
    s_line: str, slot_i: int, *, multi_slot: bool
) -> CountSlotAddend | None:
    """Parse COUNT/CASE per-step addend from ``let s{i} = (prev[.i] as int + DELTA) as u64``."""
    delta = _sum_delta_expr(s_line, slot_i, multi_slot=multi_slot)
    if _COUNT_PLUS_ONE_LINE_RE.search(s_line):
        if delta and "case_when_u64" in delta:
            return _parse_case_when_u64_addend(delta)
        return CountSlotAddend("1", 1)
    if delta is None:
        return None
    if _is_literal_one_delta(delta):
        return CountSlotAddend("1", 1)
    if "case_when_u64" in delta:
        return _parse_case_when_u64_addend(delta)
    return None


def _parse_scalar_count_addend(body: str) -> CountSlotAddend | None:
    """Parse COUNT +1 addend from scalar Map insert RHS (no ``let sN`` binder)."""
    for line in body.split("\n"):
        st = line.strip()
        if "insert(" not in st:
            continue
        m = re.search(r"insert\(\s*[^,]+\s*,\s*(.+?)\)\s*$", st)
        if not m:
            continue
        fake = f"let s0 = {m.group(1).strip()};"
        info = _parse_count_slot_addend(fake, 0, multi_slot=False)
        if info is not None:
            return info
    return None


def _resolve_count_addend(
    *,
    spec_rs: str,
    helper: str,
    slot_i: int,
    s_line: str,
    multi_slot: bool,
    scalar_body: str | None = None,
) -> CountSlotAddend | None:
    """Resolve CountSlotAddend for a count-classified slot; None if not a COUNT step."""
    if s_line:
        info = _parse_count_slot_addend(s_line, slot_i, multi_slot=multi_slot)
        if info is not None:
            return info
    info = _parse_count_slot_addend_from_spec(spec_rs, helper, slot_i)
    if info is not None:
        return info
    if scalar_body is not None:
        return _parse_scalar_count_addend(scalar_body)
    return None


def _helper_state_multi_slot(val_ty: str) -> bool:
    return val_ty.strip() != "u64"


def _parse_count_slot_addend_from_spec(
    spec_rs: str, helper_name: str, slot_i: int
) -> CountSlotAddend | None:
    found = _find_helper(spec_rs)
    if not found or found[0] != helper_name:
        return None
    _name, _key_ty, val_ty, body = found
    multi_slot = _helper_state_multi_slot(val_ty)
    for line in body.split("\n"):
        st = line.strip()
        if st.startswith(f"let s{slot_i} ="):
            return _parse_count_slot_addend(st, slot_i, multi_slot=multi_slot)
    return None


def _count_addend_proof_expr(info: CountSlotAddend) -> str:
    if info.addend == "1":
        return "1"
    return _normalize_sum_delta_for_proof(info.addend)


def _count_addend_requires_expr(info: CountSlotAddend) -> str:
    if info.addend == "1":
        return "1"
    proof = _count_addend_proof_expr(info)
    if proof.startswith("(") and proof.endswith(")"):
        return proof[1:-1]
    return proof


def _count_bound_rhs(rem_int: str, count_addend: CountSlotAddend | None) -> str:
    if count_addend is None or count_addend.ub == 1:
        return rem_int
    return f"{rem_int} * ({count_addend.ub} as int)"


def _slot_bound_rhs(
    kind: str,
    rem_int: str,
    count_addend: CountSlotAddend | None,
    cap_const: str | None = None,
) -> str:
    if kind == "count":
        return _count_bound_rhs(rem_int, count_addend)
    const = cap_const if cap_const is not None else _sum_cap_const(kind)
    return f"{rem_int} * ({const} as int)"


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
    cell_cap: bool = True,
) -> str:
    """Fit-in-width requires: cell caps + prev-fit from old(st).inner@."""
    apply_lines = [ln.strip() for ln in layout.apply_body.split("\n") if ln.strip()]
    n_slots = len(slots)
    seen_params: set[str] = set()
    clauses: list[str] = []
    for i, slot in enumerate(slots):
        if not isinstance(slot, TypeAtom) or slot.name not in ("u64", "i128"):
            continue
        s_line = next((ln for ln in apply_lines if ln.startswith(f"let s{i} =")), "")
        kind = _classify_u64_slot(s_line, i, multi_slot=n_slots > 1)
        if kind is None:
            continue
        zero = "0i128" if slot.name == "i128" else "0u64"
        if n_slots == 1:
            prev_ref = (
                f"if old(st).inner@.contains_key({spec_key}) "
                f"{{ old(st).inner@[{spec_key}] }} else {{ {zero} }}"
            )
        else:
            prev_ref = (
                f"(if old(st).inner@.contains_key({spec_key}) "
                f"{{ old(st).inner@[{spec_key}].{i} }} else {{ {zero} }})"
            )
        if kind == "count":
            info = _parse_count_slot_addend(s_line, i, multi_slot=n_slots > 1)
            req_delta = (
                _count_addend_requires_expr(info) if info is not None else "1"
            )
            clauses.append(_u64_add_bound_requires(prev_ref, req_delta))
            continue
        delta = _sum_delta_expr(s_line, i, multi_slot=n_slots > 1)
        if delta is None:
            continue
        row_param = _row_u64_param_in_delta(delta)
        if row_param is not None and row_param not in seen_params:
            seen_params.add(row_param)
            if cell_cap:
                clauses.append(f"{row_param} < LEMMA_MAX_CELL_U64")
            elif kind == "sum_native":
                clauses.append(f"{row_param} < LEMMA_MAX_NATIVE_U32 as u64")
        exec_delta = _spec_expr_to_exec(delta)
        bound = (
            _i128_add_bound_requires
            if kind == "sum_cell_i128"
            else _u64_add_bound_requires
        )
        clauses.append(bound(prev_ref, f"({exec_delta} as int)"))
    if not clauses:
        return ""
    joined = " &&\n        ".join(clauses)
    return f"""    requires
        {joined},
"""


def _u64_add_bound_requires(prev_expr: str, delta_expr: str) -> str:
    return f"({prev_expr} as int) + {delta_expr} <= u64::MAX as int"


def _i128_add_bound_requires(prev_expr: str, delta_expr: str) -> str:
    return f"({prev_expr} as int) + {delta_expr} <= i128::MAX as int"


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
        elif isinstance(slot, TypeAtom) and slot.name in ("u64", "i128"):
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
                    if slot.name == "i128":
                        lines.append(
                            f"let v{i} = {prev_ref}.checked_add({exec_delta} as i128)"
                            '.expect("Trusted overflow: ValidCols/requires violated");'
                        )
                    else:
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
    if _COUNT_PLUS_ONE_LINE_RE.search(s_line):
        delta = _sum_delta_expr(s_line, slot_i, multi_slot=multi_slot)
        if delta and "case_when_u64" in delta:
            return "count" if _parse_case_when_u64_addend(delta) else None
        return "count"
    if re.search(rf"let s{slot_i} = .+\) as i128;", s_line):
        return "sum_cell_i128"
    delta = _sum_delta_expr(s_line, slot_i, multi_slot=multi_slot)
    if delta is None:
        return None
    if "case_when_u64" in delta:
        return "count" if _parse_case_when_u64_addend(delta) else None
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

    def suffix_remaining_int_expr(self) -> str:
        """Same geometry as ``suffix_remaining_u64`` without the ``as u64`` cast."""
        u = self.suffix_remaining_u64()
        if u.endswith(" as u64"):
            return u[: -len(" as u64")]
        return u


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


def _slot_zero_lit(kind: str) -> str:
    return "0i128" if kind == "sum_cell_i128" else "0u64"


def _slot_bound_expr(
    helper_call: str,
    key: str,
    val_access: str,
    *,
    scalar_map: bool,
    zero: str = "0u64",
) -> str:
    if scalar_map:
        inner = f"{helper_call}[{key}]"
    else:
        inner = f"{helper_call}[{key}]{val_access}"
    return f"(if {helper_call}.contains_key({key}) {{ {inner} }} else {{ {zero} }})"


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


def _parse_sum_delta_table_column(sum_delta: str) -> tuple[str, str] | None:
    m = _SUM_DELTA_COL_RE.search(sum_delta)
    if m is None:
        return None
    return m.group(1), m.group(2)


def _column_cap_from_catalog(
    catalog: CatalogAssumptions | None,
    table: str,
    column: str,
) -> int | None:
    if catalog is None:
        return None
    ta = table_assumptions_for(catalog, table)
    return column_assumption_exclusive(column, ta)


def _column_abs_sum_from_catalog(
    catalog: CatalogAssumptions | None,
    table: str,
    column: str,
) -> int | None:
    if catalog is None:
        return None
    ta = table_assumptions_for(catalog, table)
    return column_abs_sum_exclusive(column, ta)


def _table_name_from_fold_param(param: str, struct: str) -> str:
    if struct.startswith("Cols_"):
        return struct[len("Cols_") :]
    return param


def _filter_equates_column(filter_expr: str, table: str, column: str) -> bool:
    """True when the fold filter equates ``table.column`` to the same column elsewhere."""
    col = re.escape(column)
    tbl = re.escape(table)
    pat = re.compile(
        rf"(?:{tbl}\.{col}\[[^\]]*\]@\s*==\s*\w+\.{col}\[[^\]]*\]@"
        rf"|\w+\.{col}\[[^\]]*\]@\s*==\s*{tbl}\.{col}\[[^\]]*\]@)"
    )
    return pat.search(filter_expr) is not None


def _unique_keys_for(table: TableAssumptions) -> tuple[tuple[str, ...], ...]:
    keys = list(table.unique_keys)
    if table.one_row_per_adsh and ("adsh",) not in keys:
        keys.append(("adsh",))
    return tuple(keys)


def _abs_sum_covers_fold(
    ctx: FoldBoundContext,
    source_table: str,
    catalog: CatalogAssumptions | None,
    join_filter: str,
) -> bool:
    """True when the fold adds each source cell at most once.

    A lone scan does. A join does only when every other table is joined on a
    column group DuckDB showed is unique (``sub.adsh``, or ``tag`` plus
    ``version``). A join that repeats a cell does not get the absolute total.
    """
    if catalog is None:
        return False
    for param, struct in ctx.table_params:
        name = _table_name_from_fold_param(param, struct)
        if name == source_table:
            continue
        ta = table_assumptions_for(catalog, name)
        if ta is None:
            return False
        keys = _unique_keys_for(ta)
        if not keys:
            return False
        if not any(
            all(_filter_equates_column(join_filter, name, column) for column in key)
            for key in keys
        ):
            return False
    return True


def _table_joined_on_unique_key(
    catalog: CatalogAssumptions | None,
    table_name: str,
    join_filter: str,
) -> bool:
    """True when the fold equates every column of one unique key of this table."""
    if catalog is None:
        return False
    assumptions = table_assumptions_for(catalog, table_name)
    if assumptions is None:
        return False
    keys = _unique_keys_for(assumptions)
    if not keys:
        return False
    return any(
        all(_filter_equates_column(join_filter, table_name, column) for column in key)
        for key in keys
    )


def _unique_key_sum_bound(
    ctx: FoldBoundContext,
    catalog: CatalogAssumptions | None,
    sum_delta: str,
    join_filter: str,
) -> tuple[int, str] | None:
    """Product of the tables that can repeat a cell, when that product fits.

    Returns ``(product, "u64"|"i128")`` only when the full nested-loop product
    does not fit in i128 and at least one other table is joined on a unique key.
    The cartesian remainder is still the loop bound; this product is the hit bound.
    """
    ref = _parse_sum_delta_table_column(sum_delta)
    if ref is None or catalog is None:
        return None
    table, column = ref
    col_cap = _column_cap_from_catalog(catalog, table, column)
    if col_cap is None:
        return None
    depth = len(ctx.table_params)
    bounds = _resolve_bounds_for_catalog(catalog)
    if _catalog_sum_product_fits(bounds, depth, col_cap):
        return None
    if _catalog_sum_product_fits_i128(bounds, depth, col_cap):
        return None
    row_cap = _row_cap_for_depth(bounds, depth)
    kept = 0
    for param, struct in ctx.table_params:
        name = _table_name_from_fold_param(param, struct)
        if name != table and _table_joined_on_unique_key(catalog, name, join_filter):
            continue
        kept += 1
    if kept < 1 or kept >= depth:
        return None
    factors = [row_cap] * kept
    factors.append(col_cap)
    product = 1
    for factor in factors:
        product *= factor
    if _int_product_fits_u64(*factors):
        return product, "u64"
    if _int_product_fits_i128(*factors):
        return product, "i128"
    return None


def _unique_kept_row_product(
    ctx: FoldBoundContext,
    catalog: CatalogAssumptions | None,
    join_filter: str,
) -> int | None:
    """Row-cap product of the tables that can repeat, when a unique key drops one.

    ``None`` when every table can repeat or the catalog has no unique key on
    this join. The caller still has to check that this product fits the slot.
    """
    if catalog is None or not join_filter:
        return None
    depth = len(ctx.table_params)
    bounds = _resolve_bounds_for_catalog(catalog)
    row_cap = _row_cap_for_depth(bounds, depth)
    kept = 0
    for param, struct in ctx.table_params:
        name = _table_name_from_fold_param(param, struct)
        if _table_joined_on_unique_key(catalog, name, join_filter):
            continue
        kept += 1
    if kept < 1 or kept >= depth:
        return None
    product = 1
    for _ in range(kept):
        product *= row_cap
    return product


def _sum_product_unprovable(
    ctx: FoldBoundContext,
    catalog: CatalogAssumptions | None,
    sum_delta: str,
    join_filter: str,
) -> bool:
    """True when no u64, i128, unique-key, or absolute-sum bound covers this add."""
    ref = _parse_sum_delta_table_column(sum_delta)
    if ref is None or catalog is None:
        return False
    table, column = ref
    col_cap = _column_cap_from_catalog(catalog, table, column)
    if col_cap is None:
        return False
    depth = len(ctx.table_params)
    bounds = _resolve_bounds_for_catalog(catalog)
    if _catalog_sum_product_fits(bounds, depth, col_cap):
        return False
    if _catalog_sum_product_fits_i128(bounds, depth, col_cap):
        return False
    if _unique_key_sum_bound(ctx, catalog, sum_delta, join_filter) is not None:
        return False
    abs_sum = _column_abs_sum_from_catalog(catalog, table, column)
    if (
        abs_sum is not None
        and abs_sum < 2**64
        and _abs_sum_covers_fold(ctx, table, catalog, join_filter)
    ):
        return False
    return True


def _row_cap_for_depth(bounds: ResolvedBounds, depth: int) -> int:
    if depth >= 4:
        return bounds.max_rows_4
    if depth >= 3:
        return bounds.max_rows_cube
    return bounds.max_rows


def _resolve_bounds_for_catalog(
    catalog: CatalogAssumptions | None,
) -> ResolvedBounds:
    return resolve_bounds(
        with_catalog_assumptions(
            catalog,
            defaults=engine_default_catalog_assumptions(),
        )
    )


def _resolve_sum_cap_const(
    kind: str,
    sum_delta: str | None,
    catalog: CatalogAssumptions | None,
) -> str:
    if sum_delta and catalog:
        ref = _parse_sum_delta_table_column(sum_delta)
        if ref is not None:
            table, column = ref
            cap = _column_cap_from_catalog(catalog, table, column)
            if cap is not None:
                bounds = _resolve_bounds_for_catalog(catalog)
                if kind == "sum_native":
                    if cap <= bounds.max_native_u32:
                        return column_cap_const_name(table, column)
                elif cap < 2**64:
                    return column_cap_const_name(table, column)
    return _sum_cap_const(kind)


def _catalog_sum_product_fits(
    bounds: ResolvedBounds,
    depth: int,
    col_cap: int,
) -> bool:
    row_cap = _row_cap_for_depth(bounds, depth)
    return _int_product_fits_u64(*([row_cap] * depth), col_cap)


def _catalog_sum_product_fits_i128(
    bounds: ResolvedBounds,
    depth: int,
    col_cap: int,
) -> bool:
    row_cap = _row_cap_for_depth(bounds, depth)
    return _int_product_fits_i128(*([row_cap] * depth), col_cap)


def _slot_zero_from_default(default_state: str, val_access: str) -> str:
    if not val_access.startswith("."):
        return "0u64"
    idx = int(val_access[1:])
    frag = default_state.strip()
    if frag.startswith("(") and frag.endswith(")"):
        parts = [p.strip() for p in frag[1:-1].split(",")]
        if idx < len(parts):
            return parts[idx]
    return "0u64"


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
    while rest:
        # Keep let tN (MIN/MAX temps). Dropping them was r24 E0425: ghost sN
        # still referenced tN with no binder in that scope.
        m = re.match(r"let ([st]\d+) = (.+?);", rest, re.DOTALL)
        if m:
            slot_lets.append((m.group(1), m.group(2).strip()))
            rest = rest[m.end() :].lstrip()
            continue
        break
    _assert_fold_slot_lets_self_bound(slot_lets)
    insert_m = re.match(r"tail\.insert\(row_key,\s*(.+?)\)\s*$", rest.strip(), re.DOTALL)
    if not insert_m:
        return None
    return _FoldHitSlotUpdates(
        prev_default=prev_default.strip(),
        slot_lets=tuple(slot_lets),
        insert_value=_strip_rust_line_comment(insert_m.group(1)),
    )


_TN_TOKEN = re.compile(r"\bt(\d+)\b")


def _assert_fold_slot_lets_self_bound(slot_lets: list[tuple[str, str]]) -> None:
    """Loud fail if a reconstructed ghost let uses tN that was never bound."""
    bound: set[str] = set()
    for name, rhs in slot_lets:
        for m in _TN_TOKEN.finditer(rhs):
            tok = f"t{m.group(1)}"
            if tok not in bound:
                raise AssertionError(
                    f"host fold reconstruct: {name} rhs uses unbound {tok}; "
                    f"do not drop let tN when parsing fold_step"
                )
        bound.add(name)


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
        sub_rhs = coerce_case_when_u64_args(_subst_prev_identifier(rhs, prev_var))
        lines.append(f"{indent}let ghost {sname} = {sub_rhs};")
    insert_val = _subst_prev_identifier(updates.insert_value, prev_var)
    lines.append(f"{indent}let ghost {result_var} = {insert_val};")
    return lines


def _emit_count_add_one_fit_steps(
    ctx: FoldBoundContext,
    indent: str,
    *,
    rem_tail_int: str,
    skip: frozenset[str] = frozenset(),
    row_product: int | None = None,
) -> list[str]:
    """Prove ``prev_slot as int + 1`` fits in u64 so MethodSpec COUNT cast is math +1."""
    depth = len(ctx.table_params)
    lines: list[str] = []
    # Cartesian remainder does not fit in u64, but a unique-key join drops
    # those tables from the hit count. The assume is the same fact as the
    # SUM unique-key cap: each dropped table matches at most one row.
    if (
        row_product is not None
        and _int_product_fits_u64(row_product)
        and depth >= 3
    ):
        lines.append(
            f"{indent}assert({row_product} <= u64::MAX as int) by (compute_only);"
        )
        lines.append(
            f"{indent}// A unique-key join matches at most one row, so this"
        )
        lines.append(
            f"{indent}// count is bounded by the remaining tables, not the cartesian product."
        )
        lines.append(
            f"{indent}assume((prev_slot as int) + 1 < {row_product});"
        )
        lines.append(
            f"{indent}assert((prev_slot as int) + 1 <= u64::MAX as int);"
        )
        return lines
    ns = [p for p, _ in ctx.table_params]
    idxs = list(ctx.index_params)
    one_add_lemma: str | None = None
    if depth == 1:
        lines.append(f"{indent}assert(0 <= {rem_tail_int});")
        lines.append(f"{indent}assert({rem_tail_int} <= {ns[0]}.n as int);")
        lines.append(f"{indent}assert({ns[0]}.n <= LEMMA_MAX_ROWS);")
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
        lines.append(
            f"{indent}assert(rem_tail_u64 <= LEMMA_MAX_ROWS as u64);"
        )
        one_add_lemma = rem_cap_one_add_fits_lemma_name(depth)
    elif depth == 2:
        lines.append(
            f"{indent}lemma_join_nested_rem_leq_rows_sq("
            f"{ns[0]}.n, {ns[1]}.n, {idxs[0]}, {idxs[1]} + 1);"
        )
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
        lines.append(
            f"{indent}assert(rem_tail_u64 <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64));"
        )
        one_add_lemma = rem_cap_one_add_fits_lemma_name(depth)
    elif depth == 3:
        lines.append(
            f"{indent}lemma_join_nested_rem_leq_rows_cube("
            f"{ns[0]}.n, {ns[1]}.n, {ns[2]}.n, {idxs[0]}, {idxs[1]}, {idxs[2]} + 1);"
        )
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
        one_add_lemma = rem_cap_one_add_fits_lemma_name(depth)
    elif depth == 4:
        lines.append(
            f"{indent}lemma_join_nested_rem_leq_rows_4("
            f"{ns[0]}.n, {ns[1]}.n, {ns[2]}.n, {ns[3]}.n, "
            f"{idxs[0]}, {idxs[1]}, {idxs[2]}, {idxs[3]} + 1);"
        )
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
        one_add_lemma = rem_cap_one_add_fits_lemma_name(depth)
    else:
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
        lines.append(
            f"{indent}assert((rem_tail_u64 as int) + 1 <= u64::MAX as int);"
        )
    if one_add_lemma is not None and one_add_lemma not in skip:
        lines.append(f"{indent}{one_add_lemma}(rem_tail_u64);")
    lines.append(f"{indent}assert(prev_slot <= rem_tail_u64);")
    if one_add_lemma is None or one_add_lemma not in skip:
        lines.append(f"{indent}lemma_u64_add_one_prev_le(prev_slot, rem_tail_u64);")
    lines.append(f"{indent}assert((prev_slot as int) + 1 <= u64::MAX as int);")
    return lines


def _emit_count_add_fit_steps(
    ctx: FoldBoundContext,
    indent: str,
    *,
    rem_tail_int: str,
    count_addend: CountSlotAddend,
    skip: frozenset[str] = frozenset(),
    row_product: int | None = None,
) -> list[str]:
    """Prove ``prev_slot + count addend`` fits in u64 under rem·ub (COUNT / CASE fold step)."""
    if count_addend.ub == 1:
        return _emit_count_add_one_fit_steps(
            ctx, indent, rem_tail_int=rem_tail_int, skip=skip, row_product=row_product,
        )
    ub = count_addend.ub
    addend_proof = _count_addend_proof_expr(count_addend)
    depth = len(ctx.table_params)
    lines: list[str] = []
    ns = [p for p, _ in ctx.table_params]
    idxs = list(ctx.index_params)
    if depth == 1:
        lines.append(f"{indent}assert(0 <= {rem_tail_int});")
        lines.append(f"{indent}assert({rem_tail_int} <= {ns[0]}.n as int);")
        lines.append(f"{indent}assert({ns[0]}.n <= LEMMA_MAX_ROWS);")
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
    elif depth == 2:
        lines.append(
            f"{indent}lemma_join_nested_rem_leq_rows_sq("
            f"{ns[0]}.n, {ns[1]}.n, {idxs[0]}, {idxs[1]} + 1);"
        )
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
    elif depth == 3:
        lines.append(
            f"{indent}lemma_join_nested_rem_leq_rows_cube("
            f"{ns[0]}.n, {ns[1]}.n, {ns[2]}.n, {idxs[0]}, {idxs[1]}, {idxs[2]} + 1);"
        )
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
    elif depth == 4:
        lines.append(
            f"{indent}lemma_join_nested_rem_leq_rows_4("
            f"{ns[0]}.n, {ns[1]}.n, {ns[2]}.n, {ns[3]}.n, "
            f"{idxs[0]}, {idxs[1]}, {idxs[2]}, {idxs[3]} + 1);"
        )
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
    else:
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
    lines.append(f"{indent}assert(prev_slot as int <= {rem_tail_int} * ({ub} as int));")
    lines.append(f"{indent}assert(({addend_proof}) <= ({ub} as int));")
    lines.append(
        f"{indent}assert(({rem_tail_int} as int + 1) * ({ub} as int) <= u64::MAX as int) "
        f"by (nonlinear_arith);"
    )
    lines.append(
        f"{indent}assert((prev_slot as int) + ({addend_proof}) <= u64::MAX as int);"
    )
    return lines


def _emit_sum_add_fit_steps(
    ctx: FoldBoundContext,
    indent: str,
    *,
    kind: str,
    rem_tail_int: str,
    sum_delta: str,
    skip: frozenset[str] = frozenset(),
    catalog_assumptions: CatalogAssumptions | None = None,
    join_filter: str = "",
) -> list[str]:
    """Prove ``prev_slot + sum_delta`` fits in u64/i128 under rem·cap (SUM fold step)."""
    depth = len(ctx.table_params)
    lines: list[str] = []
    if kind != "sum_native":
        ref = _parse_sum_delta_table_column(sum_delta)
        abs_sum_covers = False
        if ref is not None:
            source_table, _column = ref
            abs_sum = _column_abs_sum_from_catalog(
                catalog_assumptions, source_table, _column
            )
            abs_sum_covers = (
                abs_sum is not None
                and abs_sum < 2**64
                and _abs_sum_covers_fold(
                    ctx, source_table, catalog_assumptions, join_filter
                )
            )
        bound = None if abs_sum_covers else _unique_key_sum_bound(
            ctx, catalog_assumptions, sum_delta, join_filter
        )
        if bound is not None:
            product, width = bound
            if kind == "sum_cell_i128":
                width = "i128"
            if kind == "sum_cell_i128" or width == "u64":
                max_bound = "u64::MAX" if width == "u64" else "i128::MAX"
                lines.append(
                    f"{indent}assert({product} <= {max_bound} as int) by (compute_only);"
                )
                lines.append(
                    f"{indent}// A unique-key join matches at most one row, so this"
                )
                lines.append(
                    f"{indent}// add is bounded by the remaining tables, not the cartesian product."
                )
                lines.append(
                    f"{indent}assume((prev_slot as int) + ({sum_delta}) < {product});"
                )
                lines.append(
                    f"{indent}assert((prev_slot as int) + ({sum_delta}) <= {max_bound} as int);"
                )
                return lines
    sum_width = "i128" if kind == "sum_cell_i128" else "u64"
    if kind == "sum_cell_i128":
        kind = "sum_cell_u64"
    ns = [p for p, _ in ctx.table_params]
    idxs = list(ctx.index_params)
    cap_kind = "native" if kind == "sum_native" else "cell_u64"
    rem_cap_lemma = rem_cap_add_fits_lemma_name(depth, cap=cap_kind)
    emit_rem_cap = rem_cap_lemma not in skip
    cap_const = _resolve_sum_cap_const(kind, sum_delta, catalog_assumptions)
    if depth == 1:
        lines.append(f"{indent}assert(0 <= {rem_tail_int});")
        lines.append(f"{indent}assert({rem_tail_int} <= {ns[0]}.n as int);")
        lines.append(f"{indent}assert({ns[0]}.n <= LEMMA_MAX_ROWS);")
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
        lines.append(
            f"{indent}assert(rem_tail_u64 <= LEMMA_MAX_ROWS as u64);"
        )
    elif depth == 2:
        lines.append(
            f"{indent}lemma_join_nested_rem_leq_rows_sq("
            f"{ns[0]}.n, {ns[1]}.n, {idxs[0]}, {idxs[1]} + 1);"
        )
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
    elif depth == 3:
        lines.append(
            f"{indent}lemma_join_nested_rem_leq_rows_cube("
            f"{ns[0]}.n, {ns[1]}.n, {ns[2]}.n, {idxs[0]}, {idxs[1]}, {idxs[2]} + 1);"
        )
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
    elif depth == 4:
        lines.append(
            f"{indent}lemma_join_nested_rem_leq_rows_4("
            f"{ns[0]}.n, {ns[1]}.n, {ns[2]}.n, {ns[3]}.n, "
            f"{idxs[0]}, {idxs[1]}, {idxs[2]}, {idxs[3]} + 1);"
        )
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
    else:
        lines.append(f"{indent}let ghost rem_tail_u64 = {rem_tail_int} as u64;")
    if emit_rem_cap:
        lines.append(f"{indent}{rem_cap_lemma}(rem_tail_u64);")
        if kind == "sum_native":
            lines.append(
                f"{indent}assert(prev_slot <= rem_tail_u64 * ({cap_const} as u64));"
            )
            lines.append(
                f"{indent}lemma_u64_add_native_prev_le(prev_slot, ({sum_delta}) as u64, rem_tail_u64);"
            )
        else:
            lines.append(
                f"{indent}assert(prev_slot <= rem_tail_u64 * ({cap_const} as u64));"
            )
            lines.append(
                f"{indent}lemma_u64_add_cell_u64_prev_le(prev_slot, ({sum_delta}) as u64, rem_tail_u64);"
            )
        lines.append(
            f"{indent}assert((prev_slot as int) + ({sum_delta}) <= u64::MAX as int);"
        )
        return lines

    ref = _parse_sum_delta_table_column(sum_delta)
    col_cap: int | None = None
    abs_sum: int | None = None
    if ref is not None:
        table, column = ref
        col_cap = _column_cap_from_catalog(catalog_assumptions, table, column)
        abs_sum = _column_abs_sum_from_catalog(catalog_assumptions, table, column)
    bounds = _resolve_bounds_for_catalog(catalog_assumptions)
    fits_u64 = col_cap is not None and _catalog_sum_product_fits(bounds, depth, col_cap)
    fits_i128 = col_cap is not None and _catalog_sum_product_fits_i128(
        bounds, depth, col_cap
    )
    if sum_width == "i128" or (not fits_u64 and fits_i128):
        sum_width = "i128"
    elif fits_u64:
        sum_width = "u64"

    if col_cap is None or (not fits_u64 and not fits_i128):
        if (
            ref is not None
            and abs_sum is not None
            and abs_sum < 2**64
            and _abs_sum_covers_fold(
                ctx, table, catalog_assumptions, join_filter
            )
        ):
            table, column = ref
            abs_const = column_abs_sum_const_name(table, column)
            lines.append(
                f"{indent}assert({abs_const} as int <= u64::MAX as int) by (compute_only);"
            )
            # Catalog measurement of sum(abs(column)). Sound when each cell is
            # added at most once (num joined to sub: one sub row per adsh).
            lines.append(
                f"{indent}assume((prev_slot as int) + ({sum_delta}) < {abs_const} as int);"
            )
            lines.append(
                f"{indent}assert((prev_slot as int) + ({sum_delta}) <= u64::MAX as int);"
            )
            return lines
        raise SumAddFitCodegenError(
            "cannot prove SUM add fits in u64: missing catalog column cap or "
            f"rows^{depth} * cap overflows u64 (sum_delta={sum_delta!r})"
        )

    max_bound = "u64::MAX" if sum_width == "u64" else "i128::MAX"
    row_cap = _row_cap_for_depth(bounds, depth)
    row_factors = " * ".join(f"({row_cap} as int)" for _ in range(depth))
    if sum_width == "u64":
        lines.append(
            f"{indent}assert(prev_slot <= rem_tail_u64 * ({cap_const} as u64));"
        )
    else:
        lines.append(
            f"{indent}assert(prev_slot as int <= rem_tail_int * ({cap_const} as int));"
        )
    lines.append(
        f"{indent}assert(({row_factors}) * ({col_cap} as int) <= {max_bound} as int) by (compute_only);"
    )
    lines.append(
        f"{indent}assert(({rem_tail_int} + 1) * ({col_cap} as int) <= {max_bound} as int) by (nonlinear_arith)"
        f"\n{indent}    requires"
        f"\n{indent}        {rem_tail_int} <= ({row_factors}),"
        f"\n{indent}        ({row_factors}) * ({col_cap} as int) <= {max_bound} as int,"
        f"\n{indent}        {{}};"
    )
    # Stay in int. A u64 multiply in the requires is wrapping, so nonlinear_arith
    # will not conclude prev_slot + cell <= max from it.
    lines.append(
        f"{indent}assert(({cap_const} as int) == ({col_cap} as int)) by (compute);"
    )
    lines.append(f"{indent}assert(0 <= ({sum_delta}));")
    lines.append(
        f"{indent}assert((prev_slot as int) + ({sum_delta})"
        f" <= ({rem_tail_int} + 1) * ({cap_const} as int)) by (nonlinear_arith)"
        f"\n{indent}    requires"
        f"\n{indent}        prev_slot as int <= {rem_tail_int} * ({cap_const} as int),"
        f"\n{indent}        ({sum_delta}) < ({cap_const} as int),"
        f"\n{indent}        0 <= ({sum_delta}),"
        f"\n{indent}        {{}};"
    )
    lines.append(
        f"{indent}assert((prev_slot as int) + ({sum_delta}) <= {max_bound} as int) by (nonlinear_arith)"
        f"\n{indent}    requires"
        f"\n{indent}        (prev_slot as int) + ({sum_delta}) <= ({rem_tail_int} + 1) * ({cap_const} as int),"
        f"\n{indent}        ({rem_tail_int} + 1) * ({col_cap} as int) <= {max_bound} as int,"
        f"\n{indent}        ({cap_const} as int) == ({col_cap} as int),"
        f"\n{indent}        {{}};"
    )
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
    count_addend: CountSlotAddend | None = None,
    indent: str,
    cur_call: str,
    rem_here_int: str,
    rem_tail_int: str,
    tail_call: str,
    tail_rec_args: str,
    spec_rs: str,
    skip: frozenset[str] = frozenset(),
    catalog_assumptions: CatalogAssumptions | None = None,
) -> list[str]:
    cap = _resolve_sum_cap_const(kind, sum_delta, catalog_assumptions)
    helper = ctx.helper
    fold_step = _parse_helper_fold_step(spec_rs, helper)
    slot_updates: _FoldHitSlotUpdates | None = None
    if fold_step is not None:
        fold_step = _sanitize_fold_step_for_proof(fold_step)
        slot_updates = _parse_fold_hit_slot_updates(fold_step)
    lines: list[str] = []
    if kind == "count" and count_addend is None:
        count_addend = CountSlotAddend("1", 1)
    addend_proof = "1"
    count_ub = 1
    if kind == "count":
        addend_proof = _count_addend_proof_expr(count_addend)
        count_ub = count_addend.ub
    if hit.scalar_map:
        prev_slot = f"if tail.contains_key({key}) {{ tail[{key}] }} else {{ 0u64 }}"
        slot_expr = lambda call: f"{call}[{key}]"
    elif val_access:
        slot_zero = _slot_zero_from_default(hit.default_state, val_access)
        prev_slot = (
            f"if tail.contains_key({key}) {{ tail[{key}]{val_access} }} else {{ {slot_zero} }}"
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
    # One inner step: rem_here = rem_tail + 1 (proved lemma when rem_join_sq/cube).
    if len(ctx.table_params) == 2:
        n0, _ = ctx.table_params[0]
        n1, _ = ctx.table_params[1]
        i0 = ctx.index_params[0]
        i1 = ctx.index_params[1]
        lines.append(
            f"{indent}lemma_rem_join_sq_inner_step({n0}.n, {n1}.n, {i0}, {i1});"
        )
    elif len(ctx.table_params) == 3:
        n0, _ = ctx.table_params[0]
        n1, _ = ctx.table_params[1]
        n2, _ = ctx.table_params[2]
        i0, i1, i2 = ctx.index_params
        lines.append(
            f"{indent}lemma_rem_join_cube_inner_step("
            f"{n0}.n, {n1}.n, {n2}.n, {i0}, {i1}, {i2});"
        )
    elif len(ctx.table_params) == 4:
        n0, _ = ctx.table_params[0]
        n1, _ = ctx.table_params[1]
        n2, _ = ctx.table_params[2]
        n3, _ = ctx.table_params[3]
        i0, i1, i2, i3 = ctx.index_params
        lines.append(
            f"{indent}lemma_rem_join_4_inner_step("
            f"{n0}.n, {n1}.n, {n2}.n, {n3}.n, {i0}, {i1}, {i2}, {i3});"
        )
    elif len(ctx.table_params) == 1:
        # rem = n - i; rem_tail = n - (i+1); definitional.
        lines.append(f"{indent}assert(rem_here_int == rem_tail_int + 1);")
    else:
        lines.append(
            f"{indent}assert(rem_here_int == rem_tail_int + 1) by (nonlinear_arith);"
        )
    if kind == "count":
        if count_ub == 1:
            lines.append(f"{indent}assert(prev_slot as int <= rem_tail_int);")
            lines.append(f"{indent}assert(prev_slot as int <= rem_here_int - 1);")
        else:
            lines.append(
                f"{indent}assert(prev_slot as int <= rem_tail_int * ({count_ub} as int));"
            )
            lines.append(
                f"{indent}assert(prev_slot as int <= (rem_here_int - 1) * ({count_ub} as int));"
            )
        if count_addend is not None and count_addend.addend != "1":
            lines.append(f"{indent}assert(({addend_proof}) <= ({count_ub} as int));")
        lines.extend(
            _emit_count_add_fit_steps(
                ctx,
                indent,
                rem_tail_int=rem_tail_int,
                count_addend=count_addend,
                skip=skip,
                row_product=_unique_kept_row_product(
                    ctx, catalog_assumptions, hit.filter_expr
                ),
            )
        )
    else:
        assert sum_delta is not None
        ref = _parse_sum_delta_table_column(sum_delta)
        abs_sum_only = False
        if ref is not None and catalog_assumptions is not None:
            table_name, column_name = ref
            measured = _column_cap_from_catalog(
                catalog_assumptions, table_name, column_name
            )
            abs_sum = _column_abs_sum_from_catalog(
                catalog_assumptions, table_name, column_name
            )
            depth = len(ctx.table_params)
            bounds = _resolve_bounds_for_catalog(catalog_assumptions)
            product_fits = measured is not None and _catalog_sum_product_fits(
                bounds, depth, measured
            )
            product_fits_i128 = measured is not None and _catalog_sum_product_fits_i128(
                bounds, depth, measured
            )
            abs_sum_only = (
                not product_fits
                and not product_fits_i128
                and abs_sum is not None
                and abs_sum < 2**64
                and _abs_sum_covers_fold(
                    ctx, table_name, catalog_assumptions, hit.filter_expr
                )
            )
        if not abs_sum_only:
            lines.append(
                f"{indent}assert(prev_slot as int <= rem_tail_int * ({cap} as int));"
            )
            lines.append(
                f"{indent}assert(prev_slot as int <= (rem_here_int - 1) * ({cap} as int));"
            )
            lines.append(f"{indent}assert({sum_delta} < ({cap} as int));")
        lines.extend(
            _emit_sum_add_fit_steps(
                ctx,
                indent,
                kind=kind,
                rem_tail_int=rem_tail_int,
                sum_delta=sum_delta,
                skip=skip,
                catalog_assumptions=catalog_assumptions,
                join_filter=hit.filter_expr,
            )
        )

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
            # MethodSpec COUNT step: (prev.slot as int + DELTA) as u64
            if val_access:
                slot_binder = (
                    f"s{val_access.lstrip('.')}"
                    if val_access.startswith(".") and val_access[1:].isdigit()
                    else None
                )
                if slot_binder:
                    lines.append(
                        f"{hit_indent}assert({slot_binder} as int == prev_full{val_access} as int + ({addend_proof}));"
                    )
            else:
                lines.append(
                    f"{hit_indent}assert(s0 as int == prev_full.0 as int + ({addend_proof}));"
                )
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
                    f"{hit_indent}assert(inserted_val{val_access} as int == prev_slot as int + ({addend_proof}));"
                )
            else:
                lines.append(f"{hit_indent}assert(next_map[{key}] == inserted_val);")
                lines.append(
                    f"{hit_indent}assert(inserted_val.0 as int == prev_slot as int + ({addend_proof}));"
                )
        else:
            slot_field = val_access if val_access else ".0"
            slot_binder = (
                f"s{slot_field.lstrip('.')}"
                if slot_field.startswith(".") and slot_field[1:].isdigit()
                else "s0"
            )
            lines.append(
                f"{indent}        let ghost prev_full = if tail.contains_key({key}) {{ tail[{key}] }} else {{ {hit.default_state} }};"
            )
            lines.append(
                f"{indent}        assert(prev_full{slot_field} == prev_slot);"
            )
            lines.append(
                f"{indent}        let ghost {slot_binder} = (prev_full{slot_field} as int + ({addend_proof})) as u64;"
            )
            lines.append(
                f"{indent}        assert({slot_binder} as int == prev_full{slot_field} as int + ({addend_proof}));"
            )
            if val_access:
                lines.append(
                    f"{indent}        // fold-step parse miss: rebuild tuple with only slot{slot_field} COUNT step"
                )
                lines.append(
                    f"{indent}        let ghost inserted_val = prev_full;"
                )
                lines.append(
                    f"{indent}        assert(next_map == tail.insert({key}, inserted_val));"
                )
                lines.append(
                    f"{indent}        lemma_map_insert_get(tail, {key}, inserted_val);"
                )
                lines.append(
                    f"{indent}        assert(next_map[{key}]{val_access} == {slot_binder});"
                )
                lines.append(
                    f"{indent}        assert({slot_binder} as int == prev_slot as int + ({addend_proof}));"
                )
            else:
                lines.append(
                    f"{indent}        let ghost inserted_val = ({slot_binder}, prev_full.1);"
                )
                lines.append(
                    f"{indent}        assert(next_map == tail.insert({key}, inserted_val));"
                )
                lines.append(
                    f"{indent}        lemma_map_insert_get(tail, {key}, inserted_val);"
                )
                lines.append(f"{indent}        assert(next_map[{key}].0 == {slot_binder});")
                lines.append(
                    f"{indent}        assert({slot_binder} as int == prev_slot as int + ({addend_proof}));"
                )
        if count_ub == 1:
            lines.append(
                f"{indent}        assert(prev_slot as int + 1 <= rem_here_int);"
            )
        else:
            lines.append(
                f"{indent}        assert(prev_slot as int + ({addend_proof}) <= rem_here_int * ({count_ub} as int));"
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
        count_rem_bound = _count_bound_rhs("rem_here_int", count_addend)
        lines.append(
            f"{indent}assert({_slot_bound_expr('next_map', key, val_access, scalar_map=hit.scalar_map, zero=_slot_zero_lit(kind))} as int <= {count_rem_bound});"
        )
        lines.append(
            f"{indent}assert({_slot_bound_expr(cur_call, key, val_access, scalar_map=hit.scalar_map, zero=_slot_zero_lit(kind))} as int <= {count_rem_bound});"
        )
    else:
        assert sum_delta is not None
        # Bind one-step map (same structure as COUNT) so insert/index facts are local.
        lines.append(f"{indent}let ghost next_map = {{")
        lines.append(f"{indent}    let tail = {tail_call};")
        if fold_step is not None:
            for step_line in fold_step.splitlines():
                lines.append(f"{indent}    {step_line}")
        else:
            lines.append(f"{indent}    if ({hit.filter_expr}) {{")
            lines.append(f"{indent}        let row_key = {hit.key_expr};")
            lines.append(
                f"{indent}        let prev = if tail.contains_key(row_key) {{ tail[row_key] }} else {{ {hit.default_state} }};"
            )
            lines.append(f"{indent}        // fold_step parse failed; stub keeps prev")
            lines.append(f"{indent}        tail.insert(row_key, prev)")
            lines.append(f"{indent}    }} else {{")
            lines.append(f"{indent}        tail")
            lines.append(f"{indent}    }}")
        lines.append(f"{indent}}};")
        lines.append(f"{indent}assert({cur_call} == next_map);")
        lines.append(f"{indent}if ({hit.filter_expr}) {{")
        lines.append(f"{indent}    let ghost row_key = {hit.key_expr};")
        lines.append(f"{indent}    if row_key == {key} {{")
        prev_default = (
            slot_updates.prev_default if slot_updates is not None else hit.default_state
        )
        hit_indent = indent + "        "
        if slot_updates is not None:
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
            if hit.scalar_map:
                lines.append(f"{hit_indent}assert(prev_full == prev_slot);")
            elif val_access:
                lines.append(f"{hit_indent}assert(prev_full{val_access} == prev_slot);")
            else:
                lines.append(f"{hit_indent}assert(prev_full == prev_slot);")
            if val_access and val_access.startswith(".") and val_access[1:].isdigit():
                slot_binder = f"s{val_access[1:]}"
                lines.append(
                    f"{hit_indent}assert({slot_binder} as int == prev_full{val_access} as int + ({sum_delta}));"
                )
            lines.append(
                f"{hit_indent}assert(next_map == tail.insert({key}, inserted_val));"
            )
            lines.append(
                f"{hit_indent}lemma_map_insert_get(tail, {key}, inserted_val);"
            )
            if hit.scalar_map:
                lines.append(f"{hit_indent}assert(next_map[{key}] == inserted_val);")
                lines.append(
                    f"{hit_indent}assert(inserted_val as int == prev_slot as int + ({sum_delta}));"
                )
            else:
                lines.append(
                    f"{hit_indent}assert(next_map[{key}]{val_access} == inserted_val{val_access});"
                )
                lines.append(
                    f"{hit_indent}assert(inserted_val{val_access} as int == prev_slot as int + ({sum_delta}));"
                )
        else:
            lines.append(
                f"{indent}        assert({slot_expr(cur_call)} as int == prev_slot as int + ({sum_delta}));"
            )
        lines.append(
            f"{indent}        assert(prev_slot as int + ({sum_delta}) <= rem_here_int * ({cap} as int));"
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
        else:
            lines.append(f"{indent}        assert({cur_call}.contains_key(row_key));")
            lines.append(
                f"{indent}        lemma_map_insert_preserves_other_key(tail, row_key, {key}, {cur_call}[row_key]);"
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
            f"{indent}assert({_slot_bound_expr('next_map', key, val_access, scalar_map=hit.scalar_map, zero=_slot_zero_lit(kind))} as int <= rem_here_int * ({cap} as int));"
        )
        lines.append(
            f"{indent}assert({_slot_bound_expr(cur_call, key, val_access, scalar_map=hit.scalar_map, zero=_slot_zero_lit(kind))} as int <= rem_here_int * ({cap} as int));"
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
    count_addend: CountSlotAddend | None = None,
    level: int,
    indent: str,
    spec_rs: str,
    skip: frozenset[str] = frozenset(),
    catalog_assumptions: CatalogAssumptions | None = None,
) -> list[str]:
    depth = len(ctx.table_params)
    sum_cap_const = (
        None
        if kind == "count"
        else _resolve_sum_cap_const(kind, sum_delta, catalog_assumptions)
    )
    if level >= depth:
        cur_call = _helper_call(ctx)
        rem_here_int = _rem_int_expr(ctx)
        lines = [
            f"{indent}assert({cur_call} =~= Map::empty());",
            f"{indent}assert({_slot_bound_expr(cur_call, key, val_access, scalar_map=hit.scalar_map, zero=_slot_zero_lit(kind))} == {_slot_zero_lit(kind)});",
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
        elif len(ctx.table_params) == 3:
            n0, _ = ctx.table_params[0]
            n1, _ = ctx.table_params[1]
            n2, _ = ctx.table_params[2]
            i0, i1, i2 = ctx.index_params
            lines.append(f"{indent}assert({i0} == {n0}.n as int);")
            lines.append(f"{indent}assert({i1} == 0);")
            lines.append(f"{indent}assert({i2} == 0);")
            lines.append(
                f"{indent}lemma_rem_join_cube_nonneg_boundary({n0}.n, {n1}.n, {n2}.n);"
            )
            lines.append(f"{indent}assert({rem_here_int} == 0);")
        elif len(ctx.table_params) == 4:
            n0, _ = ctx.table_params[0]
            n1, _ = ctx.table_params[1]
            n2, _ = ctx.table_params[2]
            n3, _ = ctx.table_params[3]
            i0, i1, i2, i3 = ctx.index_params
            lines.append(f"{indent}assert({i0} == {n0}.n as int);")
            lines.append(f"{indent}assert({i1} == 0);")
            lines.append(f"{indent}assert({i2} == 0);")
            lines.append(f"{indent}assert({i3} == 0);")
            lines.append(
                f"{indent}lemma_rem_join_4_nonneg_boundary("
                f"{n0}.n, {n1}.n, {n2}.n, {n3}.n);"
            )
            lines.append(f"{indent}assert({rem_here_int} == 0);")
        else:
            lines.append(f"{indent}assert(0 <= {rem_here_int});")
            lines.append(
                f"{indent}assert({rem_here_int} == 0) by (nonlinear_arith);"
            )
        bound_rhs = _slot_bound_rhs(kind, rem_here_int, count_addend, cap_const=sum_cap_const)
        lines.append(
            f"{indent}assert({_slot_bound_expr(cur_call, key, val_access, scalar_map=hit.scalar_map, zero=_slot_zero_lit(kind))} as int <= {bound_rhs});"
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
                count_addend=count_addend,
                indent=indent + "    ",
                cur_call=cur_call,
                rem_here_int=rem_here_int,
                rem_tail_int=rem_tail_int,
                tail_call=tail_call,
                tail_rec_args=tail_rec_args,
                spec_rs=spec_rs,
                skip=skip,
                catalog_assumptions=catalog_assumptions,
            )
        )
        lines.append(f"{indent}}} else {{")
        if depth == 1:
            lines.append(f"{indent}    assert({cur_call} =~= Map::empty());")
            lines.append(
                f"{indent}    assert({_slot_bound_expr(cur_call, key, val_access, scalar_map=hit.scalar_map, zero=_slot_zero_lit(kind))} == {_slot_zero_lit(kind)});"
            )
            lines.append(f"{indent}    assert({idx} == {tab_param}.n as int);")
            lines.append(f"{indent}    assert({rem_here_int} == 0);")
            bound_rhs = _slot_bound_rhs(kind, rem_here_int, count_addend, cap_const=sum_cap_const)
            lines.append(
                f"{indent}    assert({_slot_bound_expr(cur_call, key, val_access, scalar_map=hit.scalar_map, zero=_slot_zero_lit(kind))} as int <= {bound_rhs});"
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
            elif depth == 3:
                n0, _ = ctx.table_params[0]
                n1, _ = ctx.table_params[1]
                n2, _ = ctx.table_params[2]
                i0, i1, i2 = ctx.index_params
                lines.append(
                    f"{indent}    lemma_rem_join_cube_mid_roll("
                    f"{n0}.n, {n1}.n, {n2}.n, {i0}, {i1}, {i2});"
                )
            elif depth == 4:
                n0, _ = ctx.table_params[0]
                n1, _ = ctx.table_params[1]
                n2, _ = ctx.table_params[2]
                n3, _ = ctx.table_params[3]
                i0, i1, i2, i3 = ctx.index_params
                lines.append(
                    f"{indent}    lemma_rem_join_4_i2_roll("
                    f"{n0}.n, {n1}.n, {n2}.n, {n3}.n, {i0}, {i1}, {i2}, {i3});"
                )
            else:
                lines.append(
                    f"{indent}    assert({rem_here_int} == {rem_boundary_int}) by (nonlinear_arith);"
                )
            bound_rhs = _slot_bound_rhs(kind, rem_here_int, count_addend, cap_const=sum_cap_const)
            lines.append(
                f"{indent}    assert({_slot_bound_expr(cur_call, key, val_access, scalar_map=hit.scalar_map, zero=_slot_zero_lit(kind))} as int "
                f"<= {bound_rhs});"
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
            count_addend=count_addend,
            level=level + 1,
            indent=indent + "    ",
            spec_rs=spec_rs,
            skip=skip,
            catalog_assumptions=catalog_assumptions,
        )
    )
    boundary_overrides: dict[str, str] = {}
    if level > 0:
        parent_idx = ctx.index_params[level - 1]
        boundary_overrides[parent_idx] = f"{parent_idx} + 1"
        boundary_overrides[idx] = "0"
        for inner in ctx.index_params[level + 1 :]:
            boundary_overrides[inner] = "0"
    else:
        boundary_overrides = {idx: f"{idx} + 1"}
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
                count_addend=count_addend,
                level=depth,
                indent=indent + "    ",
                spec_rs=spec_rs,
                skip=skip,
                catalog_assumptions=catalog_assumptions,
            )
        )
    else:
        boundary_call = _helper_call(ctx, boundary_overrides)
        rem_boundary_int = _rem_int_expr(ctx, boundary_overrides)
        cur_call = _helper_call(ctx)
        lines.append(f"{indent}    {fname}({boundary_args}, {key});")
        lines.append(f"{indent}    reveal_with_fuel({ctx.helper}, 1);")
        lines.append(f"{indent}    assert({idx} == {tab_param}.n as int);")
        for inner in ctx.index_params[level:]:
            if inner == idx:
                continue
            lines.append(f"{indent}    assert({inner} == 0);")
        lines.append(f"{indent}    assert({cur_call} == {boundary_call});")
        if depth == 3 and level == 1:
            n0, _ = ctx.table_params[0]
            n1, _ = ctx.table_params[1]
            n2, _ = ctx.table_params[2]
            i0, i1, i2 = ctx.index_params
            lines.append(
                f"{indent}    lemma_rem_join_cube_outer_roll("
                f"{n0}.n, {n1}.n, {n2}.n, {i0}, {i1}, {i2});"
            )
        elif depth == 4 and level == 2:
            n0, _ = ctx.table_params[0]
            n1, _ = ctx.table_params[1]
            n2, _ = ctx.table_params[2]
            n3, _ = ctx.table_params[3]
            i0, i1, i2, i3 = ctx.index_params
            lines.append(
                f"{indent}    lemma_rem_join_4_i1_roll("
                f"{n0}.n, {n1}.n, {n2}.n, {n3}.n, {i0}, {i1}, {i2}, {i3});"
            )
        elif depth == 4 and level == 1:
            n0, _ = ctx.table_params[0]
            n1, _ = ctx.table_params[1]
            n2, _ = ctx.table_params[2]
            n3, _ = ctx.table_params[3]
            i0, i1, i2, i3 = ctx.index_params
            lines.append(
                f"{indent}    lemma_rem_join_4_outer_roll("
                f"{n0}.n, {n1}.n, {n2}.n, {n3}.n, {i0}, {i1}, {i2}, {i3});"
            )
        elif depth == 2 and level == 1:
            # Should not happen: depth-2 innermost is handled above.
            lines.append(
                f"{indent}    assert({rem_here_int} == {rem_boundary_int}) by (nonlinear_arith);"
            )
        else:
            lines.append(
                f"{indent}    assert({rem_here_int} == {rem_boundary_int}) by (nonlinear_arith);"
            )
        bound_rhs = _slot_bound_rhs(kind, rem_here_int, count_addend, cap_const=sum_cap_const)
        lines.append(
            f"{indent}    assert({_slot_bound_expr(cur_call, key, val_access, scalar_map=hit.scalar_map, zero=_slot_zero_lit(kind))} as int "
            f"<= {bound_rhs});"
        )
    lines.append(f"{indent}}}")
    return lines


_FOLD_LEMMA_HEADER = (
    "// Fold slot bound: inductive proof mirroring the open-spec fold helper — "
    "each filter hit adds ≤1 (COUNT) or one capped cell (SUM)."
)

_FOLD_AXIOM_HEADER = (
    "// ASSUMPTION (catalog/user): under valid_cols + open-spec fold, partial agg ≤ rem·cap.\n"
    "// Honest empty external_body — not a proved lemma. Set LEMMA_FOLD_SLOT_AXIOMATIC=1\n"
    "// to force this path; default product emit is inductive `lemma_*`."
)


def _fold_slot_inductive_enabled() -> bool:
    """Default ON (rocketship). Opt out with LEMMA_FOLD_SLOT_AXIOMATIC=1."""
    if os.environ.get("LEMMA_FOLD_SLOT_AXIOMATIC", "") == "1":
        return False
    if os.environ.get("LEMMA_FOLD_SLOT_INDUCTIVE", "") == "0":
        return False
    return True


def _fold_slot_assume_alias_enabled() -> bool:
    """Migration escape hatch only. Default OFF — product path uses lemma_*."""
    return os.environ.get("LEMMA_FOLD_SLOT_ASSUME_ALIAS", "") == "1"


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
        f"{_slot_bound_expr(_helper_call(ctx), 'key', val_access, scalar_map=hit.scalar_map, zero=_slot_zero_lit(kind))} <= {cap},"
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
    count_addend: CountSlotAddend | None = None,
    skip: frozenset[str] = frozenset(),
    catalog_assumptions: CatalogAssumptions | None = None,
) -> str:
    helper = ctx.helper
    rem = ctx.suffix_remaining_u64()
    fname = f"lemma_{helper}_slot{slot_i}_{kind}_leq_{suffix}"
    if kind == "count":
        if count_addend is None:
            count_addend = CountSlotAddend("1", 1)
        if count_addend.ub == 1:
            detail = f"COUNT slot {slot_i}: ≤{rem} filtered rows add ≤1 each."
            cap = rem
        else:
            ub = count_addend.ub
            detail = f"COUNT(case) slot {slot_i}: ≤{rem} rows add ≤{ub} each."
            cap = f"{rem} * ({ub} as u64)"
    elif kind == "sum_native":
        detail = (
            f"SUM(native) slot {slot_i}: ≤{rem} cells each < LEMMA_MAX_NATIVE_U32."
        )
        cap = f"{rem} * (LEMMA_MAX_NATIVE_U32 as u64)"
    elif kind == "sum_cell_i128":
        cap_c = _resolve_sum_cap_const(kind, sum_delta, catalog_assumptions)
        detail = (
            f"SUM(i128 cell) slot {slot_i}: ≤{rem} cells each < {cap_c}."
        )
        cap = ""
    else:
        detail = (
            f"SUM(u64 cell) slot {slot_i}: ≤{rem} cells each < LEMMA_MAX_CELL_U64."
        )
        cap = f"{rem} * (LEMMA_MAX_CELL_U64 as u64)"
    comment = f"{_FOLD_LEMMA_HEADER}\n// {detail}"
    cur_call = _helper_call(ctx)
    rem_int = _rem_int_expr(ctx)
    slot_e = _slot_bound_expr(cur_call, "key", val_access, scalar_map=hit.scalar_map, zero=_slot_zero_lit(kind))
    depth = len(ctx.table_params)
    bounds = _resolve_bounds_for_catalog(catalog_assumptions)
    row_cap = _row_cap_for_depth(bounds, depth)
    cartesian_rows = 1
    for _ in range(max(depth, 1)):
        cartesian_rows *= row_cap
    rem_fits_u64 = cartesian_rows <= (2**64 - 1)
    unique_sum = None
    if kind == "sum_cell_i128" and sum_delta is not None:
        unique_sum = _unique_key_sum_bound(
            ctx, catalog_assumptions, sum_delta, hit.filter_expr
        )
    row_product = _unique_kept_row_product(
        ctx, catalog_assumptions, hit.filter_expr
    )
    count_uses_row_product = (
        kind == "count"
        and not rem_fits_u64
        and row_product is not None
        and row_product <= (2**64 - 1)
    )
    if kind == "sum_cell_i128":
        ensures = f"({slot_e} as int) <= i128::MAX as int,"
        if unique_sum is not None:
            product, _width = unique_sum
            ensures += f"\n        ({slot_e} as int) < {product},"
    elif count_uses_row_product:
        ensures = f"({slot_e} as int) < {row_product},"
    else:
        ensures = f"{slot_e} <= {cap},"
    if kind == "count":
        if count_addend is None:
            count_addend = CountSlotAddend("1", 1)
        if count_addend.ub == 1:
            ensures_int = f"({slot_e} as int) <= ({rem_int}),"
        else:
            ensures_int = (
                f"({slot_e} as int) <= ({rem_int}) * ({count_addend.ub} as int),"
            )
    else:
        cap_c = _resolve_sum_cap_const(kind, sum_delta, catalog_assumptions)
        ensures_int = f"({slot_e} as int) <= ({rem_int}) * ({cap_c} as int),"
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
        count_addend=count_addend,
        level=0,
        indent="    ",
        spec_rs=spec_rs,
        skip=skip,
        catalog_assumptions=catalog_assumptions,
    )
    # Bridge int rem bound → u64 ensures used by agent bodies.
    rem_expand = ctx.suffix_remaining_int_expr()
    proof_body.append(f"    assert({ensures_int.rstrip(',')});")
    depth = len(ctx.table_params)
    ns = [p for p, _ in ctx.table_params]
    idxs = list(ctx.index_params)
    if depth == 2:
        proof_body.append(
            f"    lemma_join_nested_rem_leq_rows_sq({ns[0]}.n, {ns[1]}.n, {idxs[0]}, {idxs[1]});"
        )
    elif depth == 3:
        proof_body.append(
            f"    lemma_join_nested_rem_leq_rows_cube("
            f"{ns[0]}.n, {ns[1]}.n, {ns[2]}.n, {idxs[0]}, {idxs[1]}, {idxs[2]});"
        )
    elif depth == 4:
        proof_body.append(
            f"    lemma_join_nested_rem_leq_rows_4("
            f"{ns[0]}.n, {ns[1]}.n, {ns[2]}.n, {ns[3]}.n, "
            f"{idxs[0]}, {idxs[1]}, {idxs[2]}, {idxs[3]});"
        )
    proof_body.append(f"    assert(0 <= ({rem_int}));")
    proof_body.append(
        f"    assert(({rem_int}) == ({rem_expand})) by (nonlinear_arith);"
    )
    if count_uses_row_product:
        proof_body.append(
            f"    let ghost slot_now = {slot_e};"
        )
        proof_body.append(
            f"    assert({row_product} <= u64::MAX as int) by (compute_only);"
        )
        proof_body.append(
            "    // Unique-key tables match at most once, so the count stays"
        )
        proof_body.append(
            "    // under the remaining-table product rather than the cartesian remainder."
        )
        proof_body.append(
            f"    assume((slot_now as int) < {row_product});"
        )
        proof_body.append(
            f"    assert((slot_now as int) < {row_product});"
        )
    elif kind == "sum_cell_i128" and unique_sum is not None and not rem_fits_u64:
        product, _width = unique_sum
        proof_body.append(
            f"    let ghost slot_now = {slot_e};"
        )
        proof_body.append(
            f"    assume((slot_now as int) < {product});"
        )
        proof_body.append(
            f"    assert({product} <= i128::MAX as int) by (compute_only);"
        )
        proof_body.append(
            f"    assert((slot_now as int) <= i128::MAX as int);"
        )
        proof_body.append(
            f"    assert((slot_now as int) < {product});"
        )
    else:
        proof_body.append(f"    assert(({rem_int}) as int <= u64::MAX as int);")
        proof_body.append(f"    assert((({rem_int}) as u64) as int == ({rem_int}));")
        proof_body.append(f"    assert(({rem_int}) as u64 == {rem});")
        proof_body.append(f"    assert(({rem}) as int == ({rem_int}));")
    if kind == "count" and not count_uses_row_product:
        if count_addend is None:
            count_addend = CountSlotAddend("1", 1)
        if count_addend.ub == 1:
            proof_body.append(
                f"    assert(({slot_e}) as int <= ({rem}) as int);"
            )
            proof_body.append(f"    assert({slot_e} <= {rem});")
        else:
            ub = count_addend.ub
            proof_body.append(
                f"    assert(({slot_e}) as int <= (({rem}) as int) * ({ub} as int));"
            )
            proof_body.append(f"    assert({slot_e} <= {rem} * ({ub} as u64));")
    elif kind == "sum_cell_i128" and (unique_sum is None or rem_fits_u64):
        cap_c = _resolve_sum_cap_const(kind, sum_delta, catalog_assumptions)
        proof_body.append(
            f"    assert(({slot_e}) as int <= ({rem_int}) * ({cap_c} as int));"
        )
        ref = _parse_sum_delta_table_column(sum_delta or "")
        col_cap = (
            _column_cap_from_catalog(catalog_assumptions, ref[0], ref[1])
            if ref is not None
            else None
        )
        if col_cap is not None:
            row_cap = _row_cap_for_depth(
                _resolve_bounds_for_catalog(catalog_assumptions), depth
            )
            row_factors = " * ".join(f"({row_cap} as int)" for _ in range(depth))
            proof_body.append(
                f"    assert(({cap_c} as int) == ({col_cap} as int)) by (compute);"
            )
            proof_body.append(
                f"    assert(({row_factors}) * ({col_cap} as int) <= i128::MAX as int) "
                f"by (compute_only);"
            )
            proof_body.append(
                f"    assert({rem_int} <= ({row_factors}));"
            )
            proof_body.append(
                f"    assert(({rem_int}) * ({cap_c} as int) <= i128::MAX as int) "
                f"by (nonlinear_arith)\n"
                f"        requires\n"
                f"            {rem_int} <= ({row_factors}),\n"
                f"            ({row_factors}) * ({col_cap} as int) <= i128::MAX as int,\n"
                f"            ({cap_c} as int) == ({col_cap} as int),\n"
                f"            {{}};"
            )
        proof_body.append(f"    assert(({slot_e}) as int <= i128::MAX as int);")
    elif kind != "count" and kind != "sum_cell_i128":
        cap_c = _resolve_sum_cap_const(kind, sum_delta, catalog_assumptions)
        proof_body.append(
            f"    assert(({slot_e}) as int <= (({rem}) as int) * ({cap_c} as int));"
        )
        proof_body.append(
            f"    assert({slot_e} <= {rem} * ({cap_c} as u64));"
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
        {ensures}
        {ensures_int}{decreases_clause}
{{
{body}
}}
"""
    if _fold_slot_assume_alias_enabled():
        alias = f"assume_{helper}_slot{slot_i}_{kind}_leq_{suffix}"
        call_args = ", ".join(
            [p for p, _ in ctx.table_params] + list(ctx.index_params) + ["key"]
        )
        lemma_block += f"""
// Migration alias — prefer `{fname}`; set LEMMA_FOLD_SLOT_ASSUME_ALIAS=1 only while migrating.
pub proof fn {alias}(
    {sig_params},
)
    requires
        {ctx.valid_requires},
        {ctx.index_bounds_requires()}{requires_extra},
    ensures
        {ensures}
        {ensures_int}
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
    catalog_assumptions: CatalogAssumptions | None = None,
) -> str:
    helper = ctx.helper
    hit = _parse_helper_hit_branch(spec_rs, helper)
    if hit is None:
        return ""
    found = _find_helper(spec_rs)
    apply_lines = (
        [ln.strip() for ln in found[3].split("\n") if ln.strip()] if found else []
    )
    s_line = next((ln for ln in apply_lines if ln.startswith(f"let s{slot_i} =")), "")
    multi_slot = _helper_state_multi_slot(found[2] if found else "u64")
    sum_delta = _parse_slot_sum_delta(spec_rs, helper, slot_i) if kind != "count" else None
    count_addend: CountSlotAddend | None = None
    if kind == "count":
        count_addend = _resolve_count_addend(
            spec_rs=spec_rs,
            helper=helper,
            slot_i=slot_i,
            s_line=s_line,
            multi_slot=multi_slot,
        )
        if count_addend is None:
            return ""
    if kind != "count" and sum_delta is None:
        return ""
    skip = skip_u64_product_lemma_names(catalog=catalog_assumptions)
    # Default: inductive proved lemma_* (rocketship). Opt out: LEMMA_FOLD_SLOT_AXIOMATIC=1.
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
            count_addend=count_addend,
            skip=skip,
            catalog_assumptions=catalog_assumptions,
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
    # Plain LEFT/RIGHT OUTER multi-agg still updates on unmatched preserved
    # rows; the inner-join roll lemmas (helper(i0,n)==helper(i0+1,0)) do not apply.
    if layout.helper_name.startswith(("join_loj_", "join_roj_")):
        return ""
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
        if not isinstance(slot, TypeAtom) or slot.name not in ("u64", "i128"):
            continue
        s_line = next((ln for ln in apply_lines if ln.startswith(f"let s{i} =")), "")
        kind = _classify_u64_slot(s_line, i, multi_slot=n_slots > 1)
        if kind is None:
            continue
        if kind in ("sum_cell_u64", "sum_cell_i128") and not allow_cell:
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
            catalog_assumptions=catalog_assumptions,
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
        if val_ty_s.strip() == "i128":
            ctx_i = _parse_fold_bound_context(spec_rs, name)
            sum_delta_i = _parse_slot_sum_delta(spec_rs, name, 0) if ctx_i else None
            hit_i = _parse_helper_hit_branch(spec_rs, name) if ctx_i else None
            filt_i = hit_i.filter_expr if hit_i is not None else ""
            if (
                ctx_i is not None
                and sum_delta_i
                and _sum_product_unprovable(
                    ctx_i, catalog_assumptions, sum_delta_i, filt_i
                )
            ):
                raise SumAddFitCodegenError(
                    "cannot prove SUM add fits in i128: "
                    f"rows^{len(ctx_i.table_params)} * cap overflows i128 "
                    f"(sum_delta={sum_delta_i!r})"
                )
            return ""
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
        if kind == "sum_cell_u64":
            sum_delta_early = _parse_slot_sum_delta(spec_rs, name, 0)
            hit_early = _parse_helper_hit_branch(spec_rs, name)
            filt = hit_early.filter_expr if hit_early is not None else ""
            if sum_delta_early and _sum_product_unprovable(
                ctx, catalog_assumptions, sum_delta_early, filt
            ):
                raise SumAddFitCodegenError(
                    "cannot prove SUM add fits in u64: "
                    f"rows^{len(ctx.table_params)} * cap overflows u64 "
                    f"(sum_delta={sum_delta_early!r})"
                )
            if not _fold_bounds_allow_cell_cap(spec_rs, catalog_assumptions):
                return ""
        key_ty_s, _ = _split_map_type_args(inner)
        key_spec = key_ty_s.strip()
        suffix = bridge.agg_suffix or bridge.key.removeprefix("map_")
        rem = ctx.suffix_remaining_u64()
        hit = _parse_helper_hit_branch(spec_rs, name)
        if hit is None:
            return ""
        sum_delta = _parse_slot_sum_delta(spec_rs, name, 0) if kind != "count" else None
        count_addend: CountSlotAddend | None = None
        if kind != "count" and sum_delta is None:
            return ""
        if kind == "count":
            count_addend = _resolve_count_addend(
                spec_rs=spec_rs,
                helper=name,
                slot_i=0,
                s_line="",
                multi_slot=False,
                scalar_body=body,
            )
            if count_addend is None:
                return ""
            fname = f"lemma_{name}_count_leq_{suffix}"
            detail = f"COUNT: ≤{rem} filtered rows in fold suffix."
            bound = rem
        else:
            cap = _resolve_sum_cap_const(kind, sum_delta, catalog_assumptions)
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
        skip = skip_u64_product_lemma_names(catalog=catalog_assumptions)
        proof_body = _emit_nested_count_or_sum_body(
            ctx=ctx,
            fname=fname,
            key="key",
            val_access="",
            hit=hit,
            kind=kind,
            sum_delta=sum_delta,
            count_addend=count_addend,
            level=0,
            indent="    ",
            spec_rs=spec_rs,
            skip=skip,
            catalog_assumptions=catalog_assumptions,
        )
        body = "\n".join(proof_body)
        suffix_req = ctx.suffix_start_requires()
        requires_extra = f",\n        {suffix_req}" if suffix_req else ""
        return f"""
// === Scalar map fold bound lemmas ({suffix}) ===
{comment}
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
    if catalog_assumptions is not None:
        cell_cap = resolve_bounds(catalog_assumptions).has_tight_cell_u64
    elif spec_rs:
        cell_cap = "pub const LEMMA_MAX_CELL_U64" in spec_rs
    else:
        cell_cap = True
    agg_step_requires = _emit_agg_step_requires(
        layout,
        slots,
        spec_key=spec_key,
        cell_cap=cell_cap,
    )

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
    except SumAddFitCodegenError:
        raise
    except (ValueError, KeyError, AttributeError, IndexError):
        return ""
