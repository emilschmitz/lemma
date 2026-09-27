"""Main SQL → Verus Rust spec emitter."""

from __future__ import annotations

import re

from research_loop.table_assumptions import (
    CatalogAssumptions,
    ResolvedBounds,
    engine_default_catalog_assumptions,
    resolve_bounds,
    table_assumptions_for,
    with_catalog_assumptions,
)

from .agg_push import emit_cols_agg_push_verus, resolve_two_key_u32_str_groupby
from .agg_push_str import emit_cols_agg_push_str_verus, resolve_two_key_str_str_groupby
from .col_exprs import (
    native_u64_term,
    spec_i64_term,
    spec_u64_term,
    spec_where_cond,
    to_col_expr,
)
from .eq_join_prelude import proved_eq_join_prelude
from .joins import (
    _table_struct_name,
    emit_join_spec_helpers,
    try_decorrelate_anti_subqueries,
)
from .parse_sql import (
    AggSpec,
    DerivedTable,
    SQLQuery,
    UnsupportedContractError,
    _agg_value_type,
    _outer_base_table,
    grouped_derived_scalar_inner_tables,
    inner_base_tables,
    is_grouped_derived_scalar_subquery,
    normalize_schema,
    parse_sql,
    support_spec_params,
)
from .recursive_cte import emit_recursive_cte_helper
from .rust_ident import rust_ident
from .subqueries import (
    compose_outer_over_derived_scalar,
    emit_derived_grouped_inner_spec,
    emit_derived_inner_spec,
    emit_exists_subquery_helper,
    emit_in_subquery_helper,
    emit_scalar_subquery_helper,
)
from .templates import emit_run_query_skeleton, emit_run_query_template
from .value_bounds import (
    SUPPORTED_SCHEMA_TYPES,
    col_spec_accessor_return,
    col_verus_type,
    emit_bound_constants,
    emit_bound_lemmas,
    emit_trusted_prelude,
    emit_valid_cols_accessor_lemmas,
    emit_valid_cols_predicate,
    row_cap_const_for_join_depth,
    spec_map_key_type,
)
from .windows import emit_window_spec_helper

_SUPPORTED_TYPES = SUPPORTED_SCHEMA_TYPES


def _outer_cols_schema(
    query: SQLQuery,
    flat_schema: dict[str, str],
    multi_schema: dict[str, dict[str, str]] | None,
) -> dict[str, str]:
    """Columns for the outer ``Cols`` struct — not inner-only EXISTS/IN columns."""
    if not multi_schema:
        return flat_schema
    derived = {d.alias for d in query.derived_tables}
    base = [t for t in query.tables if t not in derived]
    outer = base[0] if base else (query.tables[0] if query.tables else None)
    if outer and outer in multi_schema:
        return multi_schema[outer]
    return flat_schema


def _flat_outer_schema(
    flat_schema: dict[str, str],
    multi_schema: dict[str, dict[str, str]] | None,
) -> dict[str, str]:
    if not multi_schema:
        return flat_schema
    merged: dict[str, str] = {}
    for cols in multi_schema.values():
        merged.update(cols)
    return merged


def _subquery_emit_binding(
    inner_table: str,
    flat_schema: dict[str, str],
    multi_schema: dict[str, dict[str, str]] | None,
    *,
    outer_table: str | None = None,
    is_join: bool = False,
) -> tuple[str, str, str, dict[str, str]]:
    """Bind inner helper to ``Cols`` only on a single-table outer program.

    Join programs have ``Cols_<table>`` per base table and no unified ``Cols``.
    Same-table IN/EXISTS on a single-table outer still shares ``cols: &Cols``.
    """
    use_table_struct = bool(
        multi_schema
        and inner_table in multi_schema
        and (is_join or inner_table != outer_table)
    )
    if use_table_struct:
        return (
            _table_struct_name(inner_table),
            f"valid_cols_{inner_table}",
            inner_table,
            multi_schema[inner_table],
        )
    schema = (
        multi_schema[inner_table]
        if multi_schema and inner_table in multi_schema
        else flat_schema
    )
    return "Cols", "valid_cols", "cols", schema


def _subquery_inner_table_name(query: SQLQuery) -> str:
    if not query.tables:
        raise UnsupportedContractError(
            "subquery inner query must have a single base table."
        )
    if query.derived_tables:
        if is_grouped_derived_scalar_subquery(query):
            return grouped_derived_scalar_inner_tables(query)[0]
        raise UnsupportedContractError(
            "subquery inner FROM derived/CTE is not supported on JOIN."
        )
    if query.joins:
        raise UnsupportedContractError(
            "subquery inner multi-table FROM is not supported on JOIN."
        )
    return query.tables[0]


def _assert_join_subquery_supported(query: SQLQuery) -> None:
    if query.is_projection and any(
        sub.alias.startswith("sel_sq") for sub in query.scalar_subqueries
    ):
        raise UnsupportedContractError(
            "scalar subquery in SELECT list on JOIN projection is not supported."
        )
    for sub in query.scalar_subqueries:
        if is_grouped_derived_scalar_subquery(sub.query):
            continue
        _subquery_inner_table_name(sub.query)
    for exists in query.exists_subqueries:
        if not exists.correlated and exists.query.joins:
            continue
        _subquery_inner_table_name(exists.query)
    for in_sub in query.in_subqueries:
        if not in_sub.correlated and in_sub.query.joins:
            continue
        _subquery_inner_table_name(in_sub.query)


def _merged_table_schema(
    tables: list[str],
    multi_schema: dict[str, dict[str, str]],
) -> dict[str, str]:
    merged: dict[str, str] = {}
    for table in tables:
        for col, typ in multi_schema[table].items():
            merged[col] = typ
    return merged


def _validate_schema(schema: dict[str, str] | dict[str, dict[str, str]]) -> None:
    flat, multi = normalize_schema(schema)
    for col_type in flat.values():
        if col_type.lower() not in _SUPPORTED_TYPES:
            raise UnsupportedContractError(f"Unsupported column type in schema: {col_type}")
    if multi:
        for cols in multi.values():
            for col_type in cols.values():
                if col_type.lower() not in _SUPPORTED_TYPES:
                    raise UnsupportedContractError(f"Unsupported column type in schema: {col_type}")


