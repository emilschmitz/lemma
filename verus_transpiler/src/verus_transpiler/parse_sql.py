"""sqlglot parse for Lemma Basic SQL (Postgres/DuckDB-ish analytical subset)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import sqlglot
from sqlglot import exp

from .col_exprs import coerce_case_when_u64_args
from .dialect_flags import require_trusted
from .value_bounds import col_verus_type


class UnsupportedContractError(Exception):
    """Raised when a SQL query falls outside the supported Lemma Basic SQL subset."""


_INT_TYPES = frozenset({
    "int", "integer", "int4", "int32", "int2", "smallint", "int16",
    "int8", "int64", "bigint", "hugeint", "tinyint", "int1",
    "usmallint", "utinyint", "uinteger", "ubigint",
    "date",
    "decimal", "numeric", "double", "float8", "float", "real",
})
_STRING_TYPES = frozenset({"string", "varchar", "text", "char", "bpchar"})
_BOOL_TYPES = frozenset({"bool", "boolean"})
_DATE_LITERAL = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_I32_MIN, _I32_MAX = -2147483648, 2147483647
_I64_MIN, _I64_MAX = -9223372036854775808, 9223372036854775807


def _contains_non_int_number(node: exp.Expression) -> bool:
    if isinstance(node, exp.Literal) and node.is_number and not str(node.this).lstrip("-").isdigit():
        return True
    return any(
        _contains_non_int_number(child)
        for child in node.args.values()
        if isinstance(child, exp.Expression)
    )


def _refuse_hardware_const_overflow(left: int, right: int, result: int, op: str) -> None:
    """DuckDB types small literals as INT32 and does not widen the operation.

    ``100000 * 100000`` is an INT32 multiply, so DuckDB errors. A literal that
    does not fit in INT32, such as ``3000000000 * 2``, is BIGINT arithmetic.
    """
    if os.environ.get("LEMMA_EXACT_SUM", "0") != "1":
        return

    def width(value: int) -> int:
        if _I32_MIN <= value <= _I32_MAX:
            return 32
        if _I64_MIN <= value <= _I64_MAX:
            return 64
        return 128

    used = max(width(left), width(right))
    if used == 32:
        lo, hi, label = _I32_MIN, _I32_MAX, "INT32"
    elif used == 64:
        lo, hi, label = _I64_MIN, _I64_MAX, "INT64"
    else:
        return
    if lo <= result <= hi:
        return
    raise UnsupportedContractError(
        f"hardware menu does not fold {op} that overflows {label}: "
        "DuckDB rejects that literal arithmetic"
    )


def _refuse_hardware_date() -> None:
    """DuckDB will not compare an INTEGER column to a DATE."""
    if os.environ.get("LEMMA_EXACT_SUM", "0") == "1":
        raise UnsupportedContractError(
            "hardware menu does not emit DATE literals: DuckDB will not "
            "compare an INTEGER column to a DATE"
        )


def _date_from_cast(node: exp.Expression) -> date | None:
    if not isinstance(node, exp.Cast):
        return None
    to = node.args.get("to")
    if getattr(to, "this", None) != exp.DataType.Type.DATE:
        return None
    lit = node.this
    if not isinstance(lit, exp.Literal) or not lit.is_string:
        return None
    match = _DATE_LITERAL.match(str(lit.this))
    if match is None:
        return None
    year, month, day = (int(part) for part in match.groups())
    return date(year, month, day)


def _fold_date_interval(node: exp.Expression) -> str | None:
    """``DATE 'YYYY-MM-DD' ± INTERVAL n DAY|YEAR`` as a YYYYMMDD integer."""
    if not isinstance(node, (exp.Add, exp.Sub)):
        return None
    try:
        base = _date_from_cast(node.left)
    except ValueError as exc:
        raise UnsupportedContractError("DATE literal is not a calendar date.") from exc
    if base is not None:
        _refuse_hardware_date()
    interval = node.right
    if base is None or not isinstance(interval, exp.Interval):
        return None
    unit_node = interval.args.get("unit")
    unit = str(getattr(unit_node, "this", unit_node) or "").upper()
    lit = interval.this
    if not isinstance(lit, exp.Literal) or not str(lit.this).lstrip("-").isdigit():
        raise UnsupportedContractError("INTERVAL size must be an integer.")
    n = int(lit.this)
    if isinstance(node, exp.Sub):
        n = -n
    if unit == "DAY":
        shifted = base + timedelta(days=n)
    elif unit == "YEAR":
        try:
            shifted = base.replace(year=base.year + n)
        except ValueError as exc:
            raise UnsupportedContractError(
                f"DATE interval from {base.isoformat()} by {n} YEAR is not a calendar date."
            ) from exc
    else:
        raise UnsupportedContractError(f"INTERVAL unit {unit} is not supported.")
    return f"{shifted.year:04d}{shifted.month:02d}{shifted.day:02d}"


def _fold_int_literal(node: exp.Expression) -> str | None:
    """Integer constant, ``DATE 'YYYY-MM-DD'``, or arithmetic of those.

    A date literal is the ``YYYYMMDD`` integer the integer date columns store.
    A fractional literal is not an integer and stays unsupported.
    """
    if isinstance(node, exp.Paren):
        return _fold_int_literal(node.this)
    if isinstance(node, exp.Neg):
        inner = _fold_int_literal(node.this)
        if inner is None:
            return None
        return str(-int(inner))
    if isinstance(node, exp.Literal) and node.is_number and str(node.this).lstrip("-").isdigit():
        return str(int(node.this))
    if isinstance(node, exp.Cast):
        to = node.args.get("to")
        dtype = getattr(to, "this", None)
        if dtype != exp.DataType.Type.DATE:
            return None
        _refuse_hardware_date()
        lit = node.this
        if not isinstance(lit, exp.Literal) or not lit.is_string:
            return None
        match = _DATE_LITERAL.match(str(lit.this))
        if match is None:
            raise UnsupportedContractError(
                f"DATE literal {lit.this!r} is not YYYY-MM-DD."
            )
        year, month, day = (int(part) for part in match.groups())
        try:
            date(year, month, day)
        except ValueError as exc:
            raise UnsupportedContractError(
                f"DATE literal {lit.this!r} is not a calendar date."
            ) from exc
        return f"{year:04d}{month:02d}{day:02d}"
    if isinstance(node, (exp.Add, exp.Sub)):
        shifted = _fold_date_interval(node)
        if shifted is not None:
            return shifted
    if isinstance(node, (exp.Add, exp.Sub, exp.Mul)):
        left = _fold_int_literal(node.left)
        right = _fold_int_literal(node.right)
        if left is None or right is None:
            return None
        a, b = int(left), int(right)
        if isinstance(node, exp.Add):
            result = a + b
            op = "addition"
        elif isinstance(node, exp.Sub):
            result = a - b
            op = "subtraction"
        else:
            result = a * b
            op = "multiplication"
        _refuse_hardware_const_overflow(a, b, result, op)
        return str(result)
    return None


def _kind_of(col_type: str) -> str:
    t = col_type.lower()
    if t in _BOOL_TYPES or t.split("(")[0] in _BOOL_TYPES:
        return "bool"
    if t in _INT_TYPES or t.split("(")[0] in _INT_TYPES:
        return "int"
    if t in _STRING_TYPES or t.split("(")[0] in _STRING_TYPES:
        return "string"
    raise UnsupportedContractError(f"Unrecognized column type {col_type!r}")


def normalize_schema(
    schema: dict[str, str] | dict[str, dict[str, str]],
) -> tuple[dict[str, str], dict[str, dict[str, str]] | None]:
    """Return (flat_schema, multi_table_schema_or_none)."""
    if not schema:
        raise UnsupportedContractError("empty schema")
    first_val = next(iter(schema.values()))
    if isinstance(first_val, dict):
        multi: dict[str, dict[str, str]] = {
            str(table): {str(col): str(typ) for col, typ in cols.items()}
            for table, cols in schema.items()
            if isinstance(cols, dict)
        }
        flat: dict[str, str] = {}
        for _table, cols in multi.items():
            for col, typ in cols.items():
                if col in flat and flat[col] != typ:
                    raise UnsupportedContractError(
                        f"ambiguous column {col!r} across tables with different types"
                    )
                flat[col] = typ
        return flat, multi
    flat_single: dict[str, str] = {
        str(col): str(typ) for col, typ in schema.items() if isinstance(typ, str)
    }
    return flat_single, None


def _build_schema_resolver(
    schema: dict[str, str] | dict[str, dict[str, str]],
    table_aliases: dict[str, str] | None = None,
    *,
    cte_columns: dict[str, dict[str, str]] | None = None,
) -> dict[str, tuple[str, str, str | None]]:
    """Map lower-case column ref -> (canonical_col, type, table_or_none)."""
    flat, multi = normalize_schema(schema)
    resolver: dict[str, tuple[str, str, str | None]] = {}
    if multi is None:
        for col, typ in flat.items():
            resolver[col.lower()] = (col, typ, None)
    else:
        for table, cols in multi.items():
            for col, typ in cols.items():
                key = col.lower()
                if key in resolver:
                    existing = resolver[key]
                    if existing[1] != typ:
                        raise UnsupportedContractError(
                            f"ambiguous column {col!r} across tables"
                        )
                    continue
                resolver[key] = (col, typ, table)
        for alias, table in (table_aliases or {}).items():
            if table in multi:
                for col, typ in multi[table].items():
                    resolver[f"{alias}.{col}".lower()] = (col, typ, table)
                    resolver.setdefault(col.lower(), (col, typ, table))

    for cte_name, cols in (cte_columns or {}).items():
        for col, typ in cols.items():
            resolver[col.lower()] = (col, typ, cte_name)
            resolver[f"{cte_name}.{col}".lower()] = (col, typ, cte_name)

    return resolver


@dataclass
class AggSpec:
    agg_type: str
    agg_column: str
    agg_expr: str
    alias: str = ""


@dataclass
class JoinSpec:
    join_type: str
    table: str
    alias: str | None
    on_equalities: list[tuple[str, str]]
    # "and" (default equijoin) or "or" (disjunction of equalities).
    on_combiner: str = "and"


@dataclass
class ScalarSubquery:
    alias: str
    query: SQLQuery
    inner_table: str = ""
    inner_tables: list[str] = field(default_factory=list)
    correlated: bool = False
    correlation_cols: list[str] = field(default_factory=list)


def is_grouped_derived_scalar_subquery(query: SQLQuery) -> bool:
    """Scalar agg over one grouped derived/CTE subquery (e.g. HAVING AVG over JOIN GROUP BY)."""
    if not query.derived_tables or len(query.derived_tables) != 1:
        return False
    if query.agg_type not in ("AVG", "SUM", "MIN", "MAX", "COUNT"):
        return False
    inner = query.derived_tables[0].query
    if inner.is_multi_agg:
        return False
    if not inner.groupby_columns or not inner.agg_type:
        return False
    if inner.derived_tables or inner.scalar_subqueries or inner.exists_subqueries:
        return False
    if inner.union_query or inner.window_specs or inner.in_subqueries:
        return False
    return True


def grouped_derived_scalar_inner_tables(query: SQLQuery) -> list[str]:
    inner = query.derived_tables[0].query
    if inner.joins:
        return list(inner.tables)
    return [inner.tables[0]]


@dataclass
class DerivedTable:
    alias: str
    query: SQLQuery
    columns: dict[str, str] = field(default_factory=dict)
    source_column: str | None = None


@dataclass
class OrderByItem:
    expr: str
    column: str
    descending: bool = False


@dataclass
class WindowSpec:
    alias: str
    func: str
    partition_columns: list[str] = field(default_factory=list)
    order_columns: list[tuple[str, bool]] = field(default_factory=list)
    term_expr: str = ""


@dataclass
class CTESpec:
    name: str
    query: SQLQuery
    columns: dict[str, str] = field(default_factory=dict)
    recursive: bool = False


@dataclass
class ExistsSubquery:
    alias: str
    query: SQLQuery
    negated: bool = False
    correlated: bool = False
    correlation_cols: list[str] = field(default_factory=list)


@dataclass
class InSubquerySpec:
    alias: str
    column: str
    query: SQLQuery
    correlated: bool = False
    correlation_cols: list[str] = field(default_factory=list)


@dataclass
class SQLQuery:
    tables: list[str] = field(default_factory=list)
    table_aliases: dict[str, str] = field(default_factory=dict)
    joins: list[JoinSpec] = field(default_factory=list)
    agg_type: str = ""
    agg_column: str = ""
    groupby_columns: list[str] = field(default_factory=list)
    groupby_tables: list[str | None] = field(default_factory=list)
    where_conditions: list[tuple[str, str, object, str]] = field(default_factory=list)
    agg_expr: str = ""
    agg_specs: list[AggSpec] = field(default_factory=list)
    select_aliases: dict[str, int] = field(default_factory=dict)
    where_expr: str = ""
    scalar_subqueries: list[ScalarSubquery] = field(default_factory=list)
    derived_tables: list[DerivedTable] = field(default_factory=list)
    having_expr: str = ""
    order_by: list[OrderByItem] = field(default_factory=list)
    limit: int | None = None
    offset: int | None = None
    distinct: bool = False
    union_all: bool | None = None
    union_query: SQLQuery | None = None
    intersect_all: bool | None = None
    intersect_query: SQLQuery | None = None
    except_all: bool | None = None
    except_query: SQLQuery | None = None
    correlated: bool = False
    ctes: list[CTESpec] = field(default_factory=list)
    exists_subqueries: list[ExistsSubquery] = field(default_factory=list)
    in_subqueries: list[InSubquerySpec] = field(default_factory=list)
    window_specs: list[WindowSpec] = field(default_factory=list)
    is_projection: bool = False
    projection_columns: list[str] = field(default_factory=list)
    projection_exprs: list[str] = field(default_factory=list)
    projection_types: list[str] = field(default_factory=list)
    groupby_exprs: list[str] = field(default_factory=list)
    groupby_types: list[str] = field(default_factory=list)

    @property
    def table(self) -> str:
        return self.tables[0] if self.tables else ""

    @property
    def has_order_or_limit(self) -> bool:
        return bool(self.order_by) or self.limit is not None or self.offset is not None

    @property
    def is_multi_agg(self) -> bool:
        return len(self.agg_specs) > 1


def _sync_primary_agg(query: SQLQuery) -> None:
    """Keep agg_type/agg_column/agg_expr aligned with first agg_specs entry."""
    if query.agg_specs:
        first = query.agg_specs[0]
        query.agg_type = first.agg_type
        query.agg_column = first.agg_column
        query.agg_expr = first.agg_expr


def _outer_table_names(query: SQLQuery) -> set[str]:
    """Table and alias names visible to correlated subqueries."""
    names = set(query.tables)
    names.update(query.table_aliases.keys())
    return names


def _check_forbidden_nodes(expression: exp.Expression) -> None:
    """Reject constructs outside Lemma Basic SQL."""
    for node in expression.walk():
        if isinstance(node, exp.Window):
            require_trusted("window")
        if isinstance(node, exp.SimilarTo):
            raise UnsupportedContractError("SIMILAR TO / regex LIKE are not supported.")
        if isinstance(node, exp.Join):
            side = (node.side or node.kind or "INNER").upper()
            if side in ("FULL",):
                require_trusted("full_join")
            elif side == "CROSS":
                require_trusted("cross_join")
            elif side in ("SEMI", "ANTI"):
                require_trusted("semi_anti_join")
            # RIGHT JOIN: honest side-swap to outer-join MethodSpec (not TRUSTED).
        if isinstance(node, exp.ILike):
            require_trusted("ilike")
        if isinstance(node, (exp.Intersect, exp.Except)):
            require_trusted("intersect_except")
        if isinstance(node, exp.With):
            if node.args.get("recursive"):
                require_trusted("recursive_cte")
        if isinstance(node, exp.Case):
            require_trusted("case_when")


def _parse_table_ref(node: exp.Expression) -> tuple[str, str | None]:
    if isinstance(node, exp.Table):
        return node.name, node.alias or None
    if isinstance(node, exp.Alias) and isinstance(node.this, exp.Table):
        return node.this.name, node.alias
    raise UnsupportedContractError("Query falls outside the supported Lemma Basic SQL subset.")


def _parse_agg_item(
    node: exp.Expression,
    resolver: dict[str, tuple[str, str, str | None]],
    *,
    alias: str = "",
) -> AggSpec:
    """Parse one aggregate SELECT item into AggSpec."""
    inner = _unwrap_alias(node)
    item_alias = alias or (node.alias if isinstance(node, exp.Alias) else "")

    if isinstance(inner, exp.Count):
        if isinstance(inner.this, exp.Distinct):
            distinct_col = inner.this.expressions[0]
            if not isinstance(distinct_col, exp.Column):
                raise UnsupportedContractError(
                    "COUNT(DISTINCT) argument must be a column."
                )
            real_col, _, _ = _resolve_col(distinct_col, resolver)
            require_trusted("count_distinct")
            return AggSpec(
                agg_type="COUNT_DISTINCT",
                agg_column=real_col,
                agg_expr=f"row.{real_col}",
                alias=item_alias,
            )
        if isinstance(inner.this, exp.Star):
            return AggSpec(
                agg_type="COUNT",
                agg_column="*",
                agg_expr="1",
                alias=item_alias,
            )
        if not isinstance(inner.this, exp.Column):
            raise UnsupportedContractError("COUNT argument must be * or a column.")
        real_col, _, _ = _resolve_col(inner.this, resolver)
        return AggSpec(
            agg_type="COUNT",
            agg_column=real_col,
            agg_expr="1",
            alias=item_alias,
        )
    if isinstance(inner, exp.Min):
        return AggSpec(
            agg_type="MIN",
            agg_column=inner.this.sql() if hasattr(inner.this, "sql") else "",
            agg_expr=_to_row_expr(inner.this, resolver),
            alias=item_alias,
        )
    if isinstance(inner, exp.Max):
        return AggSpec(
            agg_type="MAX",
            agg_column=inner.this.sql() if hasattr(inner.this, "sql") else "",
            agg_expr=_to_row_expr(inner.this, resolver),
            alias=item_alias,
        )
    if isinstance(inner, exp.Sum):
        return AggSpec(
            agg_type="SUM",
            agg_column=inner.this.sql() if hasattr(inner.this, "sql") else "",
            agg_expr=_to_row_expr(inner.this, resolver),
            alias=item_alias,
        )
    if isinstance(inner, exp.Avg):
        return AggSpec(
            agg_type="AVG",
            agg_column=inner.this.sql() if hasattr(inner.this, "sql") else "",
            agg_expr=_to_row_expr(inner.this, resolver),
            alias=item_alias,
        )
    raise UnsupportedContractError(
        f"Unsupported aggregate expression: {type(inner)}"
    )


def _left_join_aliases(query: SQLQuery) -> set[str]:
    """Table aliases introduced by LEFT JOIN (for anti-join IS NULL checks)."""
    aliases: set[str] = set()
    for join in query.joins:
        if join.join_type == "LEFT":
            if join.alias:
                aliases.add(join.alias.lower())
            aliases.add(join.table.lower())
    return aliases


def _compile_is_null_check(
    col_node: exp.Column,
    is_null: bool,
    resolver: dict[str, tuple[str, str, str | None]],
    query: SQLQuery,
) -> str:
    """Compile IS [NOT] NULL for Lemma non-nullable column loads.

    Base-table cells are always present (non-null). LEFT JOIN miss uses
    anti-join sentinel: right-side IS NULL => no matching join row.
    """
    require_trusted("null_3vl")
    real_col, col_type, table = _resolve_col(col_node, resolver)
    query.where_conditions.append(
        (real_col, "IS NOT NULL" if not is_null else "IS NULL", None, col_type)
    )
    col_ref = f"row.{real_col}"
    tbl_prefix = (col_node.table or "").lower()
    if tbl_prefix and tbl_prefix in _left_join_aliases(query):
        if is_null:
            return "left_join_miss_generic(cols, 0)"
        return "!left_join_miss_generic(cols, 0)"
    # Hardware columns have no null bit. Empty string is not SQL NULL.
    if os.environ.get("LEMMA_EXACT_SUM", "0") == "1":
        if is_null:
            return "false"
        return "true"
    # Lemma loads non-null cells for typed columns.
    if _kind_of(col_type) == "string":
        if is_null:
            return f"({col_ref} == \"\"@)"
        return f"({col_ref} != \"\"@)"
    if is_null:
        return "false"
    return "true"


def _parse_join_from(
    node: exp.Expression,
    schema: dict[str, str] | dict[str, dict[str, str]],
    resolver: dict[str, tuple[str, str, str | None]],
    *,
    parent_ctes: list[CTESpec] | None = None,
) -> tuple[str, str | None, DerivedTable | None]:
    """Parse JOIN/FROM table ref; derived subquery returns (alias, alias, DerivedTable)."""
    if isinstance(node, exp.Subquery):
        require_trusted("derived_join")
        inner_select = node.this
        if not isinstance(inner_select, exp.Select):
            raise UnsupportedContractError("derived JOIN table must be SELECT.")
        inner_q = _parse_select(
            inner_select,
            schema,
            allow_subqueries=False,
            derived_inner=True,
            parent_ctes=parent_ctes,
        )
        alias = node.alias or "derived"
        exposed, source_col = _derived_exposed_columns(
            inner_q, inner_select, resolver,
        )
        derived = DerivedTable(
            alias=alias,
            query=inner_q,
            columns=exposed,
            source_column=source_col,
        )
        return alias, alias, derived
    table_name, alias = _parse_table_ref(node)
    return table_name, alias, None


def _parse_on_equalities(
    on_expr: exp.Expression | None,
    *,
    allow_missing: bool = False,
) -> list[tuple[str, str]]:
    """Parse ON equalities (AND or OR). Prefer ``_parse_on_clause`` for combiner."""
    eqs, _combiner = _parse_on_clause(on_expr, allow_missing=allow_missing)
    return eqs


def _parse_on_clause(
    on_expr: exp.Expression | None,
    *,
    allow_missing: bool = False,
) -> tuple[list[tuple[str, str]], str]:
    """Return (equalities, combiner) where combiner is ``and`` or ``or``."""
    if on_expr is None:
        if allow_missing:
            return [], "and"
        raise UnsupportedContractError("JOIN requires ON clause with equality predicates.")

    def eq_pair(node: exp.EQ) -> tuple[str, str]:
        if not isinstance(node.left, exp.Column) or not isinstance(node.right, exp.Column):
            raise UnsupportedContractError("JOIN ON must be column equality.")
        left_ref = ".".join(p for p in (node.left.table, node.left.name) if p)
        right_ref = ".".join(p for p in (node.right.table, node.right.name) if p)
        return (left_ref or node.left.name, right_ref or node.right.name)

    def collect_and(node: exp.Expression, out: list[tuple[str, str]]) -> None:
        if isinstance(node, exp.And):
            collect_and(node.left, out)
            collect_and(node.right, out)
        elif isinstance(node, exp.EQ):
            out.append(eq_pair(node))
        elif isinstance(node, exp.Or):
            raise UnsupportedContractError(
                "JOIN ON does not mix AND and OR; use OR of equalities alone."
            )
        elif isinstance(node, exp.Paren):
            collect_and(node.this, out)
        else:
            raise UnsupportedContractError("JOIN ON supports only =, AND of =, or OR of =.")

    def collect_or(node: exp.Expression, out: list[tuple[str, str]]) -> None:
        if isinstance(node, exp.Or):
            collect_or(node.left, out)
            collect_or(node.right, out)
        elif isinstance(node, exp.EQ):
            out.append(eq_pair(node))
        elif isinstance(node, exp.And):
            raise UnsupportedContractError(
                "JOIN ON does not mix AND and OR; use OR of equalities alone."
            )
        elif isinstance(node, exp.Paren):
            collect_or(node.this, out)
        else:
            raise UnsupportedContractError("JOIN ON supports only =, AND of =, or OR of =.")

    # Peel top-level parens to choose combiner.
    root = on_expr
    while isinstance(root, exp.Paren):
        root = root.this

    equalities: list[tuple[str, str]] = []
    if isinstance(root, exp.Or):
        collect_or(root, equalities)
        combiner = "or"
    else:
        collect_and(root, equalities)
        combiner = "and"
    if not equalities:
        raise UnsupportedContractError("JOIN requires at least one equality predicate.")
    if combiner == "or" and len(equalities) < 2:
        raise UnsupportedContractError("JOIN ON OR requires at least two equalities.")
    return equalities, combiner


def groupby_schema(
    flat_schema: dict[str, str],
    query: SQLQuery,
) -> dict[str, str]:
    """Catalog columns plus virtual GROUP BY keys (derived flatten / expressions)."""
    merged = dict(flat_schema)
    for col, typ in zip(query.groupby_columns, query.groupby_types, strict=False):
        if typ and col not in merged:
            merged[col] = typ
    return merged


def _unwrap_alias(node: exp.Expression) -> exp.Expression:
    if isinstance(node, exp.Alias):
        return node.this
    return node


def _is_aggregate_expr(node: exp.Expression) -> bool:
    """True for SUM/COUNT/AVG/MIN/MAX, including COUNT(DISTINCT col)."""
    inner = _unwrap_alias(node)
    return isinstance(inner, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max))


def _collect_aggregate_exprs(node: exp.Expression) -> list[exp.Expression]:
    """Collect aggregate expression nodes from a predicate tree (e.g. HAVING).

    Does not descend into scalar subqueries: inner aggregates (including
    references to derived-table column aliases like ``sub_total``) are parsed
    by the subquery's own resolver, not the outer query's.
    """
    found: list[exp.Expression] = []
    for child in node.walk(prune=lambda n: isinstance(n, exp.Subquery)):
        if _is_aggregate_expr(child):
            found.append(child)
    return found


def _agg_spec_key(spec: AggSpec) -> tuple[str, str, str]:
    return (spec.agg_type, spec.agg_column, spec.agg_expr)


def _append_agg_specs_from_exprs(
    nodes: list[exp.Expression],
    resolver: dict[str, tuple[str, str, str | None]],
    query: SQLQuery,
) -> None:
    """Parse aggregate nodes into query.agg_specs, skipping duplicates."""
    existing = {_agg_spec_key(s) for s in query.agg_specs}
    for node in nodes:
        spec = _parse_agg_item(node, resolver)
        key = _agg_spec_key(spec)
        if key in existing:
            continue
        existing.add(key)
        if spec.alias:
            query.select_aliases[spec.alias.lower()] = len(query.agg_specs)
        query.agg_specs.append(spec)


def _resolve_col(
    node: exp.Column,
    resolver: dict[str, tuple[str, str, str | None]],
) -> tuple[str, str, str | None]:
    parts = []
    if node.table:
        parts.append(node.table)
    parts.append(node.name)
    ref = ".".join(parts).lower()
    if ref in resolver:
        return resolver[ref]
    key = node.name.lower()
    if key in resolver:
        return resolver[key]
    raise UnsupportedContractError(f"Identifier '{node.name}' not found in schema.")


def query_is_self_join(query: SQLQuery) -> bool:
    """True when the same base catalog table appears under two (or more) FROM/JOIN slots."""
    derived = {d.alias for d in query.derived_tables}
    base = [t for t in query.tables if t not in derived]
    return len(base) >= 2 and len(base) != len(set(base))


def _compile_column_ref(
    node: exp.Column,
    resolver: dict[str, tuple[str, str, str | None]],
    outer_name_lower: set[str],
    *,
    outer_resolver: dict[str, tuple[str, str, str | None]] | None = None,
    qualify_alias: bool = False,
) -> tuple[str, str]:
    """Compile a column to row./outer. expression and type kind."""
    if outer_name_lower and node.table and node.table.lower() in outer_name_lower:
        lookup = outer_resolver if outer_resolver is not None else resolver
        real_col, col_type, _ = _resolve_col(node, lookup)
        return f"outer.{real_col}", _kind_of(col_type)
    real_col, col_type, _ = _resolve_col(node, resolver)
    # Self-join: keep the SQL alias so join slots can tell a.line from b.line.
    if qualify_alias and node.table:
        return f"row.{node.table}.{real_col}", _kind_of(col_type)
    return f"row.{real_col}", _kind_of(col_type)


def _compile_row_bool_expr(
    node: exp.Expression,
    resolver: dict[str, tuple[str, str, str | None]],
) -> str:
    """Compile a boolean expression over row.* for CASE WHEN conditions."""
    if isinstance(node, exp.And):
        return (
            f"({_compile_row_bool_expr(node.left, resolver)}"
            f" && {_compile_row_bool_expr(node.right, resolver)})"
        )
    if isinstance(node, exp.Or):
        return (
            f"({_compile_row_bool_expr(node.left, resolver)}"
            f" || {_compile_row_bool_expr(node.right, resolver)})"
        )
    if isinstance(node, exp.Not):
        return f"!({_compile_row_bool_expr(node.this, resolver)})"
    if isinstance(node, exp.EQ):
        left = _row_scalar_expr(node.left, resolver)
        right = _row_scalar_expr(node.right, resolver)
        return f"({left} == {right})"
    if isinstance(node, (exp.GT, exp.GTE, exp.LT, exp.LTE, exp.NEQ)):
        op_map = {
            exp.GT: ">",
            exp.GTE: ">=",
            exp.LT: "<",
            exp.LTE: "<=",
            exp.NEQ: "!=",
        }
        left = _row_scalar_expr(node.left, resolver)
        right = _row_scalar_expr(node.right, resolver)
        return f"({left} {op_map[type(node)]} {right})"
    if isinstance(node, exp.Paren):
        return f"({_compile_row_bool_expr(node.this, resolver)})"
    raise UnsupportedContractError(
        f"Unsupported CASE WHEN condition construct: {type(node)}"
    )


def _row_scalar_expr(
    node: exp.Expression,
    resolver: dict[str, tuple[str, str, str | None]],
) -> str:
    if isinstance(node, exp.Column):
        real_col, col_type, _ = _resolve_col(node, resolver)
        if _kind_of(col_type) == "string":
            raise UnsupportedContractError("CASE WHEN compares int columns only.")
        return f"row.{real_col}"
    if isinstance(node, exp.Literal):
        if node.is_number:
            return str(node.this)
        if node.is_string:
            return f'"{node.this}"@'
        raise UnsupportedContractError("Only integer/string literals in CASE WHEN.")
    if isinstance(node, exp.Paren):
        return f"({_row_scalar_expr(node.this, resolver)})"
    raise UnsupportedContractError(f"Unsupported scalar in CASE WHEN: {type(node)}")


def _compile_case_expr(
    node: exp.Case,
    resolver: dict[str, tuple[str, str, str | None]],
) -> str:
    require_trusted("case_when")
    ifs = node.args.get("ifs") or []
    if not ifs:
        raise UnsupportedContractError("CASE requires at least one WHEN branch.")
    default = node.args.get("default")
    if default is None and os.environ.get("LEMMA_EXACT_SUM", "0") == "1":
        raise UnsupportedContractError(
            "hardware menu does not emit CASE without ELSE: DuckDB yields "
            "NULL, and this helper substitutes 0"
        )
    else_expr = _to_row_expr(default, resolver) if default is not None else "0"
    result = else_expr
    for if_node in reversed(ifs):
        cond = _compile_row_bool_expr(if_node.this, resolver)
        then_expr = _to_row_expr(if_node.args["true"], resolver)
        result = f"case_when_u64({cond}, {then_expr}, {result})"
    return coerce_case_when_u64_args(result)


def _compile_extract_year(
    node: exp.Extract,
    resolver: dict[str, tuple[str, str, str | None]],
) -> str:
    if os.environ.get("LEMMA_EXACT_SUM", "0") == "1":
        raise UnsupportedContractError(
            "hardware menu does not emit EXTRACT: DuckDB has no date_part "
            "on an INTEGER column"
        )
    part = node.this
    part_name = str(getattr(part, "name", part)).lower()
    if part_name != "year":
        raise UnsupportedContractError("EXTRACT supports YEAR only.")
    inner = node.expression
    if not isinstance(inner, exp.Column):
        raise UnsupportedContractError("EXTRACT(YEAR FROM ...) requires a column.")
    real_col, col_type, _ = _resolve_col(inner, resolver)
    if _kind_of(col_type) != "int":
        raise UnsupportedContractError(
            "EXTRACT(YEAR FROM ...) requires an integer date column."
        )
    return f"((row.{real_col} as int) / 10000)"


def _compile_select_expr(
    node: exp.Expression,
    resolver: dict[str, tuple[str, str, str | None]],
    *,
    qualify_alias: bool = False,
) -> tuple[str, str]:
    """Compile one SELECT list expression to a row.* spec string and schema type."""
    inner = _unwrap_alias(node)
    if isinstance(inner, exp.Extract):
        return _compile_extract_year(inner, resolver), "int"
    if isinstance(inner, exp.Column):
        real_col, col_type, _ = _resolve_col(inner, resolver)
        if _kind_of(col_type) == "string":
            if qualify_alias and inner.table:
                return f"row.{inner.table}.{real_col}", col_type
            return f"row.{real_col}", col_type
        if qualify_alias and inner.table:
            return f"(row.{inner.table}.{real_col} as int)", col_type
        return f"(row.{real_col} as int)", col_type
    if isinstance(
        inner,
        (exp.Literal, exp.Neg, exp.Paren, exp.Mul, exp.Div, exp.Add, exp.Sub, exp.Abs),
    ):
        return _to_row_expr(inner, resolver), "int"
    raise UnsupportedContractError(
        f"Unsupported SELECT expression construct: {type(inner)}"
    )


def _to_row_expr(
    node: exp.Expression,
    resolver: dict[str, tuple[str, str, str | None]],
) -> str:
    if isinstance(node, exp.Extract):
        return _compile_extract_year(node, resolver)
    if isinstance(node, exp.Column):
        real_col, col_type, _table = _resolve_col(node, resolver)
        if _kind_of(col_type) != "int":
            raise UnsupportedContractError(
                f"Column '{real_col}' in expression must be of type 'int'."
            )
        return f"(row.{real_col} as int)"
    if isinstance(node, exp.Literal):
        if node.is_number and str(node.this).lstrip("-").isdigit():
            return str(node.this)
        raise UnsupportedContractError("Only integer literals supported in expressions.")
    if isinstance(node, exp.Neg):
        return f"-{_to_row_expr(node.this, resolver)}"
    if isinstance(node, exp.Paren):
        return f"({_to_row_expr(node.this, resolver)})"
    if isinstance(node, exp.Mul):
        # WHERE folds this product. SUM leaves the operator in the spec.
        # Either way an overflowing INT32/INT64 literal product is a DuckDB error.
        _fold_int_literal(node)
        return f"{_to_row_expr(node.left, resolver)} * {_to_row_expr(node.right, resolver)}"
    if isinstance(node, exp.Div):
        # DuckDB `/` on integers is DOUBLE division. The integer `/` below
        # truncates, so SUM(5 / 2) is 2 here and 2.5 in DuckDB.
        if os.environ.get("LEMMA_EXACT_SUM", "0") == "1":
            raise UnsupportedContractError(
                "hardware menu does not emit division: DuckDB `/` is real "
                "division (DOUBLE), not integer division"
            )
        if isinstance(node.right, exp.Literal) and node.right.this == "0":
            raise UnsupportedContractError("Division by zero literal is not supported.")
        return f"{_to_row_expr(node.left, resolver)} / {_to_row_expr(node.right, resolver)}"
    if isinstance(node, exp.Add):
        _fold_int_literal(node)
        return f"{_to_row_expr(node.left, resolver)} + {_to_row_expr(node.right, resolver)}"
    if isinstance(node, exp.Sub):
        return f"{_to_row_expr(node.left, resolver)} - {_to_row_expr(node.right, resolver)}"
    if isinstance(node, exp.Abs):
        return f"abs_u64(({_to_row_expr(node.this, resolver)}) as u64)"
    if isinstance(node, exp.Lower):
        if not isinstance(node.this, exp.Column):
            raise UnsupportedContractError("LOWER argument must be a column.")
        real_col, col_type, _ = _resolve_col(node.this, resolver)
        if _kind_of(col_type) != "string":
            raise UnsupportedContractError("LOWER is only supported on string columns.")
        return f"str_lower(row.{real_col})"
    if isinstance(node, exp.Upper):
        if not isinstance(node.this, exp.Column):
            raise UnsupportedContractError("UPPER argument must be a column.")
        real_col, col_type, _ = _resolve_col(node.this, resolver)
        if _kind_of(col_type) != "string":
            raise UnsupportedContractError("UPPER is only supported on string columns.")
        return f"str_upper(row.{real_col})"
    if isinstance(node, exp.Star):
        return "*"
    if isinstance(node, exp.Case):
        return _compile_case_expr(node, resolver)
    raise UnsupportedContractError(f"Unsupported expression construct: {type(node)}")


def _compile_like_pattern(real_col: str, pattern: str) -> str:
    """Compile LIKE (% prefix/suffix/contains; _ single-char via TRUSTED helper)."""
    col_ref = f"row.{real_col}"
    if "_" in pattern:
        require_trusted("like_underscore")
        if any(c in pattern for c in "[]|^$.*+?"):
            raise UnsupportedContractError(
                "LIKE with _ supports only % and _ wildcards (no regex)."
            )
        return f'str_like_underscore_match({col_ref}, "{pattern}"@)'
    if any(c in pattern for c in "[]|^$.*+?"):
        raise UnsupportedContractError(
            "LIKE supports only % prefix/suffix/contains wildcards (no regex)."
        )
    # Each % is a wildcard. %% is the same wildcard as %, not a literal percent.
    pattern = re.sub(r"%+", "%", pattern)
    if pattern == "%":
        return f'str_like_contains({col_ref}, ""@)'
    if pattern.startswith("%") and pattern.endswith("%") and len(pattern) >= 2:
        lit = pattern[1:-1]
        if "%" in lit:
            raise UnsupportedContractError(
                f"unsupported LIKE pattern {pattern!r} (use %foo%, foo%, or %foo)"
            )
        return f'str_like_contains({col_ref}, "{lit}"@)'
    if pattern.endswith("%") and not pattern.startswith("%"):
        lit = pattern[:-1]
        return f'str_like_prefix({col_ref}, "{lit}"@)'
    if pattern.startswith("%") and not pattern.endswith("%"):
        lit = pattern[1:]
        return f'str_like_suffix({col_ref}, "{lit}"@)'
    if "%" not in pattern:
        return f'{col_ref} == "{pattern}"@'
    raise UnsupportedContractError(
        f"unsupported LIKE pattern {pattern!r} (use %foo%, foo%, or %foo)"
    )


def _compile_ilike_pattern(real_col: str, pattern: str) -> str:
    """Compile ILIKE via TRUSTED case-insensitive pattern helper."""
    if os.environ.get("LEMMA_EXACT_SUM", "0") == "1":
        raise UnsupportedContractError(
            "hardware menu does not emit ILIKE: DuckDB folds Unicode case, "
            "and this helper folds ASCII only"
        )
    require_trusted("ilike")
    col_ref = f"row.{real_col}"
    if any(c in pattern for c in "[]|^$.*+?"):
        raise UnsupportedContractError(
            "ILIKE supports only % and _ wildcards (no regex)."
        )
    return f'str_ilike_match({col_ref}, "{pattern}"@)'


def _detect_correlation(
    inner: SQLQuery,
    schema_cols: set[str],
) -> list[str]:
    """Return column names referenced by inner query that are not in its schema."""
    refs: set[str] = set()
    for expr in (inner.where_expr, inner.having_expr, *inner.projection_exprs):
        for m in re.finditer(r"row\.([A-Za-z_][A-Za-z0-9_]*)", expr):
            refs.add(m.group(1))
        for m in re.finditer(r"outer\.([A-Za-z_][A-Za-z0-9_]*)", expr):
            refs.add(m.group(1))
    return [c for c in refs if c not in schema_cols]


def _outer_base_table(query: SQLQuery) -> str | None:
    derived = {d.alias for d in query.derived_tables}
    base = [t for t in query.tables if t not in derived]
    if base:
        return base[0]
    return query.tables[0] if query.tables else None


def inner_base_tables(query: SQLQuery) -> list[str]:
    """Catalog base tables in a subquery FROM (+ JOIN), excluding derived aliases."""
    derived = {d.alias for d in query.derived_tables}
    return [t for t in query.tables if t not in derived]


def _select_base_table_names(select: exp.Select) -> list[str]:
    """Base catalog table names from a SELECT's FROM + JOIN clauses (AST)."""
    names: list[str] = []
    from_clause = select.args.get("from_")
    if not from_clause:
        return names
    from_this = from_clause.this
    if isinstance(from_this, exp.Subquery):
        return names
    try:
        table_name, _alias = _parse_table_ref(from_this)
        names.append(table_name)
    except UnsupportedContractError:
        pass
    for join in select.args.get("joins") or []:
        if isinstance(join.this, exp.Subquery):
            continue
        try:
            jtable, _jalias = _parse_table_ref(join.this)
            names.append(jtable)
        except UnsupportedContractError:
            continue
    return names


