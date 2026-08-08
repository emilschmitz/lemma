"""JOIN MethodSpec helper emission (2-table, N-way, LEFT anti-join, derived, multi-agg)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parse_sql import AggSpec, DerivedTable, SQLQuery, UnsupportedContractError
from .subqueries import emit_derived_grouped_inner_spec
from .value_bounds import col_verus_type, spec_map_key_type


def _table_struct_name(table: str) -> str:
    return f"Cols_{table}"


@dataclass
class _Slot:
    table: str
    param: str
    idx: str
    struct: str


def _derived_aliases(query: SQLQuery) -> set[str]:
    return {d.alias for d in query.derived_tables}


def _base_tables(query: SQLQuery) -> list[str]:
    derived = _derived_aliases(query)
    return [t for t in query.tables if t not in derived]


def _alias_map(query: SQLQuery) -> dict[str, str]:
    out: dict[str, str] = {}
    for alias, table in query.table_aliases.items():
        out[alias.lower()] = table
    for t in query.tables:
        out[t.lower()] = t
    return out


def _find_table_for_col(
    col: str,
    query: SQLQuery,
    schemas_by_table: dict[str, dict[str, str]],
) -> tuple[str, str]:
    """Resolve unqualified or qualified column to (table, canonical col name)."""
    if "." in col:
        return _schema_for_ref(col, query, schemas_by_table, {})[0:2]
    aliases = _alias_map(query)
    col_l = col.lower()
    for tbl in _base_tables(query):
        schema = schemas_by_table[tbl]
        for k in schema:
            if k.lower() == col_l:
                return tbl, k
    for alias, tbl in aliases.items():
        schema = schemas_by_table.get(tbl, {})
        for k in schema:
            if k.lower() == col_l:
                return tbl, k
    raise UnsupportedContractError(f"column {col!r} not found in join schema")


def _schema_for_ref(
    ref: str,
    query: SQLQuery,
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> tuple[str, str, dict[str, str]]:
    alias, col = ref.split(".")[0].lower(), ref.split(".")[-1]
    aliases = _alias_map(query)
    name = aliases.get(alias, alias)
    if name in derived_by_alias:
        d = derived_by_alias[name]
        col_key = col
        for k in d.columns:
            if k.lower() == col.lower():
                col_key = k
                break
        return name, col_key, d.columns
    schema = schemas_by_table[name]
    col_key = col
    for k in schema:
        if k.lower() == col.lower():
            col_key = k
            break
    return name, col_key, schema


def _slot_index(slots: list[_Slot], table: str) -> int:
    for i, s in enumerate(slots):
        if s.table == table:
            return i
    raise KeyError(table)


def _col_access_ref(
    ref: str,
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> str:
    table, col, schema = _schema_for_ref(ref, query, schemas_by_table, derived_by_alias)
    if table in derived_by_alias:
        raise UnsupportedContractError(
            f"direct derived column access {ref!r} must go through map lookup"
        )
    slot = slots[_slot_index(slots, table)]
    field = col.lower()
    if col_verus_type(schema[col]) == "String":
        return f"{slot.param}.{field}[{slot.idx} as int]@"
    return f"{slot.param}.{field}[{slot.idx} as int]"


def _resolve_row_expr(
    expr: str,
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> str:
    stripped = re.sub(
        r"\((row\.[A-Za-z_][A-Za-z0-9_]*) as int\)",
        r"\1",
        expr,
    )

    def repl_col(m: re.Match[str]) -> str:
        col = m.group(1)
        for slot in slots:
            schema = schemas_by_table[slot.table]
            for k in schema:
                if k.lower() == col.lower():
                    if col_verus_type(schema[k]) == "String":
                        return f"{slot.param}.{col.lower()}[{slot.idx} as int]@"
                    return f"{slot.param}.{col.lower()}[{slot.idx} as int]"
        return f"row.{col}"

    out = re.sub(r"\brow\.([A-Za-z_][A-Za-z0-9_]*)", repl_col, stripped)
    return out


def _join_equalities_expr(
    equalities: list[tuple[str, str]],
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    derived_map_vars: dict[str, str],
) -> str:
    parts: list[str] = []
    derived = _derived_aliases(query)
    for left_ref, right_ref in equalities:
        r_alias = right_ref.split(".")[0].lower()
        if r_alias in {a.lower() for a in derived}:
            d = derived_by_alias[next(a for a in derived if a.lower() == r_alias)]
            map_var = derived_map_vars[d.alias]
            r_col = right_ref.split(".")[-1].lower()
            l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, derived_by_alias)
            if r_col in {c.lower() for c in d.query.groupby_columns}:
                continue
            parts.append(f"{map_var}[key] == {l_expr}")
        else:
            l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, derived_by_alias)
            r_expr = _col_access_ref(right_ref, query, slots, schemas_by_table, derived_by_alias)
            parts.append(f"{l_expr} == {r_expr}")
    return " && ".join(parts) if parts else "true"


def _derived_key_expr(
    join: list[tuple[str, str]],
    derived: DerivedTable,
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> str:
    key_parts: list[str] = []
    gb_lower = {c.lower() for c in derived.query.groupby_columns}
    for left_ref, right_ref in join:
        r_alias = right_ref.split(".")[0].lower()
        if r_alias != derived.alias.lower():
            continue
        r_col = right_ref.split(".")[-1].lower()
        if r_col in gb_lower:
            key_parts.append(
                _col_access_ref(left_ref, query, slots, schemas_by_table, derived_by_alias)
            )
    if not key_parts:
        raise UnsupportedContractError(
            f"derived join {derived.alias} missing group-key equalities"
        )
    if len(key_parts) == 1:
        return key_parts[0]
    return f"({', '.join(key_parts)})"


def _all_join_conds(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    derived_map_vars: dict[str, str],
) -> tuple[str, dict[str, str]]:
    """Return (combined_cond, derived_alias -> key_expr for map lookup)."""
    base_parts: list[str] = []
    derived_keys: dict[str, str] = {}
    for join in query.joins:
        jtable = join.table
        if jtable in derived_by_alias:
            d = derived_by_alias[jtable]
            map_var = derived_map_vars[d.alias]
            key_expr = _derived_key_expr(
                join.on_equalities, d, query, slots, schemas_by_table, derived_by_alias,
            )
            derived_keys[d.alias] = key_expr
            val_part = _join_equalities_expr(
                join.on_equalities, query, slots, schemas_by_table,
                derived_by_alias, derived_map_vars,
            )
            base_parts.append(f"{map_var}.contains_key({key_expr})")
            if val_part != "true":
                base_parts.append(val_part)
        else:
            part = _join_equalities_expr(
                join.on_equalities, query, slots, schemas_by_table,
                derived_by_alias, derived_map_vars,
            )
            if part != "true":
                base_parts.append(part)
    cond = " && ".join(base_parts) if base_parts else "true"
    return cond, derived_keys


def _strip_anti_join_predicates(expr: str | None) -> tuple[str | None, bool]:
    if not expr:
        return None, False
    is_anti = "left_join_miss_generic" in expr
    out = expr
    out = re.sub(r"\s*&&\s*left_join_miss_generic\(cols,\s*0\)", "", out)
    out = re.sub(r"left_join_miss_generic\(cols,\s*0\)\s*&&\s*", "", out)
    out = re.sub(r"!\s*left_join_miss_generic\(cols,\s*0\)", "false", out)
    out = out.strip()
    if out in ("", "true"):
        return None, is_anti
    return out, is_anti


def _groupby_key_parts(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> tuple[str, str]:
    parts: list[str] = []
    types: list[str] = []
    aliases = _alias_map(query)
    for col, tbl in zip(query.groupby_columns, query.groupby_tables, strict=True):
        table = aliases.get((tbl or "").lower(), tbl) if tbl else None
        if table is None:
            for slot in slots:
                if col.lower() in {c.lower() for c in schemas_by_table[slot.table]}:
                    table = slot.table
                    break
        if table is None:
            table = slots[0].table
        schema = (
            derived_by_alias[table].columns
            if table in derived_by_alias
            else schemas_by_table[table]
        )
        col_key = col
        for k in schema:
            if k.lower() == col.lower():
                col_key = k
                break
        slot = slots[_slot_index(slots, table)] if table not in derived_by_alias else slots[0]
        if table not in derived_by_alias:
            if col_verus_type(schema[col_key]) == "String":
                parts.append(f"{slot.param}.{col_key.lower()}[{slot.idx} as int]@")
            else:
                parts.append(f"{slot.param}.{col_key.lower()}[{slot.idx} as int]")
        types.append(spec_map_key_type(schema[col_key]))
    key_expr = parts[0] if len(parts) == 1 else f"({', '.join(parts)})"
    key_ty = types[0] if len(types) == 1 else f"({', '.join(types)})"
    return key_expr, key_ty


def _emit_match_helper(
    left_slot: _Slot,
    right_slot: _Slot,
    join_conds: str,
    helper_name: str = "join_right_match_helper",
) -> str:
    return f"""pub open spec fn {helper_name}(
    {left_slot.param}: &{left_slot.struct},
    {right_slot.param}: &{right_slot.struct},
    li: int,
    ri: int,
) -> (res: bool)
    decreases {right_slot.param}.n - ri,
{{
    if ri < {right_slot.param}.n {{
        if {join_conds} {{
            true
        }} else {{
            {helper_name}({left_slot.param}, {right_slot.param}, li, ri + 1)
        }}
    }} else {{
        false
    }}
}}"""


def _nested_loop_signature(slots: list[_Slot], extra_params: list[tuple[str, str]] | None = None) -> str:
    params = [f"{s.param}: &{s.struct}" for s in slots]
    if extra_params:
        params.extend(f"{n}: {t}" for n, t in extra_params)
    params.extend(f"{s.idx}: int" for s in slots)
    return ", ".join(params)


def _nested_loop_decreases(slots: list[_Slot]) -> str:
    return ", ".join(f"{s.param}.n - {s.idx}" for s in slots)


def _init_indices(slots: list[_Slot]) -> str:
    return ", ".join("0" for _ in slots)


def _gen_nested_loop(
    helper_name: str,
    slots: list[_Slot],
    *,
    join_cond: str,
    filter_cond: str | None,
    update_expr: str,
    ret_type: str,
    ret_base: str,
    extra_params: list[tuple[str, str]] | None = None,
) -> str:
    n = len(slots)
    extra_args = ", ".join(n for n, _ in (extra_params or []))
    cond_parts = [join_cond]
    if filter_cond:
        cond_parts.append(filter_cond)
    full_cond = " && ".join(f"({p})" for p in cond_parts)

    if n == 1:
        s = slots[0]
        if filter_cond:
            body = f"""if {s.idx} < {s.param}.n {{
        let tail = {helper_name}({s.param}, {s.idx} + 1);
        if {full_cond} {{
            {update_expr}
        }} else {{
            tail
        }}
    }} else {{
        {ret_base}
    }}"""
        else:
            body = f"""if {s.idx} < {s.param}.n {{
        let tail = {helper_name}({s.param}, {s.idx} + 1);
        if {join_cond} {{
            {update_expr}
        }} else {{
            tail
        }}
    }} else {{
        {ret_base}
    }}"""
        sig = f"{s.param}: &{s.struct}, {s.idx}: int"
        dec = f"{s.param}.n - {s.idx}"
        return f"""pub open spec fn {helper_name}({sig}) -> (res: {ret_type})
    decreases {dec},
{{
    {body}
}}"""

    def emit_level(level: int, indent: str) -> str:
        s = slots[level]
        if level == n - 1:
            idx_args = ", ".join(
                f"{slots[i].idx} + 1" if i == level else slots[i].idx for i in range(n)
            )
            call = f"{helper_name}({', '.join(x.param for x in slots)}{', ' + extra_args if extra_args else ''}, {idx_args})"
            return (
                f"{indent}if {s.idx} < {s.param}.n {{\n"
                f"{indent}    let tail = {call};\n"
                f"{indent}    if {full_cond} {{\n"
                f"{indent}        {update_expr}\n"
                f"{indent}    }} else {{\n"
                f"{indent}        {call}\n"
                f"{indent}    }}\n"
                f"{indent}}} else {{\n"
                f"{indent}    {ret_base}\n"
                f"{indent}}}"
            )
        next_indent = indent + "    "
        inner = emit_level(level + 1, next_indent)
        advance = ", ".join(
            f"{slots[i].idx} + 1" if i == level else ("0" if i > level else slots[i].idx)
            for i in range(n)
        )
        call = f"{helper_name}({', '.join(x.param for x in slots)}{', ' + extra_args if extra_args else ''}, {advance})"
        return (
            f"{indent}if {s.idx} < {s.param}.n {{\n"
            f"{inner}\n"
            f"{indent}}} else {{\n"
            f"{indent}    {call if level < n - 1 else ret_base}\n"
            f"{indent}}}"
        )

    body = emit_level(0, "    ")
    sig = _nested_loop_signature(slots, extra_params)
    dec = _nested_loop_decreases(slots)
    return f"""pub open spec fn {helper_name}({sig}) -> (res: {ret_type})
    decreases {dec},
{{
{body}
}}"""


def _distinct_val_expr(
    spec: AggSpec,
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> str:
    if "." in spec.agg_column:
        col = spec.agg_column.split(".")[-1]
        tbl = spec.agg_column.split(".")[0]
        aliases = _alias_map(query)
        table = aliases.get(tbl.lower(), tbl)
    else:
        table, col = _find_table_for_col(spec.agg_column, query, schemas_by_table)
    schema = schemas_by_table[table]
    col_key = col
    for k in schema:
        if k.lower() == col.lower():
            col_key = k
            break
    slot = slots[_slot_index(slots, table)]
    if col_verus_type(schema[col_key]) == "String":
        return f"{slot.param}.{col_key.lower()}[{slot.idx} as int]@"
    return f"{slot.param}.{col_key.lower()}[{slot.idx} as int]"


def _agg_term_expr(
    spec: AggSpec,
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> str:
    if spec.agg_type == "COUNT":
        return "1"
    expr = spec.agg_expr or f"row.{spec.agg_column.split('.')[-1]}"
    return _resolve_row_expr(expr, query, slots, schemas_by_table, derived_by_alias)


def _emit_join_multi_agg(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    derived_map_vars: dict[str, str],
    *,
    where_expr: str | None,
    helper_name: str = "multi_agg_helper",
) -> tuple[str, str, str]:
    from .parse_sql import _agg_value_type

    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_cond = (
        _resolve_row_expr(filter_raw, query, slots, schemas_by_table, derived_by_alias)
        if filter_raw
        else None
    )
    join_cond, _ = _all_join_conds(
        query, slots, schemas_by_table, derived_by_alias, derived_map_vars,
    )
    key_expr, key_ty = _groupby_key_parts(query, slots, schemas_by_table, derived_by_alias)

    state_types: list[str] = []
    state_defaults: list[str] = []
    update_stmts: list[tuple[int, str]] = []
    project_parts: list[str] = []

    for spec in query.agg_specs:
        pos = len(state_types)
        if spec.agg_type == "COUNT":
            state_types.append("u64")
            state_defaults.append("0u64")
            update_stmts.append((pos, f"let s{pos} = (prev.{pos} as int + 1) as u64;"))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "SUM":
            val_type = _agg_value_type(spec.agg_expr)
            state_types.append(val_type)
            state_defaults.append(f"0{val_type}")
            term = _agg_term_expr(spec, query, slots, schemas_by_table, derived_by_alias)
            update_stmts.append((
                pos,
                f"let s{pos} = (prev.{pos} as int + {term} as int) as {val_type};",
            ))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "AVG":
            sum_pos = len(state_types)
            state_types.extend(["u64", "u64"])
            state_defaults.extend(["0u64", "0u64"])
            term = _agg_term_expr(spec, query, slots, schemas_by_table, derived_by_alias)
            update_stmts.append((
                sum_pos,
                f"let s{sum_pos} = (prev.{sum_pos} as int + {term} as int) as u64;\n"
                f"            let s{sum_pos + 1} = (prev.{sum_pos + 1} as int + 1) as u64;",
            ))
            project_parts.append(
                f"if s{sum_pos + 1} == 0 {{ 0 }} else {{ s{sum_pos} / s{sum_pos + 1} }}"
            )
        elif spec.agg_type == "COUNT_DISTINCT":
            table, col_key = _find_table_for_col(
                spec.agg_column, query, schemas_by_table,
            )
            schema = schemas_by_table[table]
            val_ty = spec_map_key_type(schema[col_key])
            state_types.append(f"Map<{val_ty}, bool>")
            state_defaults.append("Map::empty()")
            val_expr = _distinct_val_expr(
                spec, query, slots, schemas_by_table, derived_by_alias,
            )
            update_stmts.append((
                pos,
                f"let s{pos} = if prev.{pos}.contains_key({val_expr}) {{ prev.{pos} }} "
                f"else {{ prev.{pos}.insert({val_expr}, true) }};",
            ))
            project_parts.append(f"s{pos}.dom().len() as u64")
        else:
            raise UnsupportedContractError(
                f"multi-agg join unsupported aggregate {spec.agg_type!r}"
            )

    n_state = len(state_types)
    if n_state == 1:
        state_tuple_type = state_types[0]
        default_state = state_defaults[0]
        rebuild = "s0"
    else:
        state_tuple_type = f"({', '.join(state_types)})"
        default_state = f"({', '.join(state_defaults)})"
        rebuild = f"({', '.join(f's{i}' for i in range(n_state))})"

    if n_state == 1:
        rendered = "\n            ".join(tmpl.replace("prev.0", "prev") for _, tmpl in update_stmts)
    else:
        rendered = "\n            ".join(tmpl for _, tmpl in update_stmts)
    if n_state == 1:
        update_expr = (
            f"let key = {key_expr};\n"
            f"            let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {default_state} }};\n"
            f"            {rendered}\n"
            f"            tail.insert(key, {rebuild})"
        )
    else:
        update_expr = (
            f"let key = {key_expr};\n"
            f"            let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {default_state} }};\n"
            f"            {rendered}\n"
            f"            tail.insert(key, {rebuild})"
        )

    if len(project_parts) == 1:
        project_expr = project_parts[0]
    else:
        project_expr = f"({', '.join(project_parts)})"

    val_types: list[str] = []
    for spec in query.agg_specs:
        if spec.agg_type in ("SUM", "COUNT", "COUNT_DISTINCT", "AVG"):
            from .parse_sql import _agg_value_type
            val_types.append(_agg_value_type(spec.agg_expr))
        else:
            val_types.append("u64")
    ret_val_ty = val_types[0] if len(val_types) == 1 else f"({', '.join(val_types)})"
    map_ret = f"Map<{key_ty}, {state_tuple_type}>"
    ret_type = f"Map<{key_ty}, {ret_val_ty}>"

    helper = _gen_nested_loop(
        helper_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=update_expr,
        ret_type=map_ret,
        ret_base="Map::empty()",
        extra_params=[(v, "Map<_, _>") for v in derived_map_vars.values()] if derived_map_vars else None,
    )

    spec_body = (
        f"let raw = {helper_name}({', '.join(s.param for s in slots)}"
        f"{', ' + ', '.join(derived_map_vars.values()) if derived_map_vars else ''}"
        f", {_init_indices(slots)});\n"
        f"    raw.map_values(|_k| {project_expr})"
    )
    return helper, spec_body, ret_type


def _having_closure_types(query: SQLQuery, flat_schema: dict[str, str]) -> tuple[str, str]:
    from .parse_sql import _agg_value_type
    if len(query.groupby_columns) == 1:
        key_ty = spec_map_key_type(flat_schema[query.groupby_columns[0]])
    else:
        parts = ", ".join(
            spec_map_key_type(flat_schema[c]) for c in query.groupby_columns
        )
        key_ty = f"({parts})"
    val_types: list[str] = []
    for spec in query.agg_specs:
        if spec.agg_type in ("SUM", "COUNT", "COUNT_DISTINCT", "AVG"):
            val_types.append(_agg_value_type(spec.agg_expr))
        else:
            val_types.append("u64")
    val_ty = val_types[0] if len(val_types) == 1 else f"({', '.join(val_types)})"
    return key_ty, val_ty


def _multi_agg_tuple_type(query: SQLQuery) -> str:
    from .parse_sql import _agg_value_type
    types: list[str] = []
    for spec in query.agg_specs:
        if spec.agg_type in ("SUM", "COUNT", "COUNT_DISTINCT", "AVG"):
            types.append(_agg_value_type(spec.agg_expr))
        else:
            types.append("u64")
    if len(types) == 1:
        return types[0]
    return f"({', '.join(types)})"


def _emit_having_helper() -> str:
    return """pub open spec fn apply_having_filter<K, V>(m: Map<K, V>, pred: spec_fn(K, V) -> bool) -> Map<K, V> {
    m.filter_keys(|k| pred(k, m[k]))
}"""


def _emit_having_filter(spec_body: str, query: SQLQuery, flat_schema: dict[str, str]) -> str:
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


def _emit_left_anti_multi_agg(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
) -> tuple[str, str, str]:
    left, right = slots[0], slots[1]
    join = query.joins[0]
    match_parts: list[str] = []
    for left_ref, right_ref in join.on_equalities:
        l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, {})
        r_col = _col_access_ref(right_ref, query, slots, schemas_by_table, {})
        r_expr = r_col.replace(f"{right.idx} as int", "rj as int")
        l_expr = l_expr.replace(f"{left.idx} as int", "li as int")
        match_parts.append(f"{l_expr} == {r_expr}")
    match_conds = " && ".join(match_parts)
    match_helper = _emit_match_helper(left, right, match_conds)

    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_cond = (
        _resolve_row_expr(filter_raw, query, [left], schemas_by_table, {})
        if filter_raw
        else None
    )
    key_expr, key_ty = _groupby_key_parts(query, slots, schemas_by_table, {})

    state_types: list[str] = []
    state_defaults: list[str] = []
    update_stmts: list[str] = []
    project_parts: list[str] = []

    specs = query.agg_specs if query.agg_specs else [
        AggSpec(query.agg_type, query.agg_column, query.agg_expr, ""),
    ]
    for i, spec in enumerate(specs):
        if spec.agg_type == "COUNT":
            state_types.append("u64")
            state_defaults.append("0u64")
            prev_ref = "prev" if len(specs) == 1 else f"prev.{i}"
            update_stmts.append(f"let s{i} = ({prev_ref} as int + 1) as u64;")
            project_parts.append(f"s{i}" if len(specs) > 1 else "s0")
        elif spec.agg_type == "SUM":
            from .parse_sql import _agg_value_type
            vt = _agg_value_type(spec.agg_expr)
            state_types.append(vt)
            state_defaults.append(f"0{vt}")
            term = _agg_term_expr(spec, query, [left], schemas_by_table, {})
            prev_ref = "prev" if len(specs) == 1 else f"prev.{i}"
            update_stmts.append(
                f"let s{i} = ({prev_ref} as int + {term} as int) as {vt};"
            )
            project_parts.append(f"s{i}" if len(specs) > 1 else "s0")
        elif spec.agg_type in ("MIN", "MAX", "AVG"):
            raise UnsupportedContractError(
                f"LEFT anti-join agg {spec.agg_type!r} not supported"
            )
        else:
            raise UnsupportedContractError(
                f"LEFT anti-join multi-agg {spec.agg_type!r} not supported"
            )

    n_state = len(state_types)
    state_tuple_type = state_types[0] if n_state == 1 else f"({', '.join(state_types)})"
    default_state = state_defaults[0] if n_state == 1 else f"({', '.join(state_defaults)})"
    rebuild = "s0" if n_state == 1 else f"({', '.join(f's{i}' for i in range(n_state))})"
    if n_state == 1:
        rendered = update_stmts[0]
    else:
        rendered = "\n            ".join(update_stmts)
    if n_state == 1 and len(project_parts) == 1 and project_parts[0] == "s0":
        project_parts = ["s0"]

    filter_part = f" && {filter_cond}" if filter_cond else ""
    update_body = (
        f"let key = {key_expr};\n"
        f"            let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {default_state} }};\n"
        f"            {rendered}\n"
        f"            tail.insert(key, {rebuild})"
    )

    helper_name = "join_anti_multi_agg_helper"
    helper = f"""pub open spec fn {helper_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    li: int,
) -> (res: Map<{key_ty}, {state_tuple_type}>)
    decreases {left.param}.n - li,
{{
    if li < {left.param}.n {{
        let tail = {helper_name}({left.param}, {right.param}, li + 1);
        if !join_right_match_helper({left.param}, {right.param}, li, 0){filter_part} {{
            {update_body}
        }} else {{
            tail
        }}
    }} else {{
        Map::empty()
    }}
}}"""

    project_expr = project_parts[0] if len(project_parts) == 1 else f"({', '.join(project_parts)})"
    if n_state == 1 and not query.is_multi_agg:
        ret_type = f"Map<{key_ty}, u64>"
        spec_body = (
            f"let raw = {helper_name}({left.param}, {right.param}, 0);\n"
            f"    raw"
        )
    else:
        ret_type = f"Map<{key_ty}, {_multi_agg_tuple_type(query)}>"
        spec_body = (
            f"let raw = {helper_name}({left.param}, {right.param}, 0);\n"
            f"    raw.map_values(|_k| {project_expr})"
        )
    return match_helper + "\n\n" + helper, spec_body, ret_type


def _emit_join_projection(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    derived_map_vars: dict[str, str],
    *,
    where_expr: str | None,
) -> tuple[str, str, str]:
    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_cond = (
        _resolve_row_expr(filter_raw, query, slots, schemas_by_table, derived_by_alias)
        if filter_raw
        else None
    )
    join_cond, _ = _all_join_conds(
        query, slots, schemas_by_table, derived_by_alias, derived_map_vars,
    )

    row_parts: list[str] = []
    row_types: list[str] = []
    for col, expr in zip(query.projection_columns, query.projection_exprs, strict=True):
        resolved = _resolve_row_expr(expr, query, slots, schemas_by_table, derived_by_alias)
        row_parts.append(resolved)
        tbl = query.table_aliases.get(col, col)
        for slot in slots:
            if slot.table == tbl or col in schemas_by_table.get(slot.table, {}):
                schema = schemas_by_table[slot.table]
                for k in schema:
                    if k.lower() == col.lower():
                        row_types.append(spec_map_key_type(schema[k]))
                        break
                break
        else:
            for slot in slots:
                schema = schemas_by_table[slot.table]
                for k, v in schema.items():
                    if expr.endswith(k) or col.lower() == k.lower():
                        row_types.append(spec_map_key_type(v))
                        break

    if len(row_parts) == 1:
        row_expr = row_parts[0]
        row_ty = row_types[0] if row_types else "u64"
    else:
        row_expr = f"({', '.join(row_parts)})"
        row_ty = f"({', '.join(row_types)})" if row_types else "(u64, u64, u64)"

    update_expr = f"tail.push({row_expr})"
    helper_name = "join_projection_helper"
    helper = _gen_nested_loop(
        helper_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=update_expr,
        ret_type=f"Seq<{row_ty}>",
        ret_base="Seq::empty()",
        extra_params=[(v, t) for v, t in zip(derived_map_vars.values(), ["Map<_, _>"] * len(derived_map_vars))] if derived_map_vars else None,
    )

    ret_type = f"Seq<{row_ty}>"
    init_args = ", ".join(
        [*(s.param for s in slots)]
        + list(derived_map_vars.values())
        + [_init_indices(slots)]
    )
    spec_body = f"{helper_name}({init_args})"
    if query.limit is not None:
        spec_body = f"spec_seq_take({spec_body}, {query.limit})"
    return helper, spec_body, ret_type


def _raw_join_equalities(
    equalities: list[tuple[str, str]],
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    derived_map_vars: dict[str, str],
    query: SQLQuery,
) -> str:
    parts: list[str] = []
    derived = _derived_aliases(query)
    for left_ref, right_ref in equalities:
        r_alias = right_ref.split(".")[0].lower()
        if r_alias in {a.lower() for a in derived}:
            d = derived_by_alias[next(a for a in derived if a.lower() == r_alias)]
            map_var = derived_map_vars[d.alias]
            r_col = right_ref.split(".")[-1].lower()
            l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, derived_by_alias)
            if r_col in {c.lower() for c in d.query.groupby_columns}:
                continue
            parts.append(f"{map_var}[key] == {l_expr}")
        else:
            l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, derived_by_alias)
            r_expr = _col_access_ref(right_ref, query, slots, schemas_by_table, derived_by_alias)
            parts.append(f"{l_expr} == {r_expr}")
    return " && ".join(parts) if parts else "true"


def _emit_full_outer_scalar_sum(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    derived_map_vars: dict[str, str],
    *,
    where_expr: str | None,
    agg_expr: str,
    val_type: str,
) -> tuple[str, str, str]:
    """FULL OUTER JOIN scalar SUM: matched pairs + unmatched left rows."""
    if len(slots) != 2:
        raise UnsupportedContractError("FULL OUTER JOIN spec supports exactly two tables")
    left, right = slots[0], slots[1]
    join = query.joins[0]
    match_parts: list[str] = []
    for left_ref, right_ref in join.on_equalities:
        l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, derived_by_alias)
        r_expr = _col_access_ref(right_ref, query, slots, schemas_by_table, derived_by_alias)
        r_expr = r_expr.replace(f"{right.idx} as int", "rj as int")
        l_expr = l_expr.replace(f"{left.idx} as int", "li as int")
        match_parts.append(f"{l_expr} == {r_expr}")
    match_conds = " && ".join(match_parts) if match_parts else "false"
    match_helper = _emit_match_helper(left, right, match_conds)

    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_cond = (
        _resolve_row_expr(filter_raw, query, slots, schemas_by_table, derived_by_alias)
        if filter_raw
        else None
    )
    join_cond = _raw_join_equalities(
        join.on_equalities, slots, schemas_by_table, derived_by_alias, derived_map_vars, query,
    )
    term = _resolve_row_expr(agg_expr, query, slots, schemas_by_table, derived_by_alias)

    matched_helper = "full_join_matched_helper"
    matched_loop = _gen_nested_loop(
        matched_helper,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=f"(tail as int + ({term}) as int) as {val_type}",
        ret_type=val_type,
        ret_base=f"0{val_type}",
        extra_params=[(v, "Map<_, _>") for v in derived_map_vars.values()] if derived_map_vars else None,
    )

    left_only_helper = "full_join_left_unmatched_helper"
    left_slots = [left]
    filter_left = (
        _resolve_row_expr(filter_raw, query, left_slots, schemas_by_table, derived_by_alias)
        if filter_raw
        else None
    )
    term_left = _resolve_row_expr(agg_expr, query, left_slots, schemas_by_table, derived_by_alias)
    left_update = (
        f"if !{match_helper}({left.param}, {right.param}, {left.idx}, 0) {{\n"
        f"            (tail as int + ({term_left}) as int) as {val_type}\n"
        f"        }} else {{\n"
        f"            tail\n"
        f"        }}"
    )
    if filter_left:
        left_body = (
            f"if {left.idx} < {left.param}.n {{\n"
            f"        let tail = {left_only_helper}({left.param}, {right.param}, {left.idx} + 1);\n"
            f"        if {filter_left} {{\n"
            f"            {left_update}\n"
            f"        }} else {{\n"
            f"            tail\n"
            f"        }}\n"
            f"    }} else {{\n"
            f"        0{val_type}\n"
            f"    }}"
        )
    else:
        left_body = (
            f"if {left.idx} < {left.param}.n {{\n"
            f"        let tail = {left_only_helper}({left.param}, {right.param}, {left.idx} + 1);\n"
            f"        {left_update}\n"
            f"    }} else {{\n"
            f"        0{val_type}\n"
            f"    }}"
        )
    left_only = f"""pub open spec fn {left_only_helper}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    {left.idx}: int,
) -> (res: {val_type})
    decreases {left.param}.n - {left.idx},
{{
    {left_body}
}}"""

    init_args = ", ".join(
        [*(s.param for s in slots)]
        + list(derived_map_vars.values())
        + [_init_indices(slots)]
    )
    spec_body = (
        f"let matched = {matched_helper}({init_args});\n"
        f"    let left_only = {left_only_helper}({left.param}, {right.param}, 0);\n"
        f"    (matched as int + left_only as int) as {val_type}"
    )
    helpers = "\n\n".join([match_helper, matched_loop, left_only])
    return helpers, spec_body, val_type


def _emit_single_agg_nway(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    derived_map_vars: dict[str, str],
    *,
    where_expr: str | None,
    agg_expr: str,
    is_sum: bool,
    val_type: str,
) -> tuple[str, str, str]:
    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_cond = (
        _resolve_row_expr(filter_raw, query, slots, schemas_by_table, derived_by_alias)
        if filter_raw
        else None
    )
    join_cond, _ = _all_join_conds(
        query, slots, schemas_by_table, derived_by_alias, derived_map_vars,
    )
    term = (
        _resolve_row_expr(agg_expr, query, slots, schemas_by_table, derived_by_alias)
        if is_sum
        else "1"
    )

    if query.groupby_columns:
        key_expr, key_ty = _groupby_key_parts(
            query, slots, schemas_by_table, derived_by_alias,
        )
        update_expr = (
            f"let key = {key_expr};\n"
            f"            let val = if tail.contains_key(key) {{ tail[key] }} else {{ 0{val_type} }};\n"
            f"            tail.insert(key, (val as int + ({term}) as int) as {val_type})"
        )
        ret_type = f"Map<{key_ty}, {val_type}>"
        ret_base = "Map::empty()"
        helper_name = "join_method_spec_helper"
    else:
        update_expr = f"(tail as int + ({term}) as int) as {val_type}"
        ret_type = val_type
        ret_base = f"0{val_type}"
        helper_name = "join_method_spec_helper"

    helper = _gen_nested_loop(
        helper_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=update_expr,
        ret_type=ret_type,
        ret_base=ret_base,
        extra_params=[(v, "Map<_, _>") for v in derived_map_vars.values()] if derived_map_vars else None,
    )
    init_args = ", ".join(
        [*(s.param for s in slots)]
        + list(derived_map_vars.values())
        + [_init_indices(slots)]
    )
    return helper, f"{helper_name}({init_args})", ret_type


def emit_join_spec_helpers(
    query: SQLQuery,
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
    agg_expr: str,
    is_sum: bool,
    val_type: str,
    flat_schema: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    """Emit nested-loop join spec helpers. Returns (helpers, spec_fn, ret_type)."""
    _ = flat_schema
    if len(query.tables) < 2:
        raise ValueError("join helpers require at least two tables")

    derived_by_alias = {d.alias: d for d in query.derived_tables}
    base = _base_tables(query)
    slots = [
        _Slot(
            table=t,
            param=t,
            idx=f"i{i}",
            struct=_table_struct_name(t),
        )
        for i, t in enumerate(base)
    ]

    join_types = {j.join_type for j in query.joins}
    for jt in join_types:
        if jt in ("SEMI", "ANTI"):
            raise UnsupportedContractError(
                f"{jt} JOIN needs real MethodSpec; not yet supported"
            )
        if jt == "FULL" and (query.groupby_columns or query.is_projection or not is_sum):
            raise UnsupportedContractError(
                "FULL OUTER JOIN group-by / projection needs real MethodSpec; not yet supported"
            )

    derived_helpers: list[str] = []
    derived_map_vars: dict[str, str] = {}
    for d in query.derived_tables:
        if not d.query.groupby_columns:
            raise UnsupportedContractError(
                f"derived JOIN {d.alias} must be grouped"
            )
        src_table = d.query.tables[0] if d.query.tables else base[0]
        src_struct = _table_struct_name(src_table)
        inner_helpers, spec_call, _ = emit_derived_grouped_inner_spec(
            d.alias,
            d.query,
            schemas_by_table[src_table],
            struct_name=src_struct,
        )
        derived_helpers.append(inner_helpers.replace("valid_cols", f"valid_cols_{src_table}"))
        map_var = f"derived_{d.alias}_map"
        derived_map_vars[d.alias] = map_var

    _, is_anti = _strip_anti_join_predicates(where_expr)
    is_left = any(j.join_type == "LEFT" for j in query.joins)

    extra_having = ""
    spec_body: str
    ret_type: str
    helpers: str

    if query.is_projection:
        proj_helper, spec_body, ret_type = _emit_join_projection(
            query, slots, schemas_by_table, derived_by_alias, derived_map_vars,
            where_expr=where_expr,
        )
        helpers = "\n\n".join(derived_helpers + [proj_helper])
    elif query.groupby_columns and is_left and is_anti and len(slots) == 2:
        anti_helper, spec_body, ret_type = _emit_left_anti_multi_agg(
            query, slots, schemas_by_table, where_expr=where_expr,
        )
        helpers = anti_helper
        if query.having_expr:
            extra_having = "\n\n" + _emit_having_helper()
            flat = {}
            for t in base:
                flat.update(schemas_by_table[t])
            spec_body = _emit_having_filter(spec_body, query, flat)
    elif query.is_multi_agg and query.groupby_columns:
        ma_helper, spec_body, ret_type = _emit_join_multi_agg(
            query, slots, schemas_by_table, derived_by_alias, derived_map_vars,
            where_expr=where_expr,
        )
        helpers = "\n\n".join(derived_helpers + [ma_helper])
        if query.having_expr:
            extra_having = "\n\n" + _emit_having_helper()
            flat = {}
            for t in base:
                flat.update(schemas_by_table[t])
            spec_body = _emit_having_filter(spec_body, query, flat)
    elif "FULL" in join_types and not query.groupby_columns:
        full_helpers, spec_body, ret_type = _emit_full_outer_scalar_sum(
            query,
            slots,
            schemas_by_table,
            derived_by_alias,
            derived_map_vars,
            where_expr=where_expr,
            agg_expr=agg_expr,
            val_type=val_type,
        )
        helpers = "\n\n".join(derived_helpers + [full_helpers])
    else:
        loop_helper, spec_body, ret_type = _emit_single_agg_nway(
            query, slots, schemas_by_table, derived_by_alias, derived_map_vars,
            where_expr=where_expr,
            agg_expr=agg_expr,
            is_sum=is_sum,
            val_type=val_type,
        )
        helpers = "\n\n".join(derived_helpers + [loop_helper])
        if query.having_expr:
            extra_having = "\n\n" + _emit_having_helper()
            flat = {}
            for t in base:
                flat.update(schemas_by_table[t])
            spec_body = _emit_having_filter(spec_body, query, flat)

    derived_prelude = ""
    for d in query.derived_tables:
        src_table = d.query.tables[0] if d.query.tables else base[0]
        map_var = derived_map_vars[d.alias]
        derived_prelude += (
            f"    let {map_var} = derived_{d.alias}_spec({src_table});\n"
        )

    if derived_prelude:
        spec_body = derived_prelude + "    " + spec_body

    param_list = ", ".join(f"{s.param}: &{s.struct}" for s in slots)
    recommends = "\n        ".join(
        f"valid_cols_{s.table}({s.param})," for s in slots
    )
    spec_fn = f"""pub open spec fn method_spec({param_list}) -> {ret_type}
    recommends
        {recommends}
{{
    {spec_body}
}}"""

    return helpers + extra_having, spec_fn, ret_type


# --- Legacy 2-table helpers (used by codegen_exec) ---

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


def _resolve_join_row_expr(
    expr: str,
    left_table: str,
    right_table: str,
    schemas_by_table: dict[str, dict[str, str]],
) -> str:
    """Rewrite row.col into left./right. indexed accesses (2-table exec path)."""

    def col_access(col: str, tbl: str | None) -> str:
        field = col.lower()
        resolved = _table_for_col(col, tbl, left_table, right_table, schemas_by_table)
        side = "right" if resolved == right_table else "left"
        idx = "ri" if side == "right" else "li"
        return f"{side}.{field}[{idx} as int]"

    stripped = re.sub(
        r"\((row\.[A-Za-z_][A-Za-z0-9_]*) as int\)",
        r"\1",
        expr,
    )

    def repl(m: re.Match[str]) -> str:
        return col_access(m.group(1), None)

    return re.sub(r"\brow\.([A-Za-z_][A-Za-z0-9_]*)", repl, stripped)
