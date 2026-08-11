"""Tests for multi-agg agg_step TRUSTED helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from verus_transpiler.column_projection import project_multi_schema_for_query
from verus_transpiler.parse_sql import normalize_schema

from research_loop.assemble_verified_program import (
    assemble_verified_program,
    prepare_agent_visible_spec,
)
from research_loop.harness import resolve_verus_bin, run_verus_verify
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.multi_agg_step_bridge import (
    _spec_expr_to_exec,
    emit_multi_agg_step_trusted,
    multi_agg_step_trusted_rs,
    parse_multi_agg_layout,
)
from research_loop.scripts.sqlsmith_trusted_coverage import (
    load_sec_schema,
    parse_sql_file,
)
from research_loop.sec_table_assumptions import sec_prove_loop_catalog_assumptions
from research_loop.trusted_ret_bridge import get_bridge, structural_bridge_for_spec_type
from verus_transpiler import transpile_sql_to_verus

ROOT = Path(__file__).resolve().parents[1]
_VACUOUS_TRUSTED_RUN_QUERY_RE = re.compile(
    r"#\[verifier::external_body\]\s*pub\s+exec\s+fn\s+run_query",
    re.MULTILINE,
)

PRE_SCHEMA = {
    "stmt": "string",
    "rfile": "string",
    "adsh": "string",
    "line": "int",
}

Q1_LIKE_SQL = """SELECT stmt, rfile, COUNT(*) AS cnt,
       COUNT(DISTINCT adsh) AS num_filings,
       AVG(line) AS avg_line_num
FROM pre
WHERE stmt IS NOT NULL
GROUP BY stmt, rfile"""

TOP_MULTI_AGG_RET_TYPES = (
    "map_str_str_str_str__u64_u64",
    "map_str_u32__u64_u64_u64",
    "map_u32_str_str__u64_u64_u64",
    "map_str_u32_str_str_str__u64_u64",
    "map_str_str__u64_u64",
    "map_str_str_str__u64_u64_u64_u64",
    "map_str_str__u64_u64_u64",
)


def _first_sql_for_ret_type(ret_type: str) -> tuple[str, str] | None:
    """Return (qid, sql) for the first scored query with this ret_type, or None."""
    score_path = ROOT / "research_loop" / "generated" / "trusted_capability_score.json"
    if not score_path.is_file():
        return None
    data = json.loads(score_path.read_text(encoding="utf-8"))
    target = next(
        (q for q in data.get("queries", []) if q.get("ret_type") == ret_type),
        None,
    )
    if target is None:
        return None
    sql_path = ROOT / target["source"]
    for qid, sql in parse_sql_file(sql_path):
        if qid == target["id"]:
            return qid, sql
    return None


def _agent_visible_for_sec_sql(sql: str) -> str:
    schema = load_sec_schema()
    flat, multi = normalize_schema(schema)
    projected = project_multi_schema_for_query(sql, multi) if multi else flat
    spec_rs = transpile_sql_to_verus(
        sql, projected, catalog_assumptions=sec_prove_loop_catalog_assumptions()
    )
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    return prepare_agent_visible_spec(spec_rs, ret_type)


@pytest.mark.parametrize("ret_type", TOP_MULTI_AGG_RET_TYPES)
def test_top_ret_types_emit_agg_step(ret_type: str) -> None:
    found = _first_sql_for_ret_type(ret_type)
    if found is None:
        pytest.skip(f"no fixture SQL for ret_type {ret_type}")
    _qid, sql = found
    visible = _agent_visible_for_sec_sql(sql)
    assert re.search(r"pub exec fn agg_step_(?:state_new_)?\w+", visible), ret_type
    assert "agg_step_apply_row_" in visible
    assert not _VACUOUS_TRUSTED_RUN_QUERY_RE.search(visible)
    helper_chunks = re.findall(
        r"pub open spec fn \w*(?:method_spec_helper|multi_agg_helper)[\s\S]*?^}",
        visible,
        re.MULTILINE,
    )
    assert helper_chunks
    assert all("arbitrary()" not in chunk for chunk in helper_chunks)


def test_parse_q1_multi_agg_layout() -> None:
    out = transpile_sql_to_verus(
        Q1_LIKE_SQL,
        {"pre": PRE_SCHEMA},
        catalog_assumptions=sec_prove_loop_catalog_assumptions(),
    )
    layout = parse_multi_agg_layout(out)
    assert layout is not None
    assert layout.helper_name == "method_spec_helper"
    names = [p.name for p in layout.row_params]
    assert "distinct_0" in names
    assert any(n.startswith("row_u64_") for n in names)
    assert "arbitrary()" not in layout.apply_body


def test_emit_agg_step_stable_names() -> None:
    out = transpile_sql_to_verus(
        Q1_LIKE_SQL,
        {"pre": PRE_SCHEMA},
        catalog_assumptions=sec_prove_loop_catalog_assumptions(),
    )
    layout = parse_multi_agg_layout(out)
    assert layout is not None
    bridge = structural_bridge_for_spec_type(
        "Map<(Seq<char>, Seq<char>), (u64, u64, u64)>"
    )
    rs = emit_multi_agg_step_trusted(layout, bridge, spec_rs=out)
    for name in (
        "AggStepState_str_str__u64_u64_u64",
        "agg_step_inner_str_str__u64_u64_u64_spec",
        "agg_step_project_str_str__u64_u64_u64",
        "agg_step_apply_row_str_str__u64_u64_u64",
        "agg_step_state_new_str_str__u64_u64_u64",
        "agg_step_str_str__u64_u64_u64",
    ):
        assert name in rs
    assert rs.count("external_body") >= 2
    assert "lemma_method_spec_helper_slot0_count_leq_str_str__u64_u64_u64" in rs
    assert "expert TCB" in rs
    assert "lemma_u64_add_one_fit" not in rs  # prelude lemmas live in transpiled spec


def test_prepare_agent_visible_spec_includes_agg_step() -> None:
    out = transpile_sql_to_verus(
        Q1_LIKE_SQL,
        {"pre": PRE_SCHEMA},
        catalog_assumptions=sec_prove_loop_catalog_assumptions(),
    )
    bridge = get_bridge("map_str_str__u64_u64_u64")
    assert bridge is not None
    visible = prepare_agent_visible_spec(out, bridge.key)
    assert "agg_step_str_str__u64_u64_u64" in visible
    assert "agg_step_apply_row_str_str__u64_u64_u64" in visible
    assert "set_insert_str" in visible
    helper = re.findall(
        r"pub open spec fn method_spec_helper[\s\S]*?^}",
        visible,
        re.MULTILINE,
    )[0]
    assert "arbitrary()" not in helper


Q26_CASE_WHEN_SQL = """SELECT n.tag, t.tlabel, t.datatype,
       COUNT(DISTINCT n.adsh) AS num_filings,
       COUNT(*) AS total_entries,
       SUM(CASE WHEN n.value > 0 THEN 1 ELSE 0 END) AS positive_count,
       SUM(CASE WHEN n.value < 0 THEN 1 ELSE 0 END) AS negative_count
