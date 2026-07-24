"""Main SQL → Verus Rust spec emitter."""

from __future__ import annotations

import re

from .agg_push import emit_cols_agg_push_verus, resolve_two_key_u32_str_groupby
from .agg_push_str import emit_cols_agg_push_str_verus, resolve_two_key_str_str_groupby
from .col_exprs import (
    native_u64_term,
    spec_i64_term,
    spec_u64_term,
    spec_where_cond,
    to_col_expr,
)
from .joins import _table_struct_name, emit_join_spec_helpers
from .parse_sql import (
    SQLQuery,
    UnsupportedContractError,
    get_rust_type,
    normalize_schema,
    parse_sql,
    _agg_value_type,
)
from .recursive_cte import emit_recursive_cte_helper
from .subqueries import (
    compose_outer_over_derived_scalar,
    emit_derived_grouped_inner_spec,
    emit_derived_inner_spec,
    emit_exists_subquery_helper,
    emit_in_subquery_helper,
    emit_scalar_subquery_helper,
)
from .windows import emit_window_spec_helper
from .templates import emit_run_query_skeleton, emit_run_query_template
from .value_bounds import (
    col_spec_accessor_return,
    col_verus_type,
    emit_bound_constants,
    emit_trusted_prelude,
    emit_valid_cols_accessor_lemmas,
    emit_valid_cols_predicate,
    spec_map_key_type,
)

_SUPPORTED_TYPES = frozenset({
    "int", "string", "bigint", "int8", "int64", "integer", "int4", "int32",
    "varchar", "text", "date", "bool", "boolean",
})


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
) -> str:
    """Emit columnar Cols struct + getters for the given schema."""
    if groupby_columns is None and sql_str is not None:
        groupby_columns = parse_sql(sql_str, schema_dict).groupby_columns
    agg_push = resolve_two_key_u32_str_groupby(groupby_columns, schema_dict)
    agg_push_str = resolve_two_key_str_str_groupby(groupby_columns, schema_dict)

    field_lines = ["    pub n: usize,"]
    for col, col_type in schema_dict.items():
        rust_ty = col_verus_type(col_type)
        field_lines.append(f"    pub {col.lower()}: Vec<{rust_ty}>,")

    getters: list[str] = []
    for col, col_type in schema_dict.items():
        field = col.lower()
        ret = col_spec_accessor_return(col_type)
        if ret == "Seq<char>":
            getters.append(f"""    pub open spec fn get_{field}(self, i: int) -> Seq<char> {{
        self.{field}[i as int]@
    }}

    #[verifier::external_body]
    pub exec fn get_{field}_exec(&self, i: usize) -> (res: String)
        requires i < self.n,
        ensures res@ == self.get_{field}(i as int),
    {{
        self.{field}[i].clone()
    }}

    #[verifier::external_body]
    pub exec fn eq_at_{field}(&self, i: usize, lit: &str) -> (res: bool)
        requires i < self.n,
        ensures res == (self.get_{field}(i as int) == lit@),
    {{
        self.{field}[i] == lit
    }}""")
        else:
            getters.append(f"""    pub open spec fn get_{field}(self, i: int) -> {ret} {{
        self.{field}[i as int]
    }}

    #[verifier::external_body]
    pub exec fn get_{field}_exec(&self, i: usize) -> (res: {ret})
        requires i < self.n,
        ensures res == self.get_{field}(i as int),
    {{
        self.{field}[i]
    }}""")

    agg_methods = ""
    if agg_push is not None:
        agg_methods += "\n" + emit_cols_agg_push_verus(*agg_push, struct_name=struct_name)
    if agg_push_str is not None:
        agg_methods += "\n" + emit_cols_agg_push_str_verus(*agg_push_str, struct_name=struct_name)

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
        field = col.lower()
        if col_verus_type(schema_dict[col]) == "String":
            parts.append(f"cols.{field}[{idx_var} as int]@")
        else:
            parts.append(f"cols.{field}[{idx_var} as int]")
    if len(parts) == 1:
        return parts[0]
    return f"({', '.join(parts)})"


