"""Schema-driven exec + hot-path emission from SQLQuery (custom query generation)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .col_exprs import native_u64_term, native_where_cond, to_col_expr
from .joins import _col_access, _resolve_join_row_expr, _table_struct_name
from .parse_sql import SQLQuery, UnsupportedContractError, normalize_schema
from .parse_sql import _agg_value_type
from .templates import (
    _exec_accessorify,
    _execify_expr,
    _filter_block,
    _scalar_loop_invariant,
    emit_run_query_template,
)
from .value_bounds import col_verus_type


@dataclass(frozen=True)
class ExecBundle:
  """Generated run_query body + optional plain-Rust hot path."""

  run_query_rs: str
  hot_path_rs: str
  bench_exec: str
  ret_type: str
  proved: bool
  table_order: tuple[str, ...] | None = None


def resolve_ret_type_key(query: SQLQuery, flat_schema: dict[str, str]) -> str:
  """Map query shape to assembler RET_TYPE_CONFIG key."""
  if not query.groupby_columns:
    return "u64"
  val_type = _agg_value_type(query.agg_expr)
  keys = [col_verus_type(flat_schema[c]) for c in query.groupby_columns]
  if len(keys) == 1:
    if keys[0] == "u32":
      return f"map_u32_{val_type}"
    if keys[0] == "String":
      return f"map_str_{val_type}"
  if len(keys) == 2:
    if keys == ["u32", "String"]:
      return f"map_u32_str_{val_type}"
    if keys == ["String", "u32"]:
      return f"map_str_str_u32_{val_type}" if val_type == "u64" else f"map_u32_str_{val_type}"
    if keys == ["String", "String"]:
      return f"map_str_str_{val_type}"
  if len(keys) == 3:
    if keys == ["String", "String", "u32"]:
      return f"map_str_str_u32_{val_type}"
    if keys == ["u32", "String", "String"]:
      return f"map_u32_str_str_{val_type}"
  raise UnsupportedContractError(
      f"unsupported group-by key types {keys!r} for custom exec generation"
  )


def _term_at_i_for_query(query: SQLQuery) -> str:
  """Exec-template term at usize index ``i``."""
  expr = (query.agg_expr or "").strip()
  if query.agg_type == "COUNT":
    return "1u64"
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
  return native_u64_term(expr, "i").replace(" as int", "")


def _exec_where_at_i(
    where_expr: str | None,
    idx: str,
    schema: dict[str, str],
) -> str | None:
  if not where_expr:
    return None
  w = to_col_expr(where_expr, idx)
  w = re.sub(rf"cols\.get_(\w+)\({re.escape(idx)}\)", rf"cols.\1[{idx}]", w)
  w = native_where_cond(w, idx, schema)
  return _execify_expr(w)


def _hot_rust_type(col_type: str) -> str:
  vt = col_verus_type(col_type)
  if vt == "String":
    return "String"
  if vt == "u64":
    return "u64"
  return "u32"


def _hot_term_at_i(query: SQLQuery, idx: str = "i") -> str:
  if query.agg_type == "COUNT":
    return "1"
  expr = (query.agg_expr or "").strip()
  if _agg_value_type(expr) == "i64":
    from .col_exprs import native_i64_term

    return native_i64_term(expr, idx).replace(" as int", "")
  return native_u64_term(expr, idx).replace(" as int", "")


def _emit_scalar_bundle(query: SQLQuery, flat_schema: dict[str, str]) -> ExecBundle:
  where_at = _exec_where_at_i(query.where_expr, "i", flat_schema)
  term_at = _term_at_i_for_query(query)

  if query.agg_type in ("SUM", "COUNT", "AVG"):
    run_query = emit_run_query_template(
        query,
        "u64",
        where_at_i=where_at,
        term_at_i=term_at,
    )
    proved = True
  elif query.agg_type == "MIN":
    where_e = _exec_accessorify(where_at) if where_at else None
    term_e = _exec_accessorify(_execify_expr(term_at))
    body = _filter_block(where_e, f"if {term_e} < res {{ res = {term_e}; }}")
    inv = _scalar_loop_invariant()
    run_query = f"""// Scalar MIN — loop invariant ties res to method_spec_helper.
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{{
    let mut res: u64 = u64::MAX;
    let mut i: usize = cols.n;
    while i > 0
        invariant
{inv}
        decreases i,
    {{
        i = i - 1;
        {body}
        assert(res == method_spec_helper(cols, i as int));
    }}
    res
}}"""
    proved = True
  elif query.agg_type == "MAX":
    where_e = _exec_accessorify(where_at) if where_at else None
    term_e = _exec_accessorify(_execify_expr(term_at))
    body = _filter_block(where_e, f"if {term_e} > res {{ res = {term_e}; }}")
    inv = _scalar_loop_invariant()
    run_query = f"""// Scalar MAX — loop invariant ties res to method_spec_helper.
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{{
    let mut res: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
{inv}
        decreases i,
    {{
        i = i - 1;
        {body}
        assert(res == method_spec_helper(cols, i as int));
    }}
    res
}}"""
    proved = True
  else:
    raise UnsupportedContractError(
        f"scalar exec generation unsupported for agg {query.agg_type!r}"
    )

  hot_cols = _collect_single_table_cols(query, flat_schema)
  hot_path, bench_exec = _emit_scalar_hot(query, flat_schema, hot_cols, where_at, term_at)
  return ExecBundle(
      run_query_rs=run_query,
      hot_path_rs=hot_path,
      bench_exec=bench_exec,
      ret_type="u64",
      proved=proved,
  )


def _collect_single_table_cols(
    query: SQLQuery,
    flat_schema: dict[str, str],
) -> list[str]:
  cols: set[str] = set()
  for c in query.groupby_columns:
    cols.add(c)
  for c in flat_schema:
    if c.lower() in (query.where_expr or "").lower():
      cols.add(c)
    if c.lower() in (query.agg_expr or "").lower():
      cols.add(c)
  if not cols:
    cols = set(flat_schema.keys())
  return sorted(cols, key=lambda x: x.lower())


def _emit_scalar_hot(
    query: SQLQuery,
    flat_schema: dict[str, str],
    col_names: list[str],
    where_at: str | None,
    term_at: str,
) -> tuple[str, str]:
  params = ", ".join(f"{c.lower()}: &[{_hot_rust_type(flat_schema[c])}]" for c in col_names)
  n_expr = f"{col_names[0].lower()}.len()"
  where_hot = _where_to_hot_loop(where_at, "i") or "true"
  term_hot = _term_to_hot_loop(term_at, "i")
  if query.agg_type == "COUNT":
    acc_line = "acc = acc.wrapping_add(1);"
  elif query.agg_type in ("MIN", "MAX"):
    cmp = "<" if query.agg_type == "MIN" else ">"
    acc_line = f"if term {cmp} acc {{ acc = term; }}"
  else:
    acc_line = "acc = acc.wrapping_add(term);"

  fn = f"""\
