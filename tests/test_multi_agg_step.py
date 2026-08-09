"""Tests for multi-agg agg_step TRUSTED helpers."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from research_loop.assemble_verified_program import assemble_verified_program, prepare_agent_visible_spec
from research_loop.harness import resolve_verus_bin, run_verus_verify
from research_loop.multi_agg_step_bridge import (
    emit_multi_agg_step_trusted,
    parse_multi_agg_layout,
)
from research_loop.trusted_ret_bridge import get_bridge, structural_bridge_for_spec_type
from verus_transpiler import transpile_sql_to_verus

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


def test_parse_q1_multi_agg_layout() -> None:
    out = transpile_sql_to_verus(Q1_LIKE_SQL, {"pre": PRE_SCHEMA})
    layout = parse_multi_agg_layout(out)
    assert layout is not None
    assert layout.helper_name == "method_spec_helper"
    names = [p.name for p in layout.row_params]
    assert "distinct_0" in names
    assert any(n.startswith("row_u64_") for n in names)
    assert "arbitrary()" not in layout.apply_body


def test_emit_agg_step_stable_names() -> None:
    out = transpile_sql_to_verus(Q1_LIKE_SQL, {"pre": PRE_SCHEMA})
    layout = parse_multi_agg_layout(out)
    assert layout is not None
    bridge = structural_bridge_for_spec_type(
        "Map<(Seq<char>, Seq<char>), (u64, u64, u64)>"
    )
    rs = emit_multi_agg_step_trusted(layout, bridge)
    for name in (
        "AggStepState_str_str__u64_u64_u64",
        "agg_step_inner_str_str__u64_u64_u64_view",
        "agg_step_project_str_str__u64_u64_u64",
        "agg_step_apply_row_str_str__u64_u64_u64",
        "agg_step_state_new_str_str__u64_u64_u64",
        "agg_step_str_str__u64_u64_u64",
    ):
        assert name in rs
    assert rs.count("external_body") >= 3


def test_prepare_agent_visible_spec_includes_agg_step() -> None:
    out = transpile_sql_to_verus(Q1_LIKE_SQL, {"pre": PRE_SCHEMA})
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


def test_sec_q1_agg_step_runquery_verus(tmp_path: Path) -> None:
    from research_loop.bench_standins.sec_q1_runquery import SEC_Q1_RUNQUERY

    spec_rs = transpile_sql_to_verus(Q1_LIKE_SQL, {"pre": PRE_SCHEMA})
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