def generate_cols_rs(
    schema_dict: dict[str, str],
    *,
    sql_str: str | None = None,
    groupby_columns: list[str] | None = None,
    struct_name: str = "Cols",
    val_type: str | None = None,
) -> str:
    """Emit columnar Cols struct + getters for the given schema."""
    parsed_query = parse_sql(sql_str, schema_dict) if sql_str is not None else None
    if groupby_columns is None and parsed_query is not None:
        groupby_columns = parsed_query.groupby_columns
    if val_type is None and parsed_query is not None and parsed_query.agg_expr:
        val_type = _agg_value_type(parsed_query.agg_expr)
    if val_type is None:
        val_type = "u64"
    agg_push = resolve_two_key_u32_str_groupby(groupby_columns, schema_dict)
    agg_push_str = resolve_two_key_str_str_groupby(groupby_columns, schema_dict)

    field_lines = ["    pub n: usize,"]
    for col, col_type in schema_dict.items():
        rust_ty = col_verus_type(col_type)
        field_lines.append(f"    pub {rust_ident(col)}: Vec<{rust_ty}>,")

    getters: list[str] = []
    for col, col_type in schema_dict.items():
        base = col.lower()
        field = rust_ident(col)
        ret = col_spec_accessor_return(col_type)
        if ret == "Seq<char>":
            getters.append(f"""    pub open spec fn get_{base}(self, i: int) -> Seq<char> {{
        self.{field}[i as int]@
    }}

    #[verifier::external_body]
    pub exec fn get_{base}_exec(&self, i: usize) -> (res: String)
        requires i < self.n,
        ensures res@ == self.get_{base}(i as int),
    {{
        self.{field}[i].clone()
    }}

    #[verifier::external_body]
    pub exec fn eq_at_{base}(&self, i: usize, lit: &str) -> (res: bool)
        requires i < self.n,
        ensures res == (self.get_{base}(i as int) == lit@),
    {{
        self.{field}[i] == lit
    }}""")
        else:
            getters.append(f"""    pub open spec fn get_{base}(self, i: int) -> {ret} {{
        self.{field}[i as int]
    }}

    #[verifier::external_body]
    pub exec fn get_{base}_exec(&self, i: usize) -> (res: {ret})
        requires i < self.n,
        ensures res == self.get_{base}(i as int),
    {{
        self.{field}[i]
    }}""")

    agg_methods = ""
    if agg_push is not None:
        agg_methods += "\n" + emit_cols_agg_push_verus(
            *agg_push, struct_name=struct_name, val_type=val_type
        )
    if agg_push_str is not None:
        agg_methods += "\n" + emit_cols_agg_push_str_verus(
            *agg_push_str, struct_name=struct_name, val_type=val_type
        )

    return f"""pub struct {struct_name} {{
{chr(10).join(field_lines)}
}}

impl {struct_name} {{
{chr(10).join(getters)}{agg_methods}
}}
"""


def _groupby_key_expr(
    groupby_columns: list[str],
    idx_var: str,
    schema_dict: dict[str, str],
) -> str:
    """Spec key at row index (String cols → Seq<char> via @)."""
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


def _support_spec_params(query: SQLQuery) -> list[tuple[str, str, str]]:
    return support_spec_params(query)


def _extra_param_sig(extras: list[tuple[str, str, str]]) -> str:
    return "".join(f", {name}: &{struct}" for name, struct, _ in extras)


def _extra_param_call(extras: list[tuple[str, str, str]]) -> str:
    return "".join(f", {name}" for name, _, _ in extras)


def _extra_param_recommends(extras: list[tuple[str, str, str]]) -> str:
    return "".join(f",\n        {valid}({name})" for name, _, valid in extras)


def _method_spec_fn(ret_type: str, spec_body: str, extras: list[tuple[str, str, str]]) -> str:
    extra_sig = _extra_param_sig(extras)
    extra_rec = _extra_param_recommends(extras)
    return f"""pub open spec fn method_spec(cols: &Cols{extra_sig}) -> {ret_type}
    recommends valid_cols(cols){extra_rec},
{{
    {spec_body}
}}"""


def _build_col_helper(
    func_name: str,
    query: SQLQuery,
    idx_var: str,
    schema_dict: dict[str, str],
    *,
    is_sum: bool,
    agg_type: str | None = None,
    extras: list[tuple[str, str, str]] | None = None,
) -> str:
    extras = extras or []
    extra_sig = _extra_param_sig(extras)
    extra_call = _extra_param_call(extras)
    extra_rec = _extra_param_recommends(extras)
    rec = f"{func_name}(cols{extra_call}, {idx_var} + 1)"
    agg = agg_type or query.agg_type
    cond = (
        spec_where_cond(to_col_expr(query.where_expr, idx_var), idx_var, schema_dict)
        if query.where_expr
        else None
    )
    val_type = _agg_value_type(query.agg_expr)

    if query.groupby_columns:
        if len(query.groupby_columns) == 1:
            col = query.groupby_columns[0]
            key_rust = spec_map_key_type(schema_dict[col])
            ret_type = f"Map<{key_rust}, {val_type}>"
        else:
            key_types = ", ".join(
                spec_map_key_type(schema_dict[c]) for c in query.groupby_columns
            )
            ret_type = f"Map<({key_types}), {val_type}>"
        key_expr = _groupby_key_expr(query.groupby_columns, idx_var, schema_dict)
        if is_sum:
            if val_type == "i64":
                term = spec_i64_term(query.agg_expr, idx_var)
            else:
                term = spec_u64_term(query.agg_expr, idx_var)
        else:
            term = f"1{val_type}"
        zero = f"0{val_type}"
        if cond:
            body_inner = (
                f"let tail = {rec};\n"
                f"        if {cond} {{\n"
                f"            let key = {key_expr};\n"
                f"            let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {zero} }};\n"
                f"            tail.insert(key, (prev as int + {term} as int) as {val_type})\n"
                f"        }} else {{\n"
                f"            tail\n"
                f"        }}"
            )
        else:
            body_inner = (
                f"let tail = {rec};\n"
                f"        let key = {key_expr};\n"
                f"        let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {zero} }};\n"
                f"        tail.insert(key, (prev as int + {term} as int) as {val_type})"
            )
        base_val = "Map::empty()"
        return f"""pub open spec fn {func_name}(cols: &Cols{extra_sig}, {idx_var}: int) -> {ret_type}
    recommends
        0 <= {idx_var} && {idx_var} <= cols.n,
        valid_cols(cols){extra_rec},
    decreases cols.n - {idx_var},
{{
    if {idx_var} < cols.n {{
        {body_inner}
    }} else {{
        {base_val}
    }}
}}"""

    ret_type = val_type
    term = spec_u64_term(query.agg_expr, idx_var) if is_sum else "1u64"
    if agg == "MIN":
        base_val = "u64::MAX"
        if cond:
            body_inner = (
                f"let tail = {rec};\n"
                f"        if {cond} {{\n"
                f"            let t = {term};\n"
                f"            if t < tail {{ t }} else {{ tail }}\n"
                f"        }} else {{ tail }}"
            )
        else:
            body_inner = (
                f"let tail = {rec};\n"
                f"        let t = {term};\n"
                f"        if t < tail {{ t }} else {{ tail }}"
            )
    elif agg == "MAX":
        base_val = "0u64"
        if cond:
            body_inner = (
                f"let tail = {rec};\n"
                f"        if {cond} {{\n"
                f"            let t = {term};\n"
                f"            if t > tail {{ t }} else {{ tail }}\n"
                f"        }} else {{ tail }}"
            )
        else:
            body_inner = (
                f"let tail = {rec};\n"
                f"        let t = {term};\n"
                f"        if t > tail {{ t }} else {{ tail }}"
            )
    elif cond:
        body_inner = (
            f"if {cond} {{ ({rec} as int + {term} as int) as u64 }}"
            f" else {{ {rec} }}"
        )
        base_val = "0u64"
    else:
        body_inner = (
            f"({rec} as int + {term} as int) as u64"
        )
        base_val = "0u64"

    return f"""pub open spec fn {func_name}(cols: &Cols{extra_sig}, {idx_var}: int) -> {ret_type}
    recommends
        0 <= {idx_var} && {idx_var} <= cols.n,
        valid_cols(cols){extra_rec},
    decreases cols.n - {idx_var},
{{
    if {idx_var} < cols.n {{
        {body_inner}
    }} else {{
        {base_val}
    }}
}}"""


