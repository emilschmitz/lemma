"""INNER JOIN MethodSpec helper emission."""

from __future__ import annotations

from .parse_sql import SQLQuery, get_rust_type


def _table_struct_name(table: str) -> str:
    return f"Cols_{table}"


def _table_for_col(
    col: str,
    table: str | None,
    left_table: str,
    right_table: str,
    schemas_by_table: dict[str, dict[str, str]],
) -> str:
    if table == right_table:
        return right_table
    if table == left_table:
        return left_table
    col_u = col.upper()
    right_cols = {c.upper() for c in schemas_by_table.get(right_table, {})}
    left_cols = {c.upper() for c in schemas_by_table.get(left_table, {})}
    if col_u in right_cols and col_u not in left_cols:
        return right_table
    if col_u in left_cols:
        return left_table
    if col_u in right_cols:
        return right_table
    return left_table


def _col_access(
    col: str,
    table: str | None,
    left_table: str,
    right_table: str,
    schemas_by_table: dict[str, dict[str, str]],
) -> str:
    field = col.lower()
    tbl = _table_for_col(col, table, left_table, right_table, schemas_by_table)
    side = "right" if tbl == right_table else "left"
    idx = "ri" if side == "right" else "li"
    return f"{side}.{field}[{idx} as int]"


def _resolve_join_row_expr(
    expr: str,
    left_table: str,
    right_table: str,
    schemas_by_table: dict[str, dict[str, str]],
) -> str:
    """Rewrite `row.col` / `(row.col as int)` into left./right. indexed accesses."""
    import re

    stripped = re.sub(
        r"\((row\.[A-Za-z_][A-Za-z0-9_]*) as int\)",
        r"\1",
        expr,
    )

    def repl(m: re.Match[str]) -> str:
        col = m.group(1)
        return _col_access(col, None, left_table, right_table, schemas_by_table)

    return re.sub(r"\brow\.([A-Za-z_][A-Za-z0-9_]*)", repl, stripped)


def _groupby_key_types(
    query: SQLQuery,
    left_table: str,
    right_table: str,
    schemas_by_table: dict[str, dict[str, str]],
) -> str:
    parts: list[str] = []
    for col, tbl in zip(query.groupby_columns, query.groupby_tables, strict=True):
        resolved = _table_for_col(col, tbl, left_table, right_table, schemas_by_table)
        parts.append(get_rust_type(col, schemas_by_table[resolved][col]))
    return ", ".join(parts)


def _emit_join_loop_body(
    *,
    helper_name: str,
    left_struct: str,
    right_struct: str,
    join_cond: str,
    filter_cond: str | None,
    term_at_pair: str,
    ret_type: str,
    key_expr: str | None,
    add_fn: str,
) -> str:
    val_ty = "i64" if add_fn == "add_i64" else "u64"
    map_insert = f"(val as int + ({term_at_pair}) as int) as {val_ty}"
    if key_expr is not None:
        if filter_cond:
            inner = f"""let tail = {helper_name}(left, right, li, ri + 1);
            if {join_cond} {{
                if {filter_cond} {{
                    let key = {key_expr};
                    let val = if tail.contains_key(key) {{ tail[key] }} else {{ 0 }};
                    tail.insert(key, {map_insert})
                }} else {{
                    tail
                }}
            }} else {{
                {helper_name}(left, right, li, ri + 1)
            }}"""
        else:
            inner = f"""let tail = {helper_name}(left, right, li, ri + 1);
            if {join_cond} {{
                let key = {key_expr};
                let val = if tail.contains_key(key) {{ tail[key] }} else {{ 0 }};
                tail.insert(key, {map_insert})
            }} else {{
                {helper_name}(left, right, li, ri + 1)
            }}"""
        loop = f"""if li < left.n {{
        if ri < right.n {{
            {inner}
        }} else {{
            {helper_name}(left, right, li + 1, 0)
        }}
    }} else {{
        Map::empty()
    }}"""
    elif filter_cond:
        loop = f"""if li < left.n {{
        if ri < right.n {{
            if {join_cond} {{
                if {filter_cond} {{
                    ({helper_name}(left, right, li, ri + 1) as int + {term_at_pair} as int) as u64
                }} else {{
                    {helper_name}(left, right, li, ri + 1)
                }}
            }} else {{
                {helper_name}(left, right, li, ri + 1)
            }}
        }} else {{
            {helper_name}(left, right, li + 1, 0)
        }}
    }} else {{
        0u64
    }}"""
    else:
        loop = f"""if li < left.n {{
        if ri < right.n {{
            if {join_cond} {{
                ({helper_name}(left, right, li, ri + 1) as int + {term_at_pair} as int) as u64
            }} else {{
                {helper_name}(left, right, li, ri + 1)
            }}
        }} else {{
            {helper_name}(left, right, li + 1, 0)
        }}
    }} else {{
        0u64
    }}"""

    return f"""pub open spec fn {helper_name}(
    left: &{left_struct},
    right: &{right_struct},
    li: int,
    ri: int,
) -> (res: {ret_type})
    decreases left.n - li, right.n - ri,
{{
    {loop}
}}"""