def support_spec_params(query: SQLQuery) -> list[tuple[str, str, str]]:
    """Inner catalog tables (not the outer FROM) that MethodSpec must take as extra args."""
    derived = {d.alias for d in query.derived_tables}
    outer = {t for t in query.tables if t not in derived}
    extras: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    def add_inner(inner: SQLQuery) -> None:
        include_overlap = bool(inner.joins)
        for table in inner_base_tables(inner):
            if table in derived:
                continue
            if table in outer and not include_overlap:
                continue
            if table in seen:
                continue
            seen.add(table)
            extras.append((table, f"Cols_{table}", f"valid_cols_{table}"))

    for exists in query.exists_subqueries:
        add_inner(exists.query)
    for in_sub in query.in_subqueries:
        add_inner(in_sub.query)
    for sub in query.scalar_subqueries:
        inner_tables = sub.inner_tables or (
            [sub.inner_table] if sub.inner_table else list(sub.query.tables)
        )
        dummy = SQLQuery(tables=list(inner_tables))
        add_inner(dummy)
    return extras


def _inner_spec_arg(
    inner_tables: list[str],
    *,
    join_context: bool,
    outer_table: str | None,
) -> str:
    """Inner table ident for EXISTS/IN/scalar calls; ``cols`` only if inner is the outer table."""
    if join_context:
        return "__INNER__"
    deduped: list[str] = []
    for table in inner_tables:
        if table not in deduped:
            deduped.append(table)
    if len(deduped) > 1:
        return ", ".join(deduped)
    if deduped:
        inner = deduped[0]
        if outer_table is None or inner != outer_table:
            return inner
    return "cols"


