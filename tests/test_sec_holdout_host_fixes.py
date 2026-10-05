"""Regression: SEC holdout join/assemble host bugs (schema-driven, not SSB-hardcoded)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from research_loop.assemble_verified_program import assemble_verified_join_program
from research_loop.harness import run_custom_sql_pipeline
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.trusted_ret_bridge import get_bridge, structural_bridge_for_spec_type
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
    HashMapWithView::new()
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


def test_join_with_scalar_subquery_transpiles_table_scoped_helpers() -> None:
    """Correlated scalar subquery on JOIN uses Cols_<table> helpers, not bare Cols."""
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
    out = transpile_sql_to_verus(sql, schema)
    assert "subquery_sq1_helper(num: &Cols_num" in out
    assert "valid_cols_num(num)" in out
    assert "subquery_sq1_spec(num, num.tag[i0 as int]@" in out
    assert "valid_cols(cols)" not in out
    assert "subquery_sq1_spec(cols)" not in out


def test_r10_q11_correlated_scalar_subquery_host_codegen_types() -> None:
    """r10 Q11: correlated scalar params are Seq<char>; subquery WHERE uses lit@."""
    sql = """SELECT s.name, n.tag, n.value
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD' AND s.fy = 2024 AND n.value IS NOT NULL
      AND n.value = (
          SELECT MAX(n2.value)
          FROM num n2
          WHERE n2.tag = n.tag AND n2.adsh = n.adsh AND n2.uom = 'USD'
      )
ORDER BY n.value DESC
LIMIT 100"""
    schema = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    out = transpile_sql_to_verus(sql, schema)
    assert "outer_tag: Seq<char>" in out
    assert "outer_adsh: Seq<char>" in out
    assert "outer_tag: String" not in out
    assert 'num.get_uom(k) == "USD"@' in out
    assert "num.get_tag(k) == outer_tag" in out
    assert "num.get_tag(k) == outer_tag@" not in out
    ret_type = resolve_ret_type_from_method_spec(out)
    bridge = structural_bridge_for_spec_type(
        "Seq<(Seq<char>, Seq<char>, u64)>"
    )
    assert ret_type == "seq_str_str_u64"
    assert (
        "pub open spec fn vec_str_str_u64_view(s: Seq<(String, String, u64)>)"
        " -> Seq<(Seq<char>, Seq<char>, u64)>" in bridge.trusted_rs
    )


def test_join_agent_shell_matches_method_spec_signature() -> None:
    """Join workspace shell must use Cols_<table> params, not bare Cols."""
    from research_loop.admit_agent_runquery import admit_agent_runquery
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
    assert "requires valid_cols_num(num), valid_cols_sub(sub)," in shell
    assert shell.count("requires ") == 1
    assert "method_spec(num, sub)" in shell
    assert "valid_cols(cols)" not in shell
    assert "pub exec fn run_query(cols: &Cols)" not in shell
    result = admit_agent_runquery(shell, method_spec_rs=spec_rs)
    assert result.ok, result.violations


_Q4_EXISTS_MULTI_AGG = """
SELECT n.tag, n.version, COUNT(*) AS cnt, SUM(n.value) AS total
FROM num n
WHERE n.uom = 'USD' AND n.ddate BETWEEN 20230101 AND 20231231
      AND n.value IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM pre p
          WHERE p.tag = n.tag AND p.version = n.version AND p.adsh = n.adsh
      )
GROUP BY n.tag, n.version
HAVING COUNT(*) > 10
"""


def test_exists_corr_string_key_and_multi_agg_having() -> None:
    """Correlated EXISTS string keys use tuple Seq<char>; HAVING sees multi-agg tuple."""
    schema = {"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]}
    out = transpile_sql_to_verus(_Q4_EXISTS_MULTI_AGG, schema)
    assert "outer_key: u32" not in out
    # NOT EXISTS over a 3-column correlation is an anti-join fold (no exists_corr_* spec fn); every correlation
    # key is a Seq<char> equality inside the right-match helper.
    assert "join_anti_multi_agg_helper" in out and "exists_corr_" not in out
    helper = out[out.index("pub open spec fn join_right_match_helper") :]
    helper = helper[: helper.index("shape: anti")]
    for col in ("adsh", "tag", "version"):
        assert f"num.{col}[li as int]@ == pre.{col}[ri as int]@" in helper
    assert "!join_right_match_helper(num, pre, li, 0)" in out
    assert re.search(
        r"apply_having_filter\(m,\s*\|k:\s*\(Seq<char>,\s*Seq<char>\),\s*v:\s*\(u64,\s*u64\)\|",
        out,
    ), out[out.find("apply_having_filter") : out.find("apply_having_filter") + 200]
    assert "v.0 > 10" in out or "(v.0 > 10)" in out
    assert "|k: (Seq<char>, Seq<char>), v: u64|" not in out


def test_strip_skeleton_keeps_items_after_the_contract() -> None:
    from research_loop.assemble_verified_program import _strip_skeleton

    src = """verus! {
pub open spec fn method_spec() -> int { 1 }
// === RunQuery skeleton (agent provides the body) ===
// pub exec fn run_query
pub open spec fn rem_join_sq() -> int { 0 }
} // verus!
"""
    out = _strip_skeleton(src)
    assert "pub open spec fn method_spec" in out
    assert "pub open spec fn rem_join_sq" in out
    assert "RunQuery skeleton" not in out
    assert "} // verus!" not in out