def _emit_multi_table_cols(
    multi_schema: dict[str, dict[str, str]],
    query: SQLQuery,
    *,
    bounds: ResolvedBounds,
    catalog: CatalogAssumptions | None = None,
) -> str:
    parts: list[str] = []
    join_depth = sum(1 for table in multi_schema if table in query.tables)
    row_cap = row_cap_const_for_join_depth(join_depth)
    for table, cols in multi_schema.items():
        if table not in query.tables:
            continue
        struct = _table_struct_name(table)
        parts.append(generate_cols_rs(cols, groupby_columns=query.groupby_columns, struct_name=struct))
        ta = table_assumptions_for(catalog, table)
        parts.append(
            emit_valid_cols_predicate(
                cols,
                struct_name=struct,
                bounds=bounds,
                catalog=catalog,
                table_assumptions=ta,
                table_name=table,
                row_cap_const=row_cap,
            ).replace("valid_cols", f"valid_cols_{table}")
        )
    return "\n\n".join(parts)


def _emit_support_spec_table_cols(
    query: SQLQuery,
    multi_schema: dict[str, dict[str, str]] | None,
    *,
    bounds: ResolvedBounds,
    catalog: CatalogAssumptions | None = None,
) -> str:
    """Emit Cols_{table} + valid_cols_{table} for inner catalog tables in subqueries."""
    if not multi_schema:
        return ""
    extras = support_spec_params(query)
    if not extras:
        return ""
    parts: list[str] = []
    for table, struct, valid in extras:
        cols = multi_schema.get(table)
        if cols is None:
            continue
        parts.append(generate_cols_rs(cols, struct_name=struct))
        ta = table_assumptions_for(catalog, table)
        parts.append(
            emit_valid_cols_predicate(
                cols,
                struct_name=struct,
                bounds=bounds,
                catalog=catalog,
                table_assumptions=ta,
                table_name=table,
            ).replace("valid_cols", valid)
        )
    return "\n\n".join(parts)


def _having_closure_types(query: SQLQuery, flat_schema: dict[str, str]) -> tuple[str, str]:
    if len(query.groupby_columns) == 1:
        key_ty = spec_map_key_type(flat_schema[query.groupby_columns[0]])
    else:
        parts = ", ".join(
            spec_map_key_type(flat_schema[c]) for c in query.groupby_columns
        )
        key_ty = f"({parts})"
    # Must match MethodSpec map value (multi-agg tuple), not singular agg_expr.
    if query.agg_specs:
        val_ty = _multi_agg_tuple_type(query)
    else:
        val_ty = _agg_value_type(query.agg_expr)
    return key_ty, val_ty


def _emit_having_filter(
    spec_body: str, query: SQLQuery, flat_schema: dict[str, str]
) -> str:
    if not query.having_expr:
        return spec_body
    key_ty, val_ty = _having_closure_types(query, flat_schema)
    pred = f"|k: {key_ty}, v: {val_ty}| {query.having_expr}"
    if "\n" in spec_body:
        wrapped = f"{{\n        {spec_body}\n    }}"
        return f"""{{
    let m = {wrapped};
    apply_having_filter(m, {pred})
}}"""
    return f"""{{
    let m = {spec_body};
    apply_having_filter(m, {pred})
}}"""


def _emit_having_helper() -> str:
    return """pub open spec fn apply_having_filter<K, V>(m: Map<K, V>, pred: spec_fn(K, V) -> bool) -> Map<K, V> {
    m.filter_keys(|k| pred(k, m[k]))
}"""


def _schema_col_key(flat_schema: dict[str, str], name: str) -> str:
    for k in flat_schema:
        if k.lower() == name.lower():
            return k
    return name


def _projection_col_type(
    expr: str,
    flat_schema: dict[str, str],
) -> str:
    if "window_sum_" in expr:
        return "u64"
    if "window_row_number_" in expr:
        return "u32"
    m = re.match(r"row\.([A-Za-z_][A-Za-z0-9_]*)", expr.strip())
    if m:
        key = _schema_col_key(flat_schema, m.group(1))
        return spec_map_key_type(flat_schema[key])
    return "u64"


def _row_expr_at(
    expr: str,
    idx_var: str,
    flat_schema: dict[str, str],
) -> str:
    out = re.sub(
        r"window_([a-z0-9_]+)_spec\(cols,\s*k\)",
        rf"window_\1_spec(cols, {idx_var})",
        expr,
    )

    def repl(m: re.Match[str]) -> str:
        key = _schema_col_key(flat_schema, m.group(1))
        field = rust_ident(key)
        if col_verus_type(flat_schema[key]) == "String":
            return f"cols.{field}[{idx_var} as int]@"
        return f"cols.{field}[{idx_var} as int]"

    return re.sub(r"\brow\.([A-Za-z_][A-Za-z0-9_]*)", repl, out)


def _emit_projection_branch(
    query: SQLQuery,
    flat_schema: dict[str, str],
    *,
    helper_name: str = "projection_helper",
    spec_name: str | None = None,
    struct_name: str = "Cols",
    extras: list[tuple[str, str, str]] | None = None,
) -> tuple[str, str, str]:
    """Projection fold; returns (helpers, spec_call, ret_type)."""
    extras = extras if extras is not None else _support_spec_params(query)
    extra_sig = _extra_param_sig(extras)
    extra_call = _extra_param_call(extras)
    extra_rec = _extra_param_recommends(extras)
    idx_var = "k"
    where_at_k = (
        spec_where_cond(to_col_expr(query.where_expr, idx_var), idx_var, flat_schema)
        if query.where_expr
        else None
    )
    row_types = [
        _projection_col_type(expr, flat_schema) for expr in query.projection_exprs
    ]
    row_exprs = [
        _row_expr_at(expr, idx_var, flat_schema) for expr in query.projection_exprs
    ]
    if len(row_exprs) == 1:
        row_expr = row_exprs[0]
        row_ty = row_types[0]
    else:
        row_expr = f"({', '.join(row_exprs)})"
        row_ty = f"({', '.join(row_types)})"

    if query.distinct:
        update_expr = (
            f"if tail.contains({row_expr}) {{ tail }} else {{ tail.push({row_expr}) }}"
        )
    else:
        update_expr = f"tail.push({row_expr})"

    container_ty = f"Seq<{row_ty}>"
    ret_type = container_ty
    ret_base = "Seq::empty()"

    rec = f"{helper_name}(cols{extra_call}, {idx_var} + 1)"
    if where_at_k:
        body_inner = (
            f"let tail = {rec};\n"
            f"        if {where_at_k} {{\n"
            f"            {update_expr}\n"
            f"        }} else {{\n"
            f"            tail\n"
            f"        }}"
        )
    else:
        body_inner = (
            f"let tail = {rec};\n"
            f"        {update_expr}"
        )

    helper = f"""pub open spec fn {helper_name}(cols: &{struct_name}{extra_sig}, {idx_var}: int) -> {container_ty}
    recommends
        0 <= {idx_var} && {idx_var} <= cols.n,
        valid_cols(cols){extra_rec},
    decreases cols.n - {idx_var},
{{
    if {idx_var} < cols.n {{
        {body_inner}
    }} else {{
        {ret_base}
    }}
}}"""

    body = f"{helper_name}(cols{extra_call}, 0)"
    if query.limit is not None:
        body = f"spec_seq_take({body}, {query.limit})"

    if spec_name:
        spec = f"""pub open spec fn {spec_name}(cols: &{struct_name}{extra_sig}) -> {ret_type}
    recommends valid_cols(cols){extra_rec},
{{
    {body}
}}"""
        return helper + "\n\n" + spec, f"{spec_name}(cols{extra_call})", ret_type
    return helper, body, ret_type


