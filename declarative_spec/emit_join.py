"""Emit open spec join conditions from a declarative ``Query``."""

from __future__ import annotations

import re
from dataclasses import dataclass

from declarative_spec.schema_types import rust_ident
from declarative_spec.surface import Join, Query

_QUAL_COL = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)$")


@dataclass(frozen=True)
class _Slot:
    table: str
    alias: str
    param: str
    struct: str
    idx: str


def _table_alias(query: Query, table: str, hint: str | None) -> str:
    if hint:
        return hint
    for alias, tname in query.aliases.items():
        if tname == table:
            return alias
    return rust_ident(table)


def _build_slots(query: Query) -> list[_Slot]:
    if not query.tables:
        return []
    slots: list[_Slot] = []
    first = query.tables[0]
    a0 = _table_alias(query, first, None)
    slots.append(
        _Slot(
            table=first,
            alias=a0,
            param=rust_ident(a0),
            struct=f"Cols_{rust_ident(first)}",
            idx="i0",
        )
    )
    for j, join in enumerate(query.joins):
        aj = _table_alias(query, join.table, join.alias)
        slots.append(
            _Slot(
                table=join.table,
                alias=aj,
                param=rust_ident(aj),
                struct=f"Cols_{rust_ident(join.table)}",
                idx=f"i{j + 1}",
            )
        )
    return slots


def _slot_by_alias(slots: list[_Slot]) -> dict[str, _Slot]:
    return {s.alias: s for s in slots}


def _col_access(slots: dict[str, _Slot], ref: str, row_idx: str) -> str:
    m = _QUAL_COL.match(ref.strip())
    if m is None:
        raise ValueError(f"join ON column must be alias.column, got {ref!r}")
    alias, col = m.group(1), m.group(2)
    slot = slots[alias]
    field = rust_ident(col)
    return f"{slot.param}.{field}@[{row_idx}]"


def _on_equality_body(
    join: Join,
    left: _Slot,
    right: _Slot,
    left_idx: str,
    right_idx: str,
    slots: dict[str, _Slot],
) -> str:
    if not join.on:
        return "true"
    parts = [
        f"{_col_access(slots, lref, left_idx)} == {_col_access(slots, rref, right_idx)}"
        for lref, rref in join.on
    ]
    combiner = join.on_combiner.casefold()
    if combiner == "or":
        return " || ".join(f"({p})" for p in parts)
    return " && ".join(parts)


def _matched_fn_name(join_index: int) -> str:
    return f"join_{join_index}_matched"


def _outer_row_fn_name(join_index: int, kind: str) -> str:
    side = "left" if kind == "left" else "right"
    return f"join_{join_index}_{side}_row"


def _emit_matched(
    join_index: int,
    join: Join,
    left: _Slot,
    right: _Slot,
    slots: dict[str, _Slot],
) -> str:
    name = _matched_fn_name(join_index)
    body = _on_equality_body(join, left, right, "li", "ri", slots)
    return f"""pub open spec fn {name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    li: int,
    ri: int,
) -> bool
{{
    {body}
}}"""


def _emit_left_row(
    join_index: int,
    left: _Slot,
    right: _Slot,
    matched_name: str,
) -> str:
    name = _outer_row_fn_name(join_index, "left")
    return f"""pub open spec fn {name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    li: int,
    ri: int,
) -> bool
{{
    &&& 0 <= li < {left.param}.n as int
    &&& ri == {right.param}.n as int || 0 <= ri < {right.param}.n as int
    &&& (
        (0 <= ri < {right.param}.n as int && {matched_name}({left.param}, {right.param}, li, ri))
        || (
            ri == {right.param}.n as int
            && !exists|j: int|
                0 <= j < {right.param}.n as int
                    && {matched_name}({left.param}, {right.param}, li, j)
        )
    )
}}"""


def _emit_right_row(
    join_index: int,
    left: _Slot,
    right: _Slot,
    matched_name: str,
) -> str:
    name = _outer_row_fn_name(join_index, "right")
    return f"""pub open spec fn {name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    li: int,
    ri: int,
) -> bool
{{
    &&& 0 <= ri < {right.param}.n as int
    &&& li == {left.param}.n as int || 0 <= li < {left.param}.n as int
    &&& (
        (0 <= li < {left.param}.n as int && {matched_name}({left.param}, {right.param}, li, ri))
        || (
            li == {left.param}.n as int
            && !exists|j: int|
                0 <= j < {left.param}.n as int
                    && {matched_name}({left.param}, {right.param}, j, ri)
        )
    )
}}"""


def _pair_condition(join_index: int, join: Join, left: _Slot, right: _Slot) -> str:
    matched = _matched_fn_name(join_index)
    kind = join.kind.casefold()
    if kind == "left":
        fn = _outer_row_fn_name(join_index, "left")
        return f"{fn}({left.param}, {right.param}, {left.idx}, {right.idx})"
    if kind == "right":
        fn = _outer_row_fn_name(join_index, "right")
        return f"{fn}({left.param}, {right.param}, {left.idx}, {right.idx})"
    return (
        f"0 <= {left.idx} < {left.param}.n as int"
        f" && 0 <= {right.idx} < {right.param}.n as int"
        f" && {matched}({left.param}, {right.param}, {left.idx}, {right.idx})"
    )


def _emit_chain(slots: list[_Slot], query: Query) -> str:
    if len(slots) < 2 or not query.joins:
        return ""
    params = ", ".join(f"{s.param}: &{s.struct}" for s in slots)
    idx_params = ", ".join(f"{s.idx}: int" for s in slots)
    conj: list[str] = []
    for j, join in enumerate(query.joins):
        left, right = slots[j], slots[j + 1]
        conj.append(_pair_condition(j, join, left, right))
        if j + 1 < len(query.joins) and join.kind.casefold() == "left":
            nxt = query.joins[j + 1]
            if nxt.kind.casefold() == "inner":
                conj.append(f"{right.idx} < {right.param}.n as int")
    body = "\n    && ".join(conj)
    return f"""pub open spec fn join_chain_row(
    {params},
    {idx_params},
) -> bool
{{
    {body}
}}"""


def join_helpers(query: Query) -> str:
    """Return open spec fns describing join matching (no nested-loop map spec)."""
    slots = _build_slots(query)
    if len(slots) < 2:
        return ""
    slot_map = _slot_by_alias(slots)
    blocks: list[str] = []
    for j, join in enumerate(query.joins):
        left, right = slots[j], slots[j + 1]
        matched_name = _matched_fn_name(j)
        blocks.append(_emit_matched(j, join, left, right, slot_map))
        kind = join.kind.casefold()
        if kind == "left":
            blocks.append(_emit_left_row(j, left, right, matched_name))
        elif kind == "right":
            blocks.append(_emit_right_row(j, left, right, matched_name))
    chain = _emit_chain(slots, query)
    if chain:
        blocks.append(chain)
    return "\n\n".join(blocks)