#[inline(always)]
fn custom_scalar_hot({params}) -> u64 {{
    let n = {n_expr};
    let mut acc: u64 = {"u64::MAX" if query.agg_type == "MIN" else "0"};
    for i in 0..n {{
        if {where_hot} {{
            let term = {term_hot};
            {acc_line}
        }}
    }}
    acc
}}"""
  bench_args = ", ".join(f"&cols.{c.lower()}" for c in col_names)
  return fn, f"custom_scalar_hot({bench_args})"


def _where_to_hot_loop(where_exec: str | None, idx: str) -> str | None:
  if not where_exec:
    return None
  out = where_exec
  out = re.sub(rf"cols\.get_(\w+)\({re.escape(idx)}\)", rf"\1[{idx}]", out)
  out = re.sub(rf"cols\.get_(\w+)_exec\({re.escape(idx)}\)", rf"\1[{idx}]", out)
  out = re.sub(rf"cols\.(\w+)\[{re.escape(idx)}\]", rf"\1[{idx}]", out)
  out = re.sub(rf"cols\.eq_at_(\w+)\({re.escape(idx)},", rf"\1[{idx}].as_str() ==", out)
  out = re.sub(r"cols\.get_(\w+)_exec\([^)]+\)", rf"\1[{idx}]", out)
  return out


def _term_to_hot_loop(term_exec: str, idx: str) -> str:
  out = term_exec
  out = re.sub(rf"cols\.get_(\w+)\({re.escape(idx)}\)", rf"\1[{idx}]", out)
  out = re.sub(rf"cols\.get_(\w+)_exec\({re.escape(idx)}\)", rf"\1[{idx}]", out)
  out = re.sub(rf"cols\.(\w+)\[{re.escape(idx)}\]", rf"\1[{idx}]", out)
  out = re.sub(r"mul_u64_u32\(([^,]+), ([^)]+)\)", r"(\1).wrapping_mul(\2 as u64)", out)
  out = re.sub(
      r"case_when_u64_exec\(([^,]+), ([^,]+), ([^)]+)\)",
      r"if \1 { \2 } else { \3 }",
      out,
  )
  out = re.sub(r"sub_u64_to_i64\(([^,]+), ([^)]+)\)", r"(\1 as i64) - (\2 as i64)", out)
  if out.strip().endswith("as u64"):
    return out
  if " as i64" in out:
    return out
  return f"({out}) as u64"


_RET_TYPE_META: dict[str, tuple[str, str]] = {
    "map_u32_str_u64": ("HashMap<(u32, String), u64>", "hashmap_u32_str_u64_view"),
    "map_str_str_u64": ("HashMap<(String, String), u64>", "hashmap_str_str_u64_view"),
    "map_str_str_u32_u64": (
        "HashMap<(String, String, u32), u64>",
        "hashmap_str_str_u32_u64_view",
    ),
    "map_u32_str_i64": ("HashMap<(u32, String), i64>", "hashmap_u32_str_i64_view"),
    "map_u32_str_str_i64": (
        "HashMap<(u32, String, String), i64>",
        "hashmap_u32_str_str_i64_view",
    ),
    "map_u32_u64": ("HashMap<u32, u64>", "hashmap_u32_u64_view"),
    "map_str_u64": ("HashMap<String, u64>", "hashmap_str_u64_view"),
    "map_u32_i64": ("HashMap<u32, i64>", "hashmap_u32_str_i64_view"),
    "map_str_i64": ("HashMap<String, i64>", "hashmap_str_u64_view"),
}


def _emit_groupby_bundle(query: SQLQuery, flat_schema: dict[str, str]) -> ExecBundle:
  ret_type = resolve_ret_type_key(query, flat_schema)

  if ret_type not in _RET_TYPE_META:
    raise UnsupportedContractError(f"no assembler config for ret_type {ret_type!r}")

  rust_ret, view_spec = _RET_TYPE_META[ret_type]
  where_at = _exec_where_at_i(query.where_expr, "i", flat_schema)
  hot_path, bench_exec = _emit_groupby_hot(query, flat_schema, ret_type, where_at)

  run_query = f"""\
