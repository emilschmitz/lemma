"""A WITH name that is a grouped aggregate, joined to a base table on its group key.

    WITH c AS (SELECT k AS g, SUM(x) AS s FROM t [WHERE w] GROUP BY g)
    SELECT b.cols, s FROM b, c WHERE b.k = g [AND b-only filters] AND s <op> (scalar over c)

selects the same rows as the single grouped query

    SELECT b.cols, SUM(x) AS s FROM b JOIN t ON b.k = t.k [WHERE w AND b-only filters]
    GROUP BY b.cols HAVING SUM(x) <op> (scalar over c)

when ``b.k`` is a declared unique key of ``b`` that the SELECT list keeps: each group of ``c`` meets at most one ``b``
row, so the groups of the joined query are exactly the groups of ``c`` that have a ``b`` row. The WITH clause stays on
the rewritten query for the scalar over ``c``. The rewrite returns the unique key it needs; the emitter refuses when
the catalog does not declare it.
"""

from __future__ import annotations

from sqlglot import exp

from declarative_spec.parse import DeclarativeUnsupported


def _conjuncts(node: exp.Expression) -> list[exp.Expression]:
    while isinstance(node, exp.Paren):
        node = node.this
    if isinstance(node, exp.And):
        return _conjuncts(node.left) + _conjuncts(node.right)
    return [node]


def _outer_columns(node: exp.Expression) -> list[exp.Column]:
    """Columns of ``node`` that are not inside a subquery."""
    return [c for c in node.find_all(exp.Column) if c.find_ancestor(exp.Subquery) is None]


def _has_agg(node: exp.Expression) -> bool:
    return node.find(exp.AggFunc) is not None