def _scalar_subquery_spec_call(
    sub: ScalarSubquery,
    *,
    join_context: bool = False,
    outer_table: str | None = None,
) -> str:
    """Placeholder call for join rewriter: __INNER__ table param, outer.{col} accessors."""
    tables = list(sub.inner_tables) or ([sub.inner_table] if sub.inner_table else list(sub.query.tables))
    inner_arg = _inner_spec_arg(tables, join_context=join_context, outer_table=outer_table)
    if sub.correlated:
        outer_args = ", ".join(f"outer.{c}" for c in sub.correlation_cols)
        return f"subquery_{sub.alias}_spec({inner_arg}, {outer_args})"
    return f"subquery_{sub.alias}_spec({inner_arg})"


def _corr_outer_key_expr(correlation_cols: list[str], *, join_context: bool) -> str:
    prefix = "outer" if join_context else "row"
    parts = [f"{prefix}.{c}" for c in correlation_cols]
    if not parts:
        return f"{prefix}.key"
    if len(parts) == 1:
        return parts[0]
    return f"({', '.join(parts)})"


def _exists_subquery_spec_call(
    exists: ExistsSubquery,
    *,
    join_context: bool = False,
    outer_table: str | None = None,
) -> str:
    inner_arg = _inner_spec_arg(
        inner_base_tables(exists.query),
        join_context=join_context,
        outer_table=outer_table,
    )
    if exists.correlated:
        outer_key = _corr_outer_key_expr(
            exists.correlation_cols, join_context=join_context,
        )
        return f"exists_corr_{exists.alias}_spec({inner_arg}, {outer_key})"
    return f"exists_{exists.alias}_spec({inner_arg})"


