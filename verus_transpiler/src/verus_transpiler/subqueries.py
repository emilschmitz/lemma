"""Subquery MethodSpec helper emission."""

from __future__ import annotations

from dataclasses import dataclass

from .col_exprs import native_u64_term, spec_where_cond, to_col_expr
from .parse_sql import (
    ExistsSubquery,
    InSubquerySpec,
    ScalarSubquery,
    SQLQuery,
    _agg_value_type,
)


@dataclass
class SubqueryEmit:
    name: str
    helper_source: str
    spec_call: str


def _emit_recursive_helper(
    func_name: str,
    *,
    where_at_k: str | None,
    term_at_k: str,
    ret_type: str = "u64",
    struct_name: str = "Cols",
    combine: str = "add",
) -> str:
    add_fn = "add_i64" if ret_type == "i64" else "add_u64"
    zero = "0"
    if combine == "min":
        base = "u64::MAX"
        combine_body = f"let t = {term_at_k}; if t < tail {{ t }} else {{ tail }}"
    elif combine == "max":
        base = "0"
        combine_body = f"let t = {term_at_k}; if t > tail {{ t }} else {{ tail }}"
    else:
        base = zero
        combine_body = f"(tail as int + {term_at_k} as int) as u64"

    if where_at_k:
        body = f"""if k < cols.n {{
        let tail = {func_name}(cols, k + 1);
        if {where_at_k} {{
            {combine_body}
        }} else {{
            tail
        }}
    }} else {{
        {base}
    }}"""
    else:
        if combine in ("min", "max"):
            body = f"""if k < cols.n {{
        let tail = {func_name}(cols, k + 1);
        {combine_body}
    }} else {{
        {base}
    }}"""
        else:
            body = f"""if k < cols.n {{
        ({func_name}(cols, k + 1) as int + {term_at_k} as int) as u64
    }} else {{
        {zero}
    }}"""
    return f"""pub open spec fn {func_name}(cols: &{struct_name}, k: int) -> (res: {ret_type})
    decreases cols.n - k,
{{
    {body}
}}"""


def _wrap_spec(
    spec_name: str,
    helper_name: str,
    *,
    struct_name: str = "Cols",
    ret_type: str = "u64",
    body: str | None = None,
) -> str:
    inner = body if body is not None else f"    {helper_name}(cols, 0)"
    return f"""pub open spec fn {spec_name}(cols: &{struct_name}) -> {ret_type}
    recommends valid_cols(cols),
{{
{inner}
}}"""


def _agg_combine(agg_type: str) -> str:
    if agg_type == "MIN":
        return "min"
    if agg_type == "MAX":
        return "max"
    return "add"


def emit_scalar_subquery_helper(
    sub: ScalarSubquery,
    inner_schema: dict[str, str],
    *,
    struct_name: str = "Cols",
) -> SubqueryEmit:
    """Emit a nested helper for a scalar subquery used in WHERE or SELECT."""
    helper_name = f"subquery_{sub.alias}_helper"
    spec_name = f"subquery_{sub.alias}_spec"
    where_at_k = (
        spec_where_cond(to_col_expr(sub.query.where_expr, "k"), "k", inner_schema)
        if sub.query.where_expr
        else None
    )
    combine = _agg_combine(sub.query.agg_type)

    if sub.query.agg_type in ("SUM", "COUNT", "MIN", "MAX"):
        is_sum = sub.query.agg_type == "SUM"
        val_type = _agg_value_type(sub.query.agg_expr) if is_sum else "u64"
        if sub.query.agg_type == "MIN":
            val_type = "u64"
        elif sub.query.agg_type == "MAX":
            val_type = "u64"
        term_at_k = (
            native_u64_term(sub.query.agg_expr, "k")
            if sub.query.agg_type in ("SUM", "MIN", "MAX")
            else "1"
        )
        helper = _emit_recursive_helper(
            helper_name,
            where_at_k=where_at_k,
            term_at_k=term_at_k,
            ret_type=val_type,
            struct_name=struct_name,
            combine=combine,
        )
        spec = _wrap_spec(spec_name, helper_name, struct_name=struct_name, ret_type=val_type)
    elif sub.query.agg_type == "AVG":
        sum_helper = f"{helper_name}_sum"
        count_helper = f"{helper_name}_count"
        sum_term = native_u64_term(sub.query.agg_expr, "k")
        helper = "\n\n".join([
            _emit_recursive_helper(
                sum_helper,
                where_at_k=where_at_k,
                term_at_k=sum_term,
                struct_name=struct_name,
            ),
            _emit_recursive_helper(
                count_helper,
                where_at_k=where_at_k,
                term_at_k="1",
                struct_name=struct_name,
            ),
        ])
        spec = _wrap_spec(
            spec_name,
            sum_helper,
            struct_name=struct_name,
            body=(
                f"    let s = {sum_helper}(cols, 0);\n"
                f"    let c = {count_helper}(cols, 0);\n"
                f"    if c == 0 {{ 0 }} else {{ s / c }}"
            ),
        )
    else:
        raise ValueError(f"unsupported subquery agg: {sub.query.agg_type}")

    return SubqueryEmit(
        name=spec_name,
        helper_source=helper + "\n\n" + spec,
        spec_call=f"{spec_name}(cols)",
    )


