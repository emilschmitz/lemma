"""Schema-driven AggPush helpers for 2-key (string, string) group-bys."""

from __future__ import annotations

from .value_bounds import col_verus_type


def agg_push_str_method_name(str_col_a: str, str_col_b: str) -> str:
    return f"agg_push_str_{str_col_a.lower()}_{str_col_b.lower()}"


def resolve_two_key_str_str_groupby(
    groupby_columns: list[str] | None,
    schema_dict: dict[str, str],
) -> tuple[str, str] | None:
    if not groupby_columns or len(groupby_columns) != 2:
        return None
    c0, c1 = groupby_columns
    if c0 not in schema_dict or c1 not in schema_dict:
        return None
    if col_verus_type(schema_dict[c0]) != "String":
        return None
    if col_verus_type(schema_dict[c1]) != "String":
        return None
    return c0, c1


def emit_cols_agg_push_str_verus(str_col_a: str, str_col_b: str, struct_name: str = "Cols") -> str:
    _ = struct_name
    name = agg_push_str_method_name(str_col_a, str_col_b)
    field_a = str_col_a.lower()
    field_b = str_col_b.lower()
    return f"""    #[verifier::external_body]
    pub exec fn {name}(
        &self,
        agg: &mut std::collections::HashMap<(String, String), u64>,
        i: usize,
        delta: u64,
    )
    {{
        let key = (self.{field_a}[i].clone(), self.{field_b}[i].clone());
        let prev = agg.get(&key).copied().unwrap_or(0);
        agg.insert(key, prev + delta);
    }}"""