def _in_subquery_contains_call(
    in_spec: InSubquerySpec,
    *,
    join_context: bool = False,
    outer_table: str | None = None,
) -> str:
    inner_arg = _inner_spec_arg(
        inner_base_tables(in_spec.query),
        join_context=join_context,
        outer_table=outer_table,
    )
    if in_spec.correlated:
        outer_key = _corr_outer_key_expr(
            in_spec.correlation_cols, join_context=join_context,
        )
        return (
            f"in_corr_{in_spec.alias}_contains("
            f"{inner_arg}, row.{in_spec.column}, {outer_key})"
        )
    return f"in_{in_spec.alias}_contains({inner_arg}, row.{in_spec.column})"


def _detect_correlation_sql(
    inner_select: exp.Select,
    outer_names: set[str],
) -> list[str]:
    """Detect outer-table-qualified column refs inside a subquery SELECT."""
    outer_lower = {n.lower() for n in outer_names}
    refs: list[str] = []
    seen: set[str] = set()
    for col in inner_select.find_all(exp.Column):
        tbl = col.table
        if tbl and tbl.lower() in outer_lower:
            if col.name not in seen:
                seen.add(col.name)
                refs.append(col.name)
    return refs


def _subquery_inner_schema(
    select: exp.Select,
    schema: dict[str, str] | dict[str, dict[str, str]],
) -> dict[str, str]:
    """Columns visible from the subquery's own FROM + JOIN base tables (not outer)."""
    flat, multi = normalize_schema(schema)
    if not multi:
        return dict(flat)
    table_names = _select_base_table_names(select)
    if not table_names:
        return dict(flat)
    merged: dict[str, str] = {}
    for table_name in table_names:
        if table_name not in multi:
            continue
        for col, typ in multi[table_name].items():
            if col in merged and merged[col] != typ:
                raise UnsupportedContractError(
                    f"ambiguous column {col!r} across inner join tables with different types"
                )
            merged[col] = typ
    if merged:
        return merged
    return dict(flat)


def _parse_exists_subquery(
    node: exp.Exists,
    outer_resolver: dict[str, tuple[str, str, str | None]],
    outer_tables: set[str],
    *,
    alias_prefix: str,
    counter: list[int],
    catalog_schema: dict[str, str] | dict[str, dict[str, str]] | None = None,
) -> ExistsSubquery:
    inner_select = node.this
    if not isinstance(inner_select, exp.Select):
        raise UnsupportedContractError("EXISTS subquery must be a SELECT.")
    flat_schema = {c: t for c, t, _ in outer_resolver.values()}
    schema = catalog_schema if catalog_schema is not None else flat_schema
    inner_schema = _subquery_inner_schema(inner_select, schema)
    outer_names = set(outer_tables) | {
        k.split(".")[0] for k in outer_resolver if "." in k
    }
    inner = _parse_select(
        inner_select,
        inner_schema,
        allow_subqueries=True,
        correlation_outer_names=outer_names,
        catalog_schema=schema,
        outer_resolver=outer_resolver,
    )
    correlated_cols = _detect_correlation_sql(inner_select, outer_names)
    if not correlated_cols:
        correlated_cols = _detect_correlation(inner, set(inner_schema.keys()))
    correlated = bool(correlated_cols)
    if correlated:
        require_trusted("correlated_subquery")
    counter[0] += 1
    alias = f"{alias_prefix}{counter[0]}"
    return ExistsSubquery(
        alias=alias,
        query=inner,
        negated=False,
        correlated=correlated,
        correlation_cols=correlated_cols,
    )


def _parse_in_subquery(
    node: exp.In,
    outer_resolver: dict[str, tuple[str, str, str | None]],
    outer_tables: set[str],
    *,
    alias_prefix: str,
    counter: list[int],
    catalog_schema: dict[str, str] | dict[str, dict[str, str]] | None = None,
) -> InSubquerySpec:
    if not isinstance(node.this, exp.Column):
        raise UnsupportedContractError("IN subquery left-hand side must be a column.")
    real_col, _, _ = _resolve_col(node.this, outer_resolver)
    subq = node.args.get("query")
    if not isinstance(subq, exp.Subquery):
        raise UnsupportedContractError("IN requires a subquery on the right-hand side.")
    inner_select = subq.this
    if not isinstance(inner_select, exp.Select):
        raise UnsupportedContractError("IN subquery must be a SELECT.")
    flat_schema = {c: t for c, t, _ in outer_resolver.values()}
    schema = catalog_schema if catalog_schema is not None else flat_schema
    inner_schema = _subquery_inner_schema(inner_select, schema)
    outer_names = set(outer_tables) | {
        k.split(".")[0] for k in outer_resolver if "." in k
    }
    inner = _parse_select(
        inner_select,
        inner_schema,
        allow_subqueries=False,
        correlation_outer_names=outer_names,
        catalog_schema=schema,
        outer_resolver=outer_resolver,
    )
    correlated_cols = _detect_correlation_sql(inner_select, outer_names)
    if not correlated_cols:
        correlated_cols = _detect_correlation(inner, set(inner_schema.keys()))
    correlated = bool(correlated_cols)
    if correlated:
        require_trusted("correlated_subquery")
    if inner.groupby_columns or inner.agg_type not in ("", "SELECT_SUBQUERY"):
        single_col_projection = inner.is_projection and len(inner.projection_columns) == 1
        single_col_groupby = len(inner.groupby_columns) == 1
        if not single_col_projection and not single_col_groupby:
            raise UnsupportedContractError(
                "IN subquery must be a single-column projection."
            )
    counter[0] += 1
    alias = f"{alias_prefix}{counter[0]}"
    return InSubquerySpec(
        alias=alias,
        column=real_col,
        query=inner,
        correlated=correlated,
        correlation_cols=correlated_cols,
    )


