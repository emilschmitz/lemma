"""A plain WITH name used as a FROM / inner JOIN table is the table itself, narrowed by the body's WHERE.

    WITH x AS (SELECT a, b FROM t WHERE w) SELECT .. FROM x p JOIN x q ON p.a = q.a

is ``FROM t p JOIN t q ON p.a = q.a`` with ``w`` (qualified per use) added to the conditions of that use. A CTE is a pure
expression of the base tables, so substituting it at each reference is exact. Only a body that selects bare columns
under their own names from one table (no GROUP BY, DISTINCT, LIMIT, join, aggregate) is inlined; any other body is left
to the derived-table path. A LEFT/RIGHT JOIN reference is left alone: the body's WHERE would have to move into its ON.
"""

from __future__ import annotations

from sqlglot import exp


def _plain_body(name: str, body: exp.Expression, ctes: dict[str, exp.Expression]) -> bool:
    if not isinstance(body, exp.Select):
        return False
    from_ = body.args.get("from_")
    if from_ is None or not isinstance(from_.this, exp.Table) or from_.this.name.lower() in ctes:
        return False
    if any(body.args.get(k) for k in ("group", "having", "order", "limit", "offset", "with_", "distinct", "joins")):
        return False
    if body.find(exp.Subquery) is not None or body.find(exp.Window) is not None:
        return False
    for item in body.expressions:
        if isinstance(item, exp.Alias):
            if item.alias.lower() != getattr(item.this, "name", "").lower() or not isinstance(item.this, exp.Column):
                return False
        elif not isinstance(item, exp.Column):
            return False
    return from_.this.name.lower() != name


def inline_plain_ctes(root: exp.Expression) -> exp.Expression:
    """Replace each FROM / inner-JOIN use of a plain WITH name by its table and filter."""
    if not isinstance(root, exp.Select) or root.args.get("with_") is None:
        return root
    ctes = {c.alias.lower(): c.this for c in root.args["with_"].expressions}
    plain = {n: b for n, b in ctes.items() if _plain_body(n, b, ctes)}
    if not plain:
        return root
    root = root.copy()
    for sel in list(root.find_all(exp.Select)):
        extra: list[exp.Expression] = []
        refs: list[tuple[exp.Table, exp.Join | None]] = []
        from_ = sel.args.get("from_")
        if from_ is not None and isinstance(from_.this, exp.Table):
            refs.append((from_.this, None))
        for join in sel.args.get("joins") or []:
            if isinstance(join.this, exp.Table) and (join.side or "").upper() in ("", "INNER"):
                refs.append((join.this, join))
        for tbl, _join in refs:
            body = plain.get(tbl.name.lower())
            if body is None:
                continue
            alias = tbl.alias or tbl.name
            inner = body.args["from_"].this
            tbl.set("this", exp.to_identifier(inner.name))
            tbl.set("alias", exp.TableAlias(this=exp.to_identifier(alias)))
            if body.args.get("where"):
                cond = body.args["where"].this.copy()
                for col in cond.find_all(exp.Column):
                    if not col.table or col.table.lower() == (inner.alias or inner.name).lower():
                        col.set("table", exp.to_identifier(alias))
                extra.append(cond)
        if extra:
            where = sel.args.get("where")
            cond = where.this if where else None
            for e in extra:
                cond = e if cond is None else exp.And(this=cond, expression=e)
            sel.set("where", exp.Where(this=cond))
    return root
