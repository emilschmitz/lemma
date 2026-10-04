"""SQL's three-valued logic over NULLABLE columns, rewritten to two-valued SQL before the surface parser.

A column the catalog declares nullable is loaded with a validity vector (``<col>__valid``: false for a NULL cell) and
its value cell is arbitrary where it is NULL. This pass states SQL's NULL semantics over those columns with plain
two-valued SQL the rest of the emitter already understands, using ``col IS [NOT] NULL`` (which the spec reads from the
validity vector):

* a WHERE / HAVING / CASE condition ``P`` becomes ``T(P)``, the condition that P is TRUE. ``T`` and ``F`` ("P is FALSE")
  are defined together: a comparison, BETWEEN, IN list or LIKE over nullable columns is TRUE when every such column is
  not NULL and it holds, FALSE when every such column is not NULL and it does not hold; ``AND`` is TRUE when both are TRUE
  and FALSE when either is FALSE; ``OR`` the dual; ``NOT`` swaps them. A NULL operand makes P neither, so a row is kept
  only when P is TRUE (``NOT (x > 1)`` is not kept for NULL x);
* an aggregate over a nullable column skips the NULL cells: ``SUM(c)`` becomes ``SUM(c) FILTER (WHERE c IS NOT NULL)``
  (the surface parser states a FILTER as a restriction of the rows that aggregate sees; ``COUNT(c)`` counts non-NULL cells,
  and an ungrouped SUM/MIN/MAX/AVG is NULL when no non-NULL cell passes);
* a nullable column that is selected (as an output cell), ordered by, joined on or used in HAVING must be proved not NULL by
  the same WHERE (a top-level ``col IS NOT NULL``, or a comparison, BETWEEN, IN or LIKE on it, which is neither TRUE nor
  FALSE for NULL); otherwise the query is refused (NULL output cells, NULL sort keys and NULL join keys are not stated yet).
  With that proof every row that passes has the column valid, so the value cell is exact.
* a nullable column in GROUP BY is allowed: SQL puts all NULL keys in ONE group. The emitter makes the key ``(valid, value)``
  (``(false, default)`` for NULL) and the output field an ``Option``, unless the WHERE proves the column non-NULL.

Anything the pass cannot state exactly raises ``DeclarativeUnsupported``.
"""

from __future__ import annotations

from sqlglot import exp

from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.schema_types import SchemaModel

_COMPARE = (exp.EQ, exp.NEQ, exp.GT, exp.LT, exp.GTE, exp.LTE)
_AGG = (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)
_VALUE_PREDICATES = (*_COMPARE, exp.Between, exp.Like, exp.In)


def _and(parts: list[exp.Expression]) -> exp.Expression:
    out = parts[0]
    for part in parts[1:]:
        out = exp.And(this=out, expression=part)
    return out


def _conjuncts(node: exp.Expression | None) -> list[exp.Expression]:
    if node is None:
        return []
    if isinstance(node, exp.And):
        return _conjuncts(node.this) + _conjuncts(node.expression)
    if isinstance(node, exp.Paren):
        return _conjuncts(node.this)
    return [node]


class _Scope:
    def __init__(self, sources: dict[str, str | None], parent: _Scope | None) -> None:
        self.sources = sources  # alias (casefold) -> table (casefold), None for a derived table
        self.parent = parent
        self.proven: set[tuple[str, str]] = set()  # (alias, column) with a top-level IS NOT NULL in this WHERE