FROM num n
JOIN tag t ON n.tag = t.tag AND n.version = t.version
WHERE n.ddate BETWEEN 20220101 AND 20221231 AND n.value IS NOT NULL
      AND t.custom = 0
GROUP BY n.tag, t.tlabel, t.datatype
HAVING COUNT(DISTINCT n.adsh) > 100
LIMIT 500"""

TAG_SCHEMA = {
    "tag": "string",
    "version": "string",
    "tlabel": "string",
    "datatype": "string",
    "custom": "int",
    "abstract": "int",
}
NUM_SCHEMA = {
    "adsh": "string",
    "tag": "string",
    "version": "string",
    "uom": "string",
    "value": "double",
    "ddate": "int",
}


def _agg_step_exec_checked_add_lines(rs: str, suffix: str) -> list[str]:
    m = re.search(
        rf"pub exec fn agg_step_{re.escape(suffix)}\([\s\S]*?\{{\n([\s\S]*?)\n\}}\n",
        rs,
    )
    assert m, f"missing agg_step_{suffix} exec body"
    return [ln for ln in m.group(1).split("\n") if "checked_add" in ln]


def test_spec_expr_to_exec_strips_ghost_int_addends() -> None:
    assert _spec_expr_to_exec("(row_u64_0) as int") == "row_u64_0"
    assert _spec_expr_to_exec("(row_u64_0 as int) as int") == "row_u64_0"
    assert (
        _spec_expr_to_exec("case_when_u64((row_u64_0 as int) > 0, 1, 0) as int")
        == "case_when_u64_exec(row_u64_0 > 0, 1, 0)"
    )


def test_exec_checked_add_no_ghost_int_q1_avg() -> None:
    """SUM/AVG row adds in exec agg_step must not cast through ghost int."""
    out = transpile_sql_to_verus(
        Q1_LIKE_SQL,
        {"pre": PRE_SCHEMA},
        catalog_assumptions=sec_prove_loop_catalog_assumptions(),
    )
    layout = parse_multi_agg_layout(out)
    assert layout is not None
    bridge = structural_bridge_for_spec_type(
        "Map<(Seq<char>, Seq<char>), (u64, u64, u64)>"
    )
    rs = emit_multi_agg_step_trusted(layout, bridge)
    bad = _agg_step_exec_checked_add_lines(rs, "str_str__u64_u64_u64")
    assert bad, "expected checked_add lines in agg_step exec"
    assert all("as int" not in ln for ln in bad), bad
    assert any("checked_add(row_u64_0)" in ln.replace(" ", "") for ln in bad)
    req_block = rs.split("pub exec fn agg_step_str_str__u64_u64_u64")[1].split("ensures")[0]
    assert "row_u64_0 < LEMMA_MAX_CELL_U64" in req_block
    assert "(prev as int) +" not in req_block
    assert "case_when_u64_exec" not in req_block


def test_exec_checked_add_no_ghost_int_count_sum() -> None:
    sql = "SELECT a, b, COUNT(*) AS c, SUM(x) AS s FROM t GROUP BY a, b"
    schema = {"t": {"a": "string", "b": "string", "x": "int"}}
    out = transpile_sql_to_verus(sql, schema)
    ret_type = resolve_ret_type_from_method_spec(out)
    rs = multi_agg_step_trusted_rs(out, ret_type)
    bad = _agg_step_exec_checked_add_lines(rs, "str_str__u64_u64")
    assert bad, "expected checked_add lines in agg_step exec"
    assert all("as int" not in ln for ln in bad), bad
    assert any("checked_add(row_u64_0)" in ln.replace(" ", "") for ln in bad)


R10_SQL_PATH = ROOT / "holdout/gendb_sec_edgar/queries_resample_r10.sql"
R10_CHECKED_ADD_QIDS = (1, 2, 4, 6, 8, 10, 12, 15, 20, 22, 26, 28, 29, 30, 32, 38)


@pytest.mark.parametrize("qid", R10_CHECKED_ADD_QIDS)
def test_r10_exec_checked_add_has_no_ghost_int(qid: int) -> None:
    if not R10_SQL_PATH.is_file():
        pytest.skip("r10 holdout SQL missing")
    schema = load_sec_schema()
    flat, multi = normalize_schema(schema)
    queries = dict(parse_sql_file(R10_SQL_PATH))
    sql = queries.get(f"Q{qid}")
    if sql is None:
        pytest.skip(f"Q{qid} missing from r10 holdout")
    projected = project_multi_schema_for_query(sql, multi) if multi else flat
    spec_rs = transpile_sql_to_verus(
        sql, projected, catalog_assumptions=sec_prove_loop_catalog_assumptions()
    )
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    rs = multi_agg_step_trusted_rs(spec_rs, ret_type)
    suffix = ret_type.removeprefix("map_")
    bad = _agg_step_exec_checked_add_lines(rs, suffix)
    if not bad:
        pytest.skip(f"Q{qid} has no checked_add in exec agg_step")
    assert all("as int" not in ln for ln in bad), bad
    assert "wrapping_add" not in rs


def test_multi_agg_case_when_cast_parentheses() -> None:
    """CASE-WHEN row compares in agg_step apply_row parenthesize (row as int) < n."""
    schema = {"num": NUM_SCHEMA, "tag": TAG_SCHEMA}
    out = transpile_sql_to_verus(
        Q26_CASE_WHEN_SQL,
        schema,
        catalog_assumptions=sec_prove_loop_catalog_assumptions(),
    )
    ret_type = resolve_ret_type_from_method_spec(out)
    rs = multi_agg_step_trusted_rs(out, ret_type)
    assert "(row_u64_0 as int) > 0" in rs
    assert "(row_u64_0 as int) < 0" in rs
    assert "row_u64_0 as int < 0" not in rs
    assert "row_u64_0 as int > 0" not in rs


def test_agg_step_requires_no_case_when_exec() -> None:
    """agg_step public requires must not embed exec helpers (case_when_u64_exec)."""
    schema = {"num": NUM_SCHEMA, "tag": TAG_SCHEMA}
    out = transpile_sql_to_verus(
        Q26_CASE_WHEN_SQL,
        schema,
        catalog_assumptions=sec_prove_loop_catalog_assumptions(),
    )
    ret_type = resolve_ret_type_from_method_spec(out)
    rs = multi_agg_step_trusted_rs(out, ret_type)
    suffix = ret_type.removeprefix("map_")
    req_block = rs.split(f"pub exec fn agg_step_{suffix}")[1].split("ensures")[0]
    assert "case_when_u64_exec" not in req_block
    assert "(prev as int) +" not in req_block

def test_sec_q1_agg_step_runquery_verus(tmp_path: Path) -> None:
    from research_loop.bench_standins.sec_q1_runquery import SEC_Q1_RUNQUERY

    spec_rs = transpile_sql_to_verus(
        Q1_LIKE_SQL,
        {"pre": PRE_SCHEMA},
        catalog_assumptions=sec_prove_loop_catalog_assumptions(),
    )
    ret_type = "map_str_str__u64_u64_u64"
    structural_bridge_for_spec_type(
        "Map<(Seq<char>, Seq<char>), (u64, u64, u64)>"
    )
    program = assemble_verified_program(
        spec_rs=spec_rs,
        run_query_body=SEC_Q1_RUNQUERY.strip(),
        schema_dict=PRE_SCHEMA,
        ret_type=ret_type,
        default_tbl=str(tmp_path / "pre.tbl"),
    )
    rs_path = tmp_path / "sec_q1_agg_step.rs"
    rs_path.write_text(program, encoding="utf-8")

    if resolve_verus_bin() is None:
        pytest.skip("verus not found")

    ok, log = run_verus_verify(str(rs_path), timeout=180)
    if not ok:
        pytest.fail(f"verus verify failed:\n{log[-6000:]}")
