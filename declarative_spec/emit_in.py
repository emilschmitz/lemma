"""``x IN (SELECT ...)`` as a spec predicate over the outer row.

An uncorrelated subquery with one output column. Either a plain filtered column
(``SELECT k FROM t WHERE ...``) or one group key with a HAVING
(``SELECT k FROM t GROUP BY k HAVING SUM(v) > 300``). ``x`` is in the result when
some row of the subquery shows ``x`` as that column (a hit row of a group whose HAVING
holds). Anything else is refused.
"""

from __future__ import annotations

import re

from declarative_spec.emit_join import _Slot
from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.schema_types import SchemaModel
from declarative_spec.surface import Query


def in_subquery_calls(
    query: Query,
    prefix: str,
    params: list[_Slot],
    model: SchemaModel,
) -> tuple[dict[str, str], list[str]]:
    """Map ``in_N`` to ``fn(<outer args>, `` text and return the helper sources."""
    from declarative_spec.emit_surface import (
        _emit_helpers,
        _having,
        _idx_call,
        _map_args,
        _param_call,
        _param_sig,
        _quant,
        _cell,
        _find_col,
    )

    by_table: dict[str, str] = {}
    for slot in params:
        by_table.setdefault(slot.table.casefold(), slot.param)
    heads: dict[str, str] = {}
    sources: list[str] = []
    for name, _col, sub in query.in_subqueries:
        _check_shape(sub)
        helpers = _emit_helpers(sub, f"{prefix}{name}_", model)
        p = _param_call(helpers.params)
        idxs = _idx_call(helpers.main)
        binders, ranges = _quant(helpers.main)
        hit = f"{helpers.row_hit}({p}, {idxs})"
        if sub.group_columns:
            key_ty = helpers.key_ty
            key_of = f"{helpers.key_at}({p}, {idxs})"
            body = f"{ranges} && {hit} && {key_of} == x && ({_having(sub, helpers, {}, key_of)})"
        else:
            slot, info = _find_col(sub.projection[0], None, helpers.main, model)
            cell = _cell(slot, sub.projection[0], info)
            key_ty = _cell_type(info)
            body = f"{ranges} && {hit} && {cell} == x"
        fn = f"{prefix}{name}_in"
        sources.append(
            helpers.source
            + f"""

pub open spec fn {fn}({_param_sig(helpers.params)}, x: {key_ty}) -> bool {{
    exists|{binders}| #![trigger {hit}] {body}
}}"""
        )
        heads[name] = f"{fn}({_map_args(helpers.params, by_table)}, "
    return heads, sources


def apply_in_calls(where_expr: str, heads: dict[str, str]) -> str:
    for name, head in heads.items():
        where_expr = re.sub(rf"\b{re.escape(name)}\(", lambda _m, h=head: h, where_expr)
    return where_expr


def _cell_type(info) -> str:
    if info.spec_as == "Seq<char>":
        return "Seq<char>"
    if info.is_float:
        return "real"
    if info.spec_as == "bool":
        return "bool"
    return "int"


def _check_shape(sub: Query) -> None:
    if len(sub.projection) != 1 or sub.derived or sub.set_op:
        raise DeclarativeUnsupported("IN subquery shape")
    if sub.group_columns:
        if sub.group_columns != sub.projection or any(not a.hidden for a in sub.aggs):
            raise DeclarativeUnsupported("IN subquery shape")
    elif sub.aggs or sub.having_expr:
        raise DeclarativeUnsupported("IN subquery shape")