class _NullRewriter:
    def __init__(self, model: SchemaModel) -> None:
        self.model = model

    # ---- column resolution ---------------------------------------------------------------------------

    def _owner(self, col: exp.Column, scope: _Scope | None) -> tuple[str, str] | None:
        """(alias, table) of the source that provides ``col``, searching this scope and then the outer ones."""
        name = col.name.casefold()
        while scope is not None:
            if col.table:
                alias = col.table.casefold()
                if alias in scope.sources:
                    table = scope.sources[alias]
                    return None if table is None else (alias, table)
            else:
                hits = [
                    (alias, table)
                    for alias, table in scope.sources.items()
                    if table is not None and name in self.model.tables.get(table, {})
                ]
                if len(hits) > 1 and len({self.model.is_nullable(t, name) for _a, t in hits}) > 1:
                    raise DeclarativeUnsupported(f"column {name!r} is ambiguous and nullable in one table only")
                if hits:
                    return hits[0]
            scope = scope.parent
        return None

    def _nullable(self, col: exp.Column, scope: _Scope | None) -> bool:
        owner = self._owner(col, scope)
        return owner is not None and self.model.is_nullable(owner[1], col.name)

    def _proven(self, col: exp.Column, scope: _Scope) -> bool:
        owner = self._owner(col, scope)
        return owner is not None and (owner[0], col.name.casefold()) in scope.proven

    def _valid_when(self, node: exp.Expression, truth: bool, scope: _Scope) -> set[tuple[str, str]]:
        """The (alias, column) pairs that are not NULL in every row where ``node`` evaluates to ``truth``.

        A comparison, BETWEEN, IN list or LIKE over a nullable column is neither TRUE nor FALSE when the column is
        NULL, so either outcome proves it non-NULL; ``col IS NULL`` proves it only when it is FALSE."""
        if isinstance(node, exp.Paren):
            return self._valid_when(node.this, truth, scope)
        if isinstance(node, exp.Not):
            return self._valid_when(node.this, not truth, scope)
        if isinstance(node, (exp.And, exp.Or)):
            left = self._valid_when(node.this, truth, scope)
            right = self._valid_when(node.expression, truth, scope)
            both = isinstance(node, exp.And) == truth  # AND true / OR false: both sides settle
            return left | right if both else left & right
        if isinstance(node, exp.Is) and isinstance(node.expression, exp.Null) and isinstance(node.this, exp.Column):
            owner = self._owner(node.this, scope)
            if not truth and owner is not None:
                return {(owner[0], node.this.name.casefold())}
            return set()
        if isinstance(node, _VALUE_PREDICATES):
            found: set[tuple[str, str]] = set()
            for col in self._nullable_columns(node, scope):
                owner = self._owner(col, scope)
                if owner is not None:
                    found.add((owner[0], col.name.casefold()))
            return found
        return set()

    def _nullable_columns(self, node: exp.Expression, scope: _Scope) -> list[exp.Column]:
        """The nullable columns of ``node`` outside any subquery (a subquery is rewritten in its own scope)."""
        found: list[exp.Column] = []
        stack = [node]
        while stack:
            cur = stack.pop()
            if isinstance(cur, (exp.Select, exp.Subquery)):
                continue
            if isinstance(cur, exp.Column) and self._nullable(cur, scope):
                found.append(cur)
            for value in cur.args.values():
                for child in value if isinstance(value, list) else [value]:
                    if isinstance(child, exp.Expression):
                        stack.append(child)
        return found

    def _unproven(self, node: exp.Expression, scope: _Scope) -> list[exp.Column]:
        return [c for c in self._nullable_columns(node, scope) if not self._proven(c, scope)]

    def _refuse_unproven(self, node: exp.Expression, scope: _Scope, what: str) -> None:
        bad = self._unproven(node, scope)
        if bad:
            raise DeclarativeUnsupported(
                f"nullable column {bad[0].sql()} in {what}: add `{bad[0].sql()} IS NOT NULL` to the WHERE "
                "(NULL group keys, NULL output cells and NULL join keys are not stated yet)"
            )

    # ---- statements ----------------------------------------------------------------------------------

    def statement(self, node: exp.Expression) -> None:
        if isinstance(node, exp.Select):
            self.select(node, None, top=True)
        elif isinstance(node, (exp.Union, exp.Intersect, exp.Except)):
            for sel in (node.this, node.expression):
                self.statement_nested(sel)
        else:
            raise DeclarativeUnsupported("unsupported top-level SQL shape")

    def statement_nested(self, node: exp.Expression) -> None:
        if isinstance(node, exp.Select):
            self.select(node, None, top=False)
        else:
            self.statement(node)

    def select(self, sel: exp.Select, parent: _Scope | None, *, top: bool) -> None:
        sources: dict[str, str | None] = {}
        from_ = sel.args.get("from_")
        raw = ([from_.this] if from_ is not None else []) + [j.this for j in sel.args.get("joins") or []]
        derived: list[exp.Subquery] = []
        for src in raw:
            if isinstance(src, exp.Table):
                sources[(src.alias or src.name).casefold()] = src.name.casefold()
            elif isinstance(src, exp.Subquery):
                sources[(src.alias or "derived").casefold()] = None
                derived.append(src)
        scope = _Scope(sources, parent)
        for sub in derived:
            inner = sub.this
            if isinstance(inner, exp.Select):
                self.select(inner, scope, top=False)
                self._derived_outputs_are_not_null(inner)
            else:
                self.statement_nested(inner)

        where = sel.args.get("where")
        if where is not None:
            scope.proven |= self._valid_when(where.this, True, scope)
        if where is not None:
            true_, _false = self.tf(where.this, scope)
            where.set("this", true_)

        for join in sel.args.get("joins") or []:
            on = join.args.get("on")
            if on is not None:
                self._refuse_unproven(on, scope, "a JOIN condition")
        order = sel.args.get("order")
        if order is not None:
            self._refuse_unproven(order, scope, "ORDER BY")
        having = sel.args.get("having")
        if having is not None:
            for agg in having.find_all(*_AGG):
                if self._unproven(agg, scope):
                    raise DeclarativeUnsupported("an aggregate over a nullable column in HAVING")
            self._refuse_unproven(having.this, scope, "HAVING")
            true_, _false = self.tf(having.this, scope)
            having.set("this", true_)

        group = sel.args.get("group")
        keys: set[tuple[str, str]] = set()
        for g in (group.expressions if group is not None else []):
            if isinstance(g, exp.Column):
                owner = self._owner(g, scope)
                if owner is not None:
                    keys.add((owner[0], g.name.casefold()))
        items = []
        for item in sel.expressions:
            items.append(self._select_item(item, scope, top, keys))
        sel.set("expressions", items)

    def _derived_outputs_are_not_null(self, inner: exp.Select) -> None:
        """A derived table's outputs are columns of the outer query: they must not carry NULL."""
        for item in inner.expressions:
            body = item.this if isinstance(item, exp.Alias) else item
            if isinstance(body, exp.Filter) or body.find(exp.Filter) is not None:
                raise DeclarativeUnsupported("an aggregate that skips NULL cells inside a derived table")

    def _select_item(
        self, item: exp.Expression, scope: _Scope, top: bool, keys: set[tuple[str, str]]
    ) -> exp.Expression:
        alias = item.alias if isinstance(item, exp.Alias) else ""
        body = item.this if isinstance(item, exp.Alias) else item
        if isinstance(body, exp.Column) and self._owner(body, scope) is not None:
            owner = self._owner(body, scope)
            if (owner[0], body.name.casefold()) in keys:
                return item  # a GROUP BY key: its NULL group is stated by the key (see the module docstring)
        if isinstance(body, _AGG):
            new = self._aggregate(body, scope, top)
        else:
            if isinstance(body, exp.Star):
                return item
            for case in ([body] if isinstance(body, exp.Case) else list(body.find_all(exp.Case))):
                self._case(case, scope)
            self._refuse_unproven(body, scope, "the SELECT list")
            new = body
        return exp.alias_(new, alias, quoted=False) if alias else new

    def _aggregate(self, agg: exp.Expression, scope: _Scope, top: bool) -> exp.Expression:
        for case in list(agg.find_all(exp.Case)):
            self._case(case, scope)
        bad = self._unproven(agg, scope)
        if not bad:
            return agg
        if not top:
            raise DeclarativeUnsupported(
                f"an aggregate over the nullable column {bad[0].sql()} outside the outermost SELECT list"
            )
        if isinstance(agg.this, exp.Star):
            return agg
        distinct: dict[str, exp.Column] = {}
        for col in bad:
            distinct.setdefault(col.sql().casefold(), col)
        guard = _and([exp.Not(this=exp.Is(this=c.copy(), expression=exp.Null())) for c in distinct.values()])
        return exp.Filter(this=agg, expression=exp.Where(this=guard))

    def _case(self, case: exp.Case, scope: _Scope) -> None:
        for arm in case.args.get("ifs") or []:
            arm.set("this", self.tf(arm.this, scope)[0])
            self._refuse_unproven(arm.args["true"], scope, "a CASE result")
        default = case.args.get("default")
        if default is not None:
            self._refuse_unproven(default, scope, "a CASE result")

    # ---- predicates ----------------------------------------------------------------------------------

    def tf(self, node: exp.Expression, scope: _Scope) -> tuple[exp.Expression, exp.Expression]:
        """(P is TRUE, P is FALSE) as two-valued SQL."""
        if isinstance(node, exp.Paren):
            true_, false_ = self.tf(node.this, scope)
            return exp.Paren(this=true_), exp.Paren(this=false_)
        if isinstance(node, exp.And):
            ta, fa = self.tf(node.this, scope)
            tb, fb = self.tf(node.expression, scope)
            return (
                exp.Paren(this=exp.And(this=ta, expression=tb)),
                exp.Paren(this=exp.Or(this=fa, expression=fb)),
            )
        if isinstance(node, exp.Or):
            ta, fa = self.tf(node.this, scope)
            tb, fb = self.tf(node.expression, scope)
            return (
                exp.Paren(this=exp.Or(this=ta, expression=tb)),
                exp.Paren(this=exp.And(this=fa, expression=fb)),
            )
        if isinstance(node, exp.Not):
            true_, false_ = self.tf(node.this, scope)
            return false_, true_
        if isinstance(node, exp.Is):
            return node, exp.Not(this=node.copy())
        if isinstance(node, exp.Exists):
            self._subqueries(node, scope)
            return node, exp.Not(this=node.copy())
        if isinstance(node, _VALUE_PREDICATES):
            self._subqueries(node, scope)
            if isinstance(node, exp.In):
                for item in node.expressions:
                    self._refuse_unproven(item, scope, "an IN list")
                query = node.args.get("query")
                if query is not None:
                    self._subquery_column_is_not_null(query)
            nullable = self._nullable_columns(node, scope)
            cols: dict[str, exp.Column] = {}
            for col in nullable:
                cols.setdefault(col.sql().casefold(), col)
            if not cols:
                return node, exp.Not(this=exp.Paren(this=node.copy()))
            guard = _and([exp.Not(this=exp.Is(this=c.copy(), expression=exp.Null())) for c in cols.values()])
            return (
                exp.Paren(this=exp.And(this=guard, expression=exp.Paren(this=node))),
                exp.Paren(this=exp.And(this=guard.copy(), expression=exp.Not(this=exp.Paren(this=node.copy())))),
            )
        if isinstance(node, exp.Boolean):
            return node, exp.Not(this=node.copy())
        if self._nullable_columns(node, scope):
            raise DeclarativeUnsupported("a nullable column in a boolean expression the NULL rewrite does not state")
        self._subqueries(node, scope)
        return node, exp.Not(this=node.copy())

    def _subqueries(self, node: exp.Expression, scope: _Scope) -> None:
        """Rewrite every SELECT directly inside ``node`` in its own scope (correlated references see ``scope``)."""
        direct = []
        for sub in node.find_all(exp.Select):
            cur, nested = sub.parent, False
            while cur is not None and cur is not node:
                if isinstance(cur, exp.Select):
                    nested = True
                    break
                cur = cur.parent
            if not nested:
                direct.append(sub)
        for sub in direct:
            self.select(sub, scope, top=False)

    def _subquery_column_is_not_null(self, query: exp.Expression) -> None:
        sel = query.this if isinstance(query, exp.Subquery) else query
        if isinstance(sel, exp.Select) and sel.find(exp.Filter) is not None:
            raise DeclarativeUnsupported("an IN subquery over a nullable column")


def rewrite_nulls(tree: exp.Expression, model: SchemaModel) -> exp.Expression:
    """``tree`` with SQL NULL semantics over the catalog's nullable columns stated in two-valued SQL (in place)."""
    if not model.nullable:
        return tree
    names = {column for _table, column in model.nullable}
    if not any(col.name.casefold() in names for col in tree.find_all(exp.Column)):
        return tree  # no nullable column is mentioned: nothing to restate
    _NullRewriter(model).statement(tree)
    return tree