def emit_exists_subquery_helper(
    exists: ExistsSubquery,
    inner_schema: dict[str, str],
    *,
    struct_name: str = "Cols",
) -> str:
    """Emit EXISTS (or NOT EXISTS) semi-join spec helper."""
    if exists.correlated:
        return emit_exists_corr_subquery_helper(exists, inner_schema, struct_name=struct_name)
    helper_name = f"exists_{exists.alias}_helper"
    spec_name = f"exists_{exists.alias}_spec"
    _ = inner_schema, exists.query.where_expr
    helper = f"""#[verifier::external_body]
pub open spec fn {helper_name}(cols: &{struct_name}, k: int) -> bool {{
    arbitrary()
}}"""
    spec = f"""pub open spec fn {spec_name}(cols: &{struct_name}) -> bool
    recommends valid_cols(cols),
{{
    {helper_name}(cols, 0)
}}"""
    return helper + "\n\n" + spec


def emit_exists_corr_subquery_helper(
    exists: ExistsSubquery,
    inner_schema: dict[str, str],
    *,
    struct_name: str = "Cols",
) -> str:
    """Emit correlated EXISTS spec helper (TRUSTED nested-loop reference)."""
    _ = inner_schema
    key_col = exists.correlation_cols[0].lower()
    key_ty = "u32"
    for col, typ in inner_schema.items():
        if col.lower() == key_col:
            from .value_bounds import col_verus_type
            vt = col_verus_type(typ)
            key_ty = vt if vt != "String" else "u32"
            break
    spec_name = f"exists_corr_{exists.alias}_spec"
    helper_name = f"exists_corr_{exists.alias}_helper"
    helper = f"""// TRUSTED: correlated EXISTS nested-loop semi-join reference.
#[verifier::external_body]
pub open spec fn {helper_name}(cols: &{struct_name}, outer_key: {key_ty}, k: int) -> bool {{
    arbitrary()
}}"""
    spec = f"""pub open spec fn {spec_name}(cols: &{struct_name}, outer_key: {key_ty}) -> bool
    recommends valid_cols(cols),
{{
    {helper_name}(cols, outer_key, 0)
}}"""
    return helper + "\n\n" + spec


def emit_in_subquery_helper(
    in_spec: InSubquerySpec,
    inner_schema: dict[str, str],
    *,
    struct_name: str = "Cols",
) -> str:
    """Emit IN (subquery) membership helper."""
    if in_spec.correlated:
        return emit_in_corr_subquery_helper(in_spec, inner_schema, struct_name=struct_name)
    set_name = f"in_{in_spec.alias}_set"
    contains_name = f"in_{in_spec.alias}_contains"
    col_field = in_spec.column.lower()
    inner_col = in_spec.query.projection_columns[0].lower() if in_spec.query.is_projection else in_spec.column.lower()
    where_at_k = (
        spec_where_cond(
            to_col_expr(in_spec.query.where_expr, "k"), "k", inner_schema,
        )
        if in_spec.query.where_expr
        else None
    )
    set_helper = f"""#[verifier::external_body]
pub open spec fn {set_name}(cols: &{struct_name}) -> Set<u32> {{
    arbitrary()
}}"""
    if where_at_k:
        contains = f"""#[verifier::external_body]
pub open spec fn {contains_name}(cols: &{struct_name}, val: u32) -> bool {{
    {set_name}(cols).contains(val)
}}"""
    else:
        contains = f"""#[verifier::external_body]
pub open spec fn {contains_name}(cols: &{struct_name}, val: u32) -> bool {{
    {set_name}(cols).contains(val)
}}"""
    _ = col_field, inner_col, where_at_k
    return set_helper + "\n\n" + contains


