"""Schema-driven AggPush helpers for 2-key (u32, string) group-bys."""

from __future__ import annotations

from .value_bounds import col_verus_type


def agg_push_method_name(u32_col: str, str_col: str) -> str:
    return f"agg_push_{u32_col.lower()}_{str_col.lower()}"


def resolve_two_key_u32_str_groupby(
    groupby_columns: list[str] | None,
    schema_dict: dict[str, str],
) -> tuple[str, str] | None:
    if not groupby_columns or len(groupby_columns) != 2:
        return None
    c0, c1 = groupby_columns
    if c0 not in schema_dict or c1 not in schema_dict:
        return None
    t0 = col_verus_type(schema_dict[c0])
    t1 = col_verus_type(schema_dict[c1])
    if t0 == "u32" and t1 == "String":
        return c0, c1
    if t0 == "String" and t1 == "u32":
        return c1, c0
    return None


def emit_cols_agg_push_verus(u32_col: str, str_col: str, struct_name: str = "Cols") -> str:
    _ = struct_name
    name = agg_push_method_name(u32_col, str_col)
    u32_field = u32_col.lower()
    str_field = str_col.lower()
    return f"""    #[verifier::external_body]
    pub exec fn {name}(
        &self,
        agg: &mut std::collections::HashMap<(u32, String), i64>,
        i: usize,
        delta: i64,
    )
    {{
        let key = (self.{u32_field}[i], self.{str_field}[i].clone());
        let prev = agg.get(&key).copied().unwrap_or(0);
        agg.insert(key, prev + delta);
    }}"""
