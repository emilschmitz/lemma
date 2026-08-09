"""Regression: SEC holdout join/assemble host bugs (schema-driven, not SSB-hardcoded)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from research_loop.assemble_verified_program import assemble_verified_join_program
from research_loop.harness import run_custom_sql_pipeline
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.trusted_ret_bridge import get_bridge
from tests.test_sec_holdout_parse import SEC_SCHEMA
from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.column_projection import project_multi_schema_for_query
from verus_transpiler.parse_sql import normalize_schema, parse_sql

ROOT = Path(__file__).resolve().parents[1]
QUERIES_PATH = ROOT / "holdout" / "gendb_sec_edgar" / "queries.sql"


def _load_query(qnum: str) -> str:
    text = QUERIES_PATH.read_text()
    m = re.search(rf"-- Q{qnum}:.*?\n(SELECT.*?;)", text, re.DOTALL | re.IGNORECASE)
    assert m, f"missing Q{qnum}"
    return m.group(1).strip()


_SIMPLE_JOIN_SQL = """SELECT s.name, SUM(n.value) AS total
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD' AND s.fy = 2022
GROUP BY s.name"""


def _join_run_query_stub(ret_type: str) -> str:
    sig = "pub exec fn run_query(num: &Cols_num, sub: &Cols_sub)"
    return f"""#[verifier::external_body]
{sig} -> (res: u64)
    requires valid_cols_num(num), valid_cols_sub(sub),
    ensures res == method_spec(num, sub),
{{
    0u64
}}"""


def test_join_where_uses_slot_accessors_not_cols_get() -> None:
    """Join MethodSpec must not reference bare cols/li from single-table to_col_expr."""
    schema = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    out = transpile_sql_to_verus(_SIMPLE_JOIN_SQL, schema)
    assert "cols.get_uom(li)" not in out
    assert "left_join_miss_generic(cols: &Cols" not in out
    assert "num.uom[i0 as int]" in out or 'num.uom[i0 as int]@' in out


def test_join_assemble_omits_cols_struct_from_trusted_prelude() -> None:
    """Two-table join assemble must not require undefined Cols from anti-join prelude."""
    schema = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    _, multi = normalize_schema(schema)
    projected = project_multi_schema_for_query(_SIMPLE_JOIN_SQL, multi)
    spec_rs = transpile_sql_to_verus(_SIMPLE_JOIN_SQL, projected)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    program = assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=_join_run_query_stub(ret_type),
        multi_schema=projected,
        table_order=("num", "sub"),
        ret_type=ret_type,
        default_tbls={"num": "", "sub": ""},
    )
    assert "left_join_miss_generic(cols: &Cols" not in program
    assert "pub struct Cols_num" in program
    assert "pub struct Cols " not in program


def test_derived_join_assemble_uses_base_tables_only() -> None:
    """Derived JOIN (Q2) must assemble as two physical tables, not derived alias m."""
    sql = _load_query("2")
    schema = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    query = parse_sql(sql, schema)
    derived = {d.alias for d in query.derived_tables}
    base = tuple(t for t in query.tables if t not in derived)
    assert base == ("num", "sub")
    _, multi = normalize_schema(schema)
    projected = project_multi_schema_for_query(sql, multi)
    spec_rs = transpile_sql_to_verus(sql, projected)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    program = assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=_join_run_query_stub(ret_type),
        multi_schema=projected,
        table_order=base,
        ret_type=ret_type,
        default_tbls={"num": "", "sub": ""},
    )
    assert "load_cols_m" not in program


def test_single_table_on_multi_catalog_assembles_flat() -> None:
    """Single-table GROUP BY on multi-table SEC catalog must not fail assemble."""
    sql = """SELECT n.tag, n.version, COUNT(*) AS cnt, SUM(n.value) AS total
FROM num n
WHERE n.uom = 'USD' AND n.ddate BETWEEN 20230101 AND 20231231
GROUP BY n.tag, n.version
HAVING COUNT(*) > 10"""
    catalog = {"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]}
    projected = project_multi_schema_for_query(sql, catalog)
    _, multi = normalize_schema(projected)
    assert multi is None
    assert "tag" in projected and "uom" in projected
    assert "pre" not in projected
    spec_rs = transpile_sql_to_verus(sql, projected)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    bridge = get_bridge(ret_type)
    assert bridge is not None
    body = f"""#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: {bridge.rust_ret})
    requires valid_cols(cols),
    ensures {bridge.ensures}
{{
    std::collections::HashMap::new()
}}"""
    res = run_custom_sql_pipeline(
        sql,
        catalog,
        run_query_body=body,
        skip_bench=True,
    )
    assert res.get("stage") != "assemble", res.get("error")
    assert "single-table custom query requires flat schema dict" not in (res.get("error") or "")


def test_single_table_multi_catalog_project_schema_is_flat() -> None:
    sql = """SELECT tag, COUNT(*) AS cnt FROM num WHERE uom = 'USD' GROUP BY tag"""
    catalog = {"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]}
    projected = project_multi_schema_for_query(sql, catalog)
    _, multi = normalize_schema(projected)
    assert multi is None
    assert "tag" in projected and "uom" in projected


def test_join_with_scalar_subquery_fails_loud_not_cols_stub() -> None:
    """Correlated scalar subquery on JOIN must not emit &Cols helpers (Spot q2 host bug)."""
    from verus_transpiler.parse_sql import UnsupportedContractError

    sql = """SELECT s.name, n.tag, n.value
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'pure' AND s.fy = 2022 AND n.value IS NOT NULL
      AND n.value = (
          SELECT MAX(n2.value)
          FROM num n2
          WHERE n2.tag = n.tag AND n2.adsh = n.adsh AND n2.uom = 'pure'
      )
ORDER BY n.value DESC
LIMIT 50"""
    schema = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    with pytest.raises(UnsupportedContractError, match="table-scoped"):
        transpile_sql_to_verus(sql, schema)


def test_join_agent_shell_matches_method_spec_signature() -> None:
    """Join workspace shell must use Cols_<table> params, not bare Cols."""
    from research_loop.assemble_runquery import build_runquery_agent_source

    sql = _load_query("2")
    schema = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    _, multi = normalize_schema(schema)
    projected = project_multi_schema_for_query(sql, multi)
    spec_rs = transpile_sql_to_verus(sql, projected)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    shell = build_runquery_agent_source(
        ret_type=ret_type,
        method_spec_rs=spec_rs,
    )
    assert "pub exec fn run_query(num: &Cols_num, sub: &Cols_sub)" in shell
    assert "requires valid_cols_num(num)," in shell
    assert "requires valid_cols_sub(sub)," in shell
    assert "method_spec(num, sub)" in shell
    assert "valid_cols(cols)" not in shell
    assert "pub exec fn run_query(cols: &Cols)" not in shell
