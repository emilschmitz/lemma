"""Parse Lemma Basic SQL into ``declarative_spec.surface.Query`` via sqlglot."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

import sqlglot
from sqlglot import exp

from declarative_spec.literals import string_token
from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.parse_exprs import (
    arith_text,
    extract_text,
    compare_to_rational,
    fold_date,
    fold_number,
)
from declarative_spec.schema_types import rust_ident
from declarative_spec.surface import Agg, Join, Output, OrderKey, Query

_DATE_LITERAL = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_query(sql: str) -> Query:
    """Parse one SQL statement into a surface ``Query``."""
    try:
        expression = sqlglot.parse_one(sql)
    except Exception as exc:
        raise DeclarativeUnsupported(f"SQL parse error: {exc}") from exc
    return _parse_expression(expression)


def _parse_expression(expression: exp.Expression) -> Query:
    _check_forbidden(expression)
    if isinstance(expression, exp.Union):
        left = _parse_expression(expression.this)
        right = _parse_expression(expression.expression)
        op = "union_all" if not expression.args.get("distinct", True) else "union"
        left.set_op = op
        left.set_query = right
        return left
    if isinstance(expression, exp.Intersect):
        left = _parse_expression(expression.this)
        right = _parse_expression(expression.expression)
        op = "intersect_all" if not expression.args.get("distinct", True) else "intersect"
        left.set_op = op
        left.set_query = right
        return left
    if isinstance(expression, exp.Except):
        left = _parse_expression(expression.this)
        right = _parse_expression(expression.expression)
        op = "except_all" if not expression.args.get("distinct", True) else "except"
        left.set_op = op
        left.set_query = right
        return left
    if isinstance(expression, exp.Select):
        return _parse_select(_fold_anti_joins(_fold_derived_agg_joins(expression)))
    raise DeclarativeUnsupported("unsupported top-level SQL shape")


def _fold_derived_agg_joins(select: exp.Select) -> exp.Select:
    """Turn ``JOIN (SELECT g.., AGG(x) AS a FROM t [WHERE w] GROUP BY g..) m ON k = m.g.. AND v = m.a``
    into ``WHERE v = (SELECT AGG(x) FROM t WHERE w AND g = k ..)``.

    The two forms select the same rows: a group exists exactly when the correlated
    subquery has rows, and a NULL key or NULL aggregate matches in neither. The join is
    only folded when the derived table is used for nothing but that equality.
    """
    select = select.copy()
    kept: list[exp.Join] = []
    extra: list[exp.Expression] = []
    for join in select.args.get("joins") or []:
        folded = _derived_join_condition(select, join)
        if folded is None:
            kept.append(join)
        else:
            extra.append(folded)
    if not extra:
        return select
    select.set("joins", kept or None)
    where = select.args.get("where")
    cond: exp.Expression | None = where.this if where else None
    for e in extra:
        cond = e if cond is None else exp.And(this=cond, expression=e)
    select.set("where", exp.Where(this=cond))
    return select


def _derived_join_condition(select: exp.Select, join: exp.Join) -> exp.Expression | None:
    sub = join.this
    if not isinstance(sub, exp.Subquery) or not sub.alias:
        return None
    if (join.side or join.kind or "INNER").upper() != "INNER":
        return None
    inner = sub.this
    if not isinstance(inner, exp.Select) or inner.args.get("joins"):
        return None
    if any(inner.args.get(k) for k in ("having", "order", "limit", "offset", "with_", "distinct")):
        return None
    from_clause = inner.args.get("from_")
    group = inner.args.get("group")
    if from_clause is None or group is None or not isinstance(from_clause.this, exp.Table):
        return None
    group_names = []
    for g in group.expressions:
        if not isinstance(g, exp.Column):
            return None
        group_names.append(g.name.lower())
    agg_item = None
    for item in inner.expressions:
        node = _unwrap_alias(item)
        if _is_aggregate(item):
            if agg_item is not None or not isinstance(item, exp.Alias):
                return None
            agg_item = item
        elif not (isinstance(node, exp.Column) and node.name.lower() in group_names):
            return None
    if agg_item is None:
        return None
    alias = sub.alias
    on = join.args.get("on")
    pairs: list[tuple[exp.Column, str]] = []  # (outer column, derived column name)

    def conjuncts(node: exp.Expression) -> list[exp.Expression]:
        while isinstance(node, exp.Paren):
            node = node.this
        if isinstance(node, exp.And):
            return conjuncts(node.left) + conjuncts(node.right)
        return [node]

    for c in conjuncts(on) if on is not None else []:
        if not isinstance(c, exp.EQ):
            return None
        left, right = c.left, c.right
        if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
            return None
        if right.table == alias and left.table != alias:
            pairs.append((left, right.name))
        elif left.table == alias and right.table != alias:
            pairs.append((right, left.name))
        else:
            return None
    value_pairs = [p for p in pairs if p[1].lower() == agg_item.alias.lower()]
    key_pairs = [p for p in pairs if p[1].lower() != agg_item.alias.lower()]
    if len(value_pairs) != 1 or {n.lower() for _c, n in key_pairs} != set(group_names):
        return None
    if len(key_pairs) != len(group_names):
        return None
    # the derived table may appear only in its own ON clause
    for col in select.find_all(exp.Column):
        if col.table == alias and not _inside(col, join):
            return None
    inner_alias = f"dq_{alias}"
    inner = inner.copy()
    inner.args["from_"].this.set("alias", exp.TableAlias(this=exp.to_identifier(inner_alias)))
    for col in inner.find_all(exp.Column):
        if not col.table:
            col.set("table", exp.to_identifier(inner_alias))
    cond = inner.args["where"].this if inner.args.get("where") else None
    for outer_col, name in key_pairs:
        eq = exp.EQ(
            this=exp.column(name, table=inner_alias),
            expression=outer_col.copy(),
        )
        cond = eq if cond is None else exp.And(this=cond, expression=eq)
    scalar = exp.Select(expressions=[agg_item.this.copy()])
    scalar.set("from_", inner.args["from_"])
    if cond is not None:
        scalar.set("where", exp.Where(this=cond))
    return exp.EQ(this=value_pairs[0][0].copy(), expression=exp.Subquery(this=scalar))


def _fold_anti_joins(select: exp.Select) -> exp.Select:
    """Turn ``LEFT JOIN t p ON eqs WHERE .. AND p.k IS NULL`` into ``AND NOT EXISTS (SELECT 1 FROM t p WHERE eqs)``.

    Sound when ``p.k`` takes part in an ON equality (a matched row then has ``p.k`` non-NULL, so
    ``p.k IS NULL`` holds exactly for unmatched rows) and ``p`` is used nowhere else.
    """
    select = select.copy()
    where = select.args.get("where")
    if where is None:
        return select
    kept: list[exp.Join] = []
    new_where = where.this
    for join in select.args.get("joins") or []:
        result = _anti_join_where(select, join, new_where)
        if result is None:
            kept.append(join)
        else:
            new_where = result
    if len(kept) == len(select.args.get("joins") or []):
        return select
    select.set("joins", kept or None)
    select.set("where", exp.Where(this=new_where))
    return select


def _anti_join_where(
    select: exp.Select, join: exp.Join, where: exp.Expression
) -> exp.Expression | None:
    if (join.side or "").upper() != "LEFT" or not isinstance(join.this, exp.Table):
        return None
    alias = join.this.alias or join.this.name
    on = join.args.get("on")
    if on is None:
        return None

    def conjuncts(node: exp.Expression) -> list[exp.Expression]:
        while isinstance(node, exp.Paren):
            node = node.this
        if isinstance(node, exp.And):
            return conjuncts(node.left) + conjuncts(node.right)
        return [node]

    on_cols = {
        c.name.lower()
        for c in conjuncts(on)
        if isinstance(c, exp.EQ)
        for c in (c.left, c.right)
        if isinstance(c, exp.Column) and c.table == alias
    }
    where_parts = conjuncts(where)
    target = None
    for part in where_parts:
        if (
            isinstance(part, exp.Is)
            and isinstance(part.expression, exp.Null)
            and isinstance(part.this, exp.Column)
            and part.this.table == alias
            and part.this.name.lower() in on_cols
        ):
            target = part
            break
    if target is None:
        return None
    for col in select.find_all(exp.Column):
        if col.table == alias and col is not target.this and not _inside(col, on):
            return None
    rest = [p for p in where_parts if p is not target]
    sub = exp.Select(expressions=[exp.Literal.number(1)])
    sub.set("from_", exp.From(this=join.this.copy()))
    sub.set("where", exp.Where(this=on.copy()))
    not_exists = exp.Not(this=exp.Exists(this=sub))
    cond: exp.Expression = not_exists
    for p in rest:
        cond = exp.And(this=p.copy(), expression=cond)
    return cond


def _inside(node: exp.Expression, ancestor: exp.Expression) -> bool:
    cur = node
    while cur is not None:
        if cur is ancestor:
            return True
        cur = cur.parent
    return False


def _check_forbidden(expression: exp.Expression) -> None:
    for node in expression.walk():
        if isinstance(node, exp.SimilarTo):
            raise DeclarativeUnsupported("SIMILAR TO")
        if isinstance(node, exp.Window):
            raise DeclarativeUnsupported("WINDOW")
        if isinstance(node, exp.ILike):
            raise DeclarativeUnsupported("ILIKE")
        if isinstance(node, exp.Join):
            side = (node.side or node.kind or "INNER").upper()
            if side == "FULL":
                raise DeclarativeUnsupported("FULL JOIN")
            if side == "CROSS":
                raise DeclarativeUnsupported("CROSS JOIN")
            if side in ("SEMI", "ANTI"):
                raise DeclarativeUnsupported(f"{side} JOIN")
        if isinstance(node, exp.With) and node.args.get("recursive"):
            raise DeclarativeUnsupported("recursive CTE")
        _check_clause_args(node)


_EXISTS_FORBIDDEN_ARGS = ("limit", "offset", "order", "distinct", "group", "having")


def _check_clause_args(node: exp.Expression) -> None:
    """Refuse clauses that are parsed but that the spec emitter would silently drop."""
    if isinstance(node, exp.Select):
        if node.args.get("offset") is not None:
            raise DeclarativeUnsupported("OFFSET")
        if node.args.get("sample") is not None:
            raise DeclarativeUnsupported("USING SAMPLE")
        group = node.args.get("group")
        if group is not None:
            for key in ("all", "rollup", "cube", "grouping_sets", "totals"):
                if group.args.get(key):
                    raise DeclarativeUnsupported(f"GROUP BY {key.upper()}")
    if isinstance(node, exp.Table) and node.args.get("sample") is not None:
        raise DeclarativeUnsupported("TABLESAMPLE")
    if isinstance(node, exp.Limit):
        value = node.expression
        is_int = isinstance(value, exp.Literal) and not value.is_string and value.this.isdigit()
        if not is_int:
            raise DeclarativeUnsupported("LIMIT must be a non-negative integer literal")
        if node.args.get("limit_options") is not None:
            raise DeclarativeUnsupported("LIMIT PERCENT / WITH TIES")
    if isinstance(node, (exp.Exists, exp.Subquery)) and isinstance(node.this, exp.Select):
        inner = node.this
        if isinstance(node, exp.Exists):
            forbidden = _EXISTS_FORBIDDEN_ARGS
        elif isinstance(node.parent, (exp.In, exp.Binary)):
            forbidden = ("limit",)
        else:
            forbidden = ()
        for key in forbidden:
            if inner.args.get(key):
                raise DeclarativeUnsupported(f"{key.upper()} inside a subquery")
    if isinstance(node, (exp.Sum, exp.Avg, exp.Min, exp.Max, exp.Count)) and node.args.get(
        "expressions"
    ):
        raise DeclarativeUnsupported("aggregate with extra arguments")


def _unwrap_alias(node: exp.Expression) -> exp.Expression:
    if isinstance(node, exp.Alias):
        return node.this
    return node


def _is_aggregate(node: exp.Expression) -> bool:
    inner = _unwrap_alias(node)
    return isinstance(inner, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max))


@dataclass
class _Scope:
    tables: list[str] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)
    cte_names: set[str] = field(default_factory=set)

    def outer_names(self) -> set[str]:
        names = set(self.tables)
        names.update(self.aliases.keys())
        names.update(self.aliases.values())
        names.update(self.cte_names)
        return {n.lower() for n in names}


@dataclass
class _Counters:
    exists: int = 0
    in_: int = 0
    scalar: int = 0

    def next_exists(self) -> str:
        self.exists += 1
        return f"exists_{self.exists}"

    def next_in(self) -> str:
        self.in_ += 1
        return f"in_{self.in_}"

    def next_scalar(self) -> str:
        self.scalar += 1
        return f"sq_{self.scalar}"


@dataclass
class _BoolCtx:
    query: Query
    scope: _Scope
    counters: _Counters
    agg_aliases: dict[str, str] = field(default_factory=dict)
    having: bool = False


def _col_ref(node: exp.Column, scope: _Scope) -> tuple[str, str | None]:
    """Return (text_ref, base_table_or_none)."""
    name = node.name
    if node.table:
        tbl = node.table
        resolved = scope.aliases.get(tbl.lower(), tbl)
        return f"{tbl}.{name}", resolved
    return name, None


def _resolve_group_table(node: exp.Column, scope: _Scope) -> str | None:
    if node.table:
        return scope.aliases.get(node.table.lower(), node.table)
    if len(scope.tables) == 1:
        return scope.tables[0]
    return None


def _parse_select(expression: exp.Select, *, outer_scope: _Scope | None = None) -> Query:
    _check_forbidden(expression)
    query = Query()
    scope = _Scope()
    if outer_scope:
        scope.tables = list(outer_scope.tables)
        scope.aliases = dict(outer_scope.aliases)
        scope.cte_names = set(outer_scope.cte_names)
    counters = _Counters()

    with_clause = expression.args.get("with_")
    if with_clause:
        if with_clause.args.get("recursive"):
            raise DeclarativeUnsupported("recursive CTE")
        for cte_node in with_clause.expressions:
            cte_name = cte_node.alias
            inner = _parse_cte_body(cte_node.this, scope)
            query.ctes.append((cte_name, inner))
            scope.cte_names.add(cte_name.lower())

    query.distinct = bool(expression.args.get("distinct"))

    from_clause = expression.args.get("from_")
    if from_clause is None:
        raise DeclarativeUnsupported("FROM")

    from_this = from_clause.this
    if isinstance(from_this, exp.Subquery):
        inner_q = _parse_subquery_select(from_this.this, scope)
        alias = from_this.alias or "derived"
        query.derived.append((alias, inner_q))
        query.tables.append(alias)
        scope.tables.append(alias)
        scope.aliases[alias.lower()] = alias
    else:
        table_name, alias = _parse_table_ref(from_this)
        if table_name.lower() in scope.cte_names:
            cte_q = next((q for n, q in query.ctes if n.lower() == table_name.lower()), None)
            if cte_q is None:
                raise DeclarativeUnsupported("a WITH name used inside a subquery")
            query.derived.append((table_name, cte_q))
        query.tables.append(table_name)
        scope.tables.append(table_name)
        if alias:
            scope.aliases[alias.lower()] = table_name
            query.aliases[alias] = table_name

    for join in expression.args.get("joins") or []:
        side = (join.side or join.kind or "INNER").upper()
        if side == "FULL":
            raise DeclarativeUnsupported("FULL JOIN")
        if side == "CROSS":
            raise DeclarativeUnsupported("CROSS JOIN")
        if side in ("SEMI", "ANTI"):
            raise DeclarativeUnsupported(f"{side} JOIN")

        jtable, jalias, jderived = _parse_join_target(join.this, scope, query)
        if jderived is not None:
            alias, inner_q = jderived
            query.derived.append((alias, inner_q))

        swap_right = side == "RIGHT"
        if side == "CROSS":
            on_equalities: list[tuple[str, str]] = []
            on_combiner = "and"
            join_kind = "inner"
        elif join.args.get("on") is None and not join.args.get("using"):
            # ``FROM a, b``: every pair of rows, narrowed by the WHERE conditions.
            on_equalities, on_combiner, join_kind = [], "and", "inner"
        else:
            on_equalities, on_combiner = _parse_on_clause(join.args.get("on"))
            join_kind = {"INNER": "inner", "LEFT": "left", "RIGHT": "right"}.get(
                side, "inner"
            )

        if swap_right:
            base = query.tables[0]
            query.tables[0] = jtable
            query.tables.append(base)
            on_equalities = [(r, l) for l, r in on_equalities]
        else:
            query.tables.append(jtable)

        if jalias:
            scope.aliases[jalias.lower()] = jtable
            query.aliases[jalias] = jtable
        elif jtable not in scope.aliases.values():
            scope.aliases.setdefault(jtable.lower(), jtable)

        scope.tables.append(jtable)
        query.joins.append(
            Join(
                kind=join_kind,
                table=jtable,
                alias=jalias,
                on=tuple(on_equalities),
                on_combiner=on_combiner,
            )
        )

    groupby_clause = expression.args.get("group")
    if groupby_clause:
        for gb in groupby_clause.expressions:
            if not isinstance(gb, exp.Column):
                raise DeclarativeUnsupported("GROUP BY expression")
            query.group_columns.append(gb.name)
            query.group_tables.append(_resolve_group_table(gb, scope))

    select_items = expression.expressions
    agg_items: list[exp.Expression] = []
    proj: list[str] = []

    if query.group_columns:
        for item in select_items:
            inner = _unwrap_alias(item)
            alias = item.alias if isinstance(item, exp.Alias) else ""
            if _is_aggregate(item):
                agg_items.append(item)
            else:
                proj.append(_select_output(item, scope, query))
        for item in agg_items:
            query.aggs.append(_parse_agg(item, scope))
    else:
        if len(select_items) == 1:
            inner = _unwrap_alias(select_items[0])
            if _is_aggregate(select_items[0]):
                query.aggs.append(_parse_agg(select_items[0], scope))
            elif isinstance(inner, exp.Column):
                proj.append(_select_output(select_items[0], scope, query))
            elif isinstance(inner, exp.Subquery):
                name = counters.next_scalar()
                sub = _parse_subquery_select(inner.this, scope)
                query.scalar_subqueries.append((name, sub))
            elif isinstance(inner, exp.Literal):
                query.projection = ["_literal"]
            else:
                proj.append(_select_output(select_items[0], scope, query))
        else:
            for item in select_items:
                if _is_aggregate(item):
                    query.aggs.append(_parse_agg(item, scope))
                else:
                    proj.append(_select_output(item, scope, query))

    query.projection = proj
    if len(proj) + len(query.aggs) == len(select_items):
        names, proj_names, agg_aliases = [], iter(proj), iter(a.alias for a in query.aggs)
        for item in select_items:
            names.append(next(agg_aliases) if _is_aggregate(item) else next(proj_names))
        query.select_order = names
    agg_alias_map = {a.alias.lower(): a.alias for a in query.aggs if a.alias}

    where_clause = expression.args.get("where")
    if where_clause:
        ctx = _BoolCtx(query=query, scope=scope, counters=counters, agg_aliases=agg_alias_map)
        query.where_expr = _compile_bool(where_clause.this, ctx)

    having_clause = expression.args.get("having")
    if having_clause:
        if not query.group_columns:
            raise DeclarativeUnsupported("HAVING without GROUP BY")
        ctx = _BoolCtx(
            query=query,
            scope=scope,
            counters=counters,
            agg_aliases=agg_alias_map,
            having=True,
        )
        query.having_expr = _compile_bool(having_clause.this, ctx)

    query.limit, query.offset = _parse_limit_offset(expression)
    query.order_by = _parse_order_by(expression, scope, agg_alias_map)
    return query


def _parse_cte_body(body: exp.Expression, scope: _Scope) -> Query:
    if isinstance(body, exp.Select):
        return _parse_select(body, outer_scope=scope)
    return _parse_expression(body)


def _parse_subquery_select(body: exp.Expression, scope: _Scope) -> Query:
    if isinstance(body, exp.Select):
        return _parse_select(body, outer_scope=scope)
    return _parse_expression(body)


def _parse_table_ref(node: exp.Expression) -> tuple[str, str | None]:
    if isinstance(node, exp.Table):
        return node.name, node.alias or None
    if isinstance(node, exp.Alias) and isinstance(node.this, exp.Table):
        return node.this.name, node.alias
    raise DeclarativeUnsupported("FROM table reference")


def _parse_join_target(
    node: exp.Expression,
    scope: _Scope,
    query: Query,
) -> tuple[str, str | None, tuple[str, Query] | None]:
    if isinstance(node, exp.Subquery):
        inner = _parse_subquery_select(node.this, scope)
        alias = node.alias or "derived"
        return alias, alias, (alias, inner)
    table, alias = _parse_table_ref(node)
    return table, alias, None


def _parse_on_clause(
    on_expr: exp.Expression | None,
) -> tuple[list[tuple[str, str]], str]:
    if on_expr is None:
        raise DeclarativeUnsupported("JOIN ON")

    def eq_pair(node: exp.EQ) -> tuple[str, str]:
        if not isinstance(node.left, exp.Column) or not isinstance(node.right, exp.Column):
            raise DeclarativeUnsupported("JOIN ON equality")
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
            raise DeclarativeUnsupported("JOIN ON mixed AND/OR")
        elif isinstance(node, exp.Paren):
            collect_and(node.this, out)
        else:
            raise DeclarativeUnsupported("JOIN ON predicate")

    def collect_or(node: exp.Expression, out: list[tuple[str, str]]) -> None:
        if isinstance(node, exp.Or):
            collect_or(node.left, out)
            collect_or(node.right, out)
        elif isinstance(node, exp.EQ):
            out.append(eq_pair(node))
        elif isinstance(node, exp.And):
            raise DeclarativeUnsupported("JOIN ON mixed AND/OR")
        elif isinstance(node, exp.Paren):
            collect_or(node.this, out)
        else:
            raise DeclarativeUnsupported("JOIN ON predicate")

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
        raise DeclarativeUnsupported("JOIN ON")
    return equalities, combiner


def _parse_agg(item: exp.Expression, scope: _Scope) -> Agg:
    alias = item.alias if isinstance(item, exp.Alias) else ""
    inner = _unwrap_alias(item)
    if isinstance(inner, exp.Count):
        if isinstance(inner.this, exp.Distinct):
            col_node = inner.this.expressions[0]
            if not isinstance(col_node, exp.Column):
                raise DeclarativeUnsupported("COUNT(DISTINCT)")
            _ref, tbl = _col_ref(col_node, scope)
            return Agg(
                kind="COUNT_DISTINCT",
                column=col_node.name,
                alias=alias or "count_distinct",
                table=tbl,
            )
        if isinstance(inner.this, exp.Star):
            return Agg(kind="COUNT", column="*", alias=alias or "count", table=None)
        if not isinstance(inner.this, exp.Column):
            raise DeclarativeUnsupported("COUNT argument")
        _ref, tbl = _col_ref(inner.this, scope)
        return Agg(kind="COUNT", column=inner.this.name, alias=alias or "count", table=tbl)
    kind_map = {
        exp.Sum: "SUM",
        exp.Avg: "AVG",
        exp.Min: "MIN",
        exp.Max: "MAX",
    }
    for cls, kind in kind_map.items():
        if isinstance(inner, cls):
            if isinstance(inner.this, exp.Case):
                return Agg(
                    kind=kind,
                    column=None,
                    alias=alias or kind.lower(),
                    table=None,
                    expr=_compile_case(inner.this, scope),
                )
            if not isinstance(inner.this, exp.Column):
                refs: list[str] = []
                text = arith_text(inner.this, lambda c: _col_ref(c, scope)[0], refs)
                if text is None or not refs:
                    raise DeclarativeUnsupported(f"{kind} argument")
                return Agg(
                    kind=kind,
                    column=None,
                    alias=alias or kind.lower(),
                    table=None,
                    arith=text,
                    arith_refs=tuple(refs),
                )
            _ref, tbl = _col_ref(inner.this, scope)
            return Agg(
                kind=kind,
                column=inner.this.name,
                alias=alias or kind.lower(),
                table=tbl,
            )
    raise DeclarativeUnsupported("aggregate")


def _parse_limit_offset(expression: exp.Select) -> tuple[int | None, int | None]:
    limit_val: int | None = None
    offset_val: int | None = None
    limit_node = expression.args.get("limit")
    if limit_node is not None:
        lit = limit_node.expression
        if isinstance(lit, exp.Literal) and lit.is_number:
            limit_val = int(lit.this)
    offset_node = expression.args.get("offset")
    if offset_node is not None:
        lit = offset_node.this if hasattr(offset_node, "this") else offset_node
        if isinstance(lit, exp.Literal) and lit.is_number:
            offset_val = int(lit.this)
    return limit_val, offset_val


def _parse_order_by(
    expression: exp.Select,
    scope: _Scope,
    agg_aliases: dict[str, str],
) -> list[OrderKey]:
    order_clause = expression.args.get("order")
    if not order_clause:
        return []
    items: list[OrderKey] = []
    for ob in order_clause.expressions:
        inner = ob.this
        desc = bool(ob.args.get("desc"))
        if isinstance(inner, exp.Column):
            ref, _ = _col_ref(inner, scope)
            items.append(OrderKey(column=ref, descending=desc))
        elif isinstance(inner, exp.Identifier):
            name = inner.name
            items.append(OrderKey(column=agg_aliases.get(name.lower(), name), descending=desc))
        else:
            raise DeclarativeUnsupported("ORDER BY")
    return items


def _compile_bool(node: exp.Expression, ctx: _BoolCtx) -> str:
    if isinstance(node, exp.And):
        return f"({_compile_bool(node.left, ctx)} && {_compile_bool(node.right, ctx)})"
    if isinstance(node, exp.Or):
        return f"({_compile_bool(node.left, ctx)} || {_compile_bool(node.right, ctx)})"
    if isinstance(node, exp.Not):
        inner = node.this
        if isinstance(inner, exp.Exists):
            name = ctx.counters.next_exists()
            sub = _parse_subquery_select(inner.this, ctx.scope)
            ctx.query.exists.append((name, sub, True))
            return f"!{name}"
        if isinstance(inner, exp.Is):
            return _compile_is_null(inner, ctx, negated=True)
        return f"!({_compile_bool(inner, ctx)})"
    if isinstance(node, exp.Exists):
        name = ctx.counters.next_exists()
        sub = _parse_subquery_select(node.this, ctx.scope)
        ctx.query.exists.append((name, sub, False))
        return name
    if isinstance(node, exp.Between):
        exact = _between_exact(node, ctx)
        if exact is not None:
            return exact
        if not isinstance(node.this, exp.Column):
            raise DeclarativeUnsupported("BETWEEN")
        col, _ = _col_ref(node.this, ctx.scope)
        low = _compile_scalar(node.args["low"], ctx)
        high = _compile_scalar(node.args["high"], ctx)
        return f"({col} >= {low} && {col} <= {high})"
    if isinstance(node, exp.In):
        subq = node.args.get("query")
        if subq is not None:
            if not isinstance(node.this, exp.Column):
                raise DeclarativeUnsupported("IN subquery")
            col_ref, col_name = _col_ref(node.this, ctx.scope)
            name = ctx.counters.next_in()
            sub = _parse_subquery_select(subq.this, ctx.scope)
            ctx.query.in_subqueries.append((name, col_name, sub))
            return f"{name}({col_ref})"
        if not node.expressions:
            raise DeclarativeUnsupported("IN list")
        if not isinstance(node.this, exp.Column):
            raise DeclarativeUnsupported("IN list")
        col_ref, _ = _col_ref(node.this, ctx.scope)
        parts = [f"({col_ref} == {_compile_scalar(v, ctx)})" for v in node.expressions]
        return f"({' || '.join(parts)})"
    if isinstance(node, exp.Like):
        return _compile_like(node, ctx)
    if isinstance(node, (exp.EQ, exp.NEQ, exp.GT, exp.LT, exp.GTE, exp.LTE)):
        op_map = {
            exp.EQ: "==",
            exp.NEQ: "!=",
            exp.GT: ">",
            exp.LT: "<",
            exp.GTE: ">=",
            exp.LTE: "<=",
        }
        op = op_map[type(node)]
        exact = _compare_exact(node, op, ctx)
        if exact is not None:
            return exact
        if isinstance(node.right, exp.Subquery) or isinstance(node.left, exp.Subquery):
            if isinstance(node.right, exp.Subquery):
                sub_node, other = node.right, node.left
                sub_on_right = True
            else:
                sub_node, other = node.left, node.right
                sub_on_right = False
            name = ctx.counters.next_scalar()
            sub = _parse_subquery_select(sub_node.this, ctx.scope)
            ctx.query.scalar_subqueries.append((name, sub))
            side = _compile_side(other, ctx)
            if sub_on_right:
                return f"({side} {op} {name})"
            return f"({name} {op} {side})"
        left = _compile_side(node.left, ctx)
        right = _compile_side(node.right, ctx)
        return f"({left} {op} {right})"
    if isinstance(node, exp.Is):
        return _compile_is_null(node, ctx, negated=False)
    if isinstance(node, exp.Paren):
        return f"({_compile_bool(node.this, ctx)})"
    if isinstance(node, exp.Boolean):
        return "true" if node.this else "false"
    folded = _fold_int_literal(node)
    if folded is not None:
        return folded
    raise DeclarativeUnsupported("WHERE expression")


def _compile_is_null(node: exp.Is, ctx: _BoolCtx, *, negated: bool) -> str:
    col_node = node.this
    if not isinstance(col_node, exp.Column):
        raise DeclarativeUnsupported("IS on a non-column")
    col_ref, _ = _col_ref(col_node, ctx.scope)
    rhs = node.expression
    if isinstance(rhs, exp.Boolean):
        # Columns hold no NULL, so ``c IS TRUE`` is ``c == true``.
        text = f"({col_ref} == {'true' if rhs.this else 'false'})"
        return f"!{text}" if negated else text
    if not isinstance(rhs, exp.Null):
        raise DeclarativeUnsupported("IS with a non-NULL, non-boolean right side")
    return f"!is_null({col_ref})" if negated else f"is_null({col_ref})"


def _compile_side(node: exp.Expression, ctx: _BoolCtx) -> str:
    if isinstance(node, exp.Column):
        ref, _ = _col_ref(node, ctx.scope)
        if ctx.having:
            key = node.name.lower()
            if key in ctx.agg_aliases:
                return ctx.agg_aliases[key]
            if node.name in ctx.query.group_columns:
                return ref
        return ref
    if isinstance(node, exp.Literal):
        if node.is_string:
            return string_token(str(node.this))
        if node.is_number:
            return str(node.this)
        if str(node.this).upper() in ("TRUE", "FALSE"):
            return "true" if str(node.this).upper() == "TRUE" else "false"
    if isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal):
        return f"-{node.this.this}"
    if isinstance(node, exp.Boolean):
        return "true" if node.this else "false"
    if isinstance(node, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)) and ctx.having:
        return _having_agg_alias(node, ctx)
    folded = _fold_int_literal(node)
    if folded is not None:
        return folded
    return _constant_or_arith_side(node, ctx)


def _compile_case(node: exp.Case, scope: _Scope) -> str:
    """A searched CASE as a spec if-expression over ``cols.<field>@[i]``."""

    def atom(n: exp.Expression) -> str:
        if isinstance(n, exp.Column):
            _col_ref(n, scope)
            return f"cols.{rust_ident(n.name)}@[i]"
        if isinstance(n, exp.Literal) and n.is_string:
            return string_token(str(n.this))
        if isinstance(n, exp.Literal) and n.is_number:
            return str(n.this)
        raise DeclarativeUnsupported("CASE")

    def cond(n: exp.Expression) -> str:
        op_map = {
            exp.EQ: "==",
            exp.NEQ: "!=",
            exp.GT: ">",
            exp.LT: "<",
            exp.GTE: ">=",
            exp.LTE: "<=",
        }
        if type(n) not in op_map:
            raise DeclarativeUnsupported("CASE")
        return f"({atom(n.left)} {op_map[type(n)]} {atom(n.right)})"

    default = node.args.get("default")
    if default is None:
        # No ELSE yields NULL, which MIN/MAX/SUM skip; the spec has no NULL.
        raise DeclarativeUnsupported("CASE without ELSE")
    text = atom(default)
    for arm in reversed(list(node.args.get("ifs") or [])):
        text = f"if {cond(arm.this)} {{ {atom(arm.args['true'])} }} else {{ {text} }}"
    return text


def _agg_kind(inner: exp.Expression) -> str:
    if isinstance(inner, exp.Sum):
        return "SUM"
    if isinstance(inner, exp.Count):
        if isinstance(inner.this, exp.Distinct):
            return "COUNT_DISTINCT"
        return "COUNT"
    if isinstance(inner, exp.Avg):
        return "AVG"
    if isinstance(inner, exp.Min):
        return "MIN"
    if isinstance(inner, exp.Max):
        return "MAX"
    return ""


def _compile_scalar(node: exp.Expression, ctx: _BoolCtx) -> str:
    return _compile_side(node, ctx)


def _fold_int_literal(node: exp.Expression) -> str | None:
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
        if getattr(to, "this", None) != exp.DataType.Type.DATE:
            return None
        lit = node.this
        if not isinstance(lit, exp.Literal) or not lit.is_string:
            return None
        match = _DATE_LITERAL.match(str(lit.this))
        if not match:
            raise DeclarativeUnsupported("DATE literal")
        return fold_date(node)
    return None


_FLIP = {"==": "==", "!=": "!=", "<": ">", "<=": ">=", ">": "<", ">=": "<="}


def _constant_or_arith_side(node: exp.Expression, ctx: _BoolCtx) -> str:
    date = fold_date(node)
    if date is not None:
        return date
    number = fold_number(node)
    if number is not None:
        if number.denominator != 1:
            raise DeclarativeUnsupported("non-integer constant operand")
        return str(number.numerator)
    return _exact_int_side(node, ctx)


def _exact_int_side(node: exp.Expression, ctx: _BoolCtx) -> str:
    """A column or integer arithmetic. The columns must be integer typed (checked at emit)."""
    refs: list[str] = []
    text = arith_text(node, lambda c: _col_ref(c, ctx.scope)[0], refs)
    if text is None or not refs:
        raise DeclarativeUnsupported("expression operand")
    ctx.query.exact_int_refs.extend(refs)
    return text


def _compare_exact(node: exp.Expression, op: str, ctx: _BoolCtx) -> str | None:
    """A comparison where one side is a non-integer constant such as ``0.06 - 0.01``."""
    left_value, right_value = fold_number(node.left), fold_number(node.right)  # type: ignore[attr-defined]
    if left_value is not None and right_value is not None:
        if left_value.denominator == 1 and right_value.denominator == 1:
            return None
        ops = {
            "==": left_value == right_value,
            "!=": left_value != right_value,
            "<": left_value < right_value,
            "<=": left_value <= right_value,
            ">": left_value > right_value,
            ">=": left_value >= right_value,
        }
        return "true" if ops[op] else "false"
    if right_value is not None and right_value.denominator != 1:
        return compare_to_rational(_exact_int_side(node.left, ctx), op, right_value)  # type: ignore[attr-defined]
    if left_value is not None and left_value.denominator != 1:
        return compare_to_rational(
            _exact_int_side(node.right, ctx), _FLIP[op], left_value  # type: ignore[attr-defined]
        )
    return None


def _between_exact(node: exp.Between, ctx: _BoolCtx) -> str | None:
    low, high = fold_number(node.args["low"]), fold_number(node.args["high"])
    if low is None or high is None:
        return None
    if low.denominator == 1 and high.denominator == 1 and isinstance(node.this, exp.Column):
        return None
    left = _exact_int_side(node.this, ctx)
    return f"({compare_to_rational(left, '>=', low)} && {compare_to_rational(left, '<=', high)})"


def _same_agg(a: Agg, b: Agg) -> bool:
    return (
        a.kind == b.kind
        and a.column == b.column
        and a.arith == b.arith
        and a.expr == b.expr
        and (a.table is None or b.table is None or a.table.casefold() == b.table.casefold())
    )


def _having_agg_alias(node: exp.Expression, ctx: _BoolCtx) -> str:
    """Name of the aggregate a HAVING condition reads: a SELECT one, else a hidden one."""
    wanted = _parse_agg(node, ctx.scope)
    for agg in ctx.query.aggs:
        if _same_agg(agg, wanted):
            return agg.alias
    alias = f"having_{wanted.kind.lower()}_{sum(a.hidden for a in ctx.query.aggs)}"
    ctx.query.aggs.append(replace(wanted, alias=alias, hidden=True))
    return alias


def _select_output(item: exp.Expression, scope: _Scope, query: Query) -> str:
    """Record a non-aggregate SELECT item and return its output name."""
    inner = _unwrap_alias(item)
    alias = item.alias if isinstance(item, exp.Alias) else ""
    if isinstance(inner, exp.Column):
        name = alias or inner.name
        query.outputs.append(Output(name, "column", _col_ref(inner, scope)[0]))
        return name
    if not alias:
        raise DeclarativeUnsupported("SELECT expression needs an alias")
    refs: list[str] = []

    def ref(col: exp.Column) -> str:
        return _col_ref(col, scope)[0]

    if isinstance(inner, exp.Extract):
        text = extract_text(inner, ref, refs)
        query.outputs.append(Output(alias, "extract", text, tuple(refs)))
        return alias
    text = arith_text(inner, ref, refs)
    if text is None or not refs:
        raise DeclarativeUnsupported("SELECT expression")
    query.outputs.append(Output(alias, "arith", text, tuple(refs)))
    return alias


def _compile_like(node: exp.Like, ctx: _BoolCtx) -> str:
    pattern = node.expression
    if (
        not isinstance(node.this, exp.Column)
        or not isinstance(pattern, exp.Literal)
        or not pattern.is_string
        or node.args.get("escape") is not None
    ):
        raise DeclarativeUnsupported("LIKE needs a column, a string literal, and no ESCAPE")
    if any(ch in str(pattern.this) for ch in '"\\'):
        raise DeclarativeUnsupported("LIKE pattern with a quote or backslash")
    col, _ = _col_ref(node.this, ctx.scope)
    text = f"spec_like({col}, {string_token(str(pattern.this))})"
    return f"!({text})" if node.args.get("negate") else text