def _emit_projection_spec(query: SQLQuery, flat_schema: dict[str, str]) -> tuple[str, str, str]:
    """Single-table SELECT projection: recursive Seq fold + optional LIMIT."""
    extras = _support_spec_params(query)
    helpers, spec_body, ret_type = _emit_projection_branch(
        query,
        flat_schema,
        helper_name="projection_helper",
        extras=extras,
    )
    spec_fn = _method_spec_fn(ret_type, spec_body, extras)
    return helpers, spec_fn, ret_type


def _emit_derived_union_outer_spec(
    query: SQLQuery,
    derived: DerivedTable,
    flat_schema: dict[str, str],
) -> tuple[str, str, str]:
    """Outer aggregate over UNION/UNION ALL derived projection."""
    inner = derived.query
    right = inner.union_query
    if right is None or not inner.is_projection:
        raise UnsupportedContractError(
            "derived UNION composition requires compatible projection branches"
        )
    if len(inner.projection_columns) != 1 or not query.agg_type:
        raise UnsupportedContractError(
            "derived UNION outer aggregate requires single-column projection + scalar agg"
        )

    prefix_l = f"derived_{derived.alias}_left"
    prefix_r = f"derived_{derived.alias}_right"
    left_helpers, left_call, _ = _emit_projection_branch(
        inner, flat_schema, helper_name=f"{prefix_l}_helper", spec_name=f"{prefix_l}_spec",
    )
    right_helpers, right_call, _ = _emit_projection_branch(
        right, flat_schema, helper_name=f"{prefix_r}_helper", spec_name=f"{prefix_r}_spec",
    )
    if inner.union_all:
        combined = f"spec_seq_concat({left_call}, {right_call})"
    else:
        combined = f"spec_seq_union_distinct({left_call}, {right_call})"

    if query.agg_type == "SUM":
        spec_body = f"seq_sum_u64({combined})"
        ret_type = "u64"
    elif query.agg_type == "COUNT":
        spec_body = f"{combined}.len() as u64"
        ret_type = "u64"
    else:
        raise UnsupportedContractError(
            f"outer {query.agg_type!r} over derived UNION not supported"
        )

    helpers = "\n\n".join([left_helpers, right_helpers])
    spec_fn = f"""pub open spec fn method_spec(cols: &Cols) -> {ret_type}
    recommends valid_cols(cols),
{{
    {spec_body}
}}"""
    return helpers, spec_fn, ret_type


def _result_row_type(base_ret: str) -> str:
    """Map group-by / projection base type to one result row for ORDER BY / LIMIT."""
    if base_ret.startswith("Map<"):
        inner = base_ret[4:-1].strip()
        comma = inner.rfind(", ")
        if comma < 0:
            return base_ret
        key_ty = inner[:comma].strip()
        val_ty = inner[comma + 2 :].strip()
        return f"({key_ty}, {val_ty})"
    if base_ret.startswith("Seq<"):
        inner = base_ret[4:-1].strip()
        if inner.startswith("("):
            return inner
        return f"({inner},)"
    if base_ret.startswith("Set<"):
        inner = base_ret[4:-1].strip()
        return inner
    return base_ret


def _emit_method_spec_result(query: SQLQuery, base_ret: str) -> str:
    if not query.has_order_or_limit:
        return ""
    if not query.groupby_columns and not query.is_projection and query.agg_type:
        return (
            "// Note: ORDER BY / LIMIT ignored for scalar aggregate queries.\n"
        )
    row_ty = _result_row_type(base_ret)
    order_cols = ", ".join(
        f"{ob.column}{' DESC' if ob.descending else ''}" for ob in query.order_by
    ) or "unspecified"
    limit_s = str(query.limit) if query.limit is not None else "none"
    offset_s = str(query.offset) if query.offset is not None else "0"
    return (
        f"// Note: ORDER BY ({order_cols}), LIMIT {limit_s}, OFFSET {offset_s} "
        f"are not part of method_spec ({row_ty}); agent may apply in run_query.\n"
    )


def _emit_set_op_helpers(
    query: SQLQuery,
    flat_schema: dict[str, str],
    *,
    op: str,
) -> tuple[str, str, str]:
    """Emit INTERSECT / EXCEPT / UNION composition over two branch specs."""
    if op == "union":
        right = query.union_query
        distinct = not query.union_all
    elif op == "intersect":
        if query.intersect_all:
            raise UnsupportedContractError(
                "INTERSECT ALL set operation needs real MethodSpec bag fold; not yet supported"
            )
        right = query.intersect_query
        distinct = True
    elif op == "except":
        if query.except_all:
            raise UnsupportedContractError(
                "EXCEPT ALL set operation needs real MethodSpec bag fold; not yet supported"
            )
        right = query.except_query
        distinct = True
    else:
        raise UnsupportedContractError(f"unknown set operation {op!r}")

    if right is None:
        raise UnsupportedContractError(f"{op.upper()} set operation missing right branch")

    left = query
    prefix_l = f"setop_{op}_left"
    prefix_r = f"setop_{op}_right"

    if left.is_projection:
        left_helpers, left_call, ret_type = _emit_projection_branch(
            left,
            flat_schema,
            helper_name=f"{prefix_l}_helper",
            spec_name=f"{prefix_l}_spec",
        )
        right_helpers, right_call, _ = _emit_projection_branch(
            right,
            flat_schema,
            helper_name=f"{prefix_r}_helper",
            spec_name=f"{prefix_r}_spec",
        )
        if op == "union":
            combined = (
                f"spec_seq_concat({left_call}, {right_call})"
                if query.union_all
                else f"spec_seq_union_distinct({left_call}, {right_call})"
            )
        elif op == "intersect":
            combined = f"spec_seq_intersect({left_call}, {right_call})"
        else:
            combined = f"spec_seq_except({left_call}, {right_call})"
        helpers = "\n\n".join([left_helpers, right_helpers])
        spec_fn = f"""pub open spec fn method_spec(cols: &Cols) -> {ret_type}
    recommends valid_cols(cols),
{{
    {combined}
}}"""
        return helpers, spec_fn, ret_type

    raise UnsupportedContractError(
        f"{op.upper()} set operation shape needs real MethodSpec fold; not yet supported"
    )


