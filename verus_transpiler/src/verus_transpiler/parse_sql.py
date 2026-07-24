"""sqlglot parse for Lemma Basic SQL (Postgres/DuckDB-ish analytical subset)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

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
class JoinSpec:
    join_type: str
    table: str
    alias: str | None
    on_equalities: list[tuple[str, str]]


@dataclass
class ScalarSubquery:
    alias: str
    query: "SQLQuery"
    correlation_cols: list[str] = field(default_factory=list)


@dataclass
class DerivedTable:
    alias: str
    query: "SQLQuery"
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
    query: "SQLQuery"
    columns: dict[str, str] = field(default_factory=dict)
    recursive: bool = False


@dataclass
class ExistsSubquery:
    alias: str
    query: "SQLQuery"
    negated: bool = False
    correlated: bool = False
    correlation_cols: list[str] = field(default_factory=list)


@dataclass
class InSubquerySpec:
    alias: str
    column: str
    query: "SQLQuery"
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
    where_expr: str = ""
    scalar_subqueries: list[ScalarSubquery] = field(default_factory=list)
    derived_tables: list[DerivedTable] = field(default_factory=list)
    having_expr: str = ""
    order_by: list[OrderByItem] = field(default_factory=list)
    limit: int | None = None
    offset: int | None = None
    distinct: bool = False
    union_all: bool | None = None
    union_query: "SQLQuery | None" = None
    intersect_all: bool | None = None
    intersect_query: "SQLQuery | None" = None
    except_all: bool | None = None
    except_query: "SQLQuery | None" = None
    correlated: bool = False
    ctes: list[CTESpec] = field(default_factory=list)
    exists_subqueries: list[ExistsSubquery] = field(default_factory=list)
    in_subqueries: list[InSubquerySpec] = field(default_factory=list)
    window_specs: list[WindowSpec] = field(default_factory=list)
    is_projection: bool = False
    projection_columns: list[str] = field(default_factory=list)
    projection_exprs: list[str] = field(default_factory=list)

    @property
    def table(self) -> str:
        return self.tables[0] if self.tables else ""

    @property
    def has_order_or_limit(self) -> bool:
        return bool(self.order_by) or self.limit is not None or self.offset is not None


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
            elif side == "RIGHT":
                require_trusted("nway_join")
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


def _parse_on_equalities(
    on_expr: exp.Expression | None,
    *,
    allow_missing: bool = False,
) -> list[tuple[str, str]]:
    if on_expr is None:
        if allow_missing:
            return []
        raise UnsupportedContractError("JOIN requires ON clause with equality predicates.")
    equalities: list[tuple[str, str]] = []

    def collect(node: exp.Expression) -> None:
        if isinstance(node, exp.And):
            collect(node.left)
            collect(node.right)
        elif isinstance(node, exp.EQ):
            if not isinstance(node.left, exp.Column) or not isinstance(node.right, exp.Column):
                raise UnsupportedContractError("JOIN ON must be column equality.")
            left_ref = ".".join(p for p in (node.left.table, node.left.name) if p)
            right_ref = ".".join(p for p in (node.right.table, node.right.name) if p)
            equalities.append((left_ref or node.left.name, right_ref or node.right.name))
        else:
            raise UnsupportedContractError("JOIN ON supports only = and AND of =.")

    collect(on_expr)
    if not equalities:
        raise UnsupportedContractError("JOIN requires at least one equality predicate.")
    return equalities


def _unwrap_alias(node: exp.Expression) -> exp.Expression:
    if isinstance(node, exp.Alias):
        return node.this
    return node


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
    else_expr = _to_row_expr(default, resolver) if default is not None else "0"
    result = else_expr
    for if_node in reversed(ifs):
        cond = _compile_row_bool_expr(if_node.this, resolver)
        then_expr = _to_row_expr(if_node.args["true"], resolver)
        result = f"case_when_u64({cond}, {then_expr}, {result})"
    return result


def _to_row_expr(
    node: exp.Expression,
    resolver: dict[str, tuple[str, str, str | None]],
) -> str:
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
        return f"{_to_row_expr(node.left, resolver)} * {_to_row_expr(node.right, resolver)}"
    if isinstance(node, exp.Div):
        if isinstance(node.right, exp.Literal) and node.right.this == "0":
            raise UnsupportedContractError("Division by zero literal is not supported.")
        return f"{_to_row_expr(node.left, resolver)} / {_to_row_expr(node.right, resolver)}"
    if isinstance(node, exp.Add):
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
    if pattern.startswith("%") and pattern.endswith("%") and len(pattern) >= 2:
        lit = pattern[1:-1]
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
    return [c for c in refs if c not in schema_cols]


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
    """Columns visible from the subquery's own FROM (not outer)."""
    flat, multi = normalize_schema(schema)
    from_clause = select.args.get("from_")
    if not from_clause:
        return dict(flat)
    try:
        table_name, _alias = _parse_table_ref(from_clause.this)
    except UnsupportedContractError:
        return dict(flat)
    if multi and table_name in multi:
        return dict(multi[table_name])
    return dict(flat)


