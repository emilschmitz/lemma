"""SQL surface the declarative spec must accept.

Feature modules fill a ``Query`` and emit Verus conditions from it. The spec
states conditions on the result. It does not define the query as a walk that
inserts into a map, and it does not emit ``method_spec``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Agg:
    """One SELECT aggregate. ``kind`` is COUNT, COUNT_DISTINCT, SUM, AVG, MIN, or MAX."""

    kind: str
    column: str | None
    alias: str
    table: str | None = None
    # Spec expression for the aggregated value when it is not a bare column.
    expr: str = ""


@dataclass(frozen=True)
class Join:
    """One join. ``kind`` is inner, left, or right. Equalities are (left, right) column pairs."""

    kind: str
    table: str
    alias: str | None
    on: tuple[tuple[str, str], ...]
    on_combiner: str = "and"


@dataclass(frozen=True)
class OrderKey:
    column: str
    descending: bool = False


@dataclass
class Query:
    """One SELECT. Nested queries (FROM subquery, EXISTS, IN, scalar, CTE) are ``Query`` values."""

    tables: list[str] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)
    joins: list[Join] = field(default_factory=list)
    group_columns: list[str] = field(default_factory=list)
    group_tables: list[str | None] = field(default_factory=list)
    aggs: list[Agg] = field(default_factory=list)
    # Verus boolean expression over row columns. Empty means every row.
    where_expr: str = ""
    having_expr: str = ""
    order_by: list[OrderKey] = field(default_factory=list)
    limit: int | None = None
    offset: int | None = None
    distinct: bool = False
    projection: list[str] = field(default_factory=list)
    set_op: str | None = None
    set_query: Query | None = None
    ctes: list[tuple[str, Query]] = field(default_factory=list)
    exists: list[tuple[str, Query, bool]] = field(default_factory=list)
    in_subqueries: list[tuple[str, str, Query]] = field(default_factory=list)
    scalar_subqueries: list[tuple[str, Query]] = field(default_factory=list)
    derived: list[tuple[str, Query]] = field(default_factory=list)