def _emit_union_helpers(query: SQLQuery, flat_schema: dict[str, str]) -> tuple[str, str, str]:
    """Emit UNION / UNION ALL composition over two branch specs."""
    return _emit_set_op_helpers(query, flat_schema, op="union")


def _multi_agg_val_types(query: SQLQuery) -> list[str]:
    types: list[str] = []
    for spec in query.agg_specs:
        if spec.agg_type in ("SUM", "COUNT", "COUNT_DISTINCT", "AVG", "MIN", "MAX"):
            types.append(_agg_value_type(spec.agg_expr))
        else:
            types.append("u64")
    return types


def _multi_agg_tuple_type(query: SQLQuery) -> str:
    types = _multi_agg_val_types(query)
    if len(types) == 1:
        return types[0]
    return f"({', '.join(types)})"


def _distinct_val_expr(spec: AggSpec, idx_var: str, flat_schema: dict[str, str]) -> str:
    col = spec.agg_column
    field = rust_ident(col)
    if col_verus_type(flat_schema[col]) == "String":
        return f"cols.{field}[{idx_var} as int]@"
    return f"cols.{field}[{idx_var} as int]"


def _emit_multi_agg_spec(
    query: SQLQuery,
    flat_schema: dict[str, str],
    *,
    helper_name: str = "multi_agg_helper",
) -> tuple[str, str, str]:
    """Multi-aggregate group-by spec: recursive fold with Map<Key, state tuple>."""
    idx_var = "k"
    extras = _support_spec_params(query)
    extra_sig = _extra_param_sig(extras)
    extra_call = _extra_param_call(extras)
    extra_rec = _extra_param_recommends(extras)
    rec = f"{helper_name}(cols{extra_call}, {idx_var} + 1)"
    cond = (
        spec_where_cond(to_col_expr(query.where_expr, idx_var), idx_var, flat_schema)
        if query.where_expr
        else None
    )
    key_expr = _groupby_key_expr(query.groupby_columns, idx_var, flat_schema)

    state_types: list[str] = []
    state_defaults: list[str] = []
    update_stmts: list[tuple[int, str]] = []
    project_parts: list[str] = []

    for spec in query.agg_specs:
        pos = len(state_types)

        if spec.agg_type == "COUNT":
            state_types.append("u64")
            state_defaults.append("0u64")
            update_stmts.append((pos, f"let s{pos} = (__PREV__ as int + 1) as u64;"))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "SUM":
            val_type = _agg_value_type(spec.agg_expr)
            state_types.append(val_type)
            state_defaults.append(f"0{val_type}")
            term = (
                spec_i64_term(spec.agg_expr, idx_var)
                if val_type == "i64"
                else spec_u64_term(spec.agg_expr, idx_var)
            )
            update_stmts.append((
                pos,
                f"let s{pos} = (__PREV__ as int + {term} as int) as {val_type};",
            ))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "MIN":
            state_types.append("u64")
            state_defaults.append("u64::MAX")
            term = spec_u64_term(spec.agg_expr, idx_var)
            update_stmts.append((
                pos,
                f"let t{pos} = {term};\n"
                f"            let s{pos} = if t{pos} < __PREV__ {{ t{pos} }} else {{ __PREV__ }};",
            ))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "MAX":
            state_types.append("u64")
            state_defaults.append("0u64")
            term = spec_u64_term(spec.agg_expr, idx_var)
            update_stmts.append((
                pos,
                f"let t{pos} = {term};\n"
                f"            let s{pos} = if t{pos} > __PREV__ {{ t{pos} }} else {{ __PREV__ }};",
            ))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "AVG":
            sum_pos = len(state_types)
            state_types.extend(["u64", "u64"])
            state_defaults.extend(["0u64", "0u64"])
            term = spec_u64_term(spec.agg_expr, idx_var)
            update_stmts.append((
                sum_pos,
                f"let s{sum_pos} = (__PREV_SUM__ as int + {term} as int) as u64;\n"
                f"            let s{sum_pos + 1} = (__PREV_CNT__ as int + 1) as u64;",
            ))
            project_parts.append(
                f"if s{sum_pos + 1} == 0 {{ 0 }} else {{ s{sum_pos} / s{sum_pos + 1} }}"
            )
        elif spec.agg_type == "COUNT_DISTINCT":
            val_ty = spec_map_key_type(flat_schema[spec.agg_column])
            state_types.append(f"Map<{val_ty}, bool>")
            state_defaults.append("Map::empty()")
            val_expr = _distinct_val_expr(spec, idx_var, flat_schema)
            update_stmts.append((
                pos,
                f"let s{pos} = if __PREV__.contains_key({val_expr}) {{ __PREV__ }} "
                f"else {{ __PREV__.insert({val_expr}, true) }};",
            ))
            project_parts.append(f"s{pos}.dom().len() as u64")
        else:
            raise UnsupportedContractError(
                f"multi-agg unsupported aggregate {spec.agg_type!r}"
            )

    n_state = len(state_types)

    def pref(i: int) -> str:
        return f"prev.{i}" if n_state > 1 else "prev"

    rendered_updates: list[str] = []
    for pos, tmpl in update_stmts:
        pos_i = int(pos)
        if "__PREV_SUM__" in tmpl:
            rendered = tmpl.replace("__PREV_SUM__", pref(pos_i)).replace(
                "__PREV_CNT__", pref(pos_i + 1)
            )
        else:
            rendered = tmpl.replace("__PREV__", pref(pos_i))
        rendered_updates.append(rendered)

    if n_state == 1:
        state_tuple_type = state_types[0]
        default_state = state_defaults[0]
        rebuild_state = "s0"
        val_bind = "v"
    else:
        state_tuple_type = f"({', '.join(state_types)})"
        default_state = f"({', '.join(state_defaults)})"
        rebuild_state = f"({', '.join(f's{i}' for i in range(n_state))})"
        val_bind = "v"

    # Projection reads the folded state value `v` (not free s0/s1 names).
    def _project_from_v(expr: str) -> str:
        out = expr
        if n_state == 1:
            return out.replace("s0", "v")
        # High→low so s10 is not mangled by replacing s1 first.
        for i in range(n_state - 1, -1, -1):
            out = out.replace(f"s{i}", f"v.{i}")
        return out

    if len(project_parts) == 1:
        project_expr = _project_from_v(project_parts[0])
    else:
        project_expr = f"({', '.join(_project_from_v(p) for p in project_parts)})"

    update_block = "\n            ".join(rendered_updates)

    if cond:
        body_inner = (
            f"let tail = {rec};\n"
            f"        if {cond} {{\n"
            f"            let key = {key_expr};\n"
            f"            let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {default_state} }};\n"
            f"            {update_block}\n"
            f"            tail.insert(key, {rebuild_state})\n"
            f"        }} else {{\n"
            f"            tail\n"
            f"        }}"
        )
    else:
        body_inner = (
            f"let tail = {rec};\n"
            f"        let key = {key_expr};\n"
            f"        let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {default_state} }};\n"
            f"        {update_block}\n"
            f"        tail.insert(key, {rebuild_state})"
        )

    if len(query.groupby_columns) == 1:
        c = query.groupby_columns[0]
        map_key_ty = spec_map_key_type(flat_schema[c])
    else:
        map_key_ty = f"({', '.join(spec_map_key_type(flat_schema[c]) for c in query.groupby_columns)})"
    ret_type = f"Map<{map_key_ty}, {_multi_agg_tuple_type(query)}>"
    map_state_ret = f"Map<{map_key_ty}, {state_tuple_type}>"

    helper = f"""pub open spec fn {helper_name}(cols: &Cols{extra_sig}, {idx_var}: int) -> {map_state_ret}
    recommends
        0 <= {idx_var} && {idx_var} <= cols.n,
        valid_cols(cols){extra_rec},
    decreases cols.n - {idx_var},
{{
    if {idx_var} < cols.n {{
        {body_inner}
    }} else {{
        Map::empty()
    }}
}}"""

    spec_body = (
        f"let raw = {helper_name}(cols{extra_call}, 0);\n"
        f"    raw.map_values(|{val_bind}: {state_tuple_type}| {project_expr})"
    )
    extra = ""
    if query.having_expr:
        extra = "\n\n" + _emit_having_helper()
        spec_body = _emit_having_filter(spec_body, query, flat_schema).strip()

    spec_fn = _method_spec_fn(ret_type, spec_body, extras)
    return helper + extra, spec_fn, ret_type


