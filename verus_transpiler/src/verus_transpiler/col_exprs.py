"""Shared row→columnar expression conversion for spec emission."""

from __future__ import annotations

import re

from .rust_ident import rust_ident
from .value_bounds import col_verus_type


def _matching_paren(text: str, open_pos: int) -> int:
    if open_pos >= len(text) or text[open_pos] != "(":
        raise ValueError("expected '('")
    depth = 0
    for i in range(open_pos, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("unbalanced parentheses")


def _split_top_level_commas(inner: str) -> list[str]:
    args: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(inner):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(inner[start:i].strip())
            start = i + 1
    args.append(inner[start:].strip())
    return args


def coerce_u64_case_arg(arg: str) -> str:
    """then/else of case_when_u64 must be u64, not ghost int or unsuffixed literals."""
    a = arg.strip()
    m = re.fullmatch(r"\((row_u64_\d+) as int\)", a)
    if m:
        return m.group(1)
    m = re.fullmatch(r"(row_u64_\d+) as int", a)
    if m:
        return m.group(1)
    m = re.fullmatch(r"\(row\.([A-Za-z_][A-Za-z0-9_]*) as int\)", a)
    if m:
        return f"row.{m.group(1)}"
    m = re.fullmatch(r"row\.([A-Za-z_][A-Za-z0-9_]*) as int", a)
    if m:
        return f"row.{m.group(1)}"
    if re.fullmatch(r"-?\d+u64", a):
        return a
    if re.fullmatch(r"-?\d+", a):
        return f"{a}u64"
    return a


def coerce_case_when_u64_args(text: str) -> str:
    """Rewrite case_when_u64 then/else to u64. Does not touch case_when_u64_exec."""
    i = 0
    out: list[str] = []
    key = "case_when_u64("
    while i < len(text):
        if text.startswith("case_when_u64_exec(", i):
            out.append("case_when_u64_exec(")
            i += len("case_when_u64_exec(")
            continue
        if text.startswith(key, i):
            open_idx = i + len("case_when_u64")
            close = _matching_paren(text, open_idx)
            inner = text[open_idx + 1 : close]
            args = _split_top_level_commas(inner)
            if len(args) != 3:
                out.append(text[i : close + 1])
                i = close + 1
                continue
            cond, then_v, else_v = args
            cond = coerce_case_when_u64_args(cond)
            then_v = coerce_case_when_u64_args(coerce_u64_case_arg(then_v))
            else_v = coerce_case_when_u64_args(coerce_u64_case_arg(else_v))
            out.append(f"case_when_u64({cond}, {then_v}, {else_v})")
            i = close + 1
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def assert_case_when_u64_then_else_u64(text: str) -> None:
    """Loud fail if then/else still look like ghost int (r24 leftover E0308)."""
    i = 0
    key = "case_when_u64("
    while i < len(text):
        if text.startswith("case_when_u64_exec(", i):
            i += len("case_when_u64_exec(")
            continue
        if text.startswith(key, i):
            open_idx = i + len("case_when_u64")
            close = _matching_paren(text, open_idx)
            inner = text[open_idx + 1 : close]
            args = _split_top_level_commas(inner)
            if len(args) == 3:
                for label, arg in (("then", args[1]), ("else", args[2])):
                    stripped = arg.strip()
                    if re.fullmatch(r"\(?row_u64_\d+ as int\)?", stripped):
                        raise AssertionError(
                            f"case_when_u64 {label} is ghost int ({stripped}); expected u64"
                        )
                    if re.fullmatch(r"-?\d+", stripped):
                        raise AssertionError(
                            f"case_when_u64 {label} is unsuffixed literal {stripped}; use {stripped}u64"
                        )
            i = close + 1
            continue
        i += 1


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
        # Table-scoped getters (num.get_uom(k)) as well as bare cols.get_*.
        getter_pat = rf"\w+\.get_{col_pat.lower()}\({re.escape(idx)}\)"
        out = re.sub(
            rf"({getter_pat})\s*==\s*(\"[^\"]*\")(?!\@)",
            r"\1 == \2@",
            out,
        )
        out = re.sub(
            rf"({getter_pat})\s*!=\s*(\"[^\"]*\")(?!\@)",
            r"\1 != \2@",
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
        a, b = rust_ident(m.group(1)), rust_ident(m.group(2))
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
        return coerce_case_when_u64_args(
            f"case_when_u64({row_cond_to_spec(cond)}, "
            f"{spec_u64_term(then_v, idx)}, {spec_u64_term(else_v, idx)})"
        )
    m = re.match(
        r"\(row\.([A-Za-z_][A-Za-z0-9_]*) as int\) \* \(row\.([A-Za-z_][A-Za-z0-9_]*) as int\)",
        term_row_expr.strip(),
    )
    if m:
        a, b = rust_ident(m.group(1)), rust_ident(m.group(2))
        return f"((cols.{a}[{idx} as int] as int) * (cols.{b}[{idx} as int] as int)) as u64"
    converted = to_col_expr(term_row_expr, idx)
    return f"({converted}) as u64"


def native_i64_term(term_row_expr: str, idx: str) -> str:
    m = re.match(
        r"\(row\.([A-Za-z_][A-Za-z0-9_]*) as int\) - \(row\.([A-Za-z_][A-Za-z0-9_]*) as int\)",
        term_row_expr.strip(),
    )
    if m:
        a, b = rust_ident(m.group(1)), rust_ident(m.group(2))
        return f"sub_u64_to_i64(cols.{a}[{idx} as int], cols.{b}[{idx} as int])"
    return f"({to_col_expr(term_row_expr, idx)}) as i64"


def spec_i64_term(term_row_expr: str, idx: str) -> str:
    m = re.match(
        r"\(row\.([A-Za-z_][A-Za-z0-9_]*) as int\) - \(row\.([A-Za-z_][A-Za-z0-9_]*) as int\)",
        term_row_expr.strip(),
    )
    if m:
        a, b = rust_ident(m.group(1)), rust_ident(m.group(2))
        return f"((cols.{a}[{idx} as int] as int) - (cols.{b}[{idx} as int] as int)) as i64"
    return f"({to_col_expr(term_row_expr, idx)}) as i64"


def merge_where_exprs(left: str | None, right: str | None) -> str | None:
    if left and right:
        return f"({left}) && ({right})"
    return left or right