def _parse_exists_subquery(
    node: exp.Exists,
    outer_resolver: dict[str, tuple[str, str, str | None]],
    outer_tables: set[str],
    *,
    alias_prefix: str,
    counter: list[int],
) -> ExistsSubquery:
    inner_select = node.this
    if not isinstance(inner_select, exp.Select):
        raise UnsupportedContractError("EXISTS subquery must be a SELECT.")
    flat_schema = {c: t for c, t, _ in outer_resolver.values()}
    inner_schema = _subquery_inner_schema(inner_select, flat_schema)
    inner = _parse_select(inner_select, inner_schema, allow_subqueries=True)
    outer_names = set(outer_tables) | set(outer_resolver.keys())
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
    inner_schema = _subquery_inner_schema(inner_select, flat_schema)
    inner = _parse_select(inner_select, inner_schema, allow_subqueries=False)
    outer_names = set(outer_tables) | {
        k.split(".")[0] for k in outer_resolver if "." in k
    }
    correlated_cols = _detect_correlation_sql(inner_select, outer_names)
    if not correlated_cols:
        correlated_cols = _detect_correlation(inner, set(inner_schema.keys()))
    correlated = bool(correlated_cols)
    if correlated:
        require_trusted("correlated_subquery")
    if inner.groupby_columns or inner.agg_type not in ("", "SELECT_SUBQUERY"):
        if not inner.is_projection or len(inner.projection_columns) != 1:
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
) -> str:
    if outer_tables is None:
        outer_tables = _outer_table_names(query)
    if exists_counter is None:
        exists_counter = [0]
    if in_counter is None:
        in_counter = [0]

    if isinstance(node, exp.And):
        return (
            f"({_compile_where_expr(node.left, resolver, query, scalar_subqueries, outer_tables=outer_tables, exists_counter=exists_counter, in_counter=in_counter)}"
            f" && {_compile_where_expr(node.right, resolver, query, scalar_subqueries, outer_tables=outer_tables, exists_counter=exists_counter, in_counter=in_counter)})"
        )
    if isinstance(node, exp.Or):
        return (
            f"({_compile_where_expr(node.left, resolver, query, scalar_subqueries, outer_tables=outer_tables, exists_counter=exists_counter, in_counter=in_counter)}"
            f" || {_compile_where_expr(node.right, resolver, query, scalar_subqueries, outer_tables=outer_tables, exists_counter=exists_counter, in_counter=in_counter)})"
        )
    if isinstance(node, exp.Not):
        inner = node.this
        if isinstance(inner, exp.Exists):
            exists = _parse_exists_subquery(
                inner, resolver, outer_tables,
                alias_prefix="exists_", counter=exists_counter,
            )
            exists.negated = True
            query.exists_subqueries.append(exists)
            if exists.correlated:
                query.correlated = True
                key = exists.correlation_cols[0]
                return f"!exists_corr_{exists.alias}_spec(cols, row.{key})"
            return f"!exists_{exists.alias}_spec(cols)"
        return f"!({_compile_where_expr(inner, resolver, query, scalar_subqueries, outer_tables=outer_tables, exists_counter=exists_counter, in_counter=in_counter)})"
    if isinstance(node, exp.Exists):
        exists = _parse_exists_subquery(
            node, resolver, outer_tables,
            alias_prefix="exists_", counter=exists_counter,
        )
        query.exists_subqueries.append(exists)
        if exists.correlated:
            query.correlated = True
            key = exists.correlation_cols[0]
            return f"exists_corr_{exists.alias}_spec(cols, row.{key})"
        return f"exists_{exists.alias}_spec(cols)"
    if isinstance(node, exp.Between):
        if not isinstance(node.this, exp.Column):
            raise UnsupportedContractError("BETWEEN left-hand side must be a column.")
        real_col, col_type, _ = _resolve_col(node.this, resolver)
        if _kind_of(col_type) != "int":
            raise UnsupportedContractError(
                f"BETWEEN is only supported on int columns, not '{col_type}'."
            )
        low = _compile_where_expr(
            node.args["low"], resolver, query, scalar_subqueries,
            outer_tables=outer_tables, exists_counter=exists_counter, in_counter=in_counter,
        )
        high = _compile_where_expr(
            node.args["high"], resolver, query, scalar_subqueries,
            outer_tables=outer_tables, exists_counter=exists_counter, in_counter=in_counter,
        )
        this_val = f"row.{real_col}"
        return f"({this_val} >= {low} && {this_val} <= {high})"
    if isinstance(node, exp.In):
        subq = node.args.get("query")
        if subq is not None:
            in_spec = _parse_in_subquery(
                node, resolver, outer_tables,
                alias_prefix="in_", counter=in_counter,
            )
            query.in_subqueries.append(in_spec)
            if in_spec.correlated:
                query.correlated = True
                key = in_spec.correlation_cols[0]
                return f"in_corr_{in_spec.alias}_contains(cols, row.{in_spec.column}, row.{key})"
            return f"in_{in_spec.alias}_contains(cols, row.{in_spec.column})"
        if not node.expressions:
            raise UnsupportedContractError("IN () with empty list is not supported.")
        if not isinstance(node.this, exp.Column):
            raise UnsupportedContractError("IN left-hand side must be a column.")
        real_col, col_type, _ = _resolve_col(node.this, resolver)
        this_val = f"row.{real_col}"
        eqs = []
        for val_node in node.expressions:
            val_str = _compile_where_expr(
                val_node, resolver, query, scalar_subqueries,
                outer_tables=outer_tables, exists_counter=exists_counter, in_counter=in_counter,
            )
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
            inner = _parse_scalar_subquery(node.right, resolver)
            scalar_subqueries[inner.alias] = inner
            left_expr = f"row.{real_col}"
            val_resolved = f"subquery_{inner.alias}_spec(cols)"
            val_type = "int"
        elif isinstance(node.left, exp.Column):
            real_col, col_type, _ = _resolve_col(node.left, resolver)
            left_expr = f"row.{real_col}"
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
                rreal_col, rcol_type, _ = _resolve_col(right_node, resolver)
                val_resolved = f"row.{rreal_col}"
                val_type = _kind_of(rcol_type)
            elif isinstance(right_node, exp.Boolean):
                val_resolved = "true" if right_node.this else "false"
                val_type = "bool"
            else:
                raise UnsupportedContractError("Query falls outside the supported Lemma Basic SQL subset.")
        else:
            raise UnsupportedContractError("Left hand side of comparison must be a column.")

        kind = _kind_of(col_type)
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
        real_col, _, _ = _resolve_col(node, resolver)
        return f"row.{real_col}"
    if isinstance(node, exp.Boolean):
        return "true" if node.this else "false"
    if isinstance(node, exp.Paren):
        return f"({_compile_where_expr(node.this, resolver, query, scalar_subqueries, outer_tables=outer_tables, exists_counter=exists_counter, in_counter=in_counter)})"
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
    if isinstance(node, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)):
        return "v"
    if isinstance(node, exp.Column):
        real_col, _, _ = _resolve_col(node, resolver)
        if real_col not in query.groupby_columns:
            raise UnsupportedContractError(
                f"HAVING column {real_col!r} must be a GROUP BY column."
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
    alias_prefix: str = "sq",
) -> ScalarSubquery:
    inner_select = node.this
    if not isinstance(inner_select, exp.Select):
        raise UnsupportedContractError("scalar subquery must be a SELECT.")
    flat_schema = {c: t for c, t, _ in outer_resolver.values()}
    inner = _parse_select(inner_select, flat_schema, allow_subqueries=False)
    if inner.groupby_columns:
        raise UnsupportedContractError("scalar subquery with GROUP BY not supported in this shape.")
    if inner.derived_tables:
        raise UnsupportedContractError("scalar subquery with derived FROM not supported.")
    alias = f"{alias_prefix}{len(flat_schema)}"
    return ScalarSubquery(alias=alias, query=inner)


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
        return {"_scalar": "bigint"}
    raise UnsupportedContractError(
        "CTE must expose a projection, scalar aggregate, or group-by shape."
    )


