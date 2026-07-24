"""Shared row→columnar expression conversion for spec emission."""

from __future__ import annotations

import re

from .value_bounds import col_verus_type


def to_col_expr(expr: str, idx: str) -> str:
    return re.sub(
        r"\brow\.([A-Za-z_][A-Za-z0-9_]*)",
        lambda m: f"cols.get_{m.group(1).lower()}({idx})",
        expr,
    )


def native_where_cond(cond: str, idx: str, schema_dict: dict[str, str]) -> str:
    """Exec-path WHERE: string == via eq_at_* (usize index)."""
    out = cond
    for col, col_type in schema_dict.items():
        if col_verus_type(col_type) != "String":
            continue
        col_pat = re.escape(col)
        out = re.sub(
            rf"cols\.get_{col_pat.lower()}\({re.escape(idx)}\)\s*==\s*(\"[^\"]*\")",
            rf"cols.eq_at_{col.lower()}({idx}, \1)",
            out,
        )
    return out


def spec_where_cond(cond: str, idx: str, schema_dict: dict[str, str]) -> str:
    """Spec-path WHERE: string == on Seq<char> (int index)."""
    out = cond
    for col, col_type in schema_dict.items():
        if col_verus_type(col_type) != "String":
            continue
        col_pat = re.escape(col)
        out = re.sub(
            rf"cols\.get_{col_pat.lower()}\({re.escape(idx)}\)\s*==\s*(\"[^\"]*\")",
            rf"cols.get_{col.lower()}({idx}) == \1@",
            out,
        )
    out = re.sub(
        r'(str_like_(?:prefix|suffix|contains)\(cols\.get_\w+\([^)]+\),\s*)("(?:[^"\\]|\\.)*")(\))',
        r"\1\2@\3",
        out,
    )
    out = re.sub(
        r'(str_(?:ilike_match|like_underscore_match)\(cols\.get_\w+\([^)]+\),\s*)("(?:[^"\\]|\\.)*")(\))',
        r"\1\2@\3",
        out,
    )
    return out


def native_u64_term(term_row_expr: str, idx: str) -> str:
    """Exec-path term (may call mul_u64_u32 / case_when_u64_exec)."""

    def row_cond_to_exec(cond: str) -> str:
        out = cond
        for m in re.finditer(r"row\.([A-Za-z_][A-Za-z0-9_]*)", cond):
            col = m.group(1).lower()
            out = out.replace(f"row.{m.group(1)}", f"cols.get_{col}_exec({idx})")
        return out

    m = re.match(
        r"case_when_u64\((.+), (.+), (.+)\)",
        term_row_expr.strip(),
    )
    if m:
        cond, then_v, else_v = m.group(1), m.group(2), m.group(3)
        return (
            f"case_when_u64_exec({row_cond_to_exec(cond)}, "
            f"{native_u64_term(then_v, idx)}, {native_u64_term(else_v, idx)})"
        )
    m = re.match(
        r"\(row\.([A-Za-z_][A-Za-z0-9_]*) as int\) \* \(row\.([A-Za-z_][A-Za-z0-9_]*) as int\)",
        term_row_expr.strip(),
    )
    if m:
        a, b = m.group(1).lower(), m.group(2).lower()
        return f"mul_u64_u32(cols.{a}[{idx} as int] as u64, cols.{b}[{idx} as int])"
    converted = to_col_expr(term_row_expr, idx)
    return f"({converted}) as u64"


def spec_u64_term(term_row_expr: str, idx: str) -> str:
    """Spec-path term: pure arithmetic only (no exec helpers)."""

    def row_cond_to_spec(cond: str) -> str:
        return re.sub(
            r"row\.([A-Za-z_][A-Za-z0-9_]*)",
            lambda m: f"cols.get_{m.group(1).lower()}({idx})",
            cond,
        )

    m = re.match(
        r"case_when_u64\((.+), (.+), (.+)\)",
        term_row_expr.strip(),
    )
    if m:
        cond, then_v, else_v = m.group(1), m.group(2), m.group(3)
        return (
            f"case_when_u64({row_cond_to_spec(cond)}, "
            f"{spec_u64_term(then_v, idx)}, {spec_u64_term(else_v, idx)})"
        )
    m = re.match(
        r"\(row\.([A-Za-z_][A-Za-z0-9_]*) as int\) \* \(row\.([A-Za-z_][A-Za-z0-9_]*) as int\)",
        term_row_expr.strip(),
    )
    if m:
        a, b = m.group(1).lower(), m.group(2).lower()
        return f"((cols.{a}[{idx} as int] as int) * (cols.{b}[{idx} as int] as int)) as u64"
    converted = to_col_expr(term_row_expr, idx)
    return f"({converted}) as u64"


def native_i64_term(term_row_expr: str, idx: str) -> str:
    m = re.match(
        r"\(row\.([A-Za-z_][A-Za-z0-9_]*) as int\) - \(row\.([A-Za-z_][A-Za-z0-9_]*) as int\)",
        term_row_expr.strip(),
    )
    if m:
        a, b = m.group(1).lower(), m.group(2).lower()
        return f"sub_u64_to_i64(cols.{a}[{idx} as int], cols.{b}[{idx} as int])"
    return f"({to_col_expr(term_row_expr, idx)}) as i64"


def spec_i64_term(term_row_expr: str, idx: str) -> str:
    m = re.match(
        r"\(row\.([A-Za-z_][A-Za-z0-9_]*) as int\) - \(row\.([A-Za-z_][A-Za-z0-9_]*) as int\)",
        term_row_expr.strip(),
    )
    if m:
        a, b = m.group(1).lower(), m.group(2).lower()
        return f"((cols.{a}[{idx} as int] as int) - (cols.{b}[{idx} as int] as int)) as i64"
    return f"({to_col_expr(term_row_expr, idx)}) as i64"


def merge_where_exprs(left: str | None, right: str | None) -> str | None:
    if left and right:
        return f"({left}) && ({right})"
    return left or right
