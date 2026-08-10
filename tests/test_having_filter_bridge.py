"""Tests for HAVING apply_having_filter_exec TRUSTED helpers."""

from __future__ import annotations

from pathlib import Path

from verus_transpiler.column_projection import project_multi_schema_for_query
from verus_transpiler.parse_sql import normalize_schema

from research_loop.admit_agent_runquery import admit_agent_runquery
from research_loop.assemble_verified_program import prepare_agent_visible_spec
from research_loop.having_filter_bridge import (
    emit_having_filter_trusted,
    parse_having_filter_layout,
)
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema
from research_loop.trusted_ret_bridge import get_bridge
from verus_transpiler import transpile_sql_to_verus

ROOT = Path(__file__).resolve().parents[1]
Q9_SQL = (ROOT / "research_loop/generated/prove_loop/q9/query.sql").read_text(encoding="utf-8")


def _agent_visible_for_sec_sql(sql: str) -> str:
    schema = load_sec_schema()
    _flat, multi = normalize_schema(schema)
    projected = project_multi_schema_for_query(sql, multi) if multi else _flat
    spec_rs = transpile_sql_to_verus(sql, projected)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    return prepare_agent_visible_spec(spec_rs, ret_type)


def test_parse_having_filter_layout_from_q9() -> None:
    schema = load_sec_schema()
    _flat, multi = normalize_schema(schema)
    projected = project_multi_schema_for_query(Q9_SQL, multi)
    spec_rs = transpile_sql_to_verus(Q9_SQL, projected)
    layout = parse_having_filter_layout(spec_rs)
    assert layout is not None
    assert "v: (u64, u64)" in layout.closure_params
    assert layout.closure_body == "(v.0 > 5)"


def test_q9_visible_spec_includes_having_exec() -> None:
    visible = _agent_visible_for_sec_sql(Q9_SQL)
    assert "pub exec fn apply_having_filter_exec_str_str__u64_u64" in visible
    idx = visible.find("pub exec fn apply_having_filter_exec_str_str__u64_u64")
    window = visible[max(0, idx - 200) : idx + 80]
    assert "external_body" in window


def test_emit_having_filter_stable_name_and_predicate() -> None:
    schema = load_sec_schema()
    _flat, multi = normalize_schema(schema)
    projected = project_multi_schema_for_query(Q9_SQL, multi)
    spec_rs = transpile_sql_to_verus(Q9_SQL, projected)
    layout = parse_having_filter_layout(spec_rs)
    assert layout is not None
    bridge = get_bridge("map_str_str__u64_u64")
    assert bridge is not None
    rs = emit_having_filter_trusted(layout, bridge)
    assert "apply_having_filter_exec_str_str__u64_u64" in rs
    assert ".filter(|(_k, v)| (v.0 > 5))" in rs
    assert rs.count("external_body") == 1


def test_scalar_map_having_emits_exec() -> None:
    sql = "SELECT k, COUNT(*) AS c FROM t GROUP BY k HAVING COUNT(*) > 5"
    schema = {"k": "int"}
    spec_rs = transpile_sql_to_verus(sql, schema)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    visible = prepare_agent_visible_spec(spec_rs, ret_type)
    assert ret_type == "map_u32_u64"
    assert "apply_having_filter_exec_u32_u64" in visible
    assert ".filter(|(_k, v)| (v > 5))" in visible


def test_admission_rejects_agent_having_external_body_helper() -> None:
    from research_loop.assemble_runquery import (
        AGENT_EDIT_END,
        AGENT_EDIT_START,
        build_runquery_agent_source,
    )

    schema = load_sec_schema()
    _flat, multi = normalize_schema(schema)
    projected = project_multi_schema_for_query(Q9_SQL, multi)
    spec_rs = transpile_sql_to_verus(Q9_SQL, projected)
    visible = prepare_agent_visible_spec(spec_rs, "map_str_str__u64_u64")
    fn = (
        "pub exec fn run_query(pre: &Cols_pre, tag: &Cols_tag) -> "
        "(res: HashMap<(String, String), (u64, u64)>)\n"
        "    requires valid_cols_pre(pre), valid_cols_tag(tag),\n"
        "    ensures hashmap_str_str__u64_u64_view(res@) == method_spec(pre, tag),\n"
        "{\n"
        "    #[verifier::external_body]\n"
        "    fn apply_having_filter_exec_cheat(hm: HashMap<(String, String), (u64, u64)>) "
        "-> HashMap<(String, String), (u64, u64)> { hm }\n"
        "    apply_having_filter_exec_str_str__u64_u64(HashMap::new())\n"
        "}"
    )
    src = build_runquery_agent_source(
        ret_type="map_str_str__u64_u64",
        method_spec_rs=spec_rs,
    )
    start = src.index(AGENT_EDIT_START) + len(AGENT_EDIT_START)
    end = src.index(AGENT_EDIT_END)
    src = src[:start] + "\n" + fn + "\n" + src[end:]
    result = admit_agent_runquery(src, method_spec_rs=visible)
    assert not result.ok
    assert any("external_body" in v for v in result.violations)


def test_having_oracle_matches_exec_retain() -> None:
    from research_loop.trusted_semantic_oracle import apply_having_filter_oracle

    hm = {("a", "b"): (10, 3), ("c", "d"): (4, 1)}
    out = apply_having_filter_oracle(hm, "(v.0 > 5)")
    assert out == {("a", "b"): (10, 3)}