def _compile_where_expr(
    node: exp.Expression,
    resolver: dict[str, tuple[str, str, str | None]],
    query: SQLQuery,
    scalar_subqueries: dict[str, ScalarSubquery],
    *,
    outer_tables: set[str] | None = None,
    exists_counter: list[int] | None = None,
    in_counter: list[int] | None = None,
    correlation_outer_names: set[str] | None = None,
    catalog_schema: dict[str, str] | dict[str, dict[str, str]] | None = None,
    scalar_counter: list[int] | None = None,
    outer_resolver: dict[str, tuple[str, str, str | None]] | None = None,
) -> str:
    if outer_tables is None:
        outer_tables = _outer_table_names(query)
    if exists_counter is None:
        exists_counter = [0]
    if in_counter is None:
        in_counter = [0]
    if scalar_counter is None:
        scalar_counter = [0]
    join_context = bool(query.joins)
    qualify_alias = query_is_self_join(query)
    outer_name_lower = (
        {n.lower() for n in correlation_outer_names}
        if correlation_outer_names is not None
        else set()
    )

    def _compile_child(child: exp.Expression) -> str:
        return _compile_where_expr(
            child,
            resolver,
            query,
            scalar_subqueries,
            outer_tables=outer_tables,
            exists_counter=exists_counter,
            in_counter=in_counter,
            correlation_outer_names=correlation_outer_names,
            catalog_schema=catalog_schema,
            scalar_counter=scalar_counter,
            outer_resolver=outer_resolver,
        )

    if isinstance(node, exp.And):
        return f"({_compile_child(node.left)} && {_compile_child(node.right)})"
    if isinstance(node, exp.Or):
        return f"({_compile_child(node.left)} || {_compile_child(node.right)})"
    if isinstance(node, exp.Not):
        inner = node.this
        if isinstance(inner, exp.Exists):
            exists = _parse_exists_subquery(
                inner, resolver, outer_tables,
                alias_prefix="exists_", counter=exists_counter,
                catalog_schema=catalog_schema,
            )
            exists.negated = True
            query.exists_subqueries.append(exists)
            if exists.correlated:
                query.correlated = True
            return f"!{_exists_subquery_spec_call(exists, join_context=join_context, outer_table=_outer_base_table(query))}"
        if isinstance(inner, exp.Is):
            col_node = inner.this
            if not isinstance(col_node, exp.Column):
                raise UnsupportedContractError("IS NOT NULL requires a column.")
            return _compile_is_null_check(col_node, is_null=False, resolver=resolver, query=query)
        return f"!({_compile_child(inner)})"
    if isinstance(node, exp.Exists):
        exists = _parse_exists_subquery(
            node, resolver, outer_tables,
            alias_prefix="exists_", counter=exists_counter,
            catalog_schema=catalog_schema,
        )
        query.exists_subqueries.append(exists)
        if exists.correlated:
            query.correlated = True
        return _exists_subquery_spec_call(exists, join_context=join_context, outer_table=_outer_base_table(query))
    if isinstance(node, exp.Between):
        if not isinstance(node.this, exp.Column):
            raise UnsupportedContractError("BETWEEN left-hand side must be a column.")
        real_col, col_type, _ = _resolve_col(node.this, resolver)
        if _kind_of(col_type) != "int":
            raise UnsupportedContractError(
                f"BETWEEN is only supported on int columns, not '{col_type}'."
            )
        low = _compile_child(node.args["low"])
        high = _compile_child(node.args["high"])
        this_val = f"row.{real_col}"
        return f"({this_val} >= {low} && {this_val} <= {high})"
    if isinstance(node, exp.In):
        subq = node.args.get("query")
        if subq is not None:
            in_spec = _parse_in_subquery(
                node, resolver, outer_tables,
                alias_prefix="in_", counter=in_counter,
                catalog_schema=catalog_schema,
            )
            query.in_subqueries.append(in_spec)
            if in_spec.correlated:
                query.correlated = True
            return _in_subquery_contains_call(in_spec, join_context=join_context, outer_table=_outer_base_table(query))
        if not node.expressions:
            raise UnsupportedContractError("IN () with empty list is not supported.")
        if not isinstance(node.this, exp.Column):
            raise UnsupportedContractError("IN left-hand side must be a column.")
        real_col, col_type, _ = _resolve_col(node.this, resolver)
        this_val = f"row.{real_col}"
        eqs = []
        for val_node in node.expressions:
            val_str = _compile_child(val_node)
            eqs.append(f"{this_val} == {val_str}")
        return f"({' || '.join(eqs)})"
    if isinstance(node, exp.Like):
        if not isinstance(node.this, exp.Column):
            raise UnsupportedContractError("LIKE left-hand side must be a column.")
        real_col, col_type, _ = _resolve_col(node.this, resolver)
        if _kind_of(col_type) != "string":
            raise UnsupportedContractError("LIKE is only supported on string columns.")
        pat_node = node.args.get("expression")
        if not isinstance(pat_node, exp.Literal) or not pat_node.is_string:
            raise UnsupportedContractError("LIKE pattern must be a string literal.")
        return _compile_like_pattern(real_col, pat_node.this)
    if isinstance(node, exp.ILike):
        require_trusted("ilike")
        if not isinstance(node.this, exp.Column):
            raise UnsupportedContractError("ILIKE left-hand side must be a column.")
        real_col, col_type, _ = _resolve_col(node.this, resolver)
        if _kind_of(col_type) != "string":
            raise UnsupportedContractError("ILIKE is only supported on string columns.")
        pat_node = node.args.get("expression")
        if not isinstance(pat_node, exp.Literal) or not pat_node.is_string:
            raise UnsupportedContractError("ILIKE pattern must be a string literal.")
        return _compile_ilike_pattern(real_col, pat_node.this)
    if isinstance(node, (exp.EQ, exp.NEQ, exp.GT, exp.LT, exp.GTE, exp.LTE)):
        op_map = {exp.EQ: "==", exp.NEQ: "!=", exp.GT: ">", exp.LT: "<", exp.GTE: ">=", exp.LTE: "<="}
        op = op_map[type(node)]

        if isinstance(node.right, exp.Subquery):
            if not isinstance(node.left, exp.Column):
                raise UnsupportedContractError("scalar subquery comparison requires column on other side.")
            real_col, col_type, _ = _resolve_col(node.left, resolver)
            inner = _parse_scalar_subquery(
                node.right,
                resolver,
                outer_tables=outer_tables or _outer_table_names(query),
                catalog_schema=catalog_schema,
                alias_prefix="sq",
                counter=scalar_counter,
            )
            scalar_subqueries[inner.alias] = inner
            left_expr = f"row.{real_col}"
            val_resolved = _scalar_subquery_spec_call(inner, join_context=join_context, outer_table=_outer_base_table(query))
            kind = _kind_of(col_type)
            val_type = "int"
        elif isinstance(node.left, exp.Column):
            left_expr, kind = _compile_column_ref(
                node.left,
                resolver,
                outer_name_lower,
                outer_resolver=outer_resolver,
                qualify_alias=qualify_alias,
            )
            real_col, _, _ = _resolve_col(node.left, resolver)
            right_node = node.right
            if isinstance(right_node, exp.Literal):
                if right_node.is_string:
                    val_resolved = f'"{right_node.this}"'
                    val_type = "string"
                elif getattr(right_node, "is_boolean", False) or str(right_node.this).upper() in (
                    "TRUE",
                    "FALSE",
                ):
                    val_resolved = "true" if str(right_node.this).upper() == "TRUE" else "false"
                    val_type = "bool"
                elif right_node.is_number:
                    val_resolved = str(right_node.this)
                    val_type = "int"
                else:
                    raise UnsupportedContractError("Query falls outside the supported Lemma Basic SQL subset.")
            elif isinstance(right_node, exp.Neg) and isinstance(right_node.this, exp.Literal):
                val_resolved = f"-{right_node.this.this}"
                val_type = "int"
            elif isinstance(right_node, exp.Column):
                val_resolved, val_type = _compile_column_ref(
                    right_node,
                    resolver,
                    outer_name_lower,
                    outer_resolver=outer_resolver,
                    qualify_alias=qualify_alias,
                )
            elif isinstance(right_node, exp.Boolean):
                val_resolved = "true" if right_node.this else "false"
                val_type = "bool"
            else:
                folded = _fold_int_literal(right_node)
                if folded is None:
                    raise UnsupportedContractError(
                        "Query falls outside the supported Lemma Basic SQL subset."
                    )
                val_resolved = folded
                val_type = "int"
        else:
            raise UnsupportedContractError("Left hand side of comparison must be a column.")

        if kind == "int" and val_type != "int":
            raise UnsupportedContractError("Type mismatch: comparing int column with non-int value.")
        if kind == "bool" and val_type != "bool":
            raise UnsupportedContractError("Type mismatch: comparing bool column with non-bool value.")
        if kind == "string":
            if val_type != "string":
                raise UnsupportedContractError("Type mismatch: comparing string column with non-string value.")
            if op not in ("==", "!="):
                raise UnsupportedContractError(f"Unsupported operator '{op}' for string comparison.")

        if isinstance(node.left, exp.Column) and isinstance(node.right, exp.Literal):
            val_raw = node.right.this
            val_t = "string" if node.right.is_string else "int"
            query.where_conditions.append((real_col, "=" if op == "==" else op, val_raw, val_t))
        elif (
            isinstance(node.left, exp.Column)
            and val_type == "int"
            and _fold_int_literal(node.right) is not None
        ):
            query.where_conditions.append(
                (real_col, "=" if op == "==" else op, val_resolved, "int")
            )
        return f"{left_expr} {op} {val_resolved}"
    if isinstance(node, exp.Literal):
        if node.is_string:
            return f'"{node.this}"'
        if getattr(node, "is_boolean", False) or str(node.this).upper() in ("TRUE", "FALSE"):
            return "true" if str(node.this).upper() == "TRUE" else "false"
        if node.is_number:
            return str(node.this)
        raise UnsupportedContractError("Unsupported literal type.")
    if isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal):
        return f"-{node.this.this}"
    if isinstance(node, exp.Column):
        expr, _ = _compile_column_ref(
            node,
            resolver,
            outer_name_lower,
            outer_resolver=outer_resolver,
            qualify_alias=qualify_alias,
        )
        return expr
    if isinstance(node, exp.Boolean):
        return "true" if node.this else "false"
    if isinstance(node, exp.Is):
        col_node = node.this
        if not isinstance(col_node, exp.Column):
            raise UnsupportedContractError("IS NULL requires a column.")
        is_null = isinstance(node.expression, exp.Null)
        return _compile_is_null_check(col_node, is_null=is_null, resolver=resolver, query=query)
    if isinstance(node, exp.Paren):
        return f"({_compile_child(node.this)})"
    folded = _fold_int_literal(node)
    if folded is not None:
        return folded
    if _contains_non_int_number(node):
        raise UnsupportedContractError("Non-integer numeric literal is not a Lemma int.")
    raise UnsupportedContractError(f"Unsupported node in filter expression: {type(node)}")


def _compile_having_expr(
    node: exp.Expression,
    resolver: dict[str, tuple[str, str, str | None]],
    query: SQLQuery,
    agg_expr: str,
) -> str:
    """Compile HAVING predicate over group key `k` and aggregate value `v`."""
    if isinstance(node, exp.And):
        return (
            f"({_compile_having_expr(node.left, resolver, query, agg_expr)}"
            f" && {_compile_having_expr(node.right, resolver, query, agg_expr)})"
        )
    if isinstance(node, exp.Or):
        return (
            f"({_compile_having_expr(node.left, resolver, query, agg_expr)}"
            f" || {_compile_having_expr(node.right, resolver, query, agg_expr)})"
        )
    if isinstance(node, exp.Not):
        return f"!({_compile_having_expr(node.this, resolver, query, agg_expr)})"
    if isinstance(node, (exp.EQ, exp.NEQ, exp.GT, exp.LT, exp.GTE, exp.LTE)):
        op_map = {exp.EQ: "==", exp.NEQ: "!=", exp.GT: ">", exp.LT: "<", exp.GTE: ">=", exp.LTE: "<="}
        op = op_map[type(node)]
        left = _compile_having_expr_side(node.left, resolver, query, agg_expr)
        right = _compile_having_expr_side(node.right, resolver, query, agg_expr)
        return f"({left} {op} {right})"
    if isinstance(node, exp.Literal):
        if node.is_number:
            return str(node.this)
        raise UnsupportedContractError("HAVING supports only numeric literals.")
    raise UnsupportedContractError(f"Unsupported node in HAVING expression: {type(node)}")


def _compile_having_expr_side(
    node: exp.Expression,
    resolver: dict[str, tuple[str, str, str | None]],
    query: SQLQuery,
    agg_expr: str,
) -> str:
    if isinstance(node, exp.Subquery):
        require_trusted("having_subquery")
        inner = _parse_scalar_subquery(
            node,
            resolver,
            outer_tables=_outer_table_names(query),
            catalog_schema=None,
            alias_prefix="having_sq",
        )
        query.scalar_subqueries.append(inner)
        return _scalar_subquery_spec_call(inner, join_context=False, outer_table=_outer_base_table(query))
    if isinstance(node, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)):
        inner = _unwrap_alias(node)
        if isinstance(inner, exp.Count) and isinstance(inner.this, exp.Distinct):
            require_trusted("count_distinct")
            idx = next(
                (i for i, a in enumerate(query.agg_specs) if a.agg_type == "COUNT_DISTINCT"),
                0,
            )
        else:
            agg_kind = (
                "SUM" if isinstance(inner, exp.Sum)
                else "COUNT" if isinstance(inner, exp.Count)
                else "AVG" if isinstance(inner, exp.Avg)
                else "MIN" if isinstance(inner, exp.Min)
                else "MAX"
            )
            idx = next(
                (i for i, a in enumerate(query.agg_specs) if a.agg_type == agg_kind),
                0,
            )
        if len(query.agg_specs) <= 1:
            return "v"
        return f"v.{idx}"
    if isinstance(node, exp.Column):
        real_col, _, _ = _resolve_col(node, resolver)
        alias_key = real_col.lower()
        if alias_key in query.select_aliases:
            idx = query.select_aliases[alias_key]
            if len(query.agg_specs) <= 1:
                return "v"
            return f"v.{idx}"
        if real_col not in query.groupby_columns:
            raise UnsupportedContractError(
                f"HAVING column {real_col!r} must be a GROUP BY column or aggregate alias."
            )
        if len(query.groupby_columns) == 1:
            return "k"
        idx = query.groupby_columns.index(real_col)
        return f"k.{idx}"
    if isinstance(node, exp.Literal) and node.is_number:
        return str(node.this)
    if isinstance(node, exp.Paren):
        return f"({_compile_having_expr_side(node.this, resolver, query, agg_expr)})"
    raise UnsupportedContractError(f"Unsupported HAVING expression side: {type(node)}")