def _derived_exposed_columns(
    inner_q: SQLQuery,
    inner_select: exp.Select,
    resolver: dict[str, tuple[str, str, str | None]],
) -> tuple[dict[str, str], str | None]:
    """Return (alias -> type, source base column for project shapes)."""
    if inner_q.joins or inner_q.derived_tables:
        raise UnsupportedContractError(
            "derived table inner query cannot contain JOINs or nested derived tables."
        )
    if inner_q.groupby_columns:
        require_trusted("grouped_derived")
        out: dict[str, str] = {c: "int" for c in inner_q.groupby_columns}
        agg_alias = "_agg"
        for item in inner_select.expressions:
            inner_expr = _unwrap_alias(item)
            if isinstance(inner_expr, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)):
                agg_alias = item.alias or "_agg"
                val_type = "bigint" if inner_q.agg_type in ("SUM", "COUNT", "AVG") else "int"
                out[agg_alias] = val_type
                break
        return out, None

    if inner_q.window_specs:
        win = inner_q.window_specs[0]
        val_type = "bigint" if win.func == "SUM" else "int"
        return {win.alias: val_type}, None

    if inner_q.is_projection:
        out: dict[str, str] = {}
        src_col: str | None = None
        for col in inner_q.projection_columns:
            out[col] = "int"
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
) -> list[OrderByItem]:
    order_clause = expression.args.get("order")
    if not order_clause:
        return []
    items: list[OrderByItem] = []
    for ob in order_clause.expressions:
        inner = ob.this
        if not isinstance(inner, exp.Column):
            raise UnsupportedContractError("ORDER BY supports column references only.")
        real_col, _, _ = _resolve_col(inner, resolver)
        desc = bool(ob.args.get("desc"))
        items.append(OrderByItem(
            expr=f"row.{real_col}",
            column=real_col,
            descending=desc,
        ))
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