def _emit_single_table_spec(
    query: SQLQuery,
    flat_schema: dict[str, str],
    *,
    helper_name: str = "method_spec_helper",
) -> tuple[str, str, str]:
    """Return (helpers, spec_fn, ret_type)."""
    extras = _support_spec_params(query)
    extra_call = _extra_param_call(extras)
    extra_helpers: list[str] = []

    if query.is_projection:
        return _emit_projection_spec(query, flat_schema)

    if query.is_multi_agg and query.groupby_columns:
        return _emit_multi_agg_spec(query, flat_schema, helper_name=helper_name)

    if query.agg_type == "SELECT_SUBQUERY":
        ret_type = "u64"
        spec_fn = _method_spec_fn(ret_type, query.agg_expr, extras)
        return "", spec_fn, ret_type

    if query.derived_tables:
        if len(query.derived_tables) != 1:
            raise UnsupportedContractError("only one derived table in FROM is supported.")
        derived = query.derived_tables[0]
        inner = derived.query
        recursive_cte = next(
            (c for c in query.ctes if c.recursive and c.name == derived.alias), None
        )
        if recursive_cte is not None:
            raise UnsupportedContractError(
                f"outer aggregate over derived recursive CTE '{derived.alias}' "
                "needs real MethodSpec; not yet supported"
            )
        if inner.union_query is not None:
            return _emit_derived_union_outer_spec(query, derived, flat_schema)
        if inner.window_specs:
            raise UnsupportedContractError(
                "outer aggregate over derived window column needs real MethodSpec; "
                "not yet supported"
            )
        if inner.groupby_columns:
            inner_helpers, inner_spec_call, _inner_ret = emit_derived_grouped_inner_spec(
                derived.alias, inner, flat_schema
            )
            spec_body = f"""{{
    let m = {inner_spec_call};
    m.values().fold(0u64, |acc, v| (acc as int + v as int) as u64)
}}"""
            ret_type = "u64"
            spec_fn = f"""pub open spec fn method_spec(cols: &Cols) -> {ret_type}
    recommends valid_cols(cols),
{{
    {spec_body}
}}"""
            return inner_helpers, spec_fn, ret_type
        if not inner.agg_type:
            raise UnsupportedContractError(
                "derived table composition requires inner scalar aggregate."
            )
        inner_helpers, inner_spec_call, _inner_ret = emit_derived_inner_spec(
            derived.alias, inner, flat_schema
        )
        try:
            spec_body = compose_outer_over_derived_scalar(query.agg_type, inner_spec_call)
        except ValueError as e:
            raise UnsupportedContractError(str(e)) from e
        ret_type = "u64"
        spec_fn = f"""pub open spec fn method_spec(cols: &Cols) -> {ret_type}
    recommends valid_cols(cols),
{{
    {spec_body}
}}"""
        return inner_helpers, spec_fn, ret_type

    if query.agg_type == "AVG":
        if query.groupby_columns:
            helpers = "\n\n".join([
                _build_col_helper("sum_map_helper", query, "k", flat_schema, is_sum=True, extras=extras),
                _build_col_helper("count_map_helper", query, "k", flat_schema, is_sum=False, extras=extras),
            ])
            spec_body = (
                f"let sums = sum_map_helper(cols{extra_call}, 0);\n"
                f"    let counts = count_map_helper(cols{extra_call}, 0);\n"
                "    sums.filter(|k, _| counts.contains_key(k)).map_values(|k| {\n"
                "        let c = counts[k];\n"
                "        if c == 0 { 0 } else { sums[k] / c }\n"
                "    })"
            )
            ret_type = "Map<_, u64>"
        else:
            helpers = "\n\n".join([
                _build_col_helper("sum_helper", query, "k", flat_schema, is_sum=True, extras=extras),
                _build_col_helper("count_helper", query, "k", flat_schema, is_sum=False, extras=extras),
            ])
            spec_body = (
                f"let sum = sum_helper(cols{extra_call}, 0);\n"
                f"    let count = count_helper(cols{extra_call}, 0);\n"
                "    if count == 0 { 0 } else { sum / count }"
            )
            ret_type = "u64"
        if query.having_expr:
            extra_helpers.append(_emit_having_helper())
            spec_body = _emit_having_filter(spec_body, query, flat_schema).strip()
        spec_fn = _method_spec_fn(ret_type, spec_body, extras)
        all_helpers = "\n\n".join([helpers] + extra_helpers) if extra_helpers else helpers
        return all_helpers, spec_fn, ret_type

    is_sum = query.agg_type in ("SUM", "MIN", "MAX")
    helpers = _build_col_helper(
        helper_name, query, "k", flat_schema,
        is_sum=is_sum, agg_type=query.agg_type, extras=extras,
    )
    spec_body = f"{helper_name}(cols{extra_call}, 0)"
    if query.groupby_columns:
        val_type = _agg_value_type(query.agg_expr)
        if len(query.groupby_columns) == 1:
            c = query.groupby_columns[0]
            ret_type = f"Map<{spec_map_key_type(flat_schema[c])}, {val_type}>"
        else:
            key_types = ", ".join(
                spec_map_key_type(flat_schema[c]) for c in query.groupby_columns
            )
            ret_type = f"Map<({key_types}), {val_type}>"
        if query.having_expr:
            extra_helpers.append(_emit_having_helper())
            spec_body = _emit_having_filter(spec_body, query, flat_schema).strip()
    else:
        ret_type = _agg_value_type(query.agg_expr)

    spec_fn = _method_spec_fn(ret_type, spec_body, extras)
    all_helpers = "\n\n".join([helpers] + extra_helpers) if extra_helpers else helpers
    return all_helpers, spec_fn, ret_type