def _build_col_helper(
    func_name: str,
    query: SQLQuery,
    idx_var: str,
    schema_dict: dict[str, str],
    *,
    is_sum: bool,
    agg_type: str | None = None,
) -> str:
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
                f"let tail = {func_name}(cols, {idx_var} + 1);\n"
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
                f"let tail = {func_name}(cols, {idx_var} + 1);\n"
                f"        let key = {key_expr};\n"
                f"        let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {zero} }};\n"
                f"        tail.insert(key, (prev as int + {term} as int) as {val_type})"
            )
        base_val = "Map::empty()"
        return f"""pub open spec fn {func_name}(cols: &Cols, {idx_var}: int) -> {ret_type}
    recommends
        0 <= {idx_var} && {idx_var} <= cols.n,
        valid_cols(cols),
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
                f"let tail = {func_name}(cols, {idx_var} + 1);\n"
                f"        if {cond} {{\n"
                f"            let t = {term};\n"
                f"            if t < tail {{ t }} else {{ tail }}\n"
                f"        }} else {{ tail }}"
            )
        else:
            body_inner = (
                f"let tail = {func_name}(cols, {idx_var} + 1);\n"
                f"        let t = {term};\n"
                f"        if t < tail {{ t }} else {{ tail }}"
            )
    elif agg == "MAX":
        base_val = "0u64"
        if cond:
            body_inner = (
                f"let tail = {func_name}(cols, {idx_var} + 1);\n"
                f"        if {cond} {{\n"
                f"            let t = {term};\n"
                f"            if t > tail {{ t }} else {{ tail }}\n"
                f"        }} else {{ tail }}"
            )
        else:
            body_inner = (
                f"let tail = {func_name}(cols, {idx_var} + 1);\n"
                f"        let t = {term};\n"
                f"        if t > tail {{ t }} else {{ tail }}"
            )
    elif cond:
        body_inner = (
            f"if {cond} {{ ({func_name}(cols, {idx_var} + 1) as int + {term} as int) as u64 }}"
            f" else {{ {func_name}(cols, {idx_var} + 1) }}"
        )
        base_val = "0u64"
    else:
        body_inner = (
            f"({func_name}(cols, {idx_var} + 1) as int + {term} as int) as u64"
        )
        base_val = "0u64"

    return f"""pub open spec fn {func_name}(cols: &Cols, {idx_var}: int) -> {ret_type}
    recommends
        0 <= {idx_var} && {idx_var} <= cols.n,
        valid_cols(cols),
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
) -> str:
    parts: list[str] = []
    for table, cols in multi_schema.items():
        if table not in query.tables:
            continue
        struct = _table_struct_name(table)
        parts.append(generate_cols_rs(cols, groupby_columns=query.groupby_columns, struct_name=struct))
        parts.append(emit_valid_cols_predicate(cols, struct_name=struct).replace(
            "valid_cols", f"valid_cols_{table}"
        ))
    return "\n\n".join(parts)


def _having_closure_types(query: SQLQuery, flat_schema: dict[str, str]) -> tuple[str, str]:
    if len(query.groupby_columns) == 1:
        key_ty = spec_map_key_type(flat_schema[query.groupby_columns[0]])
    else:
        parts = ", ".join(
            spec_map_key_type(flat_schema[c]) for c in query.groupby_columns
        )
        key_ty = f"({parts})"
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


def _emit_projection_spec(query: SQLQuery, flat_schema: dict[str, str]) -> tuple[str, str, str]:
    src_match = re.match(r"row\.([A-Za-z_][A-Za-z0-9_]*)", query.projection_exprs[0])
    src_col = src_match.group(1) if src_match else query.projection_columns[0]
    col_type = flat_schema.get(src_col) or flat_schema.get(query.projection_columns[0], "int")
    rust_ty = get_rust_type(src_col, col_type)
    if query.distinct:
        ret_type = f"Set<{rust_ty}>"
        helper = """// TRUSTED axiom: DISTINCT projection fold not yet recursive.
#[verifier::external_body]
pub open spec fn projection_distinct_helper(cols: &Cols, k: int) -> Set<u32> {
    arbitrary()
}"""
        spec_body = "projection_distinct_helper(cols, 0)"
    else:
        ret_type = f"Seq<{rust_ty}>"
        helper = """// TRUSTED axiom: projection fold not yet recursive.
#[verifier::external_body]
pub open spec fn projection_helper(cols: &Cols, k: int) -> Seq<u32> {
    arbitrary()
}"""
        spec_body = "projection_helper(cols, 0)"
    spec_fn = f"""pub open spec fn method_spec(cols: &Cols) -> {ret_type}
    recommends valid_cols(cols),
{{
    {spec_body}
}}"""
    return helper, spec_fn, ret_type


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
    return f"""// ORDER BY ({order_cols}), LIMIT {limit_s}, OFFSET {offset_s}
// TRUSTED axiom: sort/limit on multi-row results not yet defined.
#[verifier::external_body]
pub open spec fn method_spec_result(cols: &Cols) -> Seq<{row_ty}> {{
    arbitrary()
}}

"""


