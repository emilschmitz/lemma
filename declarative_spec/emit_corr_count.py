"""A group key that counts right-table rows per row of the FROM table (``surface.CorrCount``).

TPC-H Q13 shape: ``SELECT n, COUNT(*) FROM (SELECT k, COUNT(r.c) AS n FROM L LEFT JOIN R ON r.fk = L.k AND pred GROUP BY k) d(k, n) GROUP BY n``.

Meaning stated here: a LEFT JOIN whose ON has conjuncts over the right table only is the join of ``L`` with the
FILTERED right table (``pred`` removes right rows before matching, it never removes a left row). ``COUNT(r.c)`` counts the
matched right rows (a nullable ``c`` never reaches here: the NULL pass turns its COUNT into a FILTER, which this shape
refuses), so a left row without a matching row has count 0: the NULL-extended row adds nothing. Grouping by ``k`` gives one group per distinct ``k``; when ``k`` is a declared unique key of ``L`` that is one
group per row of ``L``, and the outer GROUP BY n counts those rows by their count. The spec states exactly that:
the group key of a row of ``L`` is the count fold of the inner grouped query (the existing keyed COUNT fold over ``R`` where
``pred`` holds, grouped by ``fk``) at the row's own ``k``. The uniqueness of ``k`` is required of the data
(``valid_cols``, checked by the loader), and the emitter refuses a catalog that does not declare it.
"""

from __future__ import annotations

from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.schema_types import SchemaModel
from declarative_spec.surface import CorrCount, Query


def _sides(cc: CorrCount, left: str, left_alias: str, model: SchemaModel) -> tuple[str, str, str]:
    """(left key column, right key column, the right table's name) of the ON equality, resolved on the schema."""
    right = model.lookup_table(cc.right)[0]
    if model.lookup_table(left)[0].casefold() == right.casefold():
        raise DeclarativeUnsupported("a LEFT JOIN count of a table with itself")
    # A qualifier is the alias when the table has one (it hides the table name), else the table name; the two scopes must differ.
    right_names = {(cc.right_alias or right).casefold()}
    left_names = {(left_alias or left).casefold()}
    if right_names & left_names:
        raise DeclarativeUnsupported("a LEFT JOIN count whose two tables share a qualifier")

    def table_of(ref: str) -> tuple[str, str]:
        qual, _, col = ref.rpartition(".")
        if qual:
            if qual.casefold() in right_names:
                return right, model.lookup_column(right, col)[0]
            if qual.casefold() in left_names:
                return left, model.lookup_column(left, col)[0]
            raise DeclarativeUnsupported(f"column {ref!r} is not of the two joined tables")
        table, column, _info = model.resolve_column(None, col, [left, right])
        return table, column

    (ta, ca), (tb, cb) = table_of(cc.refs[0]), table_of(cc.refs[1])
    if ta.casefold() == tb.casefold():
        raise DeclarativeUnsupported("a LEFT JOIN ON equality between two columns of one table")
    lcol, rcol = (ca, cb) if ta.casefold() == left.casefold() else (cb, ca)
    for table, col in ((left, lcol), (right, rcol)):
        if model.lookup_column(table, col)[1].is_float:
            raise DeclarativeUnsupported("a LEFT JOIN count on a float key")
    tg, cg = table_of(cc.group_ref)
    if tg.casefold() != left.casefold() or cg.casefold() != lcol.casefold():
        raise DeclarativeUnsupported("the derived table groups by a column other than the LEFT JOIN's left key")
    tc, _cc = table_of(cc.count_ref)
    if tc.casefold() != right.casefold():
        raise DeclarativeUnsupported("COUNT over a LEFT JOIN must count a column of the right table")
    return lcol, rcol, right


def left_key(cc: CorrCount, left: str, left_alias: str, model: SchemaModel) -> str:
    """The left table's key column of the ON equality (it must be a declared unique key)."""
    return _sides(cc, left, left_alias, model)[0]


def corr_inner(cc: CorrCount, left: str, left_alias: str, model: SchemaModel) -> tuple[Query, str]:
    """The keyed inner query ``SELECT fk, COUNT(*) FROM R WHERE pred GROUP BY fk`` and the left key column."""
    import sqlglot
    from sqlglot import exp

    from declarative_spec.parse_query import parse_query

    lcol, rcol, right = _sides(cc, left, left_alias, model)
    right_cols = model.lookup_table(right)[1]
    conds: list[str] = []
    if cc.pred_sql:
        pred = sqlglot.parse_one(cc.pred_sql, into=exp.Condition)
        for col in pred.find_all(exp.Column):
            if col.table and col.table.casefold() not in {(cc.right_alias or right).casefold()}:
                raise DeclarativeUnsupported("a LEFT JOIN ON predicate reads a column outside the right table")
            if col.name.casefold() not in right_cols:
                raise DeclarativeUnsupported(f"a LEFT JOIN ON predicate reads {col.name!r}, which is not a column of {right}")
        conds.append(f"({cc.pred_sql})")
    qual = cc.right_alias or right
    where = f" WHERE {' AND '.join(conds)}" if conds else ""
    alias = f" {cc.right_alias}" if cc.right_alias else ""
    sql = f"SELECT {qual}.{rcol}, COUNT(*) AS corr_n FROM {right}{alias}{where} GROUP BY {qual}.{rcol}"
    return parse_query(sql), lcol


def corr_count_calls(query: Query, prefix: str, main, params, model: SchemaModel, blocks: list[str]) -> dict[str, str]:
    """Token -> spec call computing the count for the FROM row at ``i0``; the inner fold's source goes into ``blocks``."""
    from declarative_spec.emit_surface import _cell, _emit_helpers, _map_args

    calls: dict[str, str] = {}
    if not query.corr_counts:
        return calls
    if len(query.tables) != 1 or query.joins or len(query.corr_counts) != 1:
        raise DeclarativeUnsupported("a LEFT JOIN count together with other tables")
    by_table = {s.table.casefold(): s.param for s in params}
    left = main[0]
    for i, cc in enumerate(query.corr_counts):
        inner, lcol = corr_inner(cc, left.table, left.alias, model)
        helpers = _emit_helpers(inner, f"{prefix}cc{i}_", model)
        agg = helpers.aggs[0]
        info = model.lookup_column(left.table, lcol)[1]
        blocks.append(helpers.source)
        calls[cc.token] = f"{agg.name}({_map_args(helpers.params, by_table)}, 0, {_cell(left, lcol, info)})"
    return calls
