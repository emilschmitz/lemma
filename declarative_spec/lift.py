"""Constant lifting: a query's literal constants in WHERE/HAVING comparisons become typed query-template parameters.

``lemma generate`` (lemma_cli/generate.py) lifts the query before the pipeline proves it, so the executor holds for every value of
those constants (one proof: declarative_spec/templates.py) and the DuckDB extension answers any later query that differs only in
them (``lemma::MatchTemplate``: the query must be the template's text with one literal token per placeholder, character for character
after normalization).

EXACTLY what is lifted: a literal token of the normalized SQL (``declarative_spec.sql_text.literal_at``: an unsigned number
``123`` / ``1.50``, a string ``'abc'``, a date ``DATE 'YYYY-MM-DD'``) that

* stands inside a WHERE or HAVING clause (of the query or of a subquery), and not inside a nested SELECT list, JOIN ... ON,
  GROUP BY, ORDER BY, LIMIT/OFFSET, QUALIFY or window clause of that clause;
* is one side of ``column <op> literal`` (``= <> < <= > >=``), a bound of ``column BETWEEN a AND b`` (not SYMMETRIC) or an item of
  ``column IN (a, b, ...)`` (the list keeps its length: the template has one parameter per item), where ``column`` is a plain column of
  a base table of the schema (parentheses around either side are fine);
* fits the column's type: an integer column takes an integer token (BIGINT parameter, the value fits i64); a DECIMAL(p,s) column a
  number with at most s fractional digits (DECIMAL(min(p,18),s) parameter); a DATE column a ``DATE '...'`` literal of a valid
  YYYY-MM-DD day (DATE parameter); a VARCHAR column a string, only under ``=``, ``<>`` or IN (VARCHAR parameter);
* lies in the range the template's ``run_query`` requires of that parameter (templates.param_ranges: the column's range).

Nothing else is lifted: not a negated number (``-5``), not a number in scientific notation, not ``'1995-01-01'`` without DATE, not a
CAST or ``::`` literal, no constant of a CASE in the SELECT list, no LIMIT/OFFSET, ORDER BY, GROUP BY, column or table name, no
DOUBLE/FLOAT/BOOLEAN/TIMESTAMP column, no comparison of two expressions (``a + 1 > 5``, ``SUM(x) > 5`` in HAVING: not a plain column),
nothing in a JOIN ... ON. A literal that is not lifted stays in the template text as written, so a later query must repeat it exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

from declarative_spec.parse import DeclarativeUnsupported

_STOP = ("Select", "Join", "Order", "Group", "Limit", "Offset", "Qualify", "Window", "Lambda")


@dataclass(frozen=True)
class Lifted:
    template: str  # `-- params: p1 TYPE, ...` + the normalized SQL with `$p<i>` in place of each lifted literal
    binding: dict[str, str]  # the query's own values (templates.spec_value text), the binding that instantiates the template to it
    literals: dict[str, str]  # name -> the literal as written in the query


def _candidates(qn: str) -> list[tuple[int, int, str]]:
    from declarative_spec.sql_text import _opaque_end, literal_at

    out = []
    i = 0
    while i < len(qn):
        lit = literal_at(qn, i)
        if lit is not None:
            out.append((i, lit[1], lit[0]))
            i = lit[1]
            continue
        j = _opaque_end(qn, i)
        i = j if j > i else i + 1
    return out


def _in_where_or_having(node) -> bool:
    from sqlglot import exp

    a = node
    while a is not None:
        if isinstance(a, (exp.Where, exp.Having)):
            return True
        if type(a).__name__ in _STOP:
            return False
        a = a.parent
    return False


def _param_for(qn: str, start: int, end: int, kind: str, schema: dict):
    """``(sql type, value text)`` when the literal at ``qn[start:end]`` may be lifted (module docstring), else None."""
    import sqlglot
    from sqlglot import exp

    from declarative_spec import templates
    from declarative_spec.schema_types import SchemaModel

    probe = "$__lemma_lift"
    try:
        tree = sqlglot.parse_one(qn[:start] + probe + qn[end:], read="duckdb")
    except sqlglot.errors.SqlglotError:
        return None
    phs = [p for p in tree.find_all(exp.Placeholder) if str(p.name) == "__lemma_lift"]
    if len(phs) != 1:
        return None
    node, parent = phs[0], phs[0].parent
    while isinstance(parent, exp.Paren):
        node, parent = parent, parent.parent
    if isinstance(parent, (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)):
        other = parent.expression if parent.this is node else parent.this
    elif isinstance(parent, exp.Between) and parent.this is not node and not parent.args.get("symmetric"):
        other = parent.this
    elif isinstance(parent, exp.In) and parent.this is not node and parent.args.get("query") is None and any(e is node for e in parent.expressions):
        other = parent.this
    else:
        return None
    if not _in_where_or_having(parent):
        return None
    other = templates._unparen(other)
    if not isinstance(other, exp.Column):
        return None
    aliases: dict[str, str] = {}
    first = None
    for table in tree.find_all(exp.Table):
        first = first or table.name
        aliases[table.alias_or_name.casefold()] = table.name
    try:
        model = SchemaModel.from_caller(dict(schema), first)
        table = templates._column_table(other, aliases, model)
        _orig, info = model.lookup_column(table, other.name)
    except (DeclarativeUnsupported, KeyError):
        return None
    text = qn[start:end]
    if info.is_date:
        if kind != "date":
            return None
        q = text.index("'")
        sql_type, value = "DATE", text[q + 1 : -1]
    elif info.exec_rust == "String":
        if kind != "string" or not isinstance(parent, (exp.EQ, exp.NEQ, exp.In)):
            return None
        sql_type, value = "VARCHAR", text[1:-1].replace("''", "'")
    elif info.precision is not None:
        if kind != "number":
            return None
        sql_type, value = f"DECIMAL({min(info.precision, 18)},{info.scale})", text
    elif not info.is_float and info.exec_rust not in ("bool", "f64"):
        if kind != "number" or "." in text:
            return None
        sql_type, value = "BIGINT", text
    else:
        return None
    param = templates.parse_template(f"-- params: x {sql_type}\nSELECT $x").params[0]
    try:
        templates.spec_value(param, value)
    except ValueError:
        return None
    return sql_type, value


def lift_constants(sql: str, schema: dict, catalog) -> Lifted | None:
    """The query template of ``sql`` with its liftable constants as parameters (module docstring), or None when nothing is lifted.
    The template's text instantiated with ``literals`` is ``normalize_sql(sql)`` exactly. Needs lemma.toml [sql] templates on."""
    from declarative_spec import templates
    from declarative_spec.sql_text import normalize_sql

    qn = normalize_sql(sql)
    if qn != normalize_sql(sql, keep_dollar=True):
        return None  # a `$` outside quotes: already a template or a prepared statement
    chosen = []
    for start, end, kind in _candidates(qn):
        got = _param_for(qn, start, end, kind, schema)
        if got is not None:
            chosen.append((start, end, *got))
    while chosen:
        names = [f"p{i + 1}" for i in range(len(chosen))]
        body, last = [], 0
        for name, (start, end, _ty, _v) in zip(names, chosen, strict=True):
            body += [qn[last:start], "$" + name]
            last = end
        body.append(qn[last:])
        text = "-- params: " + ", ".join(f"{n} {c[2]}" for n, c in zip(names, chosen, strict=True)) + "\n" + "".join(body)
        template = templates.parse_template(text)
        assert template is not None
        ranges = templates.param_ranges(template, schema, catalog)  # the authority on positions and types: raises if we disagree
        out = []
        for name, c in zip(names, chosen, strict=True):
            rng = ranges[name]
            value = templates.spec_value(template.param(name), c[3])
            if rng is None or rng[0] <= int(value) <= rng[1]:
                out.append(c)
        if len(out) == len(chosen):
            return Lifted(text, {n: c[3] for n, c in zip(names, chosen, strict=True)}, {n: qn[c[0] : c[1]] for n, c in zip(names, chosen, strict=True)})
        chosen = out  # a value outside its column's range stays a constant; name the rest again
    return None
