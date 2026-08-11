#!/usr/bin/env python3
"""Insert fold-bound proof blocks before agg_add_* / agg_step_* in prove_loop runqueries."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from verus_transpiler.column_projection import project_multi_schema_for_query
from verus_transpiler.parse_sql import normalize_schema

from research_loop.method_spec_ret_type import (
    parse_method_spec_return_type,
    resolve_ret_type_from_method_spec,
)
from research_loop.multi_agg_step_bridge import (
    _classify_scalar_map_u64,
    _classify_u64_slot,
    _find_helper,
    _parse_fold_bound_context,
    _state_slots,
    parse_multi_agg_layout,
)
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema
from research_loop.trusted_ret_bridge import (
    _key_param_specs,
    bridge_from_method_spec_type,
    get_bridge,
    parse_verus_type,
)
from research_loop.sec_table_assumptions import sec_prove_loop_catalog_assumptions
from verus_transpiler import transpile_sql_to_verus

AGG_CALL_RE = re.compile(
    r"^(\s*)(agg_add_[a-z0-9_]+|agg_step_(?!inner_|state_new_|project_|apply_row_)[a-z0-9_]+)\(",
    re.MULTILINE,
)
PROOF_HAS_LEMMA_RE = re.compile(
    r"lemma_u64_add_|assume_\w+_slot\d+_|assume_\w+_(?:count|sum)_"
)
ENSURES_RES_RE = re.compile(r"ensures\s+res@\s*==\s*method_spec")
OUT_AT_RE = re.compile(r"\bout@")
HELPER_NAMES_RE = (
    r"join_anti_multi_agg_helper|join_multi_agg_helper|join_method_spec_helper"
    r"|multi_agg_helper|method_spec_helper"
)
HELPER_CALL_RE = re.compile(rf"({HELPER_NAMES_RE})\(")
INNER_SPEC_HELPER_RE = re.compile(
    r"agg_step_inner_[a-z0-9_]+_spec\([^)]+\)\s*==\s*(\w+)\s*\(",
)
GET_EXEC_RE = re.compile(
    r"let\s+(\w+)\s*=\s*(\w+)\.get_(\w+)_exec\(([^)]+)\);"
)
GHOST_KEY_RE = re.compile(r"let ghost key = ([^;]+);")
DEC_RE = re.compile(r"(\w+)\s*=\s*\1\s*-\s*1\s*;")
HAVING_TYPO_RE = re.compile(r"apply_having_filter_exec_([a-z0-9_]+)__u64\b")
PROOF_BINDING_NAMES = frozenset({"value", "val", "line", "delta", "amt"})
FOLD_PROOF_MARKER_RE = re.compile(
    r"lemma_u64_add_|lemma_rem_cap_cell_u64_add_fits|lemma_rem_cap_one_add_fits"
    r"|lemma_join_nested_rem_leq_rows|lemma_fold_suffix_rem_leq_rows"
    r"|assume_\w+_slot\d+_|assume_\w+_(?:count|sum)_"
    r"|lemma_\w+_slot\d+_|lemma_\w+_(?:count|sum)_"
)
EXEC_IN_PROOF_RE = re.compile(r"(\w+)\.get_(\w+)_exec\(([^)]+)\)")


def _load_spec(dir_path: Path) -> str:
    transpiled = dir_path / "spec_transpiled.rs"
    if transpiled.is_file():
        return transpiled.read_text(encoding="utf-8")
    sql = (dir_path / "query.sql").read_text(encoding="utf-8")
    schema = load_sec_schema()
    _flat, multi = normalize_schema(schema)
    projected = project_multi_schema_for_query(sql, multi)
    return transpile_sql_to_verus(
        sql, projected, catalog_assumptions=sec_prove_loop_catalog_assumptions()
    )


def _vec_view_for_ret(ret_type: str) -> str | None:
    bridge = get_bridge(ret_type)
    if bridge and bridge.view_spec and bridge.view_spec.startswith("vec_"):
        return bridge.view_spec
    return None


def _rewrite_seq_views(text: str, view_fn: str) -> str:
    text = ENSURES_RES_RE.sub(f"ensures {view_fn}(res@) == method_spec", text)
    text = re.sub(rf"(?<!{re.escape(view_fn)}\()out@", f"{view_fn}(out@)", text)
    while f"{view_fn}({view_fn}(" in text:
        text = text.replace(f"{view_fn}({view_fn}(", f"{view_fn}(")
    return text


def _proof_before_has_lemma(src: str, call_start: int) -> bool:
    window = src[max(0, call_start - 4000) : call_start]
    if re.search(
        r"let ghost tail = \w+\(",
        window,
    ) and re.search(
        r"lemma_u64_add_|assume_\w+_slot\d+_|assume_\w+_(?:count|sum)_(?:money_)?leq_"
        r"|lemma_\w+_slot\d+_|lemma_\w+_(?:count|sum)_(?:money_)?leq_",
        window,
    ):
        return True
    return False


def _extract_post_proof(src: str, call_end: int) -> tuple[str, int] | None:
    m = re.search(r"\n(\s*)proof\s*\{", src[call_end:])
    if not m:
        return None
    brace = src.find("{", call_end + m.start())
    depth = 0
    i = brace
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[brace + 1 : i].strip(), i + 1
        i += 1
    return None


def _parse_tail_key_prev(proof_body: str) -> tuple[str, str, str, str] | None:
    tail_m = re.search(r"let ghost tail = (\w+)\(([^;]+)\);", proof_body)
    key_m = re.search(r"let ghost key = ([^;]+);", proof_body)
    prev_m = re.search(
        r"let ghost prev = if tail\.contains_key\(key\)\s*\{[\s\S]*?tail\[key\][\s\S]*?\}\s*else\s*\{([\s\S]*?)\};",
        proof_body,
    )
    if not prev_m:
        val_m = re.search(
            r"let ghost val = if tail\.contains_key\(key\)\s*\{ tail\[key\] \} else \{ ([^}]+) \};",
            proof_body,
        )
        if val_m:
            prev_m = val_m
    if not (tail_m and key_m and prev_m):
        return None
    return (
        tail_m.group(1),
        tail_m.group(2).strip(),
        key_m.group(1).strip(),
        prev_m.group(1).strip(),
    )


def _lemma_call_args(spec_rs: str, helper: str, tail_args: str) -> str | None:
    ctx = _parse_fold_bound_context(spec_rs, helper)
    if ctx is None:
        return None
    parts = [p.strip() for p in tail_args.split(",")]
    n_idx = len(ctx.index_params)
    n_tab = len(ctx.table_params)
    if len(parts) < n_tab + n_idx:
        return None
    table_parts = parts[:n_tab]
    idx_parts = parts[n_tab : n_tab + n_idx]
    if len(table_parts) != n_tab or len(idx_parts) != n_idx:
        return None
    return ", ".join(table_parts + idx_parts + ["key"])


def _slot_kinds(spec_rs: str) -> list[tuple[int, str]]:
    layout = parse_multi_agg_layout(spec_rs)
    if layout is None:
        return []
    slots = _state_slots(layout.state_type)
    apply_lines = [ln.strip() for ln in layout.apply_body.split("\n") if ln.strip()]
    out: list[tuple[int, str]] = []
    for i, slot in enumerate(slots):
        if getattr(slot, "name", None) != "u64":
            continue
        s_line = next((ln for ln in apply_lines if ln.startswith(f"let s{i} =")), "")
        kind = _classify_u64_slot(s_line, i, multi_slot=len(slots) > 1)
        if kind:
            out.append((i, kind))
    return out


def _effective_slot_kinds(
    spec_rs: str, money_cell: str | None
) -> list[tuple[int, str]]:
    return _slot_kinds(spec_rs)


def _scalar_kind(spec_rs: str) -> str | None:
    found = _find_helper(spec_rs)
    if not found:
        return None
    _name, _key, val_ty, body = found
    if val_ty.strip() != "u64":
        return None
    return _classify_scalar_map_u64(body)


def _split_call_args(args: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in args:
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return parts


def _last_decrement_var(src: str, call_start: int) -> str | None:
    window = src[max(0, call_start - 3000) : call_start]
    matches = list(DEC_RE.finditer(window))
    return matches[-1].group(1) if matches else None


def _extract_helper_calls(text: str) -> list[tuple[str, list[str]]]:
    out: list[tuple[str, list[str]]] = []
    for m in HELPER_CALL_RE.finditer(text):
        helper = m.group(1)
        start = m.end()
        depth = 1
        i = start
        while i < len(text) and depth > 0:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        args = _split_call_args(text[start : i - 1])
        if args:
            out.append((helper, args))
    return out


INV_HELPER_RE = re.compile(
    rf"==\s*({HELPER_NAMES_RE})\(([^)]*(?:\([^)]*\)[^)]*)*)\)",
)


def _detect_helper_invariant(
    src: str, call_start: int, *, spec_rs: str
) -> tuple[str, list[str]] | None:
    window = src[max(0, call_start - 4000) : call_start]
    inv_calls: list[tuple[str, list[str]]] = []
    for line in window.splitlines():
        if "invariant" not in line and "==" not in line:
            continue
        if "lemma_" in line or "let ghost tail" in line:
            continue
        for m in INV_HELPER_RE.finditer(line):
            args = _split_call_args(m.group(2))
            if args:
                inv_calls.append((m.group(1), args))
    if inv_calls:
        return inv_calls[-1]
    calls = _extract_helper_calls(window)
    if calls:
        return calls[-1]
    for m in INNER_SPEC_HELPER_RE.finditer(window):
        helper = m.group(1)
        ctx = _parse_fold_bound_context(spec_rs, helper)
        if ctx is None:
            continue
        args = [p for p, _ in ctx.table_params]
        args.extend(f"{idx} as int" for idx in ctx.index_params)
        return helper, args
    return None


def _tail_index_arg(inv_arg: str, idx_name: str) -> str:
    inv_arg = inv_arg.strip()
    plus1 = f"({idx_name} + 1) as int"
    if inv_arg == plus1 or inv_arg == f"{idx_name} + 1":
        return plus1
    if inv_arg == f"{idx_name} as int" or inv_arg == idx_name:
        return plus1
    return inv_arg


def _build_tail_args(
    helper: str,
    inv_args: list[str],
    *,
    dec_var: str | None,
    spec_rs: str,
) -> str | None:
    ctx = _parse_fold_bound_context(spec_rs, helper)
    if ctx is None:
        return None
    n_tab = len(ctx.table_params)
    n_idx = len(ctx.index_params)
    if len(inv_args) < n_tab + n_idx:
        return None
    out = list(inv_args[: n_tab + n_idx])
    if dec_var is not None:
        for j in range(n_tab, n_tab + n_idx):
            idx_name = ctx.index_params[j - n_tab]
            if idx_name == dec_var or dec_var in out[j]:
                out[j] = _tail_index_arg(out[j], dec_var)
    return ", ".join(out)


def _exec_bindings(src: str, call_start: int) -> dict[str, tuple[str, str, str, bool]]:
    """var -> (table, field, index_expr, is_str)."""
    window = src[max(0, call_start - 12000) : call_start]
    out: dict[str, tuple[str, str, str, bool]] = {}
    for m in GET_EXEC_RE.finditer(window):
        var, table, field, idx = m.group(1), m.group(2), m.group(3), m.group(4).strip()
        out[var] = (table, field, idx, True)
    return out


def _ghost_key_before_call(src: str, call_start: int) -> str | None:
    window = src[max(0, call_start - 4000) : call_start]
    matches = list(GHOST_KEY_RE.finditer(window))
    if not matches:
        return None
    return matches[-1].group(1).strip()


def _rem_at_call_site(ctx, tail_args: str) -> str:
    """Map fold suffix rem to agent loop variable names from tail_args."""
    parts = _split_call_args(tail_args)
    n_tab = len(ctx.table_params)
    idx_parts = parts[n_tab:]
    if len(idx_parts) != len(ctx.index_params):
        return ctx.suffix_remaining_u64()
    rem = ctx.suffix_remaining_u64()
    for formal, actual in zip(ctx.index_params, idx_parts):
        actual_stripped = actual.replace(" as int", "").strip()
        plus1 = re.match(r"\((\w+) \+ 1\)", actual_stripped)
        current = plus1.group(1) if plus1 else actual_stripped
        rem = rem.replace(formal, current)
    return rem


def _cell_spec_expr(
    cell: str, bindings: dict[str, tuple[str, str, str, bool]]
) -> str:
    """Proof-safe cell reference: prefer exec binding names over spec fields."""
    cell = cell.strip()
    if cell in ("0u64", "1u64"):
        return cell
    if cell in PROOF_BINDING_NAMES:
        return cell
    cast_m = re.match(r"^(\w+) as u64$", cell)
    if cast_m and cast_m.group(1) in PROOF_BINDING_NAMES:
        return cell
    if cast_m:
        cell = cast_m.group(1)
    if cell in PROOF_BINDING_NAMES:
        return cell
    get_m = re.match(r"^(\w+)\.get_(\w+)_exec\(([^)]+)\)$", cell)
    if get_m:
        table, field, idx = get_m.group(1), get_m.group(2), get_m.group(3).strip()
        idx_expr = idx if " as int" in idx else f"{idx} as int"
        return f"{table}.{field}[{idx_expr}]"
    if cell in bindings:
        return cell
    return cell


def _proof_safe_cell(
    cell: str, bindings: dict[str, tuple[str, str, str, bool]]
) -> str:
    spec = _cell_spec_expr(cell, bindings)
    if spec != cell and not spec.endswith("u64"):
        return f"({spec}) as u64" if " as u64" not in cell else spec
    return cell


def _spec_field_ref(table: str, field: str, idx: str, *, is_str: bool) -> str:
    idx_expr = idx if " as int" in idx else f"{idx} as int"
    if is_str:
        return f"{table}.{field}[{idx_expr}]@"
    return f"{table}.{field}[{idx_expr}]"


def _map_key_type(bridge) -> object | None:
    if not bridge or not bridge.spec_map:
        return None
    parsed = parse_verus_type(bridge.spec_map)
    if hasattr(parsed, "key"):
        return parsed.key
    return None


def _infer_key_from_call(
    call_line: str,
    *,
    bridge,
    bindings: dict[str, tuple[str, str, str, bool]],
) -> str | None:
    m = re.match(
        r"agg_(?:add|step)_(?P<suffix>[a-z0-9_]+)\((?P<args>.*)\);",
        call_line.strip(),
        re.DOTALL,
    )
    if not m:
        return None
    raw_args = _split_call_args(m.group("args"))
    if not raw_args:
        return None
    if raw_args[0].startswith("&mut"):
        raw_args = raw_args[1:]
    key_ty = _map_key_type(bridge)
    if key_ty is None:
        return None
    key_params = _key_param_specs(key_ty)
    n_key = len(key_params)
    key_args = raw_args[:n_key]
    if len(key_args) < n_key:
        return None

    spec_bits: list[str] = []
    for i, arg in enumerate(key_args):
        arg = arg.strip()
        _, _, spec_frag = key_params[i]
        is_str = spec_frag.endswith("@")
        if arg.endswith(".as_str()"):
            var = arg[:-9].strip()
            if var in bindings:
                t, f, idx, _ = bindings[var]
                spec_bits.append(_spec_field_ref(t, f, idx, is_str=True))
                continue
        bare = re.match(r"^(\w+)$", arg)
        if bare and bare.group(1) in bindings:
            t, f, idx, _ = bindings[bare.group(1)]
            spec_bits.append(_spec_field_ref(t, f, idx, is_str=is_str))
            continue
        if re.match(r"^\d+u32$", arg):
            spec_bits.append(arg)
            continue
        return None
    if n_key == 1:
        return spec_bits[0]
    return f"({', '.join(spec_bits)})"


def _default_prev_zero(spec_rs: str, helper: str) -> str:
    layout = parse_multi_agg_layout(spec_rs)
    if layout is not None:
        return layout.default_state
    found = _find_helper(spec_rs)
    if not found:
        return "0u64"
    _name, _key, val_ty, body = found
    if val_ty.strip() == "u64":
        return "0u64"
    m = re.search(
        r"let prev = if tail\.contains_key\(key\) \{ tail\[key\] \} else \{ ([^}]+) \};",
        body,
    )
    return m.group(1).strip() if m else "0u64"


def _build_post_proof(
    *,
    helper: str,
    tail_args: str,
    key: str,
    prev_zero: str,
    is_agg_step: bool,
    suffix: str,
    spec_rs: str,
) -> str | None:
    ctx = _parse_fold_bound_context(spec_rs, helper)
    if ctx is None:
        return None
    n_idx = len(ctx.index_params)
    if n_idx == 0:
        return None
    tail_parts = _split_call_args(tail_args)
    if len(tail_parts) < len(ctx.table_params) + n_idx:
        return None
    current_parts = list(tail_parts)
    for j in range(len(ctx.table_params), len(ctx.table_params) + n_idx):
        idx_name = ctx.index_params[j - len(ctx.table_params)]
        if current_parts[j] == f"({idx_name} + 1) as int":
            current_parts[j] = f"{idx_name} as int"
    current_args = ", ".join(current_parts)

    lines = [
        "proof {",
        f"    let ghost tail = {helper}({tail_args});",
        f"    let ghost key = {key};",
        f"    let ghost prev = if tail.contains_key(key) {{ tail[key] }} else {{ {prev_zero} }};",
    ]
    if is_agg_step:
        inner_m = re.search(r"agg_step_inner_([a-z0-9_]+)_spec", spec_rs)
        if inner_m is None:
            return None
        inner = inner_m.group(1)
        lines.append(
            f"    assert(agg_step_inner_{inner}_spec(st.inner@) == {helper}({current_args}));"
        )
    else:
        lines.append(f"    assert(hm@ == {helper}({current_args}));")
    lines.append("}")
    return "\n".join(lines)


def _synthesize_fold_context(
    src: str,
    call_start: int,
    call_line: str,
    *,
    spec_rs: str,
    bridge,
) -> tuple[str, str, str, str] | None:
    inv = _detect_helper_invariant(src, call_start, spec_rs=spec_rs)
    if inv is None:
        return None
    helper, inv_args = inv
    dec_var = _last_decrement_var(src, call_start)
    tail_args = _build_tail_args(helper, inv_args, dec_var=dec_var, spec_rs=spec_rs)
    if tail_args is None:
        return None
    bindings = _exec_bindings(src, call_start)
    key = _infer_key_from_call(call_line, bridge=bridge, bindings=bindings)
    if key is None:
        key = _ghost_key_before_call(src, call_start)
    if key is None:
        return None
    prev_zero = _default_prev_zero(spec_rs, helper)
    return helper, tail_args, key, prev_zero


def _fix_having_typos(text: str) -> str:
    return HAVING_TYPO_RE.sub(r"apply_having_filter_exec_\1_u64", text)


def _ghost_indices_and_rem(
    ctx, tail_args: str
) -> tuple[list[str], list[str], list[str], str, str]:
    """Ghost index bindings, current/tail idx args, rem_tail (int), rem_curr (u64)."""
    parts = _split_call_args(tail_args)
    n_tab = len(ctx.table_params)
    ghost_lines: list[str] = []
    current_idx_args: list[str] = []
    lemma_idx_args: list[str] = []
    ghost_subst: dict[str, str] = {}
    loop_subst: dict[str, str] = {}
    for k, idx_name in enumerate(ctx.index_params):
        tail_expr = parts[n_tab + k].strip()
        gname = f"{idx_name}g"
        ghost_lines.append(f"let ghost {gname} = {tail_expr};")
        ghost_subst[idx_name] = gname
        lemma_idx_args.append(gname)
        plus1 = f"({idx_name} + 1) as int"
        if tail_expr == plus1:
            current_idx_args.append(f"{idx_name} as int")
            loop_subst[idx_name] = f"{idx_name} as int"
        else:
            current_idx_args.append(tail_expr)
            loop_subst[idx_name] = tail_expr.replace(" as int", "").strip()
    rem_tail_int, _rem_curr_int = _rem_int_from_subst(ctx, ghost_subst, loop_subst)
    rem_u64 = f"({rem_tail_int}) as u64"
    return ghost_lines, current_idx_args, lemma_idx_args, rem_tail_int, rem_u64


def _rem_int_from_subst(
    ctx,
    ghost_subst: dict[str, str],
    loop_subst: dict[str, str],
) -> tuple[str, str]:
    rem = ctx.suffix_remaining_u64().replace(" as u64", "").strip()
    rem_tail = rem
    rem_curr = rem
    for idx_name in ctx.index_params:
        if idx_name in ghost_subst:
            rem_tail = rem_tail.replace(idx_name, ghost_subst[idx_name])
        if idx_name in loop_subst:
            rem_curr = rem_curr.replace(idx_name, loop_subst[idx_name])
    return rem_tail, rem_curr


def _table_rows_asserts(ctx) -> list[str]:
    """Assert row caps that follow from ``valid_cols`` (always ``LEMMA_MAX_ROWS`` today).

    Depth-specific ``ROWS_CUBE`` / ``ROWS_4`` caps are catalog constants for product
    lemmas; they are **not** in ``valid_cols`` unless/until per-query depth caps are
    wired into ``valid_cols``. Do not assert them here — proofs cannot discharge them.
    """
    seen: set[str] = set()
    lines: list[str] = []
    for param, _struct in ctx.table_params:
        if param in seen:
            continue
        seen.add(param)
        lines.append(f"assert({param}.n <= LEMMA_MAX_ROWS);")
    return lines


def _nested_join_rem_lines(ctx, lemma_idx_args: list[str]) -> list[str]:
    """Discharge rem ≤ ROWS² for 2-table nested loops (join_method_spec_helper shape)."""
    if len(ctx.table_params) < 2 or len(lemma_idx_args) < 2:
        return []
    t0, _ = ctx.table_params[0]
    t1, _ = ctx.table_params[1]
    return [
        (
            f"lemma_join_nested_rem_leq_rows_sq("
            f"{t0}.n, {t1}.n, {lemma_idx_args[0]}, {lemma_idx_args[1]});"
        )
    ]


def _single_table_rem_lines(ctx, lemma_idx_args: list[str]) -> list[str]:
    if len(ctx.table_params) != 1 or len(lemma_idx_args) < 1:
        return []
    t0, _ = ctx.table_params[0]
    ig = lemma_idx_args[0]
    return [
        f"assert(0 <= {ig} <= {t0}.n as int);",
        f"assert(({t0}.n as int - {ig}) <= LEMMA_MAX_ROWS as int);",
    ]


def _fold_suffix_rem_lines(ctx, lemma_idx_args: list[str]) -> list[str]:
    n_tab = len(ctx.table_params)
    n_idx = len(lemma_idx_args)
    if n_tab < 3 or n_idx < n_tab:
        return []
    ns = ", ".join(f"{p}.n" for p, _ in ctx.table_params)
    is_ = ", ".join(lemma_idx_args[:n_tab])
    if n_tab == 3:
        return [f"lemma_fold_suffix_rem_leq_rows_pow3({ns}, {is_});"]
    if n_tab == 4:
        return [f"lemma_fold_suffix_rem_leq_rows_pow4({ns}, {is_});"]
    return []


def _rem_cap_lines(ctx, kind: str) -> list[str]:
    n_tab = len(ctx.table_params)
    if n_tab <= 2:
        if kind == "native":
            return ["lemma_rem_cap_native_add_fits(rem);"]
        return ["lemma_rem_cap_cell_u64_add_fits(rem);"]
    if kind == "native":
        return ["lemma_rem_cap_native_add_fits_pow4(rem);"]
    return ["lemma_rem_cap_cell_u64_add_fits_pow4(rem);"]


def _join_depth(ctx) -> int:
    return len(ctx.table_params)


def _rem_cap_one_add_lemma_for_ctx(ctx) -> str | None:
    """Return rem_cap_one lemma, or None when fold_suffix already matches depth.

    Depth ≥3 uses ``lemma_fold_suffix_rem_leq_rows_pow*`` with ``LEMMA_MAX_ROWS^k``,
    which does **not** discharge ``lemma_rem_cap_one_add_fits_{cube|4}`` (CUBE / ROWS_4).
    Pass99 proofs omitted rem_cap_one on those shapes; keep that alignment.
    """
    depth = _join_depth(ctx)
    if depth >= 3:
        return None
    if depth <= 1:
        return "lemma_rem_cap_one_add_fits_rows"
    return "lemma_rem_cap_one_add_fits"


def _rem_cap_one_add_lines(ctx) -> list[str]:
    lemma = _rem_cap_one_add_lemma_for_ctx(ctx)
    if lemma is None:
        return []
    lines = [f"{lemma}(rem);"]
    if lemma == "lemma_rem_cap_one_add_fits_rows":
        lines.insert(0, "assert(rem <= LEMMA_MAX_ROWS as u64);")
    return lines


def _rem_discharge_lines(ctx, lemma_idx_args: list[str]) -> list[str]:
    n_tab = len(ctx.table_params)
    if n_tab >= 3:
        return _fold_suffix_rem_lines(ctx, lemma_idx_args)
    nested = _nested_join_rem_lines(ctx, lemma_idx_args)
    if nested:
        return nested
    return _single_table_rem_lines(ctx, lemma_idx_args)


def _lemma_args_with_ghost_indices(
    spec_rs: str, helper: str, tail_args: str, lemma_idx_args: list[str]
) -> str | None:
    ctx = _parse_fold_bound_context(spec_rs, helper)
    if ctx is None:
        return None
    parts = [p.strip() for p in _split_call_args(tail_args)]
    n_tab = len(ctx.table_params)
    if len(parts) < n_tab + len(ctx.index_params):
        return None
    table_parts = parts[:n_tab]
    if len(lemma_idx_args) != len(ctx.index_params):
        return None
    return ", ".join(table_parts + lemma_idx_args + ["key"])


def _money_cell_before_call(src: str, call_start: int) -> str | None:
    """Return the exec binding name used as the money cell (never get_*_exec RHS)."""
    window = src[max(0, call_start - 500) : call_start]
    # Prefer the binding name so proof blocks use `value`, not `get_value_exec`.
    for name in ("value", "val", "line", "delta", "amt"):
        if re.search(rf"\blet\s+{name}\s*=", window):
            return name
    for pat in (
        r"let value = ([^;]+);",
        r"let val = ([^;]+);",
        r"let line = ([^;]+);",
    ):
        m = re.search(pat, window)
        if m:
            rhs = m.group(1).strip()
            if rhs in ("1u64", "0u64"):
                return rhs
            var_m = re.match(r"^(\w+)$", rhs)
            if var_m:
                return var_m.group(1)
            cast_m = re.match(r"^(\w+) as u64$", rhs)
            if cast_m:
                return cast_m.group(1)
            # Never paste get_*_exec into proofs.
            if ".get_" in rhs and "_exec(" in rhs:
                return None
            return rhs
    if "1u64" in src[call_start : call_start + 200]:
        return "1u64"
    return None


def _build_before_proof(
    *,
    spec_rs: str,
    helper: str,
    tail_args: str,
    key: str,
    suffix: str,
    slots: list[tuple[int, str]],
    scalar_kind: str | None,
    tuple_prev: bool,
    prev_zero: str,
    money_cell: str | None,
    bindings: dict[str, tuple[str, str, str, bool]],
) -> str | None:
    ctx = _parse_fold_bound_context(spec_rs, helper)
    if ctx is None:
        return None
    ghost_lines, _current_idx_args, lemma_idx_args, rem_tail_int, rem_u64 = (
        _ghost_indices_and_rem(ctx, tail_args)
    )
    lemma_args = _lemma_args_with_ghost_indices(
        spec_rs, helper, tail_args, lemma_idx_args
    )
    if lemma_args is None:
        return None

    lines = ["proof {"]
    for gl in ghost_lines:
        lines.append(f"    {gl}")
    lines.append(f"    let ghost rem = {rem_u64};")
    for ln in _table_rows_asserts(ctx):
        lines.append(f"    {ln}")
    for ln in _rem_discharge_lines(ctx, lemma_idx_args):
        lines.append(f"    {ln}")
    lines.extend([
        f"    let ghost tail = {helper}({tail_args});",
        f"    let ghost key = {key};",
    ])
    if slots:
        lines.append(
            f"    let ghost prev = if tail.contains_key(key) {{ tail[key] }} else {{ {prev_zero} }};"
        )
        lines.append(f"    let ghost rem = {rem_u64};")
        for slot_i, kind in slots:
            fname = f"assume_{helper}_slot{slot_i}_{kind}_leq_{suffix}"
            lines.append(f"    {fname}({lemma_args});")
            if kind == "count":
                lines.append(f"    assert(prev.{slot_i} <= rem);")
                lines.extend(f"    {ln}" for ln in _table_rows_asserts(ctx))
                lines.extend(f"    {ln}" for ln in _rem_discharge_lines(ctx, lemma_idx_args))
                lines.extend(f"    {ln}" for ln in _rem_cap_one_add_lines(ctx))
                lines.append(f"    lemma_u64_add_one_prev_le(prev.{slot_i}, rem);")
            elif kind == "sum_native":
                raw_cell = money_cell or "0u64"
                cell_spec = _cell_spec_expr(raw_cell, bindings)
                lines.append(
                    f"    assert(prev.{slot_i} <= rem * (LEMMA_MAX_NATIVE_U32 as u64));"
                )
                lines.append(
                    f"    assert((({cell_spec}) as u64) < (LEMMA_MAX_NATIVE_U32 as u64));"
                )
                lines.extend(f"    {ln}" for ln in _table_rows_asserts(ctx))
                lines.extend(f"    {ln}" for ln in _rem_discharge_lines(ctx, lemma_idx_args))
                lines.extend(f"    {ln}" for ln in _rem_cap_lines(ctx, "native"))
                lines.append(
                    f"    lemma_u64_add_native_prev_le(prev.{slot_i}, ({cell_spec}) as u64, rem);"
                )
            else:
                raw_cell = money_cell or "0u64"
                cell_spec = _cell_spec_expr(raw_cell, bindings)
                lines.append(
                    f"    assert(prev.{slot_i} <= rem * (LEMMA_MAX_CELL_U64 as u64));"
                )
                lines.append(f"    assert({cell_spec} < LEMMA_MAX_CELL_U64);")
                lines.extend(f"    {ln}" for ln in _table_rows_asserts(ctx))
                lines.extend(f"    {ln}" for ln in _rem_discharge_lines(ctx, lemma_idx_args))
                lines.extend(f"    {ln}" for ln in _rem_cap_lines(ctx, "cell_u64"))
                lines.append(
                    f"    lemma_u64_add_cell_u64_prev_le(prev.{slot_i}, {cell_spec}, rem);"
                )
    else:
        zero = prev_zero if prev_zero != "0u64" else "0u64"
        lines.append(
            f"    let ghost prev = if tail.contains_key(key) {{ tail[key] }} else {{ {zero} }};"
        )
        lines.append(f"    let ghost rem = {rem_u64};")
        if scalar_kind == "count":
            lines.append(f"    assume_{helper}_count_leq_{suffix}({lemma_args});")
            lines.append("    assert(prev <= rem);")
            lines.extend(f"    {ln}" for ln in _table_rows_asserts(ctx))
            lines.extend(f"    {ln}" for ln in _rem_discharge_lines(ctx, lemma_idx_args))
            lines.extend(f"    {ln}" for ln in _rem_cap_one_add_lines(ctx))
            lines.append("    lemma_u64_add_one_prev_le(prev, rem);")
        elif scalar_kind == "sum_cell_u64":
            raw_cell = money_cell or "delta"
            cell_spec = _cell_spec_expr(raw_cell, bindings)
            lines.append("    if tail.contains_key(key) {")
            lines.append(f"        assume_{helper}_sum_cell_u64_leq_{suffix}({lemma_args});")
            lines.append(
                f"        assert((prev as int) <= ({rem_tail_int}) * (LEMMA_MAX_CELL_U64 as int));"
            )
            lines.append("    } else {")
            lines.append("        assert(prev == 0u64);")
            lines.append("    }")
            lines.append(f"    assert({cell_spec} < LEMMA_MAX_CELL_U64);")
            lines.extend(f"    {ln}" for ln in _rem_cap_lines(ctx, "cell_u64"))
            lines.append(f"    lemma_u64_add_cell_u64_prev_le(prev, {cell_spec}, rem);")
        else:
            return None
    lines.append("}")
    return "\n".join(lines)


TRUNC_AFTER_AGG_RE = re.compile(
    r"^(\s*)((?:agg_add_\w+|agg_step_\w+)\([\s\S]*?\);\n)(\s+)\}\n(\s+proof\s*\{)",
    re.MULTILINE,
)


def _agent_body_brace_depth(src: str) -> int:
    m = re.search(r"// AGENT_EDIT_START(.*)// AGENT_EDIT_END", src, re.DOTALL)
    if not m:
        return 0
    depth = 0
    for ch in m.group(1):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    return depth


def _innermost_while_var(src: str, call_start: int) -> str | None:
    window = src[max(0, call_start - 3000) : call_start]
    matches = list(re.finditer(r"decreases\s+(\w+)", window))
    return matches[-1].group(1) if matches else None


def _state_zero_assert(
    src: str, call_start: int, helper: str, inv_args: list[str], *, spec_rs: str
) -> str:
    window = src[max(0, call_start - 3000) : call_start]
    if "hm@" in window:
        state = "hm@"
    elif "agg@" in window:
        state = "agg@"
    elif "st.inner@" in window or "st.projected@" in window:
        inner_m = re.search(r"agg_step_inner_[a-z0-9_]+_spec\(st\.inner@\)", window)
        state = inner_m.group(0) if inner_m else "st.projected@"
    else:
        state = "st.projected@"
    zero_args = list(inv_args)
    ctx = _parse_fold_bound_context(spec_rs, helper)
    if ctx and len(zero_args) >= len(ctx.table_params) + len(ctx.index_params):
        j = len(ctx.table_params) + len(ctx.index_params) - 1
        zero_args[j] = "0"
    return f"assert({state} == {helper}({', '.join(zero_args)}));"


ELSE_MISSING_RE = re.compile(
    r"^(\s*)((?:agg_add_\w+|agg_step_(?!state_new_|inner_|project_|apply_row_)\w+)\([\s\S]*?\);\n)(\s+)\}\n",
    re.MULTILINE,
)


def _remove_bogus_else_insertions(src: str) -> str:
    """No-op: prior repair inserted bogus else; restore-from-assembled is the fix."""
    return src


def _extract_run_query_from_assembled(asm: str) -> str | None:
    m = re.search(r"^pub exec fn run_query\(", asm, re.MULTILINE)
    if not m:
        return None
    start = m.start()
    i = asm.find("{", m.end())
    if i < 0:
        return None
    depth = 1
    j = i + 1
    while j < len(asm) and depth:
        if asm[j] == "{":
            depth += 1
        elif asm[j] == "}":
            depth -= 1
        j += 1
    return asm[start:j].strip()


def restore_agent_from_assembled(dir_path: Path) -> bool:
    """Restore AGENT_EDIT body from assembled.rs when braces are corrupted."""
    agent_path = dir_path / "runquery_agent.rs"
    assembled_path = dir_path / "assembled.rs"
    if not agent_path.is_file() or not assembled_path.is_file():
        return False
    src = agent_path.read_text(encoding="utf-8")
    if _agent_body_brace_depth(src) == 0:
        return False
    run_query = _extract_run_query_from_assembled(assembled_path.read_text(encoding="utf-8"))
    if run_query is None or _agent_body_brace_depth("\n" + run_query + "\n") != 0:
        return False
    m = re.search(r"// AGENT_EDIT_START(.*)// AGENT_EDIT_END", src, re.DOTALL)
    if not m:
        return False
    old_body = m.group(1)
    header_m = re.match(r"(\s*//[^\n]*\n)+", old_body)
    header = header_m.group(0) if header_m else ""
    new_body = f"\n{header}{run_query}\n"
    new_src = src[: m.start(1)] + new_body + src[m.end(1) :]
    agent_path.write_text(new_src, encoding="utf-8")
    return True


def _insert_missing_else(src: str, *, spec_rs: str) -> str:
    def repl(m: re.Match[str]) -> str:
        ind = m.group(1)
        if len(m.group(3)) >= len(ind):
            return m.group(0)
        if "} else {" in src[m.end() : m.end() + 120]:
            return m.group(0)
        call_start = m.start()
        inv = _detect_helper_invariant(src, call_start, spec_rs=spec_rs)
        if not inv:
            return m.group(0)
        helper, inv_args = inv
        dec_var = _last_decrement_var(src, call_start) or _innermost_while_var(
            src, call_start
        )
        if not dec_var:
            return m.group(0)
        tail_args = _build_tail_args(
            helper, inv_args, dec_var=dec_var, spec_rs=spec_rs
        )
        if tail_args is None:
            return m.group(0)
        lhs = f"{helper}({', '.join(inv_args)})"
        rhs = f"{helper}({tail_args})"
        else_ind = ind[:-4] if len(ind) >= 4 else ind
        return (
            f"{ind}{m.group(2)}"
            f"{else_ind}}} else {{\n"
            f"{ind}proof {{\n"
            f"{ind}    assert(\n"
            f"{ind}        {lhs}\n"
            f"{ind}            == {rhs}\n"
            f"{ind}    );\n"
            f"{ind}}}\n"
            f"{else_ind}}}\n"
        )

    return ELSE_MISSING_RE.sub(repl, src)


def _repair_truncated_after_agg(src: str, *, spec_rs: str) -> str:
    src = _remove_bogus_else_insertions(src)
    repaired = _insert_missing_else(src, spec_rs=spec_rs)
    if _agent_body_brace_depth(repaired) != 0:
        return src
    return repaired


def _bindings_before_proof(window: str) -> dict[tuple[str, str, str], str]:
    """Map (table, field, idx) -> binding name from exec lets before a proof block."""
    out: dict[tuple[str, str, str], str] = {}
    for m in GET_EXEC_RE.finditer(window):
        var, table, field, idx = m.group(1), m.group(2), m.group(3), m.group(4).strip()
        out[(table, field, idx)] = var
    return out


def _replace_exec_in_proof_expr(expr: str, bindings: dict[tuple[str, str, str], str]) -> str:
    def repl(m: re.Match[str]) -> str:
        table, field, idx = m.group(1), m.group(2), m.group(3).strip()
        key = (table, field, idx)
        if key in bindings:
            return bindings[key]
        idx_expr = idx if " as int" in idx else f"{idx} as int"
        return f"{table}.{field}[{idx_expr}]"

    prev = None
    cur = expr
    while prev != cur:
        prev = cur
        cur = EXEC_IN_PROOF_RE.sub(repl, cur)
    return cur


def repair_fold_proof_blocks(text: str) -> str:
    """Rewrite illegal get_*_exec calls inside auto-injected fold-bound proof blocks."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"\s*proof\s*\{", line):
            start = i
            depth = 0
            j = i
            while j < len(lines):
                depth += lines[j].count("{") - lines[j].count("}")
                j += 1
                if depth == 0:
                    break
            block = "".join(lines[start:j])
            if FOLD_PROOF_MARKER_RE.search(block):
                window = "".join(lines[max(0, start - 40) : start])
                bindings = _bindings_before_proof(window)
                fixed_lines: list[str] = []
                for bl in lines[start:j]:
                    if ".get_" in bl and "_exec(" in bl:
                        fixed_lines.append(
                            _replace_exec_in_proof_expr(bl, bindings) + (
                                "" if bl.endswith("\n") else "\n"
                            )
                        )
                    else:
                        fixed_lines.append(bl)
                out.extend(fixed_lines)
                i = j
                continue
        out.append(line)
        i += 1
    return "".join(out)


def strip_before_agg_proofs(text: str) -> str:
    """Remove auto-injected fold-bound proof blocks (re-inject after host fixes)."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        if re.match(r"\s*proof \{", lines[i]):
            start = i
            depth = 0
            j = i
            while j < len(lines):
                depth += lines[j].count("{") - lines[j].count("}")
                j += 1
                if depth == 0:
                    break
            block = "".join(lines[start:j])
            nxt = "".join(lines[j : j + 10])
            if (
                "lemma_u64_add_one_prev_le" in block
                or "lemma_u64_add_cell_u64_prev_le" in block
                or "lemma_u64_add_native_fit" in block
                or "lemma_u64_add_native_prev_le" in block
                or "lemma_rem_cap_cell_u64_add_fits" in block
                or "assume_multi_agg_helper_slot" in block
                or "assume_join_method_spec_helper_" in block
                or "assume_method_spec_helper_slot" in block
                or "lemma_multi_agg_helper_slot" in block
                or "lemma_join_method_spec_helper_" in block
                or "lemma_method_spec_helper_slot" in block
                or "let ghost tail =" in block
            ) and re.search(r"agg_(?:add|step)_", nxt):
                i = j
                continue
        out.append(lines[i])
        i += 1
    return "".join(out)


def inject_file(
    dir_path: Path,
    *,
    dry_run: bool = False,
    strip: bool = False,
    strip_only: bool = False,
    repair_only: bool = False,
    repair_proofs_only: bool = False,
) -> bool:
    agent_path = dir_path / "runquery_agent.rs"
    if not agent_path.is_file():
        return False
    spec_rs = _load_spec(dir_path)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    spec_ret = parse_method_spec_return_type(spec_rs)
    bridge = get_bridge(ret_type) or bridge_from_method_spec_type(spec_ret)
    if bridge is None:
        return False
    suffix = bridge.agg_suffix or bridge.key.removeprefix("map_")

    original = agent_path.read_text(encoding="utf-8")
    if _agent_body_brace_depth(original) != 0:
        restore_agent_from_assembled(dir_path)
        original = agent_path.read_text(encoding="utf-8")
    src = _fix_having_typos(original)
    src = _remove_bogus_else_insertions(src)
    src = repair_fold_proof_blocks(src)
    changed = src != original
    if strip or strip_only:
        stripped = strip_before_agg_proofs(src)
        if stripped != src:
            src = stripped
            changed = True
    if strip_only:
        if changed and not dry_run:
            agent_path.write_text(src, encoding="utf-8")
        return changed

    repaired = _repair_truncated_after_agg(src, spec_rs=spec_rs)
    if repaired != src:
        src = repaired
        changed = True
    if repair_only:
        if changed and not dry_run:
            agent_path.write_text(src, encoding="utf-8")
        return changed
    if repair_proofs_only:
        if changed and not dry_run:
            agent_path.write_text(src, encoding="utf-8")
        return changed

    view_fn = _vec_view_for_ret(ret_type) or (
        bridge.view_spec if bridge.view_spec and bridge.view_spec.startswith("vec_") else None
    )
    if view_fn:
        new_src = _rewrite_seq_views(src, view_fn)
        if new_src != src:
            src = new_src

    slots = _slot_kinds(spec_rs)
    scalar_kind = _scalar_kind(spec_rs) if not slots else None

    inject_changed = False
    out: list[str] = []
    pos = 0
    for m in AGG_CALL_RE.finditer(src):
        call_start = m.start()
        out.append(src[pos:call_start])
        semi = src.find(");", m.start())
        if semi < 0:
            out.append(src[m.start() :])
            pos = len(src)
            break
        call_end = semi + 2
        call_line = src[m.start() : call_end]
        money_cell = _money_cell_before_call(src, call_start)
        bindings = _exec_bindings(src, call_start)
        call_slots = _effective_slot_kinds(spec_rs, money_cell) if slots else slots

        if _proof_before_has_lemma(src, call_start):
            out.append(call_line)
            pos = call_end
            continue

        parsed: tuple[str, str, str, str] | None = None
        consumed_post = False
        proof_end = call_end
        post = _extract_post_proof(src, call_end)
        if post is not None:
            proof_body, proof_end = post
            parsed = _parse_tail_key_prev(proof_body)
            consumed_post = parsed is not None

        if parsed is None:
            synth = _synthesize_fold_context(
                src, call_start, call_line, spec_rs=spec_rs, bridge=bridge
            )
            if synth is None:
                out.append(call_line)
                pos = call_end
                continue
            helper, tail_args, key, prev_zero = synth
        else:
            helper, tail_args, key, prev_zero = parsed
            tail_args = tail_args.rstrip(",").strip()
            key = " ".join(key.split())

        before = _build_before_proof(
            spec_rs=spec_rs,
            helper=helper,
            tail_args=tail_args,
            key=key,
            suffix=suffix,
            slots=call_slots,
            scalar_kind=scalar_kind,
            tuple_prev="(" in prev_zero,
            prev_zero=prev_zero,
            money_cell=money_cell,
            bindings=bindings,
        )
        if before is None:
            out.append(call_line)
            pos = call_end
            continue

        indent = m.group(1)
        out.append(
            "\n".join((indent + ln if ln.strip() else ln) for ln in before.splitlines())
            + "\n"
        )
        out.append(call_line)
        pos = proof_end if consumed_post else call_end
        inject_changed = True

    out.append(src[pos:])
    new_src = "".join(out)
    if (changed or inject_changed or new_src != original) and not dry_run:
        agent_path.write_text(new_src, encoding="utf-8")
    return changed or inject_changed or new_src != original


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT / "research_loop/generated/prove_loop")
    ap.add_argument("--rounds", default="r11,r12")
    ap.add_argument("--strip", action="store_true", help="strip prior injections first")
    ap.add_argument("--strip-only", action="store_true", help="only strip, do not inject")
    ap.add_argument("--repair", action="store_true", help="only repair truncated tails, no inject")
    ap.add_argument(
        "--repair-proofs",
        action="store_true",
        help="only repair get_*_exec inside fold proof blocks",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    rounds = tuple(args.rounds.split(","))
    changed = 0
    for rnd in rounds:
        for d in sorted(args.root.glob(f"{rnd}_q*")):
            if rnd == "r11" and d.name == "r11_q19":
                continue
            if inject_file(
                d,
                dry_run=args.dry_run,
                strip=args.strip,
                strip_only=args.strip_only,
                repair_only=args.repair,
                repair_proofs_only=args.repair_proofs,
            ):
                changed += 1
                print("injected", d.name)
    print("done", changed, "files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