def emit_join_spec_helpers(
    query: SQLQuery,
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
    agg_expr: str,
    is_sum: bool,
    val_type: str,
) -> tuple[str, str, str]:
    """Emit nested-loop join spec helpers. Returns (helpers, spec_fn, ret_type)."""
    if len(query.tables) < 2:
        raise ValueError("join helpers require at least two tables")

    if len(query.tables) > 2:
        from .dialect_flags import require_trusted

        require_trusted("nway_join")
        structs = [_table_struct_name(t) for t in query.tables]
        params = ", ".join(f"{t}: &{structs[i]}" for i, t in enumerate(query.tables))
        val_type = val_type if query.groupby_columns else val_type
        helper = f"""// N-way JOIN: TRUSTED left-deep nested-loop reference ({len(query.tables)} tables).
#[verifier::external_body]
pub open spec fn nway_join_method_spec_helper(
    {", ".join(f"{query.tables[i]}: &{structs[i]}" for i in range(len(query.tables)))},
) -> {val_type} {{
    arbitrary()
}}"""
        spec_fn = f"""pub open spec fn method_spec(
    {", ".join(f"{query.tables[i]}: &{structs[i]}" for i in range(len(query.tables)))},
) -> {val_type}
    recommends
        {", ".join(f"valid_cols_{query.tables[i]}({query.tables[i]})" for i in range(len(query.tables)))},
{{
    nway_join_method_spec_helper({", ".join(query.tables)})
}}"""
        return helper, spec_fn, val_type

    left_table = query.tables[0]
    right_table = query.tables[1]
    left_struct = _table_struct_name(left_table)
    right_struct = _table_struct_name(right_table)
    join_kind = query.joins[0].join_type if query.joins else "INNER"
    is_left = join_kind == "LEFT"

    join_conds = []
    if join_kind != "CROSS":
        for left_col, right_col in query.joins[0].on_equalities:
            lf = left_col.split(".")[-1].lower()
            rf = right_col.split(".")[-1].lower()
            join_conds.append(f"left.{lf}[li as int] == right.{rf}[ri as int]")
    join_cond = " && ".join(join_conds) if join_conds else "true"

    if join_kind in ("FULL", "CROSS", "SEMI", "ANTI"):
        comment = f"// {join_kind} JOIN: TRUSTED nested-loop reference.\n"
        if query.groupby_columns:
            key_types = _groupby_key_types(query, left_table, right_table, schemas_by_table)
            map_ret = f"Map<({key_types}), {val_type}>"
            helper = comment + f"""#[verifier::external_body]
pub open spec fn {join_kind.lower()}_join_method_spec_helper(
    left: &{left_struct},
    right: &{right_struct},
) -> {map_ret} {{
    arbitrary()
}}"""
            spec_body = f"{join_kind.lower()}_join_method_spec_helper(left, right)"
            ret_type = map_ret
        else:
            helper = comment + f"""#[verifier::external_body]
pub open spec fn {join_kind.lower()}_join_method_spec_helper(
    left: &{left_struct},
    right: &{right_struct},
) -> {val_type} {{
    arbitrary()
}}"""
            spec_body = f"{join_kind.lower()}_join_method_spec_helper(left, right)"
            ret_type = val_type
        spec_fn = f"""pub open spec fn method_spec(left: &{left_struct}, right: &{right_struct}) -> {ret_type}
    recommends
        valid_cols_{left_table}(left),
        valid_cols_{right_table}(right),
{{
    {spec_body}
}}"""
        return helper, spec_fn, ret_type

    if is_sum:
        term_at_pair = _resolve_join_row_expr(
            agg_expr, left_table, right_table, schemas_by_table
        )
    else:
        term_at_pair = "1"
    filter_cond = None
    if where_expr:
        # Prefer raw row.* form; also accept already-rewritten cols.get_* from caller.
        raw = where_expr
        if "cols.get_" in raw:
            import re

            raw = re.sub(
                r"cols\.get_([a-z0-9_]+)\(\w+\)",
                r"row.\1",
                raw,
            )
        filter_cond = _resolve_join_row_expr(
            raw, left_table, right_table, schemas_by_table
        )

    if is_left:
        left_comment = (
            "// LEFT JOIN: unmatched left rows appear with NULL right columns "
            "(Option/sentinel in exec; aggregates skip NULL right cells).\n"
        )
        if query.groupby_columns:
            key_types = _groupby_key_types(query, left_table, right_table, schemas_by_table)
            map_ret = f"Map<({key_types}), {val_type}>"
            helper = left_comment + f"""// TRUSTED axiom: LEFT JOIN group-by fold not yet recursive.
#[verifier::external_body]
pub open spec fn left_join_method_spec_helper(
    left: &{left_struct},
    right: &{right_struct},
) -> {map_ret} {{
    arbitrary()
}}"""
            spec_body = "left_join_method_spec_helper(left, right)"
            ret_type = map_ret
        else:
            helper = left_comment + f"""// TRUSTED axiom: LEFT JOIN group-by fold not yet recursive.
#[verifier::external_body]
pub open spec fn left_join_method_spec_helper(
    left: &{left_struct},
    right: &{right_struct},
) -> {val_type} {{
    arbitrary()
}}"""
            spec_body = "left_join_method_spec_helper(left, right)"
            ret_type = val_type
        spec_fn = f"""pub open spec fn method_spec(left: &{left_struct}, right: &{right_struct}) -> {ret_type}
    recommends
        valid_cols_{left_table}(left),
        valid_cols_{right_table}(right),
{{
    {spec_body}
}}"""
        return helper, spec_fn, ret_type

    if query.groupby_columns:
        key_parts = [
            _col_access(col, tbl, left_table, right_table, schemas_by_table)
            for col, tbl in zip(query.groupby_columns, query.groupby_tables, strict=True)
        ]
        key_types = _groupby_key_types(query, left_table, right_table, schemas_by_table)
        key_expr = f"({', '.join(key_parts)})"
        add_fn = "add_i64" if val_type == "i64" else "add_u64"
        map_ret = f"Map<({key_types}), {val_type}>"

        if query.agg_type == "AVG":
            sum_helper = _emit_join_loop_body(
                helper_name="join_sum_helper",
                left_struct=left_struct,
                right_struct=right_struct,
                join_cond=join_cond,
                filter_cond=filter_cond,
                term_at_pair=term_at_pair,
                ret_type=map_ret,
                key_expr=key_expr,
                add_fn=add_fn,
            )
            count_helper = _emit_join_loop_body(
                helper_name="join_count_helper",
                left_struct=left_struct,
                right_struct=right_struct,
                join_cond=join_cond,
                filter_cond=filter_cond,
                term_at_pair="1",
                ret_type=f"Map<({key_types}), u64>",
                key_expr=key_expr,
                add_fn="add_u64",
            )
            helper = sum_helper + "\n\n" + count_helper
            spec_body = (
                "let sums = join_sum_helper(left, right, 0, 0);\n"
                "    let counts = join_count_helper(left, right, 0, 0);\n"
                "    sums.filter(|k, _| counts.contains_key(k)).map_values(|k| {\n"
                "        let c = counts[k];\n"
                "        if c == 0 { 0 } else { sums[k] / c }\n"
                "    })"
            )
            ret_type = f"Map<({key_types}), u64>"
        else:
            helper = _emit_join_loop_body(
                helper_name="join_method_spec_helper",
                left_struct=left_struct,
                right_struct=right_struct,
                join_cond=join_cond,
                filter_cond=filter_cond,
                term_at_pair=term_at_pair,
                ret_type=map_ret,
                key_expr=key_expr,
                add_fn=add_fn,
            )
            spec_body = "join_method_spec_helper(left, right, 0, 0)"
            ret_type = map_ret
    elif query.agg_type == "AVG":
        sum_helper = _emit_join_loop_body(
            helper_name="join_sum_helper",
            left_struct=left_struct,
            right_struct=right_struct,
            join_cond=join_cond,
            filter_cond=filter_cond,
            term_at_pair=term_at_pair,
            ret_type="u64",
            key_expr=None,
            add_fn="add_u64",
        )
        count_helper = _emit_join_loop_body(
            helper_name="join_count_helper",
            left_struct=left_struct,
            right_struct=right_struct,
            join_cond=join_cond,
            filter_cond=filter_cond,
            term_at_pair="1",
            ret_type="u64",
            key_expr=None,
            add_fn="add_u64",
        )
        helper = sum_helper + "\n\n" + count_helper
        spec_body = (
            "let sum = join_sum_helper(left, right, 0, 0);\n"
            "    let count = join_count_helper(left, right, 0, 0);\n"
            "    if count == 0 { 0 } else { sum / count }"
        )
        ret_type = "u64"
    else:
        helper = _emit_join_loop_body(
            helper_name="join_method_spec_helper",
            left_struct=left_struct,
            right_struct=right_struct,
            join_cond=join_cond,
            filter_cond=filter_cond,
            term_at_pair=term_at_pair,
            ret_type=val_type,
            key_expr=None,
            add_fn="add_u64",
        )
        spec_body = "join_method_spec_helper(left, right, 0, 0)"
        ret_type = val_type

    spec_fn = f"""pub open spec fn method_spec(left: &{left_struct}, right: &{right_struct}) -> {ret_type}
    recommends
        valid_cols_{left_table}(left),
        valid_cols_{right_table}(right),
{{
    {spec_body}
}}"""

    return helper, spec_fn, ret_type
