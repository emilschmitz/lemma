"""Schema-driven Cols row-push helpers for 2-key (u32, string) group-bys.

Thin wrappers around structural ``agg_add_u32_str__*`` (vstd ``HashMapWithView``).
"""

from __future__ import annotations

from .value_bounds import col_verus_type


def agg_push_method_name(u32_col: str, str_col: str) -> str:
    return f"agg_push_{u32_col.lower()}_{str_col.lower()}"


def agg_bridge_u32_str(val_type: str) -> tuple[str, str, str]:
    """Return ``(agg_new_fn, agg_add_fn, rust_map_type)`` for u32+string keys."""
    if val_type not in ("u64", "i64"):
        raise ValueError(f"unsupported agg value type for u32+str group-by: {val_type!r}")
    suffix = f"u32_str__{val_type}"
    rust_map = f"HashMapWithView<(u32, String), {val_type}>"
    return f"agg_new_{suffix}", f"agg_add_{suffix}", rust_map


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


def _u64_prev_fit_requires(prev_expr: str, delta_expr: str) -> str:
    return (
        f"({prev_expr} as int) + ({delta_expr} as int) <= u64::MAX as int"
    )


def _i64_prev_fit_requires(prev_expr: str, delta_expr: str) -> str:
    return f"""({prev_expr} as int) + ({delta_expr} as int) >= i64::MIN as int,
        ({prev_expr} as int) + ({delta_expr} as int) <= i64::MAX as int"""


def _agg_push_u32_str_requires(
    u32_col: str,
    str_col: str,
    *,
    val_type: str,
    delta_name: str = "delta",
) -> str:
    u32_base = u32_col.lower()
    str_base = str_col.lower()
    spec_key = f"(self.get_{u32_base}(i as int), self.get_{str_base}(i as int))"
    prev_expr = (
        f"if old(agg)@.contains_key({spec_key}) {{ old(agg)@[{spec_key}] }} "
        f"else {{ 0{val_type} }}"
    )
    clauses = ["i < self.n", f"{delta_name} < LEMMA_MAX_CELL_U64"] if val_type == "u64" else ["i < self.n"]
    if val_type == "u64":
        clauses.append(_u64_prev_fit_requires(prev_expr, f"({delta_name} as int)"))
    else:
        clauses.append(_i64_prev_fit_requires(prev_expr, f"({delta_name} as int)"))
    return " &&\n        ".join(clauses)


def _agg_push_u32_str_ensures(
    u32_col: str,
    str_col: str,
    *,
    val_type: str,
    delta_name: str = "delta",
) -> str:
    u32_base = u32_col.lower()
    str_base = str_col.lower()
    spec_key = f"(self.get_{u32_base}(i as int), self.get_{str_base}(i as int))"
    return f"""final(agg)@ == old(agg)@.insert(
        {spec_key},
        if old(agg)@.contains_key({spec_key}) {{
            (old(agg)@[{spec_key}] as int + {delta_name} as int) as {val_type}
        }} else {{
            {delta_name}
        }},
    )"""


def emit_cols_agg_push_verus(
    u32_col: str,
    str_col: str,
    *,
    struct_name: str = "Cols",
    val_type: str = "u64",
) -> str:
    _ = struct_name
    name = agg_push_method_name(u32_col, str_col)
    u32_base = u32_col.lower()
    str_base = str_col.lower()
    _, _, rust_map = agg_bridge_u32_str(val_type)
    requires = _agg_push_u32_str_requires(u32_col, str_col, val_type=val_type)
    ensures = _agg_push_u32_str_ensures(u32_col, str_col, val_type=val_type)
    # Self-contained body: join queries may emit Cols.agg_push without the
    # matching ret-type agg_add_* bridge (e.g. group key order differs from ret).
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
        let key = (self.get_{u32_base}_exec(i), self.get_{str_base}_exec(i));
        let prev = agg.get(&key).copied().unwrap_or(0{val_type});
        let next = prev.checked_add(delta).expect("Trusted overflow: requires violated");
        agg.insert(key, next);
    }}"""
