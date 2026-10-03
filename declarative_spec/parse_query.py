"""Parse Lemma Basic SQL into ``declarative_spec.surface.Query`` via sqlglot."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.schema_types import rust_ident
from declarative_spec.surface import Agg, Join, OrderKey, Query

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
        return _parse_select(expression)
    raise DeclarativeUnsupported("unsupported top-level SQL shape")


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
            cte_q = next(q for n, q in query.ctes if n.lower() == table_name.lower())
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
            if isinstance(inner, exp.Column):
                proj.append(alias or inner.name)
            elif _is_aggregate(item):
                agg_items.append(item)
            else:
                raise DeclarativeUnsupported("SELECT expression")
        for item in agg_items:
            query.aggs.append(_parse_agg(item, scope))
    else:
        if len(select_items) == 1:
            inner = _unwrap_alias(select_items[0])
            if _is_aggregate(select_items[0]):
                query.aggs.append(_parse_agg(select_items[0], scope))
            elif isinstance(inner, exp.Column):
                alias = select_items[0].alias or inner.name
                proj.append(alias)
            elif isinstance(inner, exp.Subquery):
                name = counters.next_scalar()
                sub = _parse_subquery_select(inner.this, scope)
                query.scalar_subqueries.append((name, sub))
            elif isinstance(inner, exp.Literal):
                query.projection = ["_literal"]
            else:
                raise DeclarativeUnsupported("SELECT expression")
        else:
            for item in select_items:
                inner = _unwrap_alias(item)
                if isinstance(inner, exp.Column):
                    proj.append(item.alias or inner.name)
                elif _is_aggregate(item):
                    query.aggs.append(_parse_agg(item, scope))
                else:
                    raise DeclarativeUnsupported("SELECT expression")

    query.projection = proj
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
                raise DeclarativeUnsupported(f"{kind} argument")
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
        raise DeclarativeUnsupported("LIKE")
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
        raise DeclarativeUnsupported("IS NULL")
    col_ref, _ = _col_ref(col_node, ctx.scope)
    is_null = isinstance(node.expression, exp.Null)
    if negated:
        is_null = not is_null
    if is_null:
        return f"is_null({col_ref})"
    return f"!is_null({col_ref})"


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
            return f'"{node.this}"@'
        if node.is_number:
            return str(node.this)
        if str(node.this).upper() in ("TRUE", "FALSE"):
            return "true" if str(node.this).upper() == "TRUE" else "false"
    if isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal):
        return f"-{node.this.this}"
    if isinstance(node, exp.Boolean):
        return "true" if node.this else "false"
    if isinstance(node, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)) and ctx.having:
        inner = _unwrap_alias(node)
        alias = node.alias if isinstance(node, exp.Alias) else ""
        for agg in ctx.query.aggs:
            if agg.kind == _agg_kind(inner) and (not alias or agg.alias == alias):
                return agg.alias or agg.kind.lower()
        raise DeclarativeUnsupported("HAVING aggregate")
    folded = _fold_int_literal(node)
    if folded is not None:
        return folded
    raise DeclarativeUnsupported("expression operand")


def _compile_case(node: exp.Case, scope: _Scope) -> str:
    """A searched CASE as a spec if-expression over ``cols.<field>@[i]``."""

    def atom(n: exp.Expression) -> str:
        if isinstance(n, exp.Column):
            _col_ref(n, scope)
            return f"cols.{rust_ident(n.name)}@[i]"
        if isinstance(n, exp.Literal) and n.is_string:
            return f'"{n.this}"@'
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
    text = atom(default) if default is not None else "0"
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
        y, m, d = (int(x) for x in match.groups())
        return f"{y:04d}{m:02d}{d:02d}"
    return None
