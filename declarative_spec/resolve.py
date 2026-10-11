"""Schema-aware checks and rewrites on a parsed ``Query`` before it is emitted.

The parser has no schema, so two things wait for here: a join ON written with bare
column names, and the rule that arithmetic and decimal-literal compares only apply
to integer-typed columns.
"""

from __future__ import annotations

import re
from dataclasses import replace

from declarative_spec import sql_switches
from declarative_spec.emit_join import _build_slots
from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.schema_types import SchemaModel
from declarative_spec.surface import Query


def _subqueries(query: Query) -> list[Query]:
    subs = [sub for _n, sub, _neg in query.exists]
    subs += [sub for _n, sub in query.scalar_subqueries]
    subs += [sub for _n, sub in query.derived]
    subs += [sub for _n, _c, sub in query.in_subqueries]
    if query.set_query is not None:
        subs.append(query.set_query)
    return subs


def qualify_join_refs(query: Query, model: SchemaModel) -> None:
    """Rewrite bare column names in join ON pairs to ``alias.column``."""
    slots = _build_slots(query)

    def qualify(ref: str) -> str:
        if "." in ref:
            return ref
        table, column, _info = model.resolve_column(None, ref, [s.table for s in slots])
        slot = next(s for s in slots if s.table.casefold() == table.casefold())
        return f"{slot.alias}.{column}"

    for i, join in enumerate(query.joins):
        if any("." not in ref for pair in join.on for ref in pair):
            query.joins[i] = replace(join, on=tuple((qualify(a), qualify(b)) for a, b in join.on))
    for sub in _subqueries(query):
        qualify_join_refs(sub, model)


def check_exact_integer_refs(query: Query, model: SchemaModel) -> None:
    """Arithmetic and decimal-literal compares are exact only over integer columns."""
    refs = list(query.exact_int_refs)
    for agg in query.aggs:
        refs.extend(agg.arith_refs)
    tables = [s.table for s in _build_slots(query)]
    for ref in refs:
        qual, _, bare = ref.rpartition(".")
        table = query.aliases.get(qual, qual) or None
        _t, column, info = model.resolve_column(table, bare, tables)
        if info.is_float:
            continue  # float arithmetic is stated over reals (the rewriter admits only float operands)
        if info.key_kind is None or info.spec_as != "int":
            raise DeclarativeUnsupported(
                f"column {column!r} is {info.sql_type}; arithmetic and decimal literals need an integer column"
            )
    for sub in _subqueries(query):
        check_exact_integer_refs(sub, model)


