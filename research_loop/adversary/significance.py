"""Pure SQL result significance judge (no I/O)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Verdict:
    significant: bool
    reason: str


_SINGLE_QUOTED = re.compile(r"'(?:''|[^'])*'", re.DOTALL)
_ORDER_BY = re.compile(r"\border\s+by\b", re.IGNORECASE)
_LIMIT = re.compile(r"\blimit\b", re.IGNORECASE)
_FETCH = re.compile(r"\bfetch\b", re.IGNORECASE)


def _strip_sql_strings(sql: str) -> str:
    return _SINGLE_QUOTED.sub("", sql)


def sql_demands_order(sql: str) -> bool:
    return _ORDER_BY.search(_strip_sql_strings(sql)) is not None


def sql_limit_without_order(sql: str) -> bool:
    stripped = _strip_sql_strings(sql)
    if sql_demands_order(sql):
        return False
    return _LIMIT.search(stripped) is not None or _FETCH.search(stripped) is not None


def _limit_offset(sql: str) -> tuple[int, int]:
    import sqlglot

    select = sqlglot.parse_one(sql, read="duckdb")
    limit, offset = select.args.get("limit"), select.args.get("offset")
    if limit is None:
        raise ValueError(f"no LIMIT in {sql!r}")
    return int(limit.expression.this), int(offset.expression.this) if offset is not None else 0


def unlimited_sql(sql: str) -> str:
    """``sql`` without its LIMIT/OFFSET: the full result the limited one picks rows from."""
    import sqlglot

    select = sqlglot.parse_one(sql, read="duckdb")
    select.set("limit", None)
    select.set("offset", None)
    return select.sql(dialect="duckdb")


def _normalize_cell(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return value
    return str(value)


def _normalize_rows(rows: list[tuple] | None) -> list[tuple] | None:
    if rows is None:
        return None
    return [tuple(_normalize_cell(c) for c in row) for row in rows]


def classify_difference(
    sql: str,
    impl: list[tuple] | None,
    duck: list[tuple] | None,
    *,
    impl_error: str | None = None,
    duck_error: str | None = None,
    unlimited: list[tuple] | None = None,
) -> Verdict:
    """``unlimited`` is DuckDB's result for ``unlimited_sql(sql)``; LIMIT without ORDER BY needs it."""
    impl_err = (impl_error or "").strip() or None
    duck_err = (duck_error or "").strip() or None

    if impl_err and not duck_err and duck is not None:
        return Verdict(significant=True, reason="error_vs_value")
    if duck_err and not impl_err and impl is not None:
        return Verdict(significant=True, reason="error_vs_value")

    if impl_err and duck_err:
        return Verdict(significant=False, reason="both_error")

    if impl is None and duck is None and not impl_err and not duck_err:
        return Verdict(significant=False, reason="no_rows")

    impl_n = _normalize_rows(impl)
    duck_n = _normalize_rows(duck)

    if sql_limit_without_order(sql):
        # Without ORDER BY any rows may be picked. Only the count and membership are fixed.
        if unlimited is None or impl_n is None:
            raise ValueError("LIMIT without ORDER BY needs the unlimited result and impl rows")
        limit, offset = _limit_offset(sql)
        want = min(limit, max(len(unlimited) - offset, 0))
        if len(impl_n) != want:
            return Verdict(significant=True, reason="limit_row_count")
        if Counter(impl_n) - Counter(_normalize_rows(unlimited)):
            return Verdict(significant=True, reason="limit_rows_not_in_result")
        return Verdict(significant=False, reason="limit_without_order")

    if sql_demands_order(sql):
        if impl_n != duck_n:
            return Verdict(significant=True, reason="order")
        return Verdict(significant=False, reason="same_sequence")

    if Counter(impl_n) != Counter(duck_n):
        return Verdict(significant=True, reason="multiset")
    return Verdict(significant=False, reason="same_multiset")