// TRUSTED: group-by exec via plain-Rust hot path (spec fold remains recursive Map).
#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: {rust_ret})
    requires valid_cols(cols),
    ensures {view_spec}(res@) == method_spec(cols),
{{
    {bench_exec}
}}"""

  return ExecBundle(
      run_query_rs=run_query,
      hot_path_rs=hot_path,
      bench_exec=bench_exec,
      ret_type=ret_type,
      proved=False,
  )


def _groupby_hot_key_tuple(
    query: SQLQuery,
    flat_schema: dict[str, str],
    idx: str,
) -> str:
  parts: list[str] = []
  for col in query.groupby_columns:
    field = col.lower()
    if col_verus_type(flat_schema[col]) == "String":
      parts.append(f"{field}[{idx}].clone()")
    else:
      parts.append(f"{field}[{idx}]")
  if len(parts) == 1:
    return parts[0]
  return f"({', '.join(parts)})"


def _emit_groupby_hot(
    query: SQLQuery,
    flat_schema: dict[str, str],
    ret_type: str,
    where_at: str | None,
) -> tuple[str, str]:
  if ret_type not in _RET_TYPE_META:
    raise UnsupportedContractError(f"no hot-path metadata for {ret_type!r}")
  rust_ret, _view = _RET_TYPE_META[ret_type]
  val_type = _agg_value_type(query.agg_expr)
  zero = "0i64" if val_type == "i64" else "0"
  cols = _collect_single_table_cols(query, flat_schema)
  params = ", ".join(f"{c.lower()}: &[{_hot_rust_type(flat_schema[c])}]" for c in cols)
  n_expr = f"{cols[0].lower()}.len()"
  where_hot = _where_to_hot_loop(where_at, "i") or "true"
  key_tuple = _groupby_hot_key_tuple(query, flat_schema, "i")
  term_hot = _term_to_hot_loop(_hot_term_at_i(query), "i")

  fn = f"""\