def _emit_set_op_helpers(
    query: SQLQuery,
    flat_schema: dict[str, str],
    *,
    op: str,
) -> tuple[str, str, str]:
    """Emit INTERSECT / EXCEPT / UNION composition over two branch specs."""
    branch_query = query.union_query or query.intersect_query or query.except_query
    assert branch_query is not None
    left_helpers, _, left_ret = _emit_single_table_spec(
        query, flat_schema, helper_name=f"{op}_left_helper"
    )
    right_helpers, _, right_ret = _emit_single_table_spec(
        branch_query, flat_schema, helper_name=f"{op}_right_helper"
    )
    if op == "union":
        mode = "union_all" if query.union_all else "union_distinct"
    elif op == "intersect":
        mode = "intersect_all" if query.intersect_all else "intersect_distinct"
    else:
        mode = "except_all" if query.except_all else "except_distinct"
    helpers = left_helpers + "\n\n" + right_helpers + f"""

// TRUSTED axiom: {op.upper()} branch specs composed without proved recursion.
#[verifier::external_body]
pub open spec fn {op}_left_branch(cols: &Cols) -> {left_ret} {{
    arbitrary()
}}

#[verifier::external_body]
pub open spec fn {op}_right_branch(cols: &Cols) -> {right_ret} {{
    arbitrary()
}}

#[verifier::external_body]
pub open spec fn {mode}_compose(left: {left_ret}, right: {right_ret}) -> Seq<u64> {{
    arbitrary()
}}
"""
    ret_type = "Seq<u64>"
    spec_fn = f"""pub open spec fn method_spec(cols: &Cols) -> {ret_type}
    recommends valid_cols(cols),
{{
    {mode}_compose({op}_left_branch(cols), {op}_right_branch(cols))
}}"""
    return helpers, spec_fn, ret_type


def _emit_union_helpers(query: SQLQuery, flat_schema: dict[str, str]) -> tuple[str, str, str]:
    """Emit UNION / UNION ALL composition over two branch specs."""
    return _emit_set_op_helpers(query, flat_schema, op="union")


