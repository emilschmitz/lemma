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
    # Integer arithmetic over columns (bare or ``alias.col`` names), and the columns it reads.
    arith: str = ""
    arith_refs: tuple[str, ...] = ()
    # An aggregate that only HAVING reads. It is not an output column.
    hidden: bool = False
    # AVG over a DECIMAL column stored as value * 10**avg_scale: the average is in natural units.
    avg_scale: int = 0
    # ``AGG(x) FILTER (WHERE c)``: the aggregate sees only the rows where this spec condition holds (and the query's
    # WHERE). SQL's NULL-skipping aggregates over a nullable column are stated this way (``!is_null(col)``).
    filter_expr: str = ""
    # ``kind == "RATIO"``: (numerator alias, denominator alias, numerator constant, numerator scale, denominator
    # scale). The operands are hidden aggregates of the same query; the value is the real quotient
    # ``(K * N / 10**sN) / (D / 10**sD)``, with IEEE results for a zero denominator (DuckDB divides in DOUBLE).
    ratio: tuple[str, str, int, int, int] | None = None
    # A RATIO whose denominator is this nonzero whole-number constant (stored at the denominator scale), not an
    # aggregate: ``SUM(x) / 7.0`` is ``ratio_den_const == 70`` with denominator scale 1; the denominator alias is "".
    ratio_den_const: int | None = None
    # ``c * AVG(x)`` / ``AVG(x) * c`` for a constant c (DuckDB's DOUBLE product): the average is multiplied by
    # numerator/denominator, an exact rational (the float idealization states the product of the exact reals).
    avg_factor: tuple[int, int] = (1, 1)


@dataclass(frozen=True)
class Output:
    """One non-aggregate SELECT item of a subquery: a named column, date part, or integer expression."""

    name: str
    kind: str  # "column" | "extract" | "arith"
    text: str  # spec text over bare or ``alias.col`` names
    refs: tuple[str, ...] = ()  # columns an extract/arith text reads (must be integers)


@dataclass(frozen=True)
class Join:
    """One join. ``kind`` is inner, left, or right. Equalities are (left, right) column pairs."""

    kind: str
    table: str
    alias: str | None
    on: tuple[tuple[str, str], ...]
    on_combiner: str = "and"


@dataclass(frozen=True)
class CorrCount:
    """A group key that is, per row of the FROM table, the count of right-table rows matching it.

    ``SELECT n, COUNT(*) FROM (SELECT k, COUNT(r.c) AS n FROM L LEFT JOIN R ON r.fk = L.k AND pred GROUP BY k) d GROUP BY n``
    groups the rows of ``L`` by ``n = #{R rows: fk = k AND pred}`` (0 when none match), which
    is the left join's per-group count when ``k`` is unique in ``L`` and ``c`` is never NULL. Column references are kept as written; the emitter
    resolves them against the schema (which side of the ON equality is the right table, whether ``pred`` reads only it).
    """

    token: str  # the ``Query.group_exprs`` value that stands for the count
    right: str  # right table
    right_alias: str | None
    refs: tuple[str, str]  # the two sides of the ON equality, as written
    group_ref: str  # the inner GROUP BY column, as written (must be the left side of the equality)
    count_ref: str  # the counted column, as written (must belong to the right table)
    pred_sql: str  # the other ON conjuncts as SQL ("" when none); they may read the right table only


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
    # (table, column) pairs that must be declared unique keys for a rewrite to select the same rows.
    unique_needed: list[tuple[str, str]] = field(default_factory=list)
    exists: list[tuple[str, Query, bool]] = field(default_factory=list)
    in_subqueries: list[tuple[str, str, Query]] = field(default_factory=list)
    scalar_subqueries: list[tuple[str, Query]] = field(default_factory=list)
    derived: list[tuple[str, Query]] = field(default_factory=list)
    outputs: list[Output] = field(default_factory=list)
    # Output names in SELECT order, when every item is a named output or aggregate.
    select_order: list[str] = field(default_factory=list)
    # Group key name -> spec text, for keys that are a renamed column or a date part.
    group_exprs: dict[str, str] = field(default_factory=dict)
    # Column refs in WHERE/HAVING text that must be exact integers (decimal-literal compares).
    exact_int_refs: list[str] = field(default_factory=list)
    # Group keys that count right-table rows per FROM row (see ``CorrCount``).
    corr_counts: list[CorrCount] = field(default_factory=list)
