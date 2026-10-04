"""Refuse every spec that needs float ordering, equality, MIN or MAX.

The spec states a float as a `real` (the exact value), and the agent's `f64` comparisons are vstd's
uninterpreted `lt_ensures`-style predicates with no proved link to ordering on `real`. A proof that a
`f64` branch matches a `real` comparison therefore cannot be written without a trusted comparison
bridge, which is a new trusted statement and is not on this menu. Float SUM and AVG (the eps lemmas)
are unaffected: they never compare a float.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.schema_types import classify_sql_type

_REASON = "float comparison has no proved bridge to reals"
_COMPARISONS = (exp.LT, exp.LTE, exp.GT, exp.GTE, exp.EQ, exp.NEQ, exp.Between)


def _float_columns(schema: dict, tables: set[str]) -> dict[str, set[str]]:
    first = next(iter(schema.values()), None)
    if isinstance(first, str):  # flat schema: one projected table, named by the SQL's FROM
        names = {c.casefold() for c, ty in schema.items() if classify_sql_type(str(ty)).is_float}
        return {t: names for t in tables}
    return {
        t.casefold(): {c.casefold() for c, ty in cols.items() if classify_sql_type(str(ty)).is_float}
        for t, cols in schema.items()
    }


def _walk_skipping_count(node: exp.Expression):
    """Descendants of ``node`` that are not under a COUNT: counting a float compares nothing."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        for child in current.iter_expressions():
            if not isinstance(child, exp.Count):
                stack.append(child)


def refuse_float_ordering(sql: str, schema: dict) -> None:
    """Raise ``DeclarativeUnsupported`` when ``sql`` orders, compares, MINs or MAXes a float."""
    try:
        tree = sqlglot.parse_one(sql)
    except Exception:  # noqa: BLE001 - the real parser reports the SQL error with its own message
        return
    alias_to_table = {t.alias_or_name.casefold(): t.name.casefold() for t in tree.find_all(exp.Table)}
    tables = set(alias_to_table.values())
    floats = _float_columns(schema, tables)

    def column_is_float(col: exp.Column) -> bool:
        qual = col.table.casefold()
        name = col.name.casefold()
        if qual:
            return name in floats.get(alias_to_table.get(qual, qual), ())
        return any(name in floats.get(t, ()) for t in tables)

    def has_float(node: exp.Expression, float_aliases: set[str]) -> bool:
        for sub in _walk_skipping_count(node):
            if isinstance(sub, exp.Column):
                if column_is_float(sub) or (not sub.table and sub.name.casefold() in float_aliases):
                    return True
        return False

    float_aliases: set[str] = set()
    for select in tree.find_all(exp.Select):
        for item in select.expressions:
            if isinstance(item, exp.Alias) and has_float(item.this, set()):
                float_aliases.add(item.alias.casefold())

    for node in tree.walk():
        if isinstance(node, _COMPARISONS):
            kind = "comparison"
        elif isinstance(node, (exp.Min, exp.Max)):
            kind = "MIN/MAX"
        elif isinstance(node, exp.Ordered):
            kind = "ORDER BY"
        else:
            continue
        if has_float(node, float_aliases):
            raise DeclarativeUnsupported(
                f"{_REASON}: {kind} over a float value in `{node.sql()[:120]}` "
                "(f64 comparisons in vstd are uninterpreted, so a body cannot be proved equal to the real-valued spec)"
            )