def _term_at_i_for_query(query: SQLQuery) -> str:
    """Exec-template term at usize index `i` (no ghost `int` casts)."""
    expr = (query.agg_expr or "").strip()
    if query.agg_type == "COUNT":
        return "1u64"
    # SUM(col) or single column
    m = re.match(r"\(row\.([A-Za-z_][A-Za-z0-9_]*) as int\)$", expr)
    if m:
        return f"cols.{rust_ident(m.group(1))}[i] as u64"
    m = re.match(
        r"\(row\.([A-Za-z_][A-Za-z0-9_]*) as int\) \* \(row\.([A-Za-z_][A-Za-z0-9_]*) as int\)",
        expr,
    )
    if m:
        a, b = rust_ident(m.group(1)), rust_ident(m.group(2))
        return f"mul_u64_u32(cols.{a}[i] as u64, cols.{b}[i])"
    m = re.match(
        r"\(row\.([A-Za-z_][A-Za-z0-9_]*) as int\) - \(row\.([A-Za-z_][A-Za-z0-9_]*) as int\)",
        expr,
    )
    if m:
        a, b = rust_ident(m.group(1)), rust_ident(m.group(2))
        return f"sub_u64_to_i64(cols.{a}[i] as u64, cols.{b}[i] as u64)"
    # Fallback: strip row. and cast
    return native_u64_term(expr, "i").replace(" as int", "")


def _emit_run_query(
    query: SQLQuery,
    ret_type: str,
    *,
    agg_push: tuple[str, str] | None = None,
    agg_push_str: tuple[str, str] | None = None,
    where_at_k: str | None = None,
    term_at_k: str | None = None,
    enable_templates: bool = False,
    is_join: bool = False,
    val_type: str | None = None,
) -> str:
    """Emit agent RunQuery skeleton; optional proved scalar templates when enabled."""
    if val_type is None:
        val_type = _agg_value_type(query.agg_expr) if query.agg_expr else "u64"
    if (
        enable_templates
        and not is_join
        and not query.groupby_columns
        and not query.is_projection
        and query.agg_type in ("SUM", "COUNT", "AVG")
        and term_at_k is not None
    ):
        return emit_run_query_template(
            query,
            ret_type,
            where_at_i=where_at_k,
            term_at_i=term_at_k,
            agg_push=agg_push,
            agg_push_str=agg_push_str,
            val_type=val_type,
        )
    return emit_run_query_skeleton(
        query,
        ret_type,
        agg_push=agg_push,
        agg_push_str=agg_push_str,
        is_join=is_join,
        val_type=val_type,
    )