def _emit_single_table_spec(
    query: SQLQuery,
    flat_schema: dict[str, str],
    *,
    helper_name: str = "method_spec_helper",
) -> tuple[str, str, str]:
    """Return (helpers, spec_fn, ret_type)."""
    extra_helpers: list[str] = []

    if query.is_projection:
        return _emit_projection_spec(query, flat_schema)

    if query.agg_type == "SELECT_SUBQUERY":
        ret_type = "u64"
        spec_fn = f"""pub open spec fn method_spec(cols: &Cols) -> {ret_type}
    recommends valid_cols(cols),
{{
    {query.agg_expr}
}}"""
        return "", spec_fn, ret_type

    if query.derived_tables:
        if len(query.derived_tables) != 1:
            raise UnsupportedContractError("only one derived table in FROM is supported.")
        derived = query.derived_tables[0]
        inner = derived.query
        recursive_cte = next(
            (c for c in query.ctes if c.recursive and c.name == derived.alias), None
        )
        if recursive_cte is not None or inner.union_query is not None:
            inner_helpers = ""
            if recursive_cte is not None:
                inner_helpers = emit_recursive_cte_helper(recursive_cte) + "\n\n"
            inner_helpers += f"""// TRUSTED: outer SUM over derived recursive CTE '{derived.alias}'.
#[verifier::external_body]
pub open spec fn derived_{derived.alias}_outer_spec(cols: &Cols) -> u64 {{
    arbitrary()
}}"""
            spec_body = f"derived_{derived.alias}_outer_spec(cols)"
            ret_type = "u64"
            spec_fn = f"""pub open spec fn method_spec(cols: &Cols) -> {ret_type}
    recommends valid_cols(cols),
{{
    {spec_body}
}}"""
            return inner_helpers, spec_fn, ret_type
        if inner.window_specs:
            win = inner.window_specs[0]
            inner_helpers = emit_window_spec_helper(win)
            inner_helpers += f"""

// TRUSTED: outer SUM over derived window column '{win.alias}'.
#[verifier::external_body]
pub open spec fn derived_{derived.alias}_outer_spec(cols: &Cols) -> u64 {{
    arbitrary()
}}"""
            spec_body = f"derived_{derived.alias}_outer_spec(cols)"
            ret_type = "u64"
            spec_fn = f"""pub open spec fn method_spec(cols: &Cols) -> {ret_type}
    recommends valid_cols(cols),
{{
    {spec_body}
}}"""
            return inner_helpers, spec_fn, ret_type
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
                _build_col_helper("sum_map_helper", query, "k", flat_schema, is_sum=True),
                _build_col_helper("count_map_helper", query, "k", flat_schema, is_sum=False),
            ])
            spec_body = (
                "let sums = sum_map_helper(cols, 0);\n"
                "    let counts = count_map_helper(cols, 0);\n"
                "    sums.filter(|k, _| counts.contains_key(k)).map_values(|k| {\n"
                "        let c = counts[k];\n"
                "        if c == 0 { 0 } else { sums[k] / c }\n"
                "    })"
            )
            ret_type = "Map<_, u64>"
        else:
            helpers = "\n\n".join([
                _build_col_helper("sum_helper", query, "k", flat_schema, is_sum=True),
                _build_col_helper("count_helper", query, "k", flat_schema, is_sum=False),
            ])
            spec_body = (
                "let sum = sum_helper(cols, 0);\n"
                "    let count = count_helper(cols, 0);\n"
                "    if count == 0 { 0 } else { sum / count }"
            )
            ret_type = "u64"
        if query.having_expr:
            extra_helpers.append(_emit_having_helper())
            spec_body = _emit_having_filter(spec_body, query, flat_schema).strip()
        spec_fn = f"""pub open spec fn method_spec(cols: &Cols) -> {ret_type}
    recommends valid_cols(cols),
{{
    {spec_body}
}}"""
        all_helpers = "\n\n".join([helpers] + extra_helpers) if extra_helpers else helpers
        return all_helpers, spec_fn, ret_type

    is_sum = query.agg_type in ("SUM", "MIN", "MAX")
    helpers = _build_col_helper(
        helper_name, query, "k", flat_schema,
        is_sum=is_sum, agg_type=query.agg_type,
    )
    spec_body = f"{helper_name}(cols, 0)"
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

    spec_fn = f"""pub open spec fn method_spec(cols: &Cols) -> {ret_type}
    recommends valid_cols(cols),
{{
    {spec_body}
}}"""
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
        return f"cols.{m.group(1).lower()}[i] as u64"
    m = re.match(
        r"\(row\.([A-Za-z_][A-Za-z0-9_]*) as int\) \* \(row\.([A-Za-z_][A-Za-z0-9_]*) as int\)",
        expr,
    )
    if m:
        a, b = m.group(1).lower(), m.group(2).lower()
        return f"mul_u64_u32(cols.{a}[i] as u64, cols.{b}[i])"
    m = re.match(
        r"\(row\.([A-Za-z_][A-Za-z0-9_]*) as int\) - \(row\.([A-Za-z_][A-Za-z0-9_]*) as int\)",
        expr,
    )
    if m:
        a, b = m.group(1).lower(), m.group(2).lower()
        return f"sub_u64_to_i64(cols.{a}[i] as u64, cols.{b}[i] as u64)"
    # Fallback: strip row. and cast
    return native_u64_term(expr, "i").replace(" as int", "")


