"""Schema-driven NativeAggMap push helpers for 2-key (NativeU32, string) group-bys."""

from __future__ import annotations


def agg_push_method_name(u32_col: str, str_col: str) -> str:
    return f"AggPush_{u32_col}_{str_col}"


def resolve_two_key_u32_str_groupby(
    groupby_columns: list[str] | None,
    schema_dict: dict[str, str],
    *,
    col_dafny_type,
) -> tuple[str, str] | None:
    """Return (u32_col, str_col) when group-by is exactly one int + one string column."""
    if not groupby_columns or len(groupby_columns) != 2:
        return None
    c0, c1 = groupby_columns
    if c0 not in schema_dict or c1 not in schema_dict:
        return None
    t0 = col_dafny_type(schema_dict[c0])
    t1 = col_dafny_type(schema_dict[c1])
    if t0 == "NativeU32" and t1 == "string":
        return c0, c1
    if t0 == "string" and t1 == "NativeU32":
        return c1, c0
    return None


def emit_cols_agg_push_dafny(u32_col: str, str_col: str) -> str:
    name = agg_push_method_name(u32_col, str_col)
    return f"""  method {{:extern}} {{:axiom}} {name}(agg: NativeAggMap, i: int, delta: NativeI64)
    modifies agg
    ensures agg.Snapshot() == old(agg.Snapshot())[(Get{u32_col}(i), Get{str_col}(i)) := AddI64(
      if (Get{u32_col}(i), Get{str_col}(i)) in old(agg.Snapshot()) then old(agg.Snapshot())[(Get{u32_col}(i), Get{str_col}(i))] else 0 as NativeI64,
      delta)]"""


def emit_cols_agg_push_rust(u32_col: str, str_col: str) -> str:
    name = agg_push_method_name(u32_col, str_col)
    u32_field = u32_col.lower()
    str_field = str_col.lower()
    return f"""
    pub fn {name}(&self, agg: &mut NativeAggMap, i: usize, delta: i64) {{
        agg.AddStrKey(self.{u32_field}[i], self.{str_field}[i].as_str(), delta);
    }}"""
