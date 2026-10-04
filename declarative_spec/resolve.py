"""Schema-aware checks and rewrites on a parsed ``Query`` before it is emitted.

The parser has no schema, so two things wait for here: a join ON written with bare
column names, and the rule that arithmetic and decimal-literal compares only apply
to integer-typed columns.
"""

from __future__ import annotations

from dataclasses import replace

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
        if info.is_float or info.key_kind is None or info.spec_as != "int":
            raise DeclarativeUnsupported(
                f"column {column!r} is {info.sql_type}; arithmetic and decimal literals need an integer column"
            )
    for sub in _subqueries(query):
        check_exact_integer_refs(sub, model)