def _flatten_derived_project(query: SQLQuery) -> SQLQuery:
    """Rewrite filter+project derived FROM into a base-table query."""
    if not query.derived_tables:
        return query
    if len(query.derived_tables) != 1:
        raise UnsupportedContractError("only one derived table in FROM is supported.")
    derived = query.derived_tables[0]
    if derived.query.agg_type:
        return query
    if derived.query.union_query is not None or derived.query.window_specs:
        return query
    if derived.query.groupby_columns:
        return query
    if not derived.source_column:
        return query

    if len(derived.columns) != 1:
        raise UnsupportedContractError("derived projection must expose exactly one column.")
    alias = next(iter(derived.columns))

    base_table = derived.query.tables[0] if derived.query.tables else ""
    new_agg_expr = query.agg_expr.replace(f"row.{alias}", f"row.{derived.source_column}")
    new_where = _merge_where(derived.query.where_expr, query.where_expr) or ""
    new_proj_exprs = [
        e.replace(f"row.{alias}", f"row.{derived.source_column}")
        for e in query.projection_exprs
    ]
    return SQLQuery(
        tables=[base_table] if base_table else [],
        table_aliases=dict(derived.query.table_aliases),
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


def _parse_select(
    expression: exp.Select,
    schema: dict[str, str] | dict[str, dict[str, str]],
    *,
    allow_subqueries: bool = True,
    derived_inner: bool = False,
    parent_ctes: list[CTESpec] | None = None,
) -> SQLQuery:
    _check_forbidden_nodes(expression)
    query = SQLQuery()
    scalar_map: dict[str, ScalarSubquery] = {}
    exists_counter = [0]
    in_counter = [0]

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
        inner_select = from_this.this
        if not isinstance(inner_select, exp.Select):
            raise UnsupportedContractError("derived table must be SELECT.")
        inner_q = _parse_select(
            inner_select, schema, allow_subqueries=False, derived_inner=True,
            parent_ctes=list(cte_map.values()),
        )
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

        for join in expression.find_all(exp.Join):
            side = (join.side or join.kind or "INNER").upper()
            if side in ("FULL",):
                require_trusted("full_join")
            elif side == "CROSS":
                require_trusted("cross_join")
            elif side in ("SEMI", "ANTI"):
                require_trusted("semi_anti_join")
            elif side == "RIGHT":
                require_trusted("nway_join")

            jtable, jalias = _parse_table_ref(join.this)
            swap_right = side == "RIGHT"
            if side == "RIGHT":
                side = "LEFT"
            if side == "CROSS":
                join_type = "CROSS"
                on_equalities: list[tuple[str, str]] = []
            elif side == "FULL":
                join_type = "FULL"
                on_equalities = _parse_on_equalities(join.args.get("on"))
            elif side in ("SEMI", "ANTI"):
                join_type = side
                on_equalities = _parse_on_equalities(join.args.get("on"))
            elif side == "LEFT":
                join_type = "LEFT"
                on_equalities = _parse_on_equalities(join.args.get("on"))
            else:
                join_type = "INNER"
                on_equalities = _parse_on_equalities(join.args.get("on"))

            if swap_right:
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
                on_equalities = [(r, l) for l, r in on_equalities]
            else:
                query.tables.append(jtable)
                if jalias:
                    query.table_aliases[jalias] = jtable

            query.joins.append(JoinSpec(
                join_type=join_type,
                table=jtable if not swap_right else query.tables[0],
                alias=jalias,
                on_equalities=on_equalities,
            ))

    resolver = derived_resolver if (query.derived_tables or cte_map) else _build_schema_resolver(
        schema, query.table_aliases, cte_columns={n: s.columns for n, s in cte_map.items()},
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
        if len(select_items) != len(query.groupby_columns) + 1:
            raise UnsupportedContractError(
                "SELECT must list all GROUP BY columns plus one aggregate."
            )
        unwrapped = [_unwrap_alias(item) for item in select_items]
        select_cols: set[str] = set()
        for item in unwrapped:
            if isinstance(item, exp.Column):
                real_col, _, _ = _resolve_col(item, resolver)
                select_cols.add(real_col)
            elif isinstance(item, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)):
                agg_node = item
        if not agg_node or select_cols != set(query.groupby_columns):
            raise UnsupportedContractError(
                "SELECT must include all GROUP BY columns and exactly one aggregate."
            )
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
                    query.where_expr = _compile_where_expr(
                        where_clause.this, resolver, query, scalar_map,
                        outer_tables=_outer_table_names(query),
                        exists_counter=exists_counter,
                        in_counter=in_counter,
                    )
                    query.scalar_subqueries.extend(scalar_map.values())
                query.limit, query.offset = _parse_limit_offset(expression)
                query.order_by = _parse_order_by(expression, resolver)
                return query
            if isinstance(select_item, exp.Subquery):
                inner = _parse_scalar_subquery(
                    select_item, resolver, alias_prefix="sel_sq",
                )
                query.scalar_subqueries.append(inner)
                query.agg_type = "SELECT_SUBQUERY"
                query.agg_expr = f"subquery_{inner.alias}_spec(cols)"
                query.agg_column = inner.alias
                where_clause = expression.args.get("where")
                if where_clause:
                    query.where_expr = _compile_where_expr(
                        where_clause.this, resolver, query, scalar_map,
                        outer_tables=_outer_table_names(query),
                        exists_counter=exists_counter,
                        in_counter=in_counter,
                    )
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
                    query.where_expr = _compile_where_expr(
                        where_clause.this, resolver, query, scalar_map,
                        outer_tables=_outer_table_names(query),
                        exists_counter=exists_counter,
                        in_counter=in_counter,
                    )
                    query.scalar_subqueries.extend(scalar_map.values())
                return query
            elif isinstance(select_item, exp.Column) or derived_inner:
                if isinstance(select_item, exp.Column):
                    real_col, col_type, _ = _resolve_col(select_item, resolver)
                    alias = select_items[0].alias or real_col
                    query.is_projection = True
                    query.projection_columns = [alias]
                    query.projection_exprs = [f"row.{real_col}"]
                    query.agg_column = alias
                where_clause = expression.args.get("where")
                if where_clause:
                    query.where_expr = _compile_where_expr(
                        where_clause.this, resolver, query, scalar_map,
                        outer_tables=_outer_table_names(query),
                        exists_counter=exists_counter,
                        in_counter=in_counter,
                    )
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
            for item in select_items:
                inner = _unwrap_alias(item)
                if not isinstance(inner, exp.Column):
                    raise UnsupportedContractError(
                        "Multi-column projection supports column references only."
                    )
                real_col, _, _ = _resolve_col(inner, resolver)
                alias = item.alias or real_col
                proj_cols.append(alias)
                proj_exprs.append(f"row.{real_col}")
            query.is_projection = True
            query.projection_columns = proj_cols
            query.projection_exprs = proj_exprs
            where_clause = expression.args.get("where")
            if where_clause:
                query.where_expr = _compile_where_expr(
                    where_clause.this, resolver, query, scalar_map,
                    outer_tables=_outer_table_names(query),
                    exists_counter=exists_counter,
                    in_counter=in_counter,
                )
                query.scalar_subqueries.extend(scalar_map.values())
            query.limit, query.offset = _parse_limit_offset(expression)
            query.order_by = _parse_order_by(expression, resolver)
            if query.distinct and query.agg_type:
                raise UnsupportedContractError("DISTINCT with scalar aggregate is not supported.")
            return _flatten_derived_project(query)

    if isinstance(agg_node, exp.Count):
        query.agg_type = "COUNT"
        if isinstance(agg_node.this, exp.Star):
            query.agg_column = "*"
            query.agg_expr = "1"
        else:
            if not isinstance(agg_node.this, exp.Column):
                raise UnsupportedContractError("COUNT argument must be * or a column.")
            real_col, _, _ = _resolve_col(agg_node.this, resolver)
            query.agg_column = real_col
            query.agg_expr = "1"
    elif isinstance(agg_node, exp.Min):
        query.agg_type = "MIN"
        query.agg_expr = _to_row_expr(agg_node.this, resolver)
        query.agg_column = agg_node.this.sql() if hasattr(agg_node.this, "sql") else ""
    elif isinstance(agg_node, exp.Max):
        query.agg_type = "MAX"
        query.agg_expr = _to_row_expr(agg_node.this, resolver)
        query.agg_column = agg_node.this.sql() if hasattr(agg_node.this, "sql") else ""
    else:
        query.agg_type = "SUM" if isinstance(agg_node, exp.Sum) else "AVG"
        query.agg_expr = _to_row_expr(agg_node.this, resolver)
        query.agg_column = agg_node.this.sql() if hasattr(agg_node.this, "sql") else ""

    where_clause = expression.args.get("where")
    if where_clause:
        query.where_expr = _compile_where_expr(
            where_clause.this, resolver, query, scalar_map,
            outer_tables=_outer_table_names(query),
            exists_counter=exists_counter,
            in_counter=in_counter,
        )
        query.scalar_subqueries.extend(scalar_map.values())

    having_clause = expression.args.get("having")
    if having_clause:
        if not query.groupby_columns:
            raise UnsupportedContractError("HAVING requires GROUP BY.")
        query.having_expr = _compile_having_expr(
            having_clause.this, resolver, query, query.agg_expr,
        )

    query.limit, query.offset = _parse_limit_offset(expression)
    query.order_by = _parse_order_by(expression, resolver)

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