def transpile_sql_to_verus(
    sql: str,
    schema: dict[str, str] | dict[str, dict[str, str]],
    *,
    enable_templates: bool = False,
    catalog_assumptions: CatalogAssumptions | None = None,
) -> str:
    """Return a complete Verus Rust source string."""
    _validate_schema(schema)
    flat_schema, multi_schema = normalize_schema(schema)
    # EXTERNAL assumptions: explicit engine defaults at product boundary (not Trusted folklore).
    catalog_assumptions = with_catalog_assumptions(
        catalog_assumptions,
        defaults=engine_default_catalog_assumptions(),
    )
    bounds = resolve_bounds(catalog_assumptions)
    query = parse_sql(sql, schema)
    decorrelated = try_decorrelate_anti_subqueries(query)
    if decorrelated is not None:
        query = decorrelated

    is_join = bool(query.joins)
    has_subqueries = bool(
        query.scalar_subqueries or query.exists_subqueries or query.in_subqueries
    )
    multi_for_subqueries = multi_schema if (is_join or has_subqueries) else None
    if is_join and has_subqueries:
        _assert_join_subquery_supported(query)
    subquery_blocks: list[str] = []
    outer_schema = _flat_outer_schema(flat_schema, multi_for_subqueries)
    outer_table = _outer_base_table(query)
    sub_spec_calls: dict[str, str] = {}
    for sub in query.scalar_subqueries:
        inner_table = sub.inner_table or _subquery_inner_table_name(sub.query)
        struct_name, valid_fn, param_name, inner_schema = _subquery_emit_binding(
            inner_table, flat_schema, multi_for_subqueries, outer_table=outer_table, is_join=is_join,
        )
        emitted = emit_scalar_subquery_helper(
            sub,
            inner_schema,
            struct_name=struct_name,
            valid_fn=valid_fn,
            param_name=param_name,
            outer_schema=outer_schema,
            schemas_by_table=multi_for_subqueries,
        )
        subquery_blocks.append(emitted.helper_source)
        sub_spec_calls[sub.alias] = emitted.spec_call
    if sub_spec_calls and query.having_expr and not is_join:
        resolved_having = query.having_expr
        for alias, call in sub_spec_calls.items():
            resolved_having = resolved_having.replace(
                f"subquery_{alias}_spec(cols)", call,
            )
        query.having_expr = resolved_having
    for exists in query.exists_subqueries:
        inner_tables = inner_base_tables(exists.query)
        if exists.query.joins:
            if not multi_for_subqueries:
                raise UnsupportedContractError(
                    "EXISTS inner JOIN requires multi-table schema dict[table, dict[col, type]]"
                )
            inner_schema = _merged_table_schema(inner_tables, multi_for_subqueries)
            subquery_blocks.append(
                emit_exists_subquery_helper(
                    exists,
                    inner_schema,
                    schemas_by_table=multi_for_subqueries,
                    inner_tables=inner_tables,
                    outer_schema=outer_schema,
                )
            )
            continue
        inner_table = inner_tables[0]
        struct_name, valid_fn, param_name, inner_schema = _subquery_emit_binding(
            inner_table, flat_schema, multi_for_subqueries, outer_table=outer_table, is_join=is_join,
        )
        subquery_blocks.append(
            emit_exists_subquery_helper(
                exists,
                inner_schema,
                struct_name=struct_name,
                valid_fn=valid_fn,
                param_name=param_name,
                outer_schema=outer_schema,
            )
        )
    for win in query.window_specs:
        subquery_blocks.append(emit_window_spec_helper(win, schema=flat_schema))
    for in_sub in query.in_subqueries:
        inner_tables = inner_base_tables(in_sub.query)
        if in_sub.query.joins:
            if not multi_for_subqueries:
                raise UnsupportedContractError(
                    "IN inner JOIN requires multi-table schema dict[table, dict[col, type]]"
                )
            inner_schema = _merged_table_schema(inner_tables, multi_for_subqueries)
            subquery_blocks.append(
                emit_in_subquery_helper(
                    in_sub,
                    inner_schema,
                    schemas_by_table=multi_for_subqueries,
                    inner_tables=inner_tables,
                    outer_schema=outer_schema,
                )
            )
            continue
        inner_table = inner_tables[0]
        struct_name, valid_fn, param_name, inner_schema = _subquery_emit_binding(
            inner_table, flat_schema, multi_for_subqueries, outer_table=outer_table, is_join=is_join,
        )
        subquery_blocks.append(
            emit_in_subquery_helper(
                in_sub,
                inner_schema,
                struct_name=struct_name,
                valid_fn=valid_fn,
                param_name=param_name,
                outer_schema=outer_schema,
            )
        )
    for cte in query.ctes:
        if cte.recursive:
            if not any(d.alias == cte.name for d in query.derived_tables):
                subquery_blocks.append(emit_recursive_cte_helper(cte))
        else:
            subquery_blocks.append(f"// CTE {cte.name} (non-recursive; inlined in FROM)")
        if not cte.recursive and cte.query.agg_type:
            if not any(d.alias == cte.name for d in query.derived_tables):
                inner_helpers, _, _ = emit_derived_inner_spec(cte.name, cte.query, flat_schema)
                subquery_blocks.append(inner_helpers)

    agg_push = resolve_two_key_u32_str_groupby(query.groupby_columns, flat_schema)
    agg_push_str = resolve_two_key_str_str_groupby(query.groupby_columns, flat_schema)

    result_spec = ""

    if query.intersect_query is not None:
        cols_block = generate_cols_rs(
            flat_schema,
            sql_str=sql,
            groupby_columns=query.groupby_columns,
        )
        valid_cols = emit_valid_cols_predicate(
            flat_schema, bounds=bounds, catalog=catalog_assumptions
        )
        accessor_lemmas = emit_valid_cols_accessor_lemmas(
            flat_schema, bounds=bounds, catalog=catalog_assumptions
        )
        cols_block = f"{cols_block}\n\n{valid_cols}\n\n{accessor_lemmas}"
        helpers, spec_fn, ret_type = _emit_set_op_helpers(query, flat_schema, op="intersect")
        run_query = emit_run_query_skeleton(query, ret_type)
    elif query.except_query is not None:
        cols_block = generate_cols_rs(
            flat_schema,
            sql_str=sql,
            groupby_columns=query.groupby_columns,
        )
        valid_cols = emit_valid_cols_predicate(
            flat_schema, bounds=bounds, catalog=catalog_assumptions
        )
        accessor_lemmas = emit_valid_cols_accessor_lemmas(
            flat_schema, bounds=bounds, catalog=catalog_assumptions
        )
        cols_block = f"{cols_block}\n\n{valid_cols}\n\n{accessor_lemmas}"
        helpers, spec_fn, ret_type = _emit_set_op_helpers(query, flat_schema, op="except")
        run_query = emit_run_query_skeleton(query, ret_type)
    elif query.union_query is not None:
        cols_block = generate_cols_rs(
            flat_schema,
            sql_str=sql,
            groupby_columns=query.groupby_columns,
        )
        valid_cols = emit_valid_cols_predicate(
            flat_schema, bounds=bounds, catalog=catalog_assumptions
        )
        accessor_lemmas = emit_valid_cols_accessor_lemmas(
            flat_schema, bounds=bounds, catalog=catalog_assumptions
        )
        cols_block = f"{cols_block}\n\n{valid_cols}\n\n{accessor_lemmas}"
        helpers, spec_fn, ret_type = _emit_union_helpers(query, flat_schema)
        run_query = emit_run_query_skeleton(query, ret_type)
    elif is_join and multi_schema:
        cols_block = _emit_multi_table_cols(
            multi_schema, query, bounds=bounds, catalog=catalog_assumptions
        )
        # Join helpers resolve row.* via slot params; do not pre-convert to cols.get_*.
        where_at = query.where_expr
        val_type = _agg_value_type(query.agg_expr)
        is_sum = query.agg_type in ("SUM", "AVG", "MIN", "MAX")
        join_helper, spec_fn, ret_type = emit_join_spec_helpers(
            query,
            multi_schema,
            where_expr=where_at,
            agg_expr=query.agg_expr,
            is_sum=is_sum,
            val_type=val_type,
            flat_schema=flat_schema,
        )
        helpers = join_helper
        result_spec = _emit_method_spec_result(query, ret_type)
        run_query = _emit_run_query(query, ret_type, is_join=True)
    else:
        if is_join:
            raise UnsupportedContractError(
                "INNER JOIN requires multi-table schema dict[table, dict[col, type]]"
            )

        outer_schema = _outer_cols_schema(query, flat_schema, multi_schema)
        cols_block = generate_cols_rs(
            outer_schema,
            groupby_columns=query.groupby_columns,
        )
        support_cols = _emit_support_spec_table_cols(
            query, multi_schema, bounds=bounds, catalog=catalog_assumptions,
        )
        if support_cols:
            cols_block = f"{cols_block}\n\n{support_cols}"
        single_table = query.tables[0] if len(query.tables) == 1 else None
        single_ta = (
            table_assumptions_for(catalog_assumptions, single_table)
            if single_table
            else None
        )
        valid_cols = emit_valid_cols_predicate(
            outer_schema,
            bounds=bounds,
            catalog=catalog_assumptions,
            table_assumptions=single_ta,
            table_name=single_table,
        )
        accessor_lemmas = emit_valid_cols_accessor_lemmas(
            outer_schema,
            bounds=bounds,
            catalog=catalog_assumptions,
            table_assumptions=single_ta,
            table_name=single_table,
        )

        helpers, spec_fn, ret_type = _emit_single_table_spec(query, outer_schema)
        result_spec = _emit_method_spec_result(query, ret_type)

        where_at_k = to_col_expr(query.where_expr, "i") if query.where_expr else None
        if where_at_k:
            where_at_k = re.sub(
                r"cols\.get_(\w+)\(i\)",
                r"cols.\1[i]",
                where_at_k,
            )
        term_at_k = _term_at_i_for_query(query)

        run_query = _emit_run_query(
            query,
            ret_type,
            agg_push=agg_push,
            agg_push_str=agg_push_str,
            where_at_k=where_at_k,
            term_at_k=term_at_k,
            enable_templates=enable_templates,
        )

        cols_block = f"{cols_block}\n\n{valid_cols}\n\n{accessor_lemmas}"

    subquery_section = "\n\n".join(subquery_blocks)
    if subquery_section:
        subquery_section = subquery_section + "\n\n"

    join_multi = is_join and bool(multi_schema)
    trusted_prelude = emit_trusted_prelude(include_left_join_miss=not join_multi)
    eq_join_prelude = f"\n{proved_eq_join_prelude()}\n" if join_multi else ""

    hash_state_use = "\nuse std::hash::RandomState;" if join_multi else ""
    return f"""use vstd::prelude::*;
use std::collections::{{HashMap, HashSet}};{hash_state_use}

verus! {{

{emit_bound_constants(bounds=bounds, catalog=catalog_assumptions)}

{emit_bound_lemmas(bounds=bounds, catalog=catalog_assumptions)}

{trusted_prelude}
{eq_join_prelude}
{cols_block}

{helpers}

{subquery_section}{spec_fn}

{result_spec}{run_query}

}} // verus!
"""