#[inline(always)]
fn custom_groupby_hot({params}) -> {rust_ret} {{
    use std::collections::HashMap;
    let n = {n_expr};
    let mut acc: {rust_ret} = HashMap::with_capacity(64);
    for i in 0..n {{
        if {where_hot} {{
            let key = {key_tuple};
            let prev = acc.get(&key).copied().unwrap_or({zero});
            acc.insert(key, prev.wrapping_add({term_hot}));
        }}
    }}
    acc
}}"""
  bench_args = ", ".join(f"&cols.{c.lower()}" for c in cols)
  return fn, f"custom_groupby_hot({bench_args})"


def _split_table_where(
    where_expr: str | None,
    table_names: list[str],
) -> dict[str, str | None]:
  if not where_expr:
    return {t: None for t in table_names}
  parts: dict[str, list[str]] = {t: [] for t in table_names}
  for segment in re.split(r"\s*&&\s*", where_expr):
    seg = segment.strip().strip("()")
    if not seg:
      continue
    assigned = False
    for t in table_names:
      if re.search(rf"\b{re.escape(t)}\.", seg):
        parts[t].append(seg)
        assigned = True
        break
    if not assigned:
      for t in table_names:
        parts[t].append(seg)
  return {
      t: " && ".join(f"({p})" for p in ps) if ps else None
      for t, ps in parts.items()
  }


def _join_expr_to_hot(expr: str | None, idx: str = "i") -> str:
  if not expr:
    return "true"
  out = expr
  out = re.sub(r"left\.(\w+)\[li as int\]", rf"left_\1[{idx}]", out)
  out = re.sub(r"right\.(\w+)\[ri as int\]", rf"right_\1[{idx}]", out)
  out = re.sub(r"left\.(\w+)\[li\]", rf"left_\1[{idx}]", out)
  out = re.sub(r"right\.(\w+)\[ri\]", rf"right_\1[{idx}]", out)
  return out


def _nway_where_hot(
    cond: str | None,
    table: str,
    idx: str,
) -> str:
  if not cond:
    return "true"
  out = cond
  out = re.sub(
      rf"\b{re.escape(table)}\.(\w+)\[{re.escape(idx)} as int\]",
      rf"{table}_\1[{idx}]",
      out,
  )
  out = re.sub(
      rf"\b{re.escape(table)}\.(\w+)\[{re.escape(idx)}\]",
      rf"{table}_\1[{idx}]",
      out,
  )
  return out


def _emit_join_bundle(
    query: SQLQuery,
    multi_schema: dict[str, dict[str, str]],
) -> ExecBundle:
  if len(query.tables) != 2:
    raise UnsupportedContractError("join bundle requires exactly two tables")
  if query.groupby_columns:
    raise UnsupportedContractError("join group-by custom exec not yet generated")
  if query.agg_type not in ("SUM", "COUNT"):
    raise UnsupportedContractError(f"join agg {query.agg_type!r} not supported")

  left_table, right_table = query.tables[0], query.tables[1]
  left_struct = _table_struct_name(left_table)
  right_struct = _table_struct_name(right_table)
  table_order = (left_table, right_table)

  where_resolved = None
  if query.where_expr:
    raw = to_col_expr(query.where_expr, "li")
    raw = re.sub(r"cols\.get_([a-z0-9_]+)\(\w+\)", r"row.\1", raw)
    where_resolved = _resolve_join_row_expr(
        raw, left_table, right_table, multi_schema
    )

  join = query.joins[0]
  left_key = join.on_equalities[0][0].split(".")[-1].lower()
  right_key = join.on_equalities[0][1].split(".")[-1].lower()

  agg_term = _resolve_join_row_expr(
      query.agg_expr if query.agg_type == "SUM" else "1",
      left_table,
      right_table,
      multi_schema,
  )
  left_schema = multi_schema[left_table]
  right_schema = multi_schema[right_table]
  key_type = _hot_rust_type(left_schema.get(left_key.upper(), left_schema.get(left_key, "int")))

  where_by_table = _split_table_where(where_resolved, ["left", "right"])
  right_where = _join_expr_to_hot(where_by_table.get("right"))
  left_where = _join_expr_to_hot(where_by_table.get("left"))
  agg_hot = _join_expr_to_hot(agg_term)

  param_parts: list[str] = []
  for col in left_schema:
    field = col.lower()
    param_parts.append(
        f"left_{field}: &[{_hot_rust_type(left_schema[col])}]"
    )
  for col in right_schema:
    field = col.lower()
    param_parts.append(
        f"right_{field}: &[{_hot_rust_type(right_schema[col])}]"
    )
  param_sig = ", ".join(param_parts)

  hot_path = f"""\