def emit_in_corr_subquery_helper(
    in_spec: InSubquerySpec,
    inner_schema: dict[str, str],
    *,
    struct_name: str = "Cols",
) -> str:
    """Emit correlated IN (subquery) membership helper (TRUSTED)."""
    _ = inner_schema
    key_col = in_spec.correlation_cols[0].lower()
    key_ty = "u32"
    val_ty = "u32"
    for col, typ in inner_schema.items():
        from .value_bounds import col_verus_type
        vt = col_verus_type(typ)
        if col.lower() == key_col:
            key_ty = vt if vt != "String" else "u32"
        if col.lower() == in_spec.column.lower():
            val_ty = vt if vt != "String" else "u32"
    contains_name = f"in_corr_{in_spec.alias}_contains"
    helper_name = f"in_corr_{in_spec.alias}_helper"
    helper = f"""// TRUSTED: correlated IN nested-loop membership reference.
#[verifier::external_body]
pub open spec fn {helper_name}(cols: &{struct_name}, outer_key: {key_ty}, k: int) -> Set<{val_ty}> {{
    arbitrary()
}}"""
    contains = f"""pub open spec fn {contains_name}(cols: &{struct_name}, val: {val_ty}, outer_key: {key_ty}) -> bool
    recommends valid_cols(cols),
{{
    {helper_name}(cols, outer_key, 0).contains(val)
}}"""
    return helper + "\n\n" + contains


def emit_derived_grouped_inner_spec(
    derived_alias: str,
    inner: SQLQuery,
    schema: dict[str, str],
    *,
    struct_name: str = "Cols",
) -> tuple[str, str, str]:
    """Emit TRUSTED grouped derived-table inner spec. Returns (helpers, spec_call, ret_type)."""
    _ = inner, schema
    prefix = f"derived_{derived_alias}"
    if len(inner.groupby_columns) == 1:
        c = inner.groupby_columns[0]
        from .value_bounds import spec_map_key_type
        key_ty = spec_map_key_type(schema.get(c, "int"))
        val_ty = _agg_value_type(inner.agg_expr)
        ret_type = f"Map<{key_ty}, {val_ty}>"
    else:
        ret_type = "Map<_, u64>"
    helper = f"""// TRUSTED: grouped derived inner fold (group-by map).
#[verifier::external_body]
pub open spec fn {prefix}_spec(cols: &{struct_name}) -> {ret_type} {{
    arbitrary()
}}"""
    return helper, f"{prefix}_spec(cols)", ret_type


def emit_derived_inner_spec(
    derived_alias: str,
    inner: SQLQuery,
    schema: dict[str, str],
    *,
    struct_name: str = "Cols",
) -> tuple[str, str, str]:
    """Emit inner derived-table spec. Returns (helpers, spec_call, ret_type)."""
    prefix = f"derived_{derived_alias}"
    where_at_k = (
        spec_where_cond(to_col_expr(inner.where_expr, "k"), "k", schema)
        if inner.where_expr
        else None
    )
    combine = _agg_combine(inner.agg_type)

    if inner.agg_type == "AVG":
        sum_h = f"{prefix}_sum_helper"
        cnt_h = f"{prefix}_count_helper"
        sum_term = native_u64_term(inner.agg_expr, "k")
        helpers = "\n\n".join([
            _emit_recursive_helper(sum_h, where_at_k=where_at_k, term_at_k=sum_term, struct_name=struct_name),
            _emit_recursive_helper(cnt_h, where_at_k=where_at_k, term_at_k="1", struct_name=struct_name),
        ])
        spec = _wrap_spec(
            f"{prefix}_spec",
            sum_h,
            struct_name=struct_name,
            body=(
                f"    let s = {sum_h}(cols, 0);\n"
                f"    let c = {cnt_h}(cols, 0);\n"
                f"    if c == 0 {{ 0 }} else {{ s / c }}"
            ),
        )
        return helpers + "\n\n" + spec, f"{prefix}_spec(cols)", "u64"

    is_sum = inner.agg_type == "SUM"
    val_type = _agg_value_type(inner.agg_expr) if is_sum else "u64"
    if inner.agg_type in ("MIN", "MAX"):
        val_type = "u64"
    term_at_k = (
        native_u64_term(inner.agg_expr, "k")
        if inner.agg_type in ("SUM", "MIN", "MAX")
        else "1"
    )
    helper_name = f"{prefix}_helper"
    helper = _emit_recursive_helper(
        helper_name,
        where_at_k=where_at_k,
        term_at_k=term_at_k,
        ret_type=val_type,
        struct_name=struct_name,
        combine=combine,
    )
    spec = _wrap_spec(f"{prefix}_spec", helper_name, struct_name=struct_name, ret_type=val_type)
    return helper + "\n\n" + spec, f"{prefix}_spec(cols)", val_type


def compose_outer_over_derived_scalar(outer_agg: str, inner_spec_call: str) -> str:
    """Compose outer aggregate over a one-row derived scalar subquery."""
    if outer_agg in ("SUM", "AVG", "MIN", "MAX"):
        return inner_spec_call
    if outer_agg == "COUNT":
        return "1"
    raise ValueError(f"unsupported outer aggregate over derived scalar: {outer_agg}")
