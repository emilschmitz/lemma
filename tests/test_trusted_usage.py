"""Tests for Trusted helper menu / usage harvesting."""
from __future__ import annotations

from research_loop.trusted_usage import (
    list_trusted_menu,
    scan_trusted_used,
    trusted_usage_report,
)


_FAKE_SPEC = """
pub exec fn agg_new_str_u64() -> (hm: HashMap<String, u64>) { HashMap::new() }
pub exec fn agg_add_str_u64(hm: &mut HashMap<String, u64>, k: String) { }
pub exec fn set_insert_str(s: &mut Set<String>, k: String) -> (is_new: bool) { true }
pub open spec fn hashmap_str_u64_view(hm: Map<Seq<char>, u64>) -> Map<Seq<char>, u64> { hm }
pub struct AggStepState_str_u64 {
    pub projected: HashMap<String, u64>,
    pub inner: HashMap<String, (u64, u64)>,
}
pub exec fn agg_step_state_new_str_u64() -> (st: AggStepState_str_u64) { arbitrary() }
pub exec fn agg_step_str_u64(st: &mut AggStepState_str_u64, k: String) { }
"""


def test_list_trusted_menu_exec_views_and_state() -> None:
    menu = list_trusted_menu(_FAKE_SPEC)
    assert "agg_new_str_u64" in menu
    assert "agg_add_str_u64" in menu
    assert "set_insert_str" in menu
    assert "hashmap_str_u64_view" in menu
    assert "AggStepState_str_u64" in menu
    assert "agg_step_str_u64" in menu
    assert "agg_step_state_new_str_u64" in menu


def test_scan_trusted_used_body_helpers() -> None:
    menu = list_trusted_menu(_FAKE_SPEC)
    body = """
    let mut st = agg_step_state_new_str_u64();
    agg_step_str_u64(&mut st, key);
    let mut hm = agg_new_str_u64();
    agg_add_str_u64(&mut hm, key);
  // set_insert_str mentioned only in comment
    st.projected
    """
    used = scan_trusted_used(body, menu)
    assert used == [
        "agg_add_str_u64",
        "agg_new_str_u64",
        "agg_step_state_new_str_u64",
        "agg_step_str_u64",
    ]
    assert "set_insert_str" not in used
    assert "AggStepState_str_u64" not in used


def test_trusted_usage_report_unused_listed() -> None:
    body = "let hm = agg_new_str_u64(); hm"
    report = trusted_usage_report(_FAKE_SPEC, body)
    assert report["trusted_used"] == ["agg_new_str_u64"]
    assert "agg_add_str_u64" in report["trusted_unused"]
    assert "set_insert_str" in report["trusted_unused"]
    assert report["trusted_menu_count"] == len(report["trusted_menu"])
    assert report["trusted_used_count"] == 1
    assert report["trusted_unused_count"] == len(report["trusted_unused"])


def test_admit_result_includes_trusted_fields() -> None:
    from research_loop.admit_agent_runquery import admit_agent_runquery
    from research_loop.assemble_runquery import build_runquery_agent_source
    from verus_transpiler import transpile_sql_to_verus

    spec = transpile_sql_to_verus("SELECT SUM(V) FROM t", {"V": "bigint"})
    src = build_runquery_agent_source(ret_type="u64", body_inner="42u64")
    result = admit_agent_runquery(src, method_spec_rs=spec)
    assert result.trusted_menu is not None
    assert result.trusted_used is not None
    assert isinstance(result.trusted_menu, list)
    assert isinstance(result.trusted_used, list)