#[inline(always)]
fn custom_join_sum_hot({param_sig}) -> u64 {{
    use std::collections::HashSet;
    let mut right_ok: HashSet<{key_type}> = HashSet::new();
    for i in 0..right_{right_key}.len() {{
        if {right_where} {{
            right_ok.insert(right_{right_key}[i]);
        }}
    }}
    let mut acc: u64 = 0;
    for i in 0..left_{left_key}.len() {{
        if {left_where} && right_ok.contains(&left_{left_key}[i]) {{
            acc = acc.wrapping_add({agg_hot});
        }}
    }}
    acc
}}"""

  bench_cols = [f"&left.{col.lower()}" for col in left_schema]
  bench_cols.extend(f"&right.{col.lower()}" for col in right_schema)
  bench_exec = f"custom_join_sum_hot({', '.join(bench_cols)})"

  run_query = f"""\
// TRUSTED: hash-join build-probe (method_spec remains nested-loop fold).
#[verifier::external_body]
pub exec fn run_query(left: &{left_struct}, right: &{right_struct}) -> (res: u64)
    requires
        valid_cols_{left_table}(left),
        valid_cols_{right_table}(right),
    ensures res == method_spec(left, right),
{{
    {bench_exec}
}}"""

  return ExecBundle(
      run_query_rs=run_query,
      hot_path_rs=hot_path,
      bench_exec=bench_exec,
      ret_type="u64",
      proved=False,
      table_order=table_order,
  )


def _table_for_col_nway(
    col: str,
    tables: list[str],
    schemas_by_table: dict[str, dict[str, str]],
) -> str:
  col_u = col.upper()
  for t in tables:
    if col_u in {c.upper() for c in schemas_by_table.get(t, {})}:
      return t
  return tables[0]


def _resolve_nway_row_expr(
    expr: str,
    tables: list[str],
    schemas_by_table: dict[str, dict[str, str]],
) -> str:
  stripped = re.sub(
      r"\((row\.[A-Za-z_][A-Za-z0-9_]*) as int\)",
      r"\1",
      expr,
  )

  def repl(m: re.Match[str]) -> str:
    col = m.group(1)
    tbl = _table_for_col_nway(col, tables, schemas_by_table)
    return f"{tbl}.{col.lower()}"

  return re.sub(r"\brow\.([A-Za-z_][A-Za-z0-9_]*)", repl, stripped)


def _emit_nway_bundle(
    query: SQLQuery,
    multi_schema: dict[str, dict[str, str]],
) -> ExecBundle:
  if query.groupby_columns:
    raise UnsupportedContractError("n-way join group-by custom exec not yet generated")
  if query.agg_type not in ("SUM", "COUNT"):
    raise UnsupportedContractError(f"n-way agg {query.agg_type!r} not supported")

  tables = list(query.tables)
  table_order = tuple(tables)

  where_resolved = query.where_expr
  if where_resolved:
    where_resolved = _resolve_nway_row_expr(
        where_resolved, tables, multi_schema
    )

  agg_term = _resolve_nway_row_expr(
      query.agg_expr if query.agg_type == "SUM" else "1",
      tables,
      multi_schema,
  )

  params: list[str] = []
  for t in tables:
    for col in multi_schema[t]:
      field = col.lower()
      rt = _hot_rust_type(multi_schema[t][col])
      params.append(f"{t}_{field}: &[{rt}]")
  param_sig = ", ".join(params)

  stages: list[str] = []
  prev_set: str | None = None
  n = len(tables)
  for ti in range(n - 1, 0, -1):
    t = tables[ti]
    t_where = _nway_where_hot(
        _split_table_where(where_resolved, tables).get(t),
        t,
        "i",
    )
    set_name = f"ok_{t}"
    if ti == n - 1:
      join = query.joins[ti - 1]
      right_key = join.on_equalities[0][1].split(".")[-1].lower()
      key_ty = _hot_rust_type(
          multi_schema[t].get(right_key.upper(), next(iter(multi_schema[t].values())))
      )
      stages.append(f"""\
    let mut {set_name}: std::collections::HashSet<{key_ty}> = std::collections::HashSet::new();
    for i in 0..{t}_{right_key}.len() {{
        if {t_where} {{
            {set_name}.insert({t}_{right_key}[i]);
        }}
    }}""")
      prev_set = set_name
    else:
      join_up = query.joins[ti]
      left_up = join_up.on_equalities[0][0].split(".")[-1].lower()
      join_out = query.joins[ti - 1]
      out_key = join_out.on_equalities[0][1].split(".")[-1].lower()
      key_ty = _hot_rust_type(
          multi_schema[t].get(out_key.upper(), next(iter(multi_schema[t].values())))
      )
      stages.append(f"""\
    let mut {set_name}: std::collections::HashSet<{key_ty}> = std::collections::HashSet::new();
    for i in 0..{t}_{out_key}.len() {{
        if {t_where} && {prev_set}.contains(&{t}_{left_up}[i]) {{
            {set_name}.insert({t}_{out_key}[i]);
        }}
    }}""")
      prev_set = set_name

  fact = tables[0]
  fact_join_key = query.joins[0].on_equalities[0][0].split(".")[-1].lower()
  fact_where = _nway_where_hot(
      _split_table_where(where_resolved, tables).get(fact),
      fact,
      "i",
  )
  agg_hot = _nway_where_hot(agg_term, fact, "i")
  probe_set = prev_set or "ok_probe"
  body = "\n".join(stages)
  hot_path = f"""\