def _parse_scalar_subquery(
    node: exp.Subquery,
    outer_resolver: dict[str, tuple[str, str, str | None]],
    *,
    outer_tables: set[str],
    catalog_schema: dict[str, str] | dict[str, dict[str, str]] | None = None,
    alias_prefix: str = "sq",
    counter: list[int] | None = None,
) -> ScalarSubquery:
    inner_select = node.this
    if not isinstance(inner_select, exp.Select):
        raise UnsupportedContractError("scalar subquery must be a SELECT.")
    flat_schema = {c: t for c, t, _ in outer_resolver.values()}
    schema = catalog_schema if catalog_schema is not None else flat_schema
    inner_schema = _subquery_inner_schema(inner_select, schema)
    from_clause = inner_select.args.get("from_")
    if not from_clause:
        raise UnsupportedContractError("scalar subquery must have a FROM clause.")
    from_this = from_clause.this
    if isinstance(from_this, exp.Subquery):
        inner_table = ""
    else:
        inner_table, _inner_alias = _parse_table_ref(from_this)
    outer_names = set(outer_tables) | {
        k.split(".")[0] for k in outer_resolver if "." in k
    }
    inner = _parse_select(
        inner_select,
        inner_schema,
        allow_subqueries=True,
        correlation_outer_names=outer_names,
        catalog_schema=schema,
        outer_resolver=outer_resolver,
    )
    if inner.derived_tables:
        if not is_grouped_derived_scalar_subquery(inner):
            require_trusted("having_subquery")
    if inner.groupby_columns:
        if not is_grouped_derived_scalar_subquery(inner):
            require_trusted("having_subquery")
    if inner.joins and not is_grouped_derived_scalar_subquery(inner):
        raise UnsupportedContractError(
            "scalar subquery inner query with JOIN is not supported."
        )
    correlated_cols = _detect_correlation_sql(inner_select, outer_names)
    if not correlated_cols:
        correlated_cols = _detect_correlation(inner, set(inner_schema.keys()))
    correlated = bool(correlated_cols)
    if counter is None:
        counter = [0]
    counter[0] += 1
    alias = f"{alias_prefix}{counter[0]}"
    inner_tables: list[str] = []
    if is_grouped_derived_scalar_subquery(inner):
        inner_tables = grouped_derived_scalar_inner_tables(inner)
    elif inner_table:
        inner_tables = [inner_table]
    return ScalarSubquery(
        alias=alias,
        query=inner,
        inner_table=inner_table,
        inner_tables=inner_tables,
        correlated=correlated,
        correlation_cols=correlated_cols,
    )


def _cte_exposed_columns(cte_query: SQLQuery) -> dict[str, str]:
    if cte_query.is_projection:
        flat = {}
        for col in cte_query.projection_columns:
            flat[col] = "int"
        return flat
    if cte_query.union_query is not None:
        if cte_query.projection_columns:
            return {col: "int" for col in cte_query.projection_columns}
        return _cte_exposed_columns(cte_query.union_query)
    if cte_query.groupby_columns and cte_query.agg_type:
        cols = {c: "int" for c in cte_query.groupby_columns}
        cols["_agg"] = "bigint"
        return cols
    if cte_query.agg_type and not cte_query.groupby_columns:
        if cte_query.agg_specs and cte_query.agg_specs[0].alias:
            alias = cte_query.agg_specs[0].alias
            val_type = (
                "bigint"
                if cte_query.agg_type in ("SUM", "COUNT", "AVG", "COUNT_DISTINCT")
                else "int"
            )
            return {alias: val_type}
        return {"_scalar": "bigint"}
    raise UnsupportedContractError(
        "CTE must expose a projection, scalar aggregate, or group-by shape."
    )


def _derived_exposed_columns(
    inner_q: SQLQuery,
    inner_select: exp.Expression,
    resolver: dict[str, tuple[str, str, str | None]],
) -> tuple[dict[str, str], str | None]:
    """Return (alias -> type, source base column for project shapes)."""
    if inner_q.derived_tables:
        raise UnsupportedContractError(
            "derived table inner query cannot contain nested derived tables."
        )
    if inner_q.union_query is not None and inner_q.is_projection:
        out: dict[str, str] = {}
        for col in inner_q.projection_columns:
            out[col] = resolver.get(col.lower(), (col, "int", None))[1]
        src_col = inner_q.projection_columns[0] if len(inner_q.projection_columns) == 1 else None
        return out, src_col
    if (
        inner_q.is_projection
        and not inner_q.groupby_columns
        and not inner_q.agg_type
    ):
        out: dict[str, str] = {}
        types = inner_q.projection_types or ["int"] * len(inner_q.projection_columns)
        for col, typ in zip(inner_q.projection_columns, types, strict=True):
            out[col] = typ
        src_col = (
            inner_q.projection_columns[0]
            if len(inner_q.projection_columns) == 1
            else None
        )
        return out, src_col
    if inner_q.joins:
        require_trusted("having_subquery")
        out: dict[str, str] = {}
        for col in inner_q.groupby_columns:
            out[col] = resolver.get(col.lower(), (col, "int", None))[1]
        for item in inner_select.expressions:
            inner_expr = _unwrap_alias(item)
            alias = item.alias if isinstance(item, exp.Alias) else None
            if isinstance(inner_expr, exp.Column):
                real_col, col_type, _ = _resolve_col(inner_expr, resolver)
                out[alias or real_col] = col_type
            elif isinstance(inner_expr, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)):
                agg_alias = alias or "_agg"
                val_type = "bigint" if inner_q.agg_type in ("SUM", "COUNT", "AVG", "COUNT_DISTINCT") else "int"
                out[agg_alias] = val_type
        for spec in inner_q.agg_specs:
            a = spec.alias or "_agg"
            out[a] = "bigint" if spec.agg_type in ("SUM", "COUNT", "AVG", "COUNT_DISTINCT") else "int"
        if not out:
            raise UnsupportedContractError(
                "joined derived table must expose columns from its SELECT list."
            )
        return out, None
    if inner_q.groupby_columns:
        require_trusted("grouped_derived")
        out: dict[str, str] = {}
        for col in inner_q.groupby_columns:
            out[col] = resolver.get(col.lower(), (col, "int", None))[1]
        for item in inner_select.expressions:
            inner_expr = _unwrap_alias(item)
            if isinstance(inner_expr, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)):
                agg_alias = item.alias or "_agg"
                if isinstance(inner_expr, exp.Count) and isinstance(inner_expr.this, exp.Distinct):
                    val_type = "bigint"
                else:
                    val_type = "bigint" if inner_q.agg_type in ("SUM", "COUNT", "AVG", "COUNT_DISTINCT") else "int"
                out[agg_alias] = val_type
        if inner_q.agg_specs:
            for spec in inner_q.agg_specs:
                alias = spec.alias or "_agg"
                val_type = "bigint" if spec.agg_type in ("SUM", "COUNT", "AVG", "COUNT_DISTINCT") else "int"
                out[alias] = val_type
        elif not any(
            isinstance(_unwrap_alias(item), (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max))
            for item in inner_select.expressions
        ):
            out["_agg"] = "bigint"
        return out, None

    if inner_q.window_specs:
        win = inner_q.window_specs[0]
        val_type = "bigint" if win.func == "SUM" else "int"
        return {win.alias: val_type}, None

    if inner_q.is_projection:
        out: dict[str, str] = {}
        src_col: str | None = None
        types = inner_q.projection_types or ["int"] * len(inner_q.projection_columns)
        for col, typ in zip(inner_q.projection_columns, types, strict=True):
            out[col] = typ
        if len(inner_q.projection_columns) == 1:
            src_col = inner_q.projection_columns[0]
        return out, src_col

    items = inner_select.expressions
    if len(items) != 1:
        raise UnsupportedContractError(
            "derived table must expose exactly one column (scalar aggregate or projection)."
        )

    item = items[0]
    alias = item.alias
    inner_expr = _unwrap_alias(item)

    if inner_q.agg_type:
        if not alias:
            raise UnsupportedContractError(
                "derived scalar aggregate requires a column alias (AS name)."
            )
        val_type = "bigint" if inner_q.agg_type in ("SUM", "COUNT", "AVG") else "int"
        return {alias: val_type}, None

    if isinstance(inner_expr, exp.Column):
        real_col, col_type, _table = _resolve_col(inner_expr, resolver)
        out_alias = alias or real_col
        return {out_alias: col_type}, real_col

    raise UnsupportedContractError(
        "derived table inner SELECT must be a scalar aggregate or single-column projection."
    )


def _merge_where(left: str | None, right: str | None) -> str | None:
    if left and right:
        return f"({left}) && ({right})"
    return left or right


def _parse_limit_offset(expression: exp.Select) -> tuple[int | None, int | None]:
    limit_val: int | None = None
    offset_val: int | None = None
    limit_node = expression.args.get("limit")
    if limit_node is not None and limit_node.expression is not None:
        lit = limit_node.expression
        if isinstance(lit, exp.Literal) and lit.is_number:
            limit_val = int(lit.this)
    offset_node = expression.args.get("offset")
    if offset_node is not None and offset_node.expression is not None:
        lit = offset_node.expression
        if isinstance(lit, exp.Literal) and lit.is_number:
            offset_val = int(lit.this)
    return limit_val, offset_val


def _parse_order_by(
    expression: exp.Select,
    resolver: dict[str, tuple[str, str, str | None]],
    *,
    select_aliases: dict[str, str] | None = None,
    agg_alias_indices: dict[str, int] | None = None,
) -> list[OrderByItem]:
    order_clause = expression.args.get("order")
    if not order_clause:
        return []
    items: list[OrderByItem] = []
    for ob in order_clause.expressions:
        inner = ob.this
        desc = bool(ob.args.get("desc"))
        if isinstance(inner, exp.Column):
            name = inner.name.lower()
            if agg_alias_indices and name in agg_alias_indices:
                idx = agg_alias_indices[name]
                items.append(OrderByItem(
                    expr=f"agg_alias_{idx}",
                    column=name,
                    descending=desc,
                ))
                continue
            real_col, _, _ = _resolve_col(inner, resolver)
            items.append(OrderByItem(
                expr=f"row.{real_col}",
                column=real_col,
                descending=desc,
            ))
            continue
        raise UnsupportedContractError("ORDER BY supports column references only.")
    return items


def _parse_window_item(
    item: exp.Expression,
    resolver: dict[str, tuple[str, str, str | None]],
) -> WindowSpec:
    alias = item.alias if isinstance(item, exp.Alias) else "w"
    inner = _unwrap_alias(item)
    if not isinstance(inner, exp.Window):
        raise UnsupportedContractError("expected window expression")
    require_trusted("window")
    func_node = inner.this
    partition_cols: list[str] = []
    for part in inner.args.get("partition_by") or []:
        if not isinstance(part, exp.Column):
            raise UnsupportedContractError("window PARTITION BY supports columns only.")
        real_col, _, _ = _resolve_col(part, resolver)
        partition_cols.append(real_col)
    order_cols: list[tuple[str, bool]] = []
    order_clause = inner.args.get("order")
    if order_clause:
        for ob in order_clause.expressions:
            col_node = ob.this
            if not isinstance(col_node, exp.Column):
                raise UnsupportedContractError("window ORDER BY supports columns only.")
            real_col, _, _ = _resolve_col(col_node, resolver)
            order_cols.append((real_col, bool(ob.args.get("desc"))))
    if isinstance(func_node, exp.Sum):
        term = _to_row_expr(func_node.this, resolver)
        return WindowSpec(
            alias=alias,
            func="SUM",
            partition_columns=partition_cols,
            order_columns=order_cols,
            term_expr=term,
        )
    if isinstance(func_node, exp.RowNumber):
        return WindowSpec(
            alias=alias,
            func="ROW_NUMBER",
            partition_columns=partition_cols,
            order_columns=order_cols,
        )
    raise UnsupportedContractError(f"unsupported window function: {type(func_node)}")


def _rewrite_row_projection_aliases(expr: str, proj_map: dict[str, str]) -> str:
    out = expr
    for alias, inner_expr in sorted(proj_map.items(), key=lambda x: -len(x[0])):
        out = out.replace(f"row.{alias}", f"({inner_expr})")
    return out