def flatten_derived(query: Query) -> Query:
    """Merge ``SELECT ... FROM (SELECT <named outputs> FROM <joins> WHERE ...) GROUP BY ...``.

    The result reads the inner tables and WHERE directly. An outer group key that names an
    inner column or date part becomes a group expression, and an outer aggregate over an
    inner output reads that output's text. The inner query must be a plain SELECT, and the
    outer query may not filter the derived table (that would need a rewrite of its text).
    """
    if not query.derived:
        return query
    if len(query.derived) != 1 or query.tables != [query.derived[0][0]] or query.joins:
        raise DeclarativeUnsupported("derived table shape")
    _alias, inner = query.derived[0]
    if (
        inner.group_columns
        or inner.aggs
        or inner.having_expr
        or inner.order_by
        or inner.limit is not None
        or inner.offset is not None
        or inner.distinct
        or inner.set_op
        or inner.ctes
        or inner.derived
        or not inner.outputs
    ):
        raise DeclarativeUnsupported("derived table body")
    if query.where_expr or query.exists or query.in_subqueries or query.scalar_subqueries:
        raise DeclarativeUnsupported("WHERE over a derived table")
    outs = {o.name.casefold(): o for o in inner.outputs}
    names = [o.name.casefold() for o in inner.outputs]
    duplicated = {n for n in names if names.count(n) > 1}

    def output(name: str):
        if name.casefold() in duplicated:
            raise DeclarativeUnsupported(f"column {name!r} is ambiguous in the derived table")
        hit = outs.get(name.casefold())
        if hit is None:
            raise DeclarativeUnsupported(f"column {name!r} is not an output of the derived table")
        return hit

    def identity(name: str) -> None:
        """The outer name reads the inner column of the same name: a renamed output would be a silent mis-binding (the outer text is kept)."""
        src = output(name)
        if src.kind != "column" or src.text.rpartition(".")[2].casefold() != name.casefold():
            raise DeclarativeUnsupported(f"column {name!r} of a derived table is renamed or computed: only aggregates and group keys may read it")

    for name in query.projection:
        if name not in query.group_columns:
            identity(name)
    for key in query.order_by:
        if key.column.casefold() in outs and key.column not in query.group_columns:
            identity(key.column)
    for o in query.outputs:
        if o.name.casefold() in outs and o.text.rpartition(".")[2].casefold() != o.name.casefold():
            raise DeclarativeUnsupported(f"output {o.name!r} renames a column and shadows an output of the derived table")

    merged = Query(
        tables=list(inner.tables),
        aliases=dict(inner.aliases),
        joins=list(inner.joins),
        where_expr=inner.where_expr,
        exists=list(inner.exists),
        in_subqueries=list(inner.in_subqueries),
        scalar_subqueries=list(inner.scalar_subqueries),
        exact_int_refs=list(inner.exact_int_refs),
        group_columns=list(query.group_columns),
        group_tables=[None] * len(query.group_columns),
        projection=list(query.projection),
        having_expr=query.having_expr,
        order_by=list(query.order_by),
        limit=query.limit,
        offset=query.offset,
        distinct=query.distinct,
    )
    for name in query.group_columns:
        src = output(name)
        if src.kind == "arith":
            raise DeclarativeUnsupported("GROUP BY an arithmetic output of a derived table")
        merged.group_exprs[name] = src.text
        merged.exact_int_refs.extend(src.refs)
    for agg in query.aggs:
        if agg.column and agg.column != "*":
            src = output(agg.column)
            if src.kind == "column":
                agg = replace(agg, column=src.text.rpartition(".")[2], table=None)
            else:
                agg = replace(agg, column=None, table=None, arith=src.text, arith_refs=src.refs)
        elif agg.expr and sql_switches.derived_agg_expr():
            if agg.filter_expr:
                raise DeclarativeUnsupported("a FILTER over a derived table")
            text, extra = _inline_case(agg.expr, output)
            agg = replace(agg, expr=text, arith_refs=extra)  # only the substituted refs: outer names mean nothing to the inner tables
        elif agg.expr or agg.arith:
            raise DeclarativeUnsupported("aggregate expression over a derived table")
        merged.aggs.append(agg)
    return merged


_CASE_CELL = re.compile(r"\bcols\.(?:r#)?([A-Za-z_][A-Za-z0-9_]*)@\[i\]")


def _inline_case(expr: str, output) -> tuple[str, tuple[str, ...]]:
    """Rewrite the cells ``cols.<name>@[i]`` of a CASE text from derived-table output names to the inner
    expressions they stand for. A column output becomes the (alias-qualified) inner cell; an arithmetic or
    date-part output becomes its text with each column read as a cell. Returns the text and the columns
    the substituted expressions read (they must be exact integers)."""
    extra: list[str] = []

    def repl(m: re.Match[str]) -> str:
        src = output(m.group(1))
        if src.kind == "column":
            return f"cols.{src.text}@[i]"
        extra.extend(src.refs)
        refs = sorted(set(src.refs), key=len, reverse=True)
        if not refs:
            return src.text
        pattern = "(?<![\\w.])(" + "|".join(re.escape(r) for r in refs) + ")(?![\\w.(])"
        return "(" + re.sub(pattern, lambda mm: f"cols.{mm.group(1)}@[i]", src.text) + ")"

    return _CASE_CELL.sub(repl, expr), tuple(extra)