#[inline(always)]
fn custom_nway_sum_hot({param_sig}) -> u64 {{
    use std::collections::HashSet;
{body}
    let mut acc: u64 = 0;
    for i in 0..{fact}_{fact_join_key}.len() {{
        if {fact_where} && {probe_set}.contains(&{fact}_{fact_join_key}[i]) {{
            acc = acc.wrapping_add({agg_hot});
        }}
    }}
    acc
}}"""

  bench_args = ", ".join(
      f"&{t}.{col.lower()}"
      for t in tables
      for col in multi_schema[t]
  )
  bench_exec = f"custom_nway_sum_hot({bench_args})"

  struct_params = ", ".join(f"{t}: &Cols_{t}" for t in tables)
  valid_req = ",\n        ".join(
      f"valid_cols_{t}({t})" for t in tables
  )
  run_query = f"""\
// TRUSTED: n-way hash-join chain (method_spec is TRUSTED nested-loop reference).
#[verifier::external_body]
pub exec fn run_query({struct_params}) -> (res: u64)
    requires
        {valid_req},
    ensures res == method_spec({", ".join(tables)}),
{{
    {bench_exec}
}}"""

  return ExecBundle(
      run_query_rs=run_query,
      hot_path_rs=hot_path,
      bench_exec=bench_exec,
      ret_type="u64",
      proved=False,
      table_order=table_order,
  )


def generate_exec_bundle(
    query: SQLQuery,
    schema: dict[str, str] | dict[str, dict[str, str]],
    *,
    multi_schema: dict[str, dict[str, str]] | None = None,
) -> ExecBundle:
  """Emit run_query + hot path for a parsed Basic SQL query."""
  flat_schema, multi = normalize_schema(schema)
  if multi_schema is None:
    multi_schema = multi

  if (
      query.union_query
      or query.intersect_query
      or query.except_query
      or query.is_projection
      or query.derived_tables
      or query.scalar_subqueries
      or query.exists_subqueries
      or query.in_subqueries
      or query.ctes
      or query.window_specs
      or query.having_expr
  ):
    raise UnsupportedContractError(
        "custom exec generation supports scalar / group-by / equijoin SUM only"
    )

  if query.joins and multi_schema:
    if len(query.tables) == 2:
      return _emit_join_bundle(query, multi_schema)
    if len(query.tables) >= 3:
      return _emit_nway_bundle(query, multi_schema)
    raise UnsupportedContractError("join query missing table list")

  if query.groupby_columns:
    return _emit_groupby_bundle(query, flat_schema)

  if query.agg_type in ("SUM", "COUNT", "AVG", "MIN", "MAX"):
    return _emit_scalar_bundle(query, flat_schema)

  raise UnsupportedContractError(
      f"no custom exec for query shape agg={query.agg_type!r}"
  )
