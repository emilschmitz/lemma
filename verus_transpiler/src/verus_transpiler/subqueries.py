"""Subquery MethodSpec helper emission."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .col_exprs import (
    native_u64_term,
    spec_i64_term,
    spec_u64_term,
    spec_where_cond,
    to_col_expr,
)
from .parse_sql import (
    ExistsSubquery,
    InSubquerySpec,
    ScalarSubquery,
    SQLQuery,
    UnsupportedContractError,
    _agg_value_type,
)
from .rust_ident import rust_ident
from .value_bounds import col_verus_type, spec_map_key_type


@dataclass
class SubqueryEmit:
    name: str
    helper_source: str
    spec_call: str
    inner_table: str = ""
    correlated: bool = False
    correlation_cols: list[str] = field(default_factory=list)


def _outer_param_name(col: str) -> str:
    return f"outer_{rust_ident(col)}"


def _lookup_col_type(
    col: str,
    inner_schema: dict[str, str],
    outer_schema: dict[str, str] | None = None,
) -> str:
    col_l = col.lower()
    if outer_schema:
        for k, v in outer_schema.items():
            if k.lower() == col_l:
                return v
    for k, v in inner_schema.items():
        if k.lower() == col_l:
            return v
    return "int"


def _rewrite_outer_refs_in_where(
    where_at_k: str,
    correlation_cols: list[str],
    inner_schema: dict[str, str],
    outer_schema: dict[str, str] | None = None,
) -> str:
    out = where_at_k
    for col in correlation_cols:
        pname = _outer_param_name(col)
        typ = _lookup_col_type(col, inner_schema, outer_schema)
        replacement = f"{pname}@" if col_verus_type(typ) == "String" else pname
        out = re.sub(rf"\bouter\.{re.escape(col)}\b", replacement, out, flags=re.IGNORECASE)
    return out


def _corr_key_spec_type(
    col: str,
    inner_schema: dict[str, str],
    outer_schema: dict[str, str] | None = None,
) -> str:
    """Spec type for a correlated outer key (String cols → Seq<char>)."""
    return spec_map_key_type(_lookup_col_type(col, inner_schema, outer_schema))


def _corr_outer_key_type(
    correlation_cols: list[str],
    inner_schema: dict[str, str],
    outer_schema: dict[str, str] | None = None,
) -> str:
    """Spec type for correlated outer key(s); tuple when multiple cols."""
    types = [
        _corr_key_spec_type(c, inner_schema, outer_schema) for c in correlation_cols
    ]
    if not types:
        return "u32"
    if len(types) == 1:
        return types[0]
    return f"({', '.join(types)})"


def _correlated_param_specs(
    correlation_cols: list[str],
    inner_schema: dict[str, str],
    outer_schema: dict[str, str] | None = None,
) -> list[tuple[str, str]]:
    specs: list[tuple[str, str]] = []
    for col in correlation_cols:
        typ = _lookup_col_type(col, inner_schema, outer_schema)
        vt = col_verus_type(typ)
        specs.append((_outer_param_name(col), vt))
    return specs


def _emit_recursive_helper(
    func_name: str,
    *,
    where_at_k: str | None,
    term_at_k: str,
    ret_type: str = "u64",
    struct_name: str = "Cols",
    param_name: str = "cols",
    valid_fn: str = "valid_cols",
    combine: str = "add",
    extra_params: list[tuple[str, str]] | None = None,
) -> str:
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

    extra_sig = ""
    extra_call = ""
    if extra_params:
        extra_sig = ", " + ", ".join(f"{n}: {t}" for n, t in extra_params)
        extra_call = ", " + ", ".join(n for n, _ in extra_params)

    if where_at_k:
        body = f"""if k < {param_name}.n {{
        let tail = {func_name}({param_name}{extra_call}, k + 1);
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
            body = f"""if k < {param_name}.n {{
        let tail = {func_name}({param_name}{extra_call}, k + 1);
        {combine_body}
    }} else {{
        {base}
    }}"""
        else:
            body = f"""if k < {param_name}.n {{
        ({func_name}({param_name}{extra_call}, k + 1) as int + {term_at_k} as int) as u64
    }} else {{
        {zero}
    }}"""
    return f"""pub open spec fn {func_name}({param_name}: &{struct_name}{extra_sig}, k: int) -> (res: {ret_type})
    recommends {valid_fn}({param_name}),
    decreases {param_name}.n - k,
{{
    {body}
}}"""


def _groupby_key_expr(
    groupby_columns: list[str],
    idx_var: str,
    schema_dict: dict[str, str],
) -> str:
    parts: list[str] = []
    for col in groupby_columns:
        field = rust_ident(col)
        if col_verus_type(schema_dict[col]) == "String":
            parts.append(f"cols.{field}[{idx_var} as int]@")
        else:
            parts.append(f"cols.{field}[{idx_var} as int]")
    if len(parts) == 1:
        return parts[0]
    return f"({', '.join(parts)})"


def _wrap_spec(
    spec_name: str,
    helper_name: str,
    *,
    struct_name: str = "Cols",
    param_name: str = "cols",
    valid_fn: str = "valid_cols",
    ret_type: str = "u64",
    body: str | None = None,
    extra_params: list[tuple[str, str]] | None = None,
) -> str:
    extra_sig = ""
    extra_call = ""
    if extra_params:
        extra_sig = ", " + ", ".join(f"{n}: {t}" for n, t in extra_params)
        extra_call = ", " + ", ".join(n for n, _ in extra_params)
    inner = body if body is not None else f"    {helper_name}({param_name}{extra_call}, 0)"
    return f"""pub open spec fn {spec_name}({param_name}: &{struct_name}{extra_sig}) -> {ret_type}
    recommends {valid_fn}({param_name}),
{{
{inner}
}}"""


def _agg_combine(agg_type: str) -> str:
    if agg_type == "MIN":
        return "min"
    if agg_type == "MAX":
        return "max"
    return "add"


def _emit_groupby_map_helper(
    prefix: str,
    inner: SQLQuery,
    schema: dict[str, str],
    *,
    struct_name: str = "Cols",
) -> tuple[str, str, str]:
    """Single-aggregate group-by fold -> Map<Key, Val>."""
    helper_name = f"{prefix}_helper"
    spec_name = f"{prefix}_spec"
    idx_var = "k"
    where_at_k = (
        spec_where_cond(to_col_expr(inner.where_expr, idx_var), idx_var, schema)
        if inner.where_expr
        else None
    )
    combine = _agg_combine(inner.agg_type)
    is_sum = inner.agg_type == "SUM"
    val_type = _agg_value_type(inner.agg_expr) if is_sum else "u64"
    if inner.agg_type in ("MIN", "MAX"):
        val_type = "u64"
    term_at_k = (
        spec_i64_term(inner.agg_expr, idx_var)
        if is_sum and val_type == "i64"
        else (
            spec_u64_term(inner.agg_expr, idx_var)
            if inner.agg_type in ("SUM", "MIN", "MAX")
            else "1"
        )
    )

    if len(inner.groupby_columns) == 1:
        c = inner.groupby_columns[0]
        map_key_ty = spec_map_key_type(schema[c])
    else:
        map_key_ty = f"({', '.join(spec_map_key_type(schema[c]) for c in inner.groupby_columns)})"
    map_ret = f"Map<{map_key_ty}, {val_type}>"
    key_expr = _groupby_key_expr(inner.groupby_columns, idx_var, schema)
    zero = f"0{val_type}"

    if where_at_k:
        body_inner = (
            f"let tail = {helper_name}(cols, {idx_var} + 1);\n"
            f"        if {where_at_k} {{\n"
            f"            let key = {key_expr};\n"
            f"            let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {zero} }};\n"
            f"            tail.insert(key, (prev as int + {term_at_k} as int) as {val_type})\n"
            f"        }} else {{\n"
            f"            tail\n"
            f"        }}"
        )
    elif combine == "max":
        body_inner = (
            f"let tail = {helper_name}(cols, {idx_var} + 1);\n"
            f"        let key = {key_expr};\n"
            f"        let prev = if tail.contains_key(key) {{ tail[key] }} else {{ 0u64 }};\n"
            f"        let t = {term_at_k};\n"
            f"        tail.insert(key, if t > prev {{ t }} else {{ prev }})"
        )
    elif combine == "min":
        body_inner = (
            f"let tail = {helper_name}(cols, {idx_var} + 1);\n"
            f"        let key = {key_expr};\n"
            f"        let prev = if tail.contains_key(key) {{ tail[key] }} else {{ u64::MAX }};\n"
            f"        let t = {term_at_k};\n"
            f"        tail.insert(key, if t < prev {{ t }} else {{ prev }})"
        )
    else:
        body_inner = (
            f"let tail = {helper_name}(cols, {idx_var} + 1);\n"
            f"        let key = {key_expr};\n"
            f"        let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {zero} }};\n"
            f"        tail.insert(key, (prev as int + {term_at_k} as int) as {val_type})"
        )

    helper = f"""pub open spec fn {helper_name}(cols: &{struct_name}, {idx_var}: int) -> {map_ret}
    recommends
        0 <= {idx_var} && {idx_var} <= cols.n,
        valid_cols(cols),
    decreases cols.n - {idx_var},
{{
    if {idx_var} < cols.n {{
        {body_inner}
    }} else {{
        Map::empty()
    }}
}}"""
    spec = _wrap_spec(spec_name, helper_name, struct_name=struct_name, ret_type=map_ret)
    return helper + "\n\n" + spec, f"{spec_name}(cols)", map_ret


def emit_scalar_subquery_helper(
    sub: ScalarSubquery,
    inner_schema: dict[str, str],
    *,
    struct_name: str = "Cols",
    valid_fn: str = "valid_cols",
    param_name: str = "cols",
    outer_schema: dict[str, str] | None = None,
) -> SubqueryEmit:
    """Emit a nested helper for a scalar subquery used in WHERE or SELECT."""
    helper_name = f"subquery_{sub.alias}_helper"
    spec_name = f"subquery_{sub.alias}_spec"
    inner_table = sub.inner_table or (sub.query.tables[0] if sub.query.tables else "")
    corr_params = (
        _correlated_param_specs(sub.correlation_cols, inner_schema, outer_schema)
        if sub.correlated
        else []
    )
    spec_call = f"{spec_name}({param_name}"
    if sub.correlated:
        spec_call += ", " + ", ".join(
            f"outer.{c}" for c in sub.correlation_cols
        )
    spec_call += ")"

    if sub.query.derived_tables or sub.query.joins or sub.query.groupby_columns:
        extra_sig = ""
        if corr_params:
            extra_sig = ", " + ", ".join(f"{n}: {t}" for n, t in corr_params)
        helper = f"""// TRUSTED: nested scalar / HAVING subquery ({sub.alias}).
#[verifier::external_body]
pub open spec fn {spec_name}({param_name}: &{struct_name}{extra_sig}) -> u64 {{
    arbitrary()
}}"""
        return SubqueryEmit(
            name=spec_name,
            helper_source=helper,
            spec_call=spec_call,
            inner_table=inner_table,
            correlated=sub.correlated,
            correlation_cols=list(sub.correlation_cols),
        )

    where_at_k = None
    if sub.query.where_expr:
        where_row = to_col_expr(sub.query.where_expr, "k")
        if param_name != "cols":
            where_row = where_row.replace("cols.", f"{param_name}.")
        where_at_k = spec_where_cond(where_row, "k", inner_schema)
        if sub.correlated:
            where_at_k = _rewrite_outer_refs_in_where(
                where_at_k,
                sub.correlation_cols,
                inner_schema,
                outer_schema,
            )

    combine = _agg_combine(sub.query.agg_type)

    if sub.query.agg_type in ("SUM", "COUNT", "MIN", "MAX"):
        is_sum = sub.query.agg_type == "SUM"
        val_type = _agg_value_type(sub.query.agg_expr) if is_sum else "u64"
        if sub.query.agg_type == "MIN" or sub.query.agg_type == "MAX":
            val_type = "u64"
        term_at_k = (
            native_u64_term(sub.query.agg_expr, "k")
            if sub.query.agg_type in ("SUM", "MIN", "MAX")
            else "1"
        )
        if param_name != "cols":
            term_at_k = term_at_k.replace("cols.", f"{param_name}.")
        helper = _emit_recursive_helper(
            helper_name,
            where_at_k=where_at_k,
            term_at_k=term_at_k,
            ret_type=val_type,
            struct_name=struct_name,
            param_name=param_name,
            valid_fn=valid_fn,
            combine=combine,
            extra_params=corr_params or None,
        )
        extra_call = ", " + ", ".join(n for n, _ in corr_params) if corr_params else ""
        spec = _wrap_spec(
            spec_name,
            helper_name,
            struct_name=struct_name,
            param_name=param_name,
            valid_fn=valid_fn,
            ret_type=val_type,
            extra_params=corr_params or None,
            body=f"    {helper_name}({param_name}{extra_call}, 0)",
        )
    elif sub.query.agg_type == "AVG":
        sum_helper = f"{helper_name}_sum"
        count_helper = f"{helper_name}_count"
        sum_term = native_u64_term(sub.query.agg_expr, "k")
        extra_call = ", " + ", ".join(n for n, _ in corr_params) if corr_params else ""
        helper = "\n\n".join([
            _emit_recursive_helper(
                sum_helper,
                where_at_k=where_at_k,
                term_at_k=sum_term,
                struct_name=struct_name,
                param_name=param_name,
                valid_fn=valid_fn,
                extra_params=corr_params or None,
            ),
            _emit_recursive_helper(
                count_helper,
                where_at_k=where_at_k,
                term_at_k="1",
                struct_name=struct_name,
                param_name=param_name,
                valid_fn=valid_fn,
                extra_params=corr_params or None,
            ),
        ])
        spec = _wrap_spec(
            spec_name,
            sum_helper,
            struct_name=struct_name,
            param_name=param_name,
            valid_fn=valid_fn,
            extra_params=corr_params or None,
            body=(
                f"    let s = {sum_helper}({param_name}{extra_call}, 0);\n"
                f"    let c = {count_helper}({param_name}{extra_call}, 0);\n"
                f"    if c == 0 {{ 0 }} else {{ s / c }}"
            ),
        )
    else:
        raise ValueError(f"unsupported subquery agg: {sub.query.agg_type}")

    return SubqueryEmit(
        name=spec_name,
        helper_source=helper + "\n\n" + spec,
        spec_call=spec_call,
        inner_table=inner_table,
        correlated=sub.correlated,
        correlation_cols=list(sub.correlation_cols),
    )


def emit_exists_subquery_helper(
    exists: ExistsSubquery,
    inner_schema: dict[str, str],
    *,
    struct_name: str = "Cols",
    valid_fn: str = "valid_cols",
    param_name: str = "cols",
    outer_schema: dict[str, str] | None = None,
) -> str:
    """Emit EXISTS (or NOT EXISTS) semi-join spec helper."""
    if exists.correlated:
        return emit_exists_corr_subquery_helper(
            exists,
            inner_schema,
            struct_name=struct_name,
            valid_fn=valid_fn,
            param_name=param_name,
            outer_schema=outer_schema,
        )
    helper_name = f"exists_{exists.alias}_helper"
    spec_name = f"exists_{exists.alias}_spec"
    _ = inner_schema, exists.query.where_expr
    helper = f"""#[verifier::external_body]
pub open spec fn {helper_name}({param_name}: &{struct_name}, k: int) -> bool {{
    arbitrary()
}}"""
    spec = f"""pub open spec fn {spec_name}({param_name}: &{struct_name}) -> bool
    recommends {valid_fn}({param_name}),
{{
    {helper_name}({param_name}, 0)
}}"""
    return helper + "\n\n" + spec


def emit_exists_corr_subquery_helper(
    exists: ExistsSubquery,
    inner_schema: dict[str, str],
    *,
    struct_name: str = "Cols",
    valid_fn: str = "valid_cols",
    param_name: str = "cols",
    outer_schema: dict[str, str] | None = None,
) -> str:
    """Emit correlated EXISTS spec helper (TRUSTED nested-loop reference)."""
    key_ty = _corr_outer_key_type(
        exists.correlation_cols, inner_schema, outer_schema
    )
    spec_name = f"exists_corr_{exists.alias}_spec"
    helper_name = f"exists_corr_{exists.alias}_helper"
    helper = f"""// TRUSTED: correlated EXISTS nested-loop semi-join reference.
#[verifier::external_body]
pub open spec fn {helper_name}({param_name}: &{struct_name}, outer_key: {key_ty}, k: int) -> bool {{
    arbitrary()
}}"""
    spec = f"""pub open spec fn {spec_name}({param_name}: &{struct_name}, outer_key: {key_ty}) -> bool
    recommends {valid_fn}({param_name}),
{{
    {helper_name}({param_name}, outer_key, 0)
}}"""
    return helper + "\n\n" + spec


def emit_in_subquery_helper(
    in_spec: InSubquerySpec,
    inner_schema: dict[str, str],
    *,
    struct_name: str = "Cols",
    valid_fn: str = "valid_cols",
    param_name: str = "cols",
    outer_schema: dict[str, str] | None = None,
) -> str:
    """Emit IN (subquery) membership helper."""
    if in_spec.correlated:
        return emit_in_corr_subquery_helper(
            in_spec,
            inner_schema,
            struct_name=struct_name,
            valid_fn=valid_fn,
            param_name=param_name,
            outer_schema=outer_schema,
        )
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
pub open spec fn {set_name}({param_name}: &{struct_name}) -> Set<u32> {{
    arbitrary()
}}"""
    if where_at_k:
        contains = f"""#[verifier::external_body]
pub open spec fn {contains_name}({param_name}: &{struct_name}, val: u32) -> bool {{
    {set_name}({param_name}).contains(val)
}}"""
    else:
        contains = f"""#[verifier::external_body]
pub open spec fn {contains_name}({param_name}: &{struct_name}, val: u32) -> bool {{
    {set_name}({param_name}).contains(val)
}}"""
    _ = col_field, inner_col, where_at_k
    return set_helper + "\n\n" + contains


def emit_in_corr_subquery_helper(
    in_spec: InSubquerySpec,
    inner_schema: dict[str, str],
    *,
    struct_name: str = "Cols",
    valid_fn: str = "valid_cols",
    param_name: str = "cols",
    outer_schema: dict[str, str] | None = None,
) -> str:
    """Emit correlated IN (subquery) membership helper (TRUSTED)."""
    key_ty = _corr_outer_key_type(
        in_spec.correlation_cols, inner_schema, outer_schema,
    )
    val_ty = _corr_key_spec_type(in_spec.column, inner_schema, outer_schema)
    contains_name = f"in_corr_{in_spec.alias}_contains"
    helper_name = f"in_corr_{in_spec.alias}_helper"
    helper = f"""// TRUSTED: correlated IN nested-loop membership reference.
#[verifier::external_body]
pub open spec fn {helper_name}({param_name}: &{struct_name}, outer_key: {key_ty}, k: int) -> Set<{val_ty}> {{
    arbitrary()
}}"""
    contains = f"""pub open spec fn {contains_name}({param_name}: &{struct_name}, val: {val_ty}, outer_key: {key_ty}) -> bool
    recommends {valid_fn}({param_name}),
{{
    {helper_name}({param_name}, outer_key, 0).contains(val)
}}"""
    return helper + "\n\n" + contains


def emit_derived_grouped_inner_spec(
    derived_alias: str,
    inner: SQLQuery,
    schema: dict[str, str],
    *,
    struct_name: str = "Cols",
) -> tuple[str, str, str]:
    """Emit grouped derived-table inner spec. Returns (helpers, spec_call, ret_type)."""
    prefix = f"derived_{derived_alias}"
    if inner.is_multi_agg and inner.groupby_columns:
        raise UnsupportedContractError(
            "multi-agg grouped derived table in FROM needs dedicated emitter"
        )
    if not inner.groupby_columns or not inner.agg_type:
        raise UnsupportedContractError(
            "grouped derived table requires GROUP BY with aggregate"
        )
    helpers, spec_call, ret_type = _emit_groupby_map_helper(
        prefix, inner, schema, struct_name=struct_name,
    )
    return helpers, spec_call, ret_type


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
