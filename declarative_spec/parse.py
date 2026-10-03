"""Parse supported declarative SQL into a small AST."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto


class DeclarativeUnsupported(Exception):
    """SQL outside the declarative subset."""


class AggKind(Enum):
    COUNT = auto()
    SUM = auto()


@dataclass(frozen=True)
class GroupCol:
    table: str | None
    column: str


@dataclass(frozen=True)
class ParsedQuery:
    group_cols: tuple[GroupCol, ...]
    agg_kind: AggKind
    agg_alias: str
    # COUNT single-table
    from_table: str | None = None
    # SUM join
    left_table: str | None = None
    right_table: str | None = None
    join_left_table: str | None = None
    join_left_col: str | None = None
    join_right_table: str | None = None
    join_right_col: str | None = None
    sum_qual: str | None = None
    sum_column: str | None = None

    @property
    def is_join(self) -> bool:
        return self.left_table is not None


_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_FORBIDDEN = re.compile(
    r"\b(WHERE|HAVING|ORDER\s+BY|LIMIT|DISTINCT|UNION|INTERSECT|EXCEPT)\b",
    re.IGNORECASE,
)


def _split_commas(s: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_ident_piece(piece: str) -> tuple[str | None, str]:
    piece = piece.strip()
    m = re.fullmatch(rf"({_IDENT})\.({_IDENT})", piece, re.IGNORECASE)
    if m:
        return m.group(1), m.group(2)
    m = re.fullmatch(rf"({_IDENT})", piece, re.IGNORECASE)
    if m:
        return None, m.group(1)
    raise DeclarativeUnsupported(f"invalid identifier {piece!r}")


def _parse_select_item(item: str) -> tuple[str | None, str | None, AggKind | None, str | None]:
    """Returns (table, column, agg_kind, alias) for group col or aggregate."""
    item = item.strip()
    alias: str | None = None
    m_as = re.search(r"\bAS\s+(" + _IDENT + r")\s*$", item, re.IGNORECASE)
    if m_as:
        alias = m_as.group(1)
        item = item[: m_as.start()].strip()

    upper = item.upper()
    if upper == "COUNT(*)":
        return None, None, AggKind.COUNT, alias or "count"
    m_sum = re.fullmatch(rf"SUM\s*\(\s*({_IDENT}(?:\.{_IDENT})?)\s*\)", item, re.IGNORECASE)
    if m_sum:
        qual, col = _parse_ident_piece(m_sum.group(1))
        return qual, col, AggKind.SUM, alias or "sum"

    qual, col = _parse_ident_piece(item)
    return qual, col, None, None


def parse_declarative_sql(sql: str) -> ParsedQuery:
    text = sql.strip()
    if not text:
        raise DeclarativeUnsupported("empty SQL")
    if _FORBIDDEN.search(text):
        raise DeclarativeUnsupported("clause not supported in declarative subset")

    # JOIN + SUM pattern
    join_re = re.compile(
        rf"^\s*SELECT\s+(?P<select>.+?)\s+FROM\s+(?P<t1>{_IDENT})\s+JOIN\s+(?P<t2>{_IDENT})\s+"
        rf"ON\s+(?P<jl>{_IDENT})\.(?P<jlc>{_IDENT})\s*=\s*(?P<jr>{_IDENT})\.(?P<jrc>{_IDENT})\s+"
        rf"GROUP\s+BY\s+(?P<groupby>.+?)\s*$",
        re.IGNORECASE | re.DOTALL,
    )
    m_join = join_re.match(text)
    if m_join:
        select_parts = _split_commas(m_join.group("select"))
        group_parts = _split_commas(m_join.group("groupby"))
        agg: AggKind | None = None
        agg_alias = ""
        sum_qual: str | None = None
        sum_col: str | None = None
        for part in select_parts:
            qual, col, kind, alias = _parse_select_item(part)
            if kind is AggKind.SUM:
                if agg is not None:
                    raise DeclarativeUnsupported("multiple aggregates")
                agg = AggKind.SUM
                agg_alias = alias or "sum"
                sum_qual, sum_col = qual, col
            elif kind is not None:
                raise DeclarativeUnsupported("COUNT not supported with JOIN in this subset")
        group_cols: list[GroupCol] = []
        if agg is AggKind.SUM:
            for part in group_parts:
                qual, col = _parse_ident_piece(part)
                group_cols.append(GroupCol(qual, col))
            if not group_cols:
                raise DeclarativeUnsupported("GROUP BY required")
            t1, t2 = m_join.group("t1"), m_join.group("t2")
            return ParsedQuery(
                group_cols=tuple(group_cols),
                agg_kind=AggKind.SUM,
                agg_alias=agg_alias,
                left_table=t1,
                right_table=t2,
                join_left_table=m_join.group("jl"),
                join_left_col=m_join.group("jlc"),
                join_right_table=m_join.group("jr"),
                join_right_col=m_join.group("jrc"),
                sum_qual=sum_qual,
                sum_column=sum_col,
            )
        raise DeclarativeUnsupported("JOIN queries must use SUM aggregate")

    # Single-table COUNT
    count_re = re.compile(
        rf"^\s*SELECT\s+(?P<select>.+?)\s+FROM\s+(?P<table>{_IDENT})\s+"
        rf"GROUP\s+BY\s+(?P<groupby>.+?)\s*$",
        re.IGNORECASE | re.DOTALL,
    )
    m_count = count_re.match(text)
    if not m_count:
        raise DeclarativeUnsupported("unsupported SQL shape")

    select_parts = _split_commas(m_count.group("select"))
    group_parts = _split_commas(m_count.group("groupby"))
    agg = None
    agg_alias = ""
    for part in select_parts:
        qual, col, kind, alias = _parse_select_item(part)
        if kind is AggKind.COUNT:
            if agg is not None:
                raise DeclarativeUnsupported("multiple aggregates")
            agg = AggKind.COUNT
            agg_alias = alias or "count"
        elif kind is not None:
            raise DeclarativeUnsupported("only COUNT(*) supported for single-table queries")
    group_cols: list[GroupCol] = []
    for part in group_parts:
        qual, col = _parse_ident_piece(part)
        group_cols.append(GroupCol(qual, col))

    if agg is not AggKind.COUNT:
        raise DeclarativeUnsupported("single-table queries require COUNT(*)")
    if not group_cols:
        raise DeclarativeUnsupported("GROUP BY required")

    table = m_count.group("table")
    normalized_groups: list[GroupCol] = []
    for g in group_cols:
        if g.table is None:
            normalized_groups.append(GroupCol(table, g.column))
        else:
            normalized_groups.append(g)

    return ParsedQuery(
        group_cols=tuple(normalized_groups),
        agg_kind=AggKind.COUNT,
        agg_alias=agg_alias,
        from_table=table,
    )