def fold_group_join(select: exp.Select) -> tuple[exp.Select, list[tuple[str, str]]]:
    """Return the rewritten SELECT and the (table, column) unique keys it needs; unchanged when the shape is absent."""
    with_ = select.args.get("with_")
    from_ = select.args.get("from_")
    joins = select.args.get("joins") or []
    if with_ is None or from_ is None or len(joins) != 1 or select.args.get("group"):
        return select, []
    ctes = {c.alias.lower(): c.this for c in with_.expressions}
    first, second = from_.this, joins[0].this
    if not (isinstance(first, exp.Table) and isinstance(second, exp.Table)):
        return select, []
    kinds = [t.name.lower() in ctes for t in (first, second)]
    if kinds.count(True) != 1:
        return select, []
    cte_tbl, base_tbl = (first, second) if kinds[0] else (second, first)
    body = ctes[cte_tbl.name.lower()]
    if not isinstance(body, exp.Select) or body.args.get("group") is None:
        return select, []
    if (joins[0].side or joins[0].kind or "INNER").upper() != "INNER":
        raise DeclarativeUnsupported("an outer join of a grouped WITH name")
    cte_alias = cte_tbl.alias or cte_tbl.name
    if any(isinstance(i, exp.Star) for i in select.expressions) or select.args.get("distinct"):
        raise DeclarativeUnsupported("a grouped WITH name joined to a table: SELECT * or DISTINCT")
    if any(_has_agg(i) and i.find_ancestor(exp.Subquery) is None for i in select.expressions):
        raise DeclarativeUnsupported("a grouped WITH name joined to a table under an aggregate")

    # The WITH body: one table, one group key, aggregates under aliases.
    bfrom = body.args.get("from_")
    if (
        bfrom is None
        or not isinstance(bfrom.this, exp.Table)
        or body.args.get("joins")
        or any(body.args.get(k) for k in ("having", "order", "limit", "offset", "with_", "distinct"))
        or bfrom.this.name.lower() in ctes
    ):
        raise DeclarativeUnsupported("a grouped WITH name: body shape")
    group = body.args["group"].expressions
    if len(group) != 1 or not isinstance(group[0], exp.Column):
        raise DeclarativeUnsupported("a grouped WITH name: one group key column")
    inner_tbl = bfrom.this
    inner_alias = inner_tbl.alias or inner_tbl.name
    outs: dict[str, exp.Expression] = {}  # output name -> expression over the inner table
    key_item: exp.Expression | None = None
    for item in body.expressions:
        name = item.alias if isinstance(item, exp.Alias) else getattr(item, "name", "")
        inner = item.this if isinstance(item, exp.Alias) else item
        if _has_agg(inner):
            if not isinstance(item, exp.Alias):
                raise DeclarativeUnsupported("a grouped WITH name: aggregate without an alias")
            outs[name.lower()] = inner
        elif isinstance(inner, exp.Column) and name.lower() == group[0].name.lower():
            key_item = inner
            outs[name.lower()] = inner
        else:
            raise DeclarativeUnsupported("a grouped WITH name: select item is neither the key nor an aggregate")
    if key_item is None:
        raise DeclarativeUnsupported("a grouped WITH name: the group key is not selected")
    key_name = group[0].name.lower()
    agg_names = {n for n, e in outs.items() if _has_agg(e)}

    def qualified_inner(node: exp.Expression) -> exp.Expression:
        node = node.copy()
        for col in node.find_all(exp.Column):
            if not col.table:
                col.set("table", exp.to_identifier(inner_alias))
        return node

    def cte_ref(col: exp.Column) -> bool:
        if col.table:
            return col.table.lower() == cte_alias.lower()
        return col.name.lower() in outs

    where = select.args.get("where")
    on = joins[0].args.get("on")
    pool = (_conjuncts(where.this) if where else []) + (_conjuncts(on) if on is not None else [])
    key_pairs: list[exp.Column] = []
    plain: list[exp.Expression] = []
    having: list[exp.Expression] = []
    for conj in pool:
        cols = _outer_columns(conj)
        g_cols = [c for c in cols if cte_ref(c)]
        if not g_cols:
            plain.append(conj)
            continue
        if isinstance(conj, exp.EQ) and isinstance(conj.this, exp.Column) and isinstance(conj.expression, exp.Column):
            a, b = conj.this, conj.expression
            if cte_ref(a) != cte_ref(b):
                g, o = (a, b) if cte_ref(a) else (b, a)
                if g.name.lower() == key_name or g.name.lower() in outs and outs[g.name.lower()] is key_item:
                    key_pairs.append(o)
                    continue
        if len(g_cols) == len(cols) and all(c.name.lower() in agg_names for c in g_cols):
            having.append(conj)
            continue
        raise DeclarativeUnsupported("a grouped WITH name: a condition mixing its columns with the table's")
    if len(key_pairs) != 1:
        raise DeclarativeUnsupported("a grouped WITH name needs exactly one equality of its key to a table column")
    base_alias = base_tbl.alias or base_tbl.name
    if base_alias.lower() == inner_alias.lower():
        raise DeclarativeUnsupported("a grouped WITH name joined to a table that shares its name or alias with the WITH body's table")

    def qualified_base(node: exp.Expression) -> exp.Expression:
        node = node.copy()
        for col in _outer_columns(node):
            if not col.table and not cte_ref(col):
                col.set("table", exp.to_identifier(base_alias))
        return node

    base_col = qualified_base(key_pairs[0])

    # Output columns: the table's columns become group keys, the WITH aggregates are computed in place.
    new_items: list[exp.Expression] = []
    group_cols: list[exp.Expression] = []
    for item in select.expressions:
        inner = item.this if isinstance(item, exp.Alias) else item
        if not isinstance(inner, exp.Column):
            raise DeclarativeUnsupported("a grouped WITH name joined to a table: select items must be columns")
        label = item.alias or inner.name
        if cte_ref(inner):
            if inner.name.lower() not in outs:
                raise DeclarativeUnsupported("a grouped WITH name: unknown output column")
            if inner.name.lower() in agg_names:
                new_items.append(exp.Alias(this=qualified_inner(outs[inner.name.lower()]), alias=exp.to_identifier(label)))
            else:
                # The key equals the base column on every kept row.
                new_items.append(exp.Alias(this=base_col.copy(), alias=exp.to_identifier(label)))
                group_cols.append(base_col.copy())
        else:
            new_items.append(qualified_base(item))
            group_cols.append(qualified_base(inner))
    if not any(g.name.lower() == base_col.name.lower() for g in group_cols):
        raise DeclarativeUnsupported("a grouped WITH name joined to a table: the SELECT list must keep the join column")

    out = select.copy()
    inner_part = inner_tbl.copy()
    if not inner_part.alias:
        inner_part.set("alias", exp.TableAlias(this=exp.to_identifier(inner_alias)))
    out.set("from_", exp.From(this=base_tbl.copy()))
    join_eq = exp.EQ(this=base_col.copy(), expression=qualified_inner(key_item))
    out.set("joins", [exp.Join(this=inner_part, kind="INNER", on=join_eq)])
    conds = [qualified_base(c) for c in plain]
    if body.args.get("where"):
        conds.append(qualified_inner(body.args["where"].this))
    cond = None
    for c in conds:
        cond = c if cond is None else exp.And(this=cond, expression=c)
    out.set("where", exp.Where(this=cond) if cond is not None else None)
    out.set("expressions", new_items)
    out.set("group", exp.Group(expressions=group_cols))
    hcond = None
    for h in having:
        h = h.copy()
        for col in _outer_columns(h):
            if cte_ref(col):
                col.replace(qualified_inner(outs[col.name.lower()]))
        hcond = h if hcond is None else exp.And(this=hcond, expression=h)
    out.set("having", exp.Having(this=hcond) if hcond is not None else None)
    return out, [(base_tbl.name, base_col.name)]
