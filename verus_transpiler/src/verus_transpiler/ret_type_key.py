"""Map a parsed GROUP BY query to its RET_TYPE_CONFIG key."""

from __future__ import annotations

from .joins import _table_for_col
from .parse_sql import SQLQuery, UnsupportedContractError, _agg_value_type
from .value_bounds import col_verus_type


def resolve_ret_type_key(query: SQLQuery, flat_schema: dict[str, str]) -> str:
    """Map query shape to assembler RET_TYPE_CONFIG key."""
    keys = _groupby_verus_key_types(query, flat_schema)
    return _ret_type_key_from_verus_types(keys, _agg_value_type(query.agg_expr))


def _groupby_verus_key_types(
    query: SQLQuery,
    flat_schema: dict[str, str],
) -> list[str]:
    return [col_verus_type(flat_schema[c]) for c in query.groupby_columns]


def _resolve_join_groupby_ret_type_key(
    query: SQLQuery,
    multi_schema: dict[str, dict[str, str]],
) -> str:
    left_table, right_table = query.tables[0], query.tables[1]
    keys: list[str] = []
    for col, tbl in zip(query.groupby_columns, query.groupby_tables, strict=True):
        resolved = tbl or _table_for_col(
            col, tbl, left_table, right_table, multi_schema
        )
    keys.append(col_verus_type(multi_schema[resolved][col]))
    return _ret_type_key_from_verus_types(keys, _agg_value_type(query.agg_expr))


def _ret_type_key_from_verus_types(keys: list[str], val_type: str) -> str:
    if len(keys) == 1:
        if keys[0] == "u32":
            return f"map_u32_{val_type}"
        if keys[0] == "String":
            return f"map_str_{val_type}"
    if len(keys) == 2:
        if keys == ["u32", "String"]:
            return f"map_u32_str_{val_type}"
        if keys == ["String", "u32"]:
            return (
                f"map_str_str_u32_{val_type}"
                if val_type == "u64"
                else f"map_u32_str_{val_type}"
            )
        if keys == ["String", "String"]:
            return f"map_str_str_{val_type}"
    if len(keys) == 3:
        if keys == ["String", "String", "u32"]:
            return f"map_str_str_u32_{val_type}"
        if keys == ["u32", "String", "String"]:
            return f"map_u32_str_str_{val_type}"
    raise UnsupportedContractError(
        f"unsupported group-by key types {keys!r} for custom exec generation"
    )