def _flatten_derived_project(query: SQLQuery) -> SQLQuery:
    """Rewrite filter+project derived FROM into a base-table query."""
    if not query.derived_tables:
        return query
    if len(query.derived_tables) != 1:
        raise UnsupportedContractError("only one derived table in FROM is supported.")
    derived = query.derived_tables[0]
    inner = derived.query
    if inner.agg_type:
        return query
    if inner.union_query is not None or inner.window_specs:
        return query
    if inner.groupby_columns:
        return query
    if inner.derived_tables:
        raise UnsupportedContractError(
            "flattening derived projection with nested derived tables is not supported."
        )

    if inner.is_projection and inner.projection_columns:
        if len(inner.projection_columns) == 1 and derived.source_column:
            alias = inner.projection_columns[0]
            base_table = inner.tables[0] if inner.tables else ""
            new_agg_expr = query.agg_expr.replace(
                f"row.{alias}", f"row.{derived.source_column}",
            )
            new_where = _merge_where(inner.where_expr, query.where_expr) or ""
            new_proj_exprs = [
                e.replace(f"row.{alias}", f"row.{derived.source_column}")
                for e in query.projection_exprs
            ]
            return SQLQuery(
                tables=[base_table] if base_table else list(inner.tables),
                table_aliases=dict(inner.table_aliases),
                joins=list(inner.joins),
                agg_type=query.agg_type,
                agg_column=query.agg_column,
                groupby_columns=list(query.groupby_columns),
                groupby_tables=list(query.groupby_tables),
                where_conditions=list(inner.where_conditions),
                agg_expr=new_agg_expr,
                where_expr=new_where,
                scalar_subqueries=list(inner.scalar_subqueries)
                + list(query.scalar_subqueries),
                derived_tables=[],
                having_expr=query.having_expr,
                order_by=list(query.order_by),
                limit=query.limit,
                offset=query.offset,
                distinct=query.distinct,
                union_all=query.union_all,
                union_query=query.union_query,
                intersect_all=query.intersect_all,
                intersect_query=query.intersect_query,
                except_all=query.except_all,
                except_query=query.except_query,
                correlated=query.correlated,
                ctes=list(query.ctes),
                exists_subqueries=list(inner.exists_subqueries)
                + list(query.exists_subqueries),
                in_subqueries=list(inner.in_subqueries) + list(query.in_subqueries),
                is_projection=query.is_projection,
                projection_columns=list(query.projection_columns),
                projection_exprs=new_proj_exprs,
            )

        proj_map = dict(
            zip(inner.projection_columns, inner.projection_exprs, strict=True),
        )
        type_map = dict(derived.columns)
        if inner.projection_types:
            type_map.update(
                zip(inner.projection_columns, inner.projection_types, strict=True),
            )
        new_gb_exprs: list[str] = []
        new_gb_types: list[str] = []
        for col in query.groupby_columns:
            if col in proj_map:
                new_gb_exprs.append(proj_map[col])
                new_gb_types.append(type_map.get(col, "int"))
            else:
                new_gb_exprs.append("")
                new_gb_types.append(type_map.get(col, "int"))

        new_agg_specs: list[AggSpec] = []
        for spec in query.agg_specs:
            new_agg_specs.append(
                AggSpec(
                    agg_type=spec.agg_type,
                    agg_column=spec.agg_column,
                    agg_expr=_rewrite_row_projection_aliases(spec.agg_expr, proj_map),
                    alias=spec.alias,
                )
            )
        new_agg_expr = _rewrite_row_projection_aliases(query.agg_expr, proj_map)
        new_where = _merge_where(inner.where_expr, query.where_expr) or ""
        flat = SQLQuery(
            tables=list(inner.tables),
            table_aliases=dict(inner.table_aliases),
            joins=list(inner.joins),
            agg_type=query.agg_type,
            agg_column=query.agg_column,
            groupby_columns=list(query.groupby_columns),
            groupby_tables=list(query.groupby_tables),
            groupby_exprs=new_gb_exprs,
            groupby_types=new_gb_types,
            where_conditions=list(inner.where_conditions),
            agg_expr=new_agg_expr,
            agg_specs=new_agg_specs,
            select_aliases=dict(query.select_aliases),
            where_expr=new_where,
            scalar_subqueries=list(inner.scalar_subqueries)
            + list(query.scalar_subqueries),
            derived_tables=[],
            having_expr=query.having_expr,
            order_by=list(query.order_by),
            limit=query.limit,
            offset=query.offset,
            distinct=query.distinct,
            union_all=query.union_all,
            union_query=query.union_query,
            intersect_all=query.intersect_all,
            intersect_query=query.intersect_query,
            except_all=query.except_all,
            except_query=query.except_query,
            correlated=query.correlated,
            ctes=list(query.ctes),
            exists_subqueries=list(inner.exists_subqueries)
            + list(query.exists_subqueries),
            in_subqueries=list(inner.in_subqueries) + list(query.in_subqueries),
            is_projection=query.is_projection,
            projection_columns=list(query.projection_columns),
            projection_exprs=list(query.projection_exprs),
        )
        if flat.agg_specs:
            _sync_primary_agg(flat)
        return flat

    if not derived.source_column:
        return query

    if len(derived.columns) != 1:
        raise UnsupportedContractError("derived projection must expose exactly one column.")
    alias = next(iter(derived.columns))

    base_table = inner.tables[0] if inner.tables else ""
    new_agg_expr = query.agg_expr.replace(f"row.{alias}", f"row.{derived.source_column}")
    new_where = _merge_where(inner.where_expr, query.where_expr) or ""
    new_proj_exprs = [
        e.replace(f"row.{alias}", f"row.{derived.source_column}")
        for e in query.projection_exprs
    ]
    return SQLQuery(
        tables=[base_table] if base_table else [],
        table_aliases=dict(inner.table_aliases),
        joins=[],
        agg_type=query.agg_type,
        agg_column=query.agg_column,
        groupby_columns=list(query.groupby_columns),
        groupby_tables=list(query.groupby_tables),
        where_conditions=list(query.where_conditions),
        agg_expr=new_agg_expr,
        where_expr=new_where,
        scalar_subqueries=list(query.scalar_subqueries),
        derived_tables=[],
        having_expr=query.having_expr,
        order_by=list(query.order_by),
        limit=query.limit,
        offset=query.offset,
        distinct=query.distinct,
        union_all=query.union_all,
        union_query=query.union_query,
        intersect_all=query.intersect_all,
        intersect_query=query.intersect_query,
        except_all=query.except_all,
        except_query=query.except_query,
        correlated=query.correlated,
        ctes=list(query.ctes),
        exists_subqueries=list(query.exists_subqueries),
        in_subqueries=list(query.in_subqueries),
        is_projection=query.is_projection,
        projection_columns=list(query.projection_columns),
        projection_exprs=new_proj_exprs,
    )


def _resolve_cte_or_table(
    name: str,
    cte_map: dict[str, CTESpec],
    schema: dict[str, str] | dict[str, dict[str, str]],
) -> tuple[str, DerivedTable | None]:
    if name in cte_map:
        cte = cte_map[name]
        exposed = cte.columns or _cte_exposed_columns(cte.query)
        src_col = cte.query.projection_columns[0] if (
            cte.query.is_projection and len(cte.query.projection_columns) == 1
        ) else None
        derived = DerivedTable(
            alias=name,
            query=cte.query,
            columns=exposed,
            source_column=src_col,
        )
        return name, derived
    _, multi = normalize_schema(schema)
    if multi and name in multi:
        return name, None
    return name, None


def _and_predicates(node: exp.Expression) -> list[exp.Expression]:
    if isinstance(node, exp.And):
        return _and_predicates(node.left) + _and_predicates(node.right)
    if isinstance(node, exp.Paren):
        return _and_predicates(node.this)
    return [node]


def _column_home(node: exp.Column, schema: dict) -> str | None:
    if node.table:
        return str(node.table)
    _flat, multi = normalize_schema(schema)
    if multi is None:
        return None
    hits = [
        table
        for table, cols in multi.items()
        if any(col.lower() == node.name.lower() for col in cols)
    ]
    if len(hits) == 1:
        return hits[0]
    return None


def _lift_comma_joins(expression: exp.Select, schema: dict) -> None:
    """Turn ``FROM a, b WHERE a.k = b.k`` into an inner join on that equality."""
    joins = expression.args.get("joins") or []
    where = expression.args.get("where")
    from_clause = expression.args.get("from_")
    if not joins or where is None or from_clause is None:
        return
    if not isinstance(from_clause.this, exp.Table):
        return
    preds = _and_predicates(where.this)
    seen = {from_clause.this.name.lower()}
    used: set[int] = set()
    fixed: list[exp.Join] = []
    pending: list[exp.Join] = []
    for join in joins:
        if not isinstance(join.this, exp.Table):
            fixed.append(join)
            continue
        if join.args.get("on") or (join.side or join.kind):
            seen.add(join.this.name.lower())
            fixed.append(join)
        else:
            pending.append(join)

    def connecting(join: exp.Join) -> list[exp.Expression]:
        new = join.this.name.lower()
        chosen: list[exp.Expression] = []
        for pred in preds:
            if id(pred) in used or not isinstance(pred, exp.EQ):
                continue
            if not isinstance(pred.left, exp.Column) or not isinstance(pred.right, exp.Column):
                continue
            left_home = _column_home(pred.left, schema)
            right_home = _column_home(pred.right, schema)
            if left_home is None or right_home is None:
                continue
            pair = {left_home.lower(), right_home.lower()}
            if new in pair and pair - {new} and pair - {new} <= seen:
                chosen.append(pred)
        return chosen

    ordered = list(fixed)
    progressed = True
    while pending and progressed:
        progressed = False
        for index, join in enumerate(pending):
            chosen = connecting(join)
            if not chosen:
                continue
            for pred in chosen:
                used.add(id(pred))
            on: exp.Expression = chosen[0]
            for extra in chosen[1:]:
                on = exp.And(this=on, expression=extra)
            join.set("on", on)
            join.set("kind", "INNER")
            seen.add(join.this.name.lower())
            ordered.append(join)
            del pending[index]
            progressed = True
            break
    expression.set("joins", ordered + pending)
    if not used:
        return
    remaining = [pred for pred in preds if id(pred) not in used]
    if not remaining:
        expression.set("where", None)
        return
    acc: exp.Expression = remaining[0]
    for pred in remaining[1:]:
        acc = exp.And(this=acc, expression=pred)
    where.set("this", acc)


