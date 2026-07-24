"""Schema-driven NativeAggStrMap push helpers for 2-key (string, string) group-bys."""

from __future__ import annotations


def agg_push_str_method_name(str_col_a: str, str_col_b: str) -> str:
    return f"AggPushStr_{str_col_a}_{str_col_b}"


def resolve_two_key_str_str_groupby(
    groupby_columns: list[str] | None,
    schema_dict: dict[str, str],
    *,
    col_dafny_type,
) -> tuple[str, str] | None:
    """Return (str_col_a, str_col_b) when group-by is exactly two string columns."""
    if not groupby_columns or len(groupby_columns) != 2:
        return None
    c0, c1 = groupby_columns
    if c0 not in schema_dict or c1 not in schema_dict:
        return None
    if col_dafny_type(schema_dict[c0]) != "string":
        return None
    if col_dafny_type(schema_dict[c1]) != "string":
        return None
    return c0, c1


def emit_cols_agg_push_str_dafny(str_col_a: str, str_col_b: str) -> str:
    name = agg_push_str_method_name(str_col_a, str_col_b)
    return f"""  method {{:extern}} {{:axiom}} {name}(agg: NativeAggStrMap, i: int, delta: NativeU64)
    modifies agg
    ensures agg.Snapshot() == old(agg.Snapshot())[(Get{str_col_a}(i), Get{str_col_b}(i)) := AddU64(
      if (Get{str_col_a}(i), Get{str_col_b}(i)) in old(agg.Snapshot()) then old(agg.Snapshot())[(Get{str_col_a}(i), Get{str_col_b}(i))] else 0 as NativeU64,
      delta)]"""


def emit_cols_agg_push_str_rust(str_col_a: str, str_col_b: str) -> str:
    name = agg_push_str_method_name(str_col_a, str_col_b)
    field_a = str_col_a.lower()
    field_b = str_col_b.lower()
    return f"""
    pub fn {name}(&self, agg: &mut NativeAggStrMap, i: usize, delta: u64) {{
        agg.AddStrPair(self.{field_a}[i].as_str(), self.{field_b}[i].as_str(), delta);
    }}"""
