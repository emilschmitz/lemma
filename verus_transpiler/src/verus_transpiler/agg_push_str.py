"""Schema-driven Cols row-push helpers for 2-key (string, string) group-bys.

Thin wrappers around structural ``agg_add_str_str__*`` (vstd ``HashMapWithView``).
"""

from __future__ import annotations

from .agg_push import _i64_prev_fit_requires, _u64_prev_fit_requires
from .value_bounds import col_verus_type


def agg_push_str_method_name(str_col_a: str, str_col_b: str) -> str:
    return f"agg_push_str_{str_col_a.lower()}_{str_col_b.lower()}"


def agg_bridge_str_str(val_type: str) -> tuple[str, str, str]:
    """Return ``(agg_new_fn, agg_add_fn, rust_map_type)`` for two-string keys."""
    if val_type not in ("u64", "i64"):
        raise ValueError(f"unsupported agg value type for str+str group-by: {val_type!r}")
    suffix = f"str_str__{val_type}"
    rust_map = f"HashMapWithView<(String, String), {val_type}>"
    return f"agg_new_{suffix}", f"agg_add_{suffix}", rust_map


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


def _agg_push_str_str_requires(
    str_col_a: str,
    str_col_b: str,
    *,
    val_type: str,
    delta_name: str = "delta",
) -> str:
    a_base = str_col_a.lower()
    b_base = str_col_b.lower()
    spec_key = f"(self.get_{a_base}(i as int), self.get_{b_base}(i as int))"
    prev_expr = (
        f"if old(agg)@.contains_key({spec_key}) {{ old(agg)@[{spec_key}] }} "
        f"else {{ 0{val_type} }}"
    )
    clauses = ["i < self.n"]
    if val_type == "u64":
        clauses.append(f"{delta_name} < LEMMA_MAX_CELL_U64")
        clauses.append(_u64_prev_fit_requires(prev_expr, f"({delta_name} as int)"))
    else:
        clauses.append(_i64_prev_fit_requires(prev_expr, f"({delta_name} as int)"))
    return " &&\n        ".join(clauses)


def _agg_push_str_str_ensures(
    str_col_a: str,
    str_col_b: str,
    *,
    val_type: str,
    delta_name: str = "delta",
) -> str:
    a_base = str_col_a.lower()
    b_base = str_col_b.lower()
    spec_key = f"(self.get_{a_base}(i as int), self.get_{b_base}(i as int))"
    return f"""final(agg)@ == old(agg)@.insert(
        {spec_key},
        if old(agg)@.contains_key({spec_key}) {{
            (old(agg)@[{spec_key}] as int + {delta_name} as int) as {val_type}
        }} else {{
            {delta_name}
        }},
    )"""


def emit_cols_agg_push_str_verus(
    str_col_a: str,
    str_col_b: str,
    *,
    struct_name: str = "Cols",
    val_type: str = "u64",
) -> str:
    _ = struct_name
    name = agg_push_str_method_name(str_col_a, str_col_b)
    a_base = str_col_a.lower()
    b_base = str_col_b.lower()
    _, _, rust_map = agg_bridge_str_str(val_type)
    requires = _agg_push_str_str_requires(str_col_a, str_col_b, val_type=val_type)
    ensures = _agg_push_str_str_ensures(str_col_a, str_col_b, val_type=val_type)
    return f"""    #[verifier::external_body]
    pub exec fn {name}(
        &self,
        agg: &mut {rust_map},
        i: usize,
        delta: {val_type},
    )
        requires
            {requires},
        ensures
            {ensures},
    {{
        let key = (self.get_{a_base}_exec(i), self.get_{b_base}_exec(i));
        let prev = agg.get(&key).copied().unwrap_or(0{val_type});
        let next = prev.checked_add(delta).expect("Trusted overflow: requires violated");
        agg.insert(key, next);
    }}"""