def _parse_select(
    expression: exp.Select,
    schema: dict[str, str] | dict[str, dict[str, str]],
    *,
    allow_subqueries: bool = True,
    derived_inner: bool = False,
    parent_ctes: list[CTESpec] | None = None,
    correlation_outer_names: set[str] | None = None,
    catalog_schema: dict[str, str] | dict[str, dict[str, str]] | None = None,
    outer_resolver: dict[str, tuple[str, str, str | None]] | None = None,
) -> SQLQuery:
    _check_forbidden_nodes(expression)
    query = SQLQuery()
    scalar_map: dict[str, ScalarSubquery] = {}
    exists_counter = [0]
    in_counter = [0]
    scalar_counter = [0]
    full_schema = catalog_schema if catalog_schema is not None else schema

    cte_map: dict[str, CTESpec] = {}
    for cte in parent_ctes or []:
        cte_map[cte.name] = cte

    with_clause = expression.args.get("with_")
    if with_clause:
        is_recursive = bool(with_clause.args.get("recursive"))
        if is_recursive:
            require_trusted("recursive_cte")
        for cte_node in with_clause.expressions:
            cte_name = cte_node.alias
            cte_body = cte_node.this
            if is_recursive and isinstance(cte_body, exp.Union):
                anchor_body = cte_body.this
                step_body = cte_body.expression
                if isinstance(anchor_body, exp.Select):
                    anchor_q = _parse_select(
                        anchor_body, schema, allow_subqueries=True,
                        parent_ctes=list(cte_map.values()),
                    )
                else:
                    anchor_q = _parse_expression(anchor_body, schema)
                exposed = _cte_exposed_columns(anchor_q)
                partial = CTESpec(
                    name=cte_name,
                    query=anchor_q,
                    columns=exposed,
                    recursive=True,
                )
                extended_ctes = list(cte_map.values()) + [partial]
                if isinstance(step_body, exp.Select):
                    step_q = _parse_select(
                        step_body, schema, allow_subqueries=True,
                        parent_ctes=extended_ctes,
                    )
                else:
                    step_q = _parse_expression(step_body, schema)
                _validate_union_compatible(anchor_q, step_q)
                anchor_q.union_all = True
                anchor_q.union_query = step_q
                inner_cte = anchor_q
            elif isinstance(cte_body, exp.Select):
                inner_cte = _parse_select(
                    cte_body, schema, allow_subqueries=True, parent_ctes=list(cte_map.values()),
                )
            else:
                raise UnsupportedContractError("CTE body must be a SELECT or recursive UNION.")
            spec = CTESpec(
                name=cte_name,
                query=inner_cte,
                columns=_cte_exposed_columns(inner_cte),
                recursive=is_recursive,
            )
            query.ctes.append(spec)
            cte_map[cte_name] = spec

    query.distinct = bool(expression.args.get("distinct"))

    from_clause = expression.args.get("from_")
    if not from_clause:
        raise UnsupportedContractError("Query must have a FROM clause.")

    from_this = from_clause.this
    derived_resolver = dict(_build_schema_resolver(
        schema, cte_columns={n: s.columns for n, s in cte_map.items()},
    ))
    if isinstance(from_this, exp.Subquery) and allow_subqueries:
        inner_expr = from_this.this
        if isinstance(inner_expr, exp.Select):
            inner_q = _parse_select(
                inner_expr, schema, allow_subqueries=False, derived_inner=True,
                parent_ctes=list(cte_map.values()),
            )
            inner_select = inner_expr
        elif isinstance(inner_expr, (exp.Union, exp.Intersect, exp.Except)):
            inner_q = _parse_expression(inner_expr, schema)
            inner_select = inner_expr
        else:
            raise UnsupportedContractError("derived table must be SELECT or UNION.")
        alias = from_this.alias or "derived"
        exposed, source_col = _derived_exposed_columns(
            inner_q, inner_select, _build_schema_resolver(schema),
        )
        query.derived_tables.append(DerivedTable(
            alias=alias,
            query=inner_q,
            columns=exposed,
            source_column=source_col,
        ))
        query.tables.append(alias)
        query.table_aliases[alias] = alias
        for col, typ in exposed.items():
            derived_resolver[col.lower()] = (col, typ, alias)
            derived_resolver[f"{alias}.{col}".lower()] = (col, typ, alias)
    else:
        table_name, alias = _parse_table_ref(from_this)
        resolved_name, cte_derived = _resolve_cte_or_table(
            table_name, cte_map, schema,
        )
        if cte_derived is not None:
            query.derived_tables.append(cte_derived)
            query.tables.append(resolved_name)
            query.table_aliases[resolved_name] = resolved_name
            for col, typ in cte_derived.columns.items():
                derived_resolver[col.lower()] = (col, typ, resolved_name)
                derived_resolver[f"{resolved_name}.{col}".lower()] = (col, typ, resolved_name)
        else:
            query.tables.append(table_name)
            if alias:
                query.table_aliases[alias] = table_name

        _lift_comma_joins(expression, schema)
        for join in expression.args.get("joins") or []:
            side = (join.side or join.kind or "INNER").upper()
            if side in ("FULL",):
                require_trusted("full_join")
            elif side == "CROSS":
                require_trusted("cross_join")
            elif side in ("SEMI", "ANTI"):
                require_trusted("semi_anti_join")
            # RIGHT JOIN: honest side-swap to outer-join MethodSpec (not TRUSTED).

            jtable, jalias, jderived = _parse_join_from(
                join.this,
                schema,
                derived_resolver,
                parent_ctes=list(cte_map.values()),
            )
            if jderived is not None:
                query.derived_tables.append(jderived)
                for col, typ in jderived.columns.items():
                    derived_resolver[col.lower()] = (col, typ, jderived.alias)
                    derived_resolver[f"{jderived.alias}.{col}".lower()] = (col, typ, jderived.alias)
                jtable = jderived.alias
                jalias = jderived.alias
            swap_right = side == "RIGHT"
            on_combiner = "and"
            if side == "CROSS":
                join_type = "CROSS"
                on_equalities: list[tuple[str, str]] = []
            elif side == "FULL":
                join_type = "FULL"
                on_equalities, on_combiner = _parse_on_clause(join.args.get("on"))
            elif side in ("SEMI", "ANTI"):
                join_type = side
                on_equalities, on_combiner = _parse_on_clause(join.args.get("on"))
            elif side == "LEFT":
                join_type = "LEFT"
                on_equalities, on_combiner = _parse_on_clause(join.args.get("on"))
            elif side == "RIGHT":
                # Keep join_type RIGHT for MethodSpec; still side-swap tables below.
                join_type = "RIGHT"
                on_equalities, on_combiner = _parse_on_clause(join.args.get("on"))
            else:
                join_type = "INNER"
                on_equalities, on_combiner = _parse_on_clause(join.args.get("on"))

            if swap_right:
                # A RIGHT JOIN B ≡ B LEFT JOIN A: preserved side becomes slots[0].
                base_table = query.tables[0]
                base_alias = None
                for alias, table in query.table_aliases.items():
                    if table == base_table:
                        base_alias = alias
                        break
                query.tables[0] = jtable
                if jalias:
                    query.table_aliases[jalias] = jtable
                elif jtable not in query.table_aliases.values():
                    query.table_aliases[jtable] = jtable
                query.tables.append(base_table)
                if base_alias:
                    query.table_aliases[base_alias] = base_table
                on_equalities = [(right, left) for left, right in on_equalities]
            else:
                query.tables.append(jtable)
                if jalias:
                    query.table_aliases[jalias] = jtable

            query.joins.append(JoinSpec(
                join_type=join_type,
                table=jtable if not swap_right else query.tables[0],
                alias=jalias,
                on_equalities=on_equalities,
                on_combiner=on_combiner,
            ))

    resolver = derived_resolver if (query.derived_tables or cte_map) else _build_schema_resolver(
        schema, query.table_aliases, cte_columns={n: s.columns for n, s in cte_map.items()},
    )

    def _compile_where(node_expr: exp.Expression) -> str:
        return _compile_where_expr(
            node_expr,
            resolver,
            query,
            scalar_map,
            outer_tables=_outer_table_names(query),
            exists_counter=exists_counter,
            in_counter=in_counter,
            correlation_outer_names=correlation_outer_names,
            catalog_schema=full_schema,
            scalar_counter=scalar_counter,
            outer_resolver=outer_resolver,
        )

    groupby_clause = expression.args.get("group")
    if groupby_clause:
        for groupby_node in groupby_clause.expressions:
            if not isinstance(groupby_node, exp.Column):
                raise UnsupportedContractError("GROUP BY supports column references only.")
            real_col, _, table = _resolve_col(groupby_node, resolver)
            if real_col in query.groupby_columns:
                raise UnsupportedContractError("Duplicate group-by columns are not supported.")
            query.groupby_columns.append(real_col)
            query.groupby_tables.append(table)

    select_items = expression.expressions
    agg_node = None
    if query.groupby_columns:
        unwrapped = [_unwrap_alias(item) for item in select_items]
        select_cols: set[str] = set()
        agg_items: list[exp.Expression] = []
        for item, raw in zip(unwrapped, select_items, strict=True):
            if isinstance(item, exp.Column):
                real_col, _, _ = _resolve_col(item, resolver)
                select_cols.add(real_col)
            elif _is_aggregate_expr(item):
                agg_items.append(raw)
        if not select_cols.issubset(set(query.groupby_columns)):
            raise UnsupportedContractError(
                "Non-aggregated SELECT columns must appear in GROUP BY."
            )
        if len(select_items) != len(select_cols) + len(agg_items):
            raise UnsupportedContractError(
                "SELECT must list GROUP BY columns (optional) plus one or more aggregates."
            )
        _append_agg_specs_from_exprs(agg_items, resolver, query)
        agg_node = _unwrap_alias(agg_items[0]) if agg_items else None
        if query.agg_specs:
            _sync_primary_agg(query)
    else:
        if len(select_items) == 1:
            select_item = _unwrap_alias(select_items[0])
            if isinstance(select_item, exp.Window):
                win = _parse_window_item(select_items[0], resolver)
                query.window_specs.append(win)
                query.is_projection = True
                query.projection_columns = [win.alias]
                query.projection_exprs = [
                    f"window_{win.func.lower()}_{win.alias}_spec(cols, k)"
                ]
                where_clause = expression.args.get("where")
                if where_clause:
                    query.where_expr = _compile_where(where_clause.this)
                    query.scalar_subqueries.extend(scalar_map.values())
                query.limit, query.offset = _parse_limit_offset(expression)
                query.order_by = _parse_order_by(expression, resolver)
                return query
            if isinstance(select_item, exp.Subquery):
                inner = _parse_scalar_subquery(
                    select_item,
                    resolver,
                    outer_tables=_outer_table_names(query),
                    catalog_schema=full_schema,
                    alias_prefix="sel_sq",
                    counter=scalar_counter,
                )
                query.scalar_subqueries.append(inner)
                query.agg_type = "SELECT_SUBQUERY"
                query.agg_expr = _scalar_subquery_spec_call(
                    inner,
                    join_context=bool(query.joins),
                    outer_table=_outer_base_table(query),
                )
                query.agg_column = inner.alias
                where_clause = expression.args.get("where")
                if where_clause:
                    query.where_expr = _compile_where(where_clause.this)
                    query.scalar_subqueries.extend(scalar_map.values())
                query.limit, query.offset = _parse_limit_offset(expression)
                query.order_by = _parse_order_by(expression, resolver)
                return _flatten_derived_project(query)

            if isinstance(select_item, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)):
                agg_node = select_item
            elif isinstance(select_item, exp.Literal):
                query.is_projection = True
                query.projection_columns = ["_exists"]
                query.projection_exprs = ["1"]
                where_clause = expression.args.get("where")
                if where_clause:
                    query.where_expr = _compile_where(where_clause.this)
                    query.scalar_subqueries.extend(scalar_map.values())
                return query
            elif isinstance(select_item, exp.Column) or derived_inner:
                if isinstance(select_item, exp.Column):
                    real_col, _, _ = _resolve_col(select_item, resolver)
                    alias = select_items[0].alias or real_col
                    query.is_projection = True
                    query.projection_columns = [alias]
                    if query_is_self_join(query) and select_item.table:
                        query.projection_exprs = [
                            f"row.{select_item.table}.{real_col}"
                        ]
                    else:
                        query.projection_exprs = [f"row.{real_col}"]
                    query.agg_column = alias
                where_clause = expression.args.get("where")
                if where_clause:
                    query.where_expr = _compile_where(where_clause.this)
                    query.scalar_subqueries.extend(scalar_map.values())
                query.limit, query.offset = _parse_limit_offset(expression)
                query.order_by = _parse_order_by(expression, resolver)
                if query.distinct and query.agg_type:
                    raise UnsupportedContractError(
                        "DISTINCT with scalar aggregate is not supported."
                    )
                return _flatten_derived_project(query)
            else:
                raise UnsupportedContractError(
                    "SELECT without GROUP BY must be a single aggregate or column projection."
                )
        else:
            proj_cols: list[str] = []
            proj_exprs: list[str] = []
            proj_types: list[str] = []
            qualify = query_is_self_join(query)
            for item in select_items:
                inner = _unwrap_alias(item)
                expr, typ = _compile_select_expr(
                    item, resolver, qualify_alias=qualify,
                )
                if isinstance(inner, exp.Column):
                    real_col, _, _ = _resolve_col(inner, resolver)
                    alias = item.alias or real_col
                elif item.alias:
                    alias = item.alias
                else:
                    raise UnsupportedContractError(
                        "Derived projection expressions require an alias."
                    )
                proj_cols.append(alias)
                proj_exprs.append(expr)
                proj_types.append(typ)
            query.is_projection = True
            query.projection_columns = proj_cols
            query.projection_exprs = proj_exprs
            query.projection_types = proj_types
            where_clause = expression.args.get("where")
            if where_clause:
                query.where_expr = _compile_where(where_clause.this)
                query.scalar_subqueries.extend(scalar_map.values())
            query.limit, query.offset = _parse_limit_offset(expression)
            query.order_by = _parse_order_by(expression, resolver)
            if query.distinct and query.agg_type:
                raise UnsupportedContractError("DISTINCT with scalar aggregate is not supported.")
            return _flatten_derived_project(query)

    if agg_node is not None and not query.agg_specs:
        spec = _parse_agg_item(
            next(raw for raw in select_items if isinstance(_unwrap_alias(raw), (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max))),
            resolver,
        )
        query.agg_specs.append(spec)
        _sync_primary_agg(query)

    where_clause = expression.args.get("where")
    if where_clause:
        query.where_expr = _compile_where(where_clause.this)
        query.scalar_subqueries.extend(scalar_map.values())

    having_clause = expression.args.get("having")
    if having_clause:
        if not query.groupby_columns:
            raise UnsupportedContractError("HAVING requires GROUP BY.")
        _append_agg_specs_from_exprs(
            _collect_aggregate_exprs(having_clause.this),
            resolver,
            query,
        )
        if query.agg_specs:
            _sync_primary_agg(query)
        query.having_expr = _compile_having_expr(
            having_clause.this, resolver, query, query.agg_expr,
        )

    query.limit, query.offset = _parse_limit_offset(expression)
    agg_alias_indices = {
        alias: idx for alias, idx in query.select_aliases.items()
    }
    query.order_by = _parse_order_by(
        expression, resolver, agg_alias_indices=agg_alias_indices,
    )

    if query.distinct and query.agg_type and not query.groupby_columns:
        raise UnsupportedContractError("DISTINCT with scalar aggregate is not supported.")

    return _flatten_derived_project(query)


def _validate_union_compatible(left: SQLQuery, right: SQLQuery) -> None:
    if left.is_projection != right.is_projection:
        raise UnsupportedContractError("UNION branches must have the same result shape.")
    if left.is_projection:
        if left.projection_columns != right.projection_columns:
            raise UnsupportedContractError("UNION projection branches must have matching columns.")
        return
    if left.groupby_columns != right.groupby_columns:
        raise UnsupportedContractError("UNION branches must have matching GROUP BY columns.")
    if left.agg_type != right.agg_type:
        raise UnsupportedContractError("UNION branches must use the same aggregate.")


def _parse_expression(
    expression: exp.Expression,
    schema: dict[str, str] | dict[str, dict[str, str]],
) -> SQLQuery:
    _check_forbidden_nodes(expression)
    if isinstance(expression, exp.Union):
        left = _parse_expression(expression.this, schema)
        right = _parse_expression(expression.expression, schema)
        _validate_union_compatible(left, right)
        union_all = not expression.args.get("distinct", True)
        left.union_all = union_all
        left.union_query = right
        return left
    if isinstance(expression, exp.Intersect):
        require_trusted("intersect_except")
        left = _parse_expression(expression.this, schema)
        right = _parse_expression(expression.expression, schema)
        _validate_union_compatible(left, right)
        left.intersect_all = not expression.args.get("distinct", True)
        left.intersect_query = right
        return left
    if isinstance(expression, exp.Except):
        require_trusted("intersect_except")
        left = _parse_expression(expression.this, schema)
        right = _parse_expression(expression.expression, schema)
        _validate_union_compatible(left, right)
        left.except_all = not expression.args.get("distinct", True)
        left.except_query = right
        return left
    if isinstance(expression, exp.Select):
        return _parse_select(expression, schema)
    raise UnsupportedContractError("Query falls outside the supported Lemma Basic SQL subset.")


def parse_sql(
    sql_str: str,
    schema: dict[str, str] | dict[str, dict[str, str]],
) -> SQLQuery:
    """Parse SQL within the Lemma Basic SQL contract boundary."""
    try:
        expression = sqlglot.parse_one(sql_str)
    except Exception as e:
        raise UnsupportedContractError(f"Query parsing failed: {e}") from e

    return _parse_expression(expression, schema)


def get_rust_type(col: str, col_type: str) -> str:
    return col_verus_type(col_type)


def _agg_value_type(agg_expr: str) -> str:
    return "i64" if "-" in agg_expr else "u64"
