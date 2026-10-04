"""Merge a plain filter/projection over a derived table with GROUP BY into one grouped query.

    SELECT k, c FROM (SELECT x AS k, COUNT(*) AS c FROM t WHERE w GROUP BY x) d WHERE c > 3 ORDER BY c DESC LIMIT 5
    -->  SELECT x AS k, COUNT(*) AS c FROM t WHERE w GROUP BY x HAVING COUNT(*) > 3 ORDER BY c DESC LIMIT 5

Exact: an outer conjunct over group keys filters rows before grouping (WHERE), one over an aggregate filters
groups (HAVING). Anything else (outer aggregate, DISTINCT, GROUP BY, join, subquery in the filter, a derived
LIMIT or ORDER BY, SELECT *) is left unchanged, and the later stages refuse it as before.
"""

from __future__ import annotations

from sqlglot import exp


def _conjuncts(node: exp.Expression) -> list[exp.Expression]:
    if isinstance(node, exp.And):
        return _conjuncts(node.this) + _conjuncts(node.expression)
    return [node.copy()]


def _and(parts: list[exp.Expression]) -> exp.Expression | None:
    out: exp.Expression | None = None
    for part in parts:
        out = part if out is None else exp.And(this=out, expression=part)
    return out


def flatten_group_derived(tree: exp.Expression) -> exp.Expression:
    if not isinstance(tree, exp.Select):
        return tree
    source = tree.args.get("from_")
    if source is None or not isinstance(source.this, exp.Subquery) or tree.args.get("joins"):
        return tree
    inner = source.this.this
    if not isinstance(inner, exp.Select) or inner.args.get("group") is None:
        return tree
    if any(inner.args.get(k) for k in ("order", "limit", "offset", "distinct", "with_")):
        return tree
    if any(tree.args.get(k) for k in ("group", "having", "distinct", "with_", "qualify")):
        return tree
    outer_parts = [*tree.expressions, tree.args.get("where"), tree.args.get("order")]
    if any(p is not None and (p.find(exp.AggFunc) or p.find(exp.Window)) for p in outer_parts):
        return tree
    alias = source.this.alias
    outputs: dict[str, exp.Expression] = {}
    for item in inner.expressions:
        if isinstance(item, exp.Star):
            return tree
        name = item.alias if isinstance(item, exp.Alias) else getattr(item, "name", "")
        if not name:
            return tree
        outputs[name.casefold()] = (item.this if isinstance(item, exp.Alias) else item).copy()

    def resolve(col: exp.Column) -> exp.Expression | None:
        if col.table and col.table.casefold() != alias.casefold():
            return None
        return outputs.get(col.name.casefold())

    def substitute(node: exp.Expression) -> exp.Expression | None:
        node = node.copy()
        if isinstance(node, exp.Column):
            return resolve(node)
        for col in list(node.find_all(exp.Column)):
            repl = resolve(col)
            if repl is None:
                return None
            col.replace(repl.copy())
        return node

    items: list[exp.Expression] = []
    projected: dict[str, str] = {}
    for item in tree.expressions:
        body = item.this if isinstance(item, exp.Alias) else item
        if not isinstance(body, exp.Column):
            return tree
        repl = resolve(body)
        if repl is None:
            return tree
        out_name = item.alias if isinstance(item, exp.Alias) else body.name
        items.append(exp.alias_(repl, out_name, quoted=False))
        projected.setdefault(body.name.casefold(), out_name)
        projected[out_name.casefold()] = out_name

    where_parts: list[exp.Expression] = []
    having_parts: list[exp.Expression] = []
    where = tree.args.get("where")
    for conj in _conjuncts(where.this) if where is not None else []:
        if conj.find(exp.Subquery) is not None or conj.find(exp.Select) is not None:
            return tree
        merged = substitute(conj)
        if merged is None:
            return tree
        (having_parts if merged.find(exp.AggFunc) is not None else where_parts).append(merged)

    order = tree.args.get("order")
    new_order = None
    if order is not None:
        new_order = order.copy()
        for col in list(new_order.find_all(exp.Column)):
            name = projected.get(col.name.casefold())
            if name is not None:
                col.replace(exp.column(name))
                continue
            repl = resolve(col)
            if repl is None:
                return tree
            col.replace(repl.copy())

    merged = inner.copy()
    merged.set("expressions", items)
    inner_where = inner.args.get("where")
    all_where = ([inner_where.this.copy()] if inner_where is not None else []) + where_parts
    cond = _and(all_where)
    merged.set("where", exp.Where(this=cond) if cond is not None else None)
    inner_having = inner.args.get("having")
    all_having = ([inner_having.this.copy()] if inner_having is not None else []) + having_parts
    cond = _and(all_having)
    merged.set("having", exp.Having(this=cond) if cond is not None else None)
    merged.set("order", new_order)
    for key in ("limit", "offset"):
        if tree.args.get(key) is not None:
            merged.set(key, tree.args[key].copy())
    return merged


def move_inner_join_filters(tree: exp.Expression) -> bool:
    """Move the non-equality conjuncts of an INNER JOIN's ON into WHERE (exact for inner joins). True when changed."""
    changed = False
    for sel in tree.find_all(exp.Select):
        for join in sel.args.get("joins") or []:
            if (join.side or "").upper() or (join.kind or "").upper() not in ("", "INNER"):
                continue
            on = join.args.get("on")
            if on is None:
                continue
            parts = _conjuncts(on)
            keep = [
                p for p in parts if isinstance(p, exp.EQ) and isinstance(p.this, exp.Column) and isinstance(p.expression, exp.Column)
            ]
            move = [p for p in parts if p not in keep]
            if not keep or not move:
                continue
            join.set("on", _and(keep))
            where = sel.args.get("where")
            cond = _and(([where.this] if where is not None else []) + move)
            sel.set("where", exp.Where(this=cond))
            changed = True
    return changed