def transpile_sql_to_verus(
    sql: str,
    schema: dict[str, str] | dict[str, dict[str, str]],
    *,
    enable_templates: bool = False,
) -> str:
    """Return a complete Verus Rust source string."""
    _validate_schema(schema)
    flat_schema, multi_schema = normalize_schema(schema)
    query = parse_sql(sql, schema)

    is_join = bool(query.joins)
    subquery_blocks: list[str] = []
    for sub in query.scalar_subqueries:
        emitted = emit_scalar_subquery_helper(sub, flat_schema)
        subquery_blocks.append(emitted.helper_source)
    for exists in query.exists_subqueries:
        subquery_blocks.append(emit_exists_subquery_helper(exists, flat_schema))
    for win in query.window_specs:
        subquery_blocks.append(emit_window_spec_helper(win))
    for in_sub in query.in_subqueries:
        subquery_blocks.append(emit_in_subquery_helper(in_sub, flat_schema))
    for cte in query.ctes:
        if cte.recursive:
            if not any(d.alias == cte.name for d in query.derived_tables):
                subquery_blocks.append(emit_recursive_cte_helper(cte))
        else:
            subquery_blocks.append(f"// CTE {cte.name} (non-recursive; inlined in FROM)")
        if not cte.recursive and cte.query.agg_type:
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
        valid_cols = emit_valid_cols_predicate(flat_schema)
        accessor_lemmas = emit_valid_cols_accessor_lemmas(flat_schema)
        cols_block = f"{cols_block}\n\n{valid_cols}\n\n{accessor_lemmas}"
        helpers, spec_fn, ret_type = _emit_set_op_helpers(query, flat_schema, op="intersect")
        run_query = emit_run_query_skeleton(query, ret_type)
    elif query.except_query is not None:
        cols_block = generate_cols_rs(
            flat_schema,
            sql_str=sql,
            groupby_columns=query.groupby_columns,
        )
        valid_cols = emit_valid_cols_predicate(flat_schema)
        accessor_lemmas = emit_valid_cols_accessor_lemmas(flat_schema)
        cols_block = f"{cols_block}\n\n{valid_cols}\n\n{accessor_lemmas}"
        helpers, spec_fn, ret_type = _emit_set_op_helpers(query, flat_schema, op="except")
        run_query = emit_run_query_skeleton(query, ret_type)
    elif query.union_query is not None:
        cols_block = generate_cols_rs(
            flat_schema,
            sql_str=sql,
            groupby_columns=query.groupby_columns,
        )
        valid_cols = emit_valid_cols_predicate(flat_schema)
        accessor_lemmas = emit_valid_cols_accessor_lemmas(flat_schema)
        cols_block = f"{cols_block}\n\n{valid_cols}\n\n{accessor_lemmas}"
        helpers, spec_fn, ret_type = _emit_union_helpers(query, flat_schema)
        run_query = emit_run_query_skeleton(query, ret_type)
    elif is_join and multi_schema:
        cols_block = _emit_multi_table_cols(multi_schema, query)
        where_at = to_col_expr(query.where_expr, "li") if query.where_expr else None
        val_type = _agg_value_type(query.agg_expr)
        is_sum = query.agg_type in ("SUM", "AVG", "MIN", "MAX")
        join_helper, spec_fn, ret_type = emit_join_spec_helpers(
            query,
            multi_schema,
            where_expr=where_at,
            agg_expr=query.agg_expr,
            is_sum=is_sum,
            val_type=val_type,
        )
        helpers = join_helper
        run_query = emit_run_query_skeleton(query, ret_type, is_join=True)
    else:
        if is_join:
            raise UnsupportedContractError(
                "INNER JOIN requires multi-table schema dict[table, dict[col, type]]"
            )

        cols_block = generate_cols_rs(
            flat_schema,
            sql_str=sql,
            groupby_columns=query.groupby_columns,
        )
        valid_cols = emit_valid_cols_predicate(flat_schema)
        accessor_lemmas = emit_valid_cols_accessor_lemmas(flat_schema)

        helpers, spec_fn, ret_type = _emit_single_table_spec(query, flat_schema)
        result_spec = _emit_method_spec_result(query, ret_type)

        where_at_k = to_col_expr(query.where_expr, "i") if query.where_expr else None
        if where_at_k:
            where_at_k = re.sub(
                r"cols\.get_(\w+)\(i\)",
                r"cols.\1[i]",
                where_at_k,
            )
        term_at_k = _term_at_i_for_query(query)

        if enable_templates and not query.is_projection:
            run_query = emit_run_query_template(
                query,
                ret_type,
                where_at_i=where_at_k,
                term_at_i=term_at_k,
                agg_push=agg_push,
                agg_push_str=agg_push_str,
            )
        else:
            run_query = emit_run_query_skeleton(
                query,
                ret_type,
                agg_push=agg_push,
                agg_push_str=agg_push_str,
            )

        cols_block = f"{cols_block}\n\n{valid_cols}\n\n{accessor_lemmas}"

    subquery_section = "\n\n".join(subquery_blocks)
    if subquery_section:
        subquery_section = subquery_section + "\n\n"

    return f"""use vstd::prelude::*;
use std::collections::HashMap;

verus! {{

{emit_bound_constants()}

{emit_trusted_prelude()}

{cols_block}

{helpers}

{subquery_section}{spec_fn}

{result_spec}{run_query}

}} // verus!
"""
