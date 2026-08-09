"""Adversarial tests for Trusted / admission / MethodSpec scaffold surfaces.

Default style: try to cheat, escape the menu, weaken ensures, or fake success.
See docs/ADVERSARIAL_TESTS.md. Admission happy-path + cheat matrix lives in
tests/test_admit_agent_runquery.py — this file fills gaps and cross-surface attacks.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError

from research_loop.admit_agent_runquery import admit_agent_runquery
from research_loop.assemble_runquery import (
    AGENT_EDIT_END,
    AGENT_EDIT_START,
    build_runquery_agent_source,
    host_edit_fingerprint,
    write_runquery_agent_file,
)
from research_loop.assemble_verified_program import prepare_agent_visible_spec
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.scripts.sqlsmith_trusted_coverage import classify_query
from research_loop.trusted_ret_bridge import get_bridge, structural_bridge_for_spec_type
from research_loop.trusted_usage import list_trusted_menu, scan_trusted_used
from tests.test_sec_holdout_parse import (
    SEC_QUERIES,
    SEC_SCHEMA,
    _fold_helpers,
    _fold_helpers_have_no_arbitrary,
)
from verus_transpiler import transpile_sql_to_verus

_SCALAR_SQL = "SELECT SUM(V) FROM t"
_SCALAR_SCHEMA = {"V": "bigint"}

Q1_LIKE_SQL = """SELECT stmt, rfile, COUNT(*) AS cnt,
       COUNT(DISTINCT adsh) AS num_filings,
       AVG(line) AS avg_line_num
FROM pre
WHERE stmt IS NOT NULL
GROUP BY stmt, rfile"""

_VACUOUS_TRUSTED_RUN_QUERY_RE = re.compile(
    r"#\[verifier::external_body\]\s*pub\s+exec\s+fn\s+run_query",
    re.MULTILINE,
)


def _scalar_spec() -> str:
    return transpile_sql_to_verus(_SCALAR_SQL, _SCALAR_SCHEMA)


def _replace_edit_region(source: str, new_fn: str) -> str:
    start = source.index(AGENT_EDIT_START) + len(AGENT_EDIT_START)
    end = source.index(AGENT_EDIT_END)
    return source[:start] + "\n" + new_fn + "\n" + source[end:]


def _admit(source: str, spec_rs: str, *, fp: str | None = None):
    return admit_agent_runquery(source, method_spec_rs=spec_rs, expected_fingerprint=fp)


def _agent_visible_for_sql(sql: str, schema: dict) -> str:
    spec_rs = transpile_sql_to_verus(sql, schema)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    return prepare_agent_visible_spec(spec_rs, ret_type)


# --- Admission escape gaps (see test_admit_agent_runquery.py for the main matrix) ---


@pytest.mark.parametrize(
    "cheat_body",
    [
        "#[verifier::admit]\n    0u64",
        "proof { admit(); }\n    0u64",
        "#[verifier::external_body]\n    fn cheat() {}\n    0u64",
    ],
    ids=["verifier-admit-attr", "admit-call", "external-body-helper"],
)
def test_admission_rejects_trust_expansion_in_edit(cheat_body: str) -> None:
    spec = _scalar_spec()
    src = build_runquery_agent_source(ret_type="u64", body_inner=cheat_body)
    result = _admit(src, spec)
    assert not result.ok, result.violations


def test_admission_rejects_ensures_without_method_spec() -> None:
    spec = _scalar_spec()
    fn = (
        "pub exec fn run_query(cols: &Cols) -> (res: u64)\n"
        "    requires valid_cols(cols),\n"
        "    ensures res == 42u64,\n"
        "{\n    42u64\n}"
    )
    result = _admit(_replace_edit_region(build_runquery_agent_source(ret_type="u64"), fn), spec)
    assert not result.ok
    assert any("ensures" in v.lower() or "method_spec" in v for v in result.violations)


def test_admission_rejects_host_shell_tamper_outside_edit_markers(tmp_path: Path) -> None:
    """Fingerprint covers host shell outside AGENT_EDIT — not only MethodSpec comments."""
    spec = _scalar_spec()
    dest = tmp_path / "runquery_agent.rs"
    write_runquery_agent_file(dest, ret_type="u64", body_inner="1u64")
    source = dest.read_text(encoding="utf-8")
    fp = host_edit_fingerprint(source)
    tampered = source.replace(
        "//! Host-owned shell — edit ONLY between AGENT_EDIT_START/END.",
        "//! Host-owned shell — TAMPERED outside AGENT_EDIT.",
    )
    result = _admit(tampered, spec, fp=fp)
    assert not result.ok
    assert any("tampered" in v or "fingerprint" in v for v in result.violations)


# --- Trusted usage logging adversarial ---


_FAKE_SPEC = """
pub exec fn agg_new_str_u64() -> (hm: HashMap<String, u64>) { HashMap::new() }
pub exec fn agg_add_str_u64(hm: &mut HashMap<String, u64>, k: String) { }
pub exec fn agg_add_str_u64_extra(hm: &mut HashMap<String, u64>, k: String) { }
pub open spec fn hashmap_str_u64_view(hm: Map<Seq<char>, u64>) -> Map<Seq<char>, u64> { hm }
"""


def test_trusted_used_ignores_comment_and_string_mentions() -> None:
    menu = list_trusted_menu(_FAKE_SPEC)
    body = '''
    let hm = agg_new_str_u64();
    // agg_add_str_u64 is not a call
    let _s = "agg_add_str_u64";
    hm
    '''
    assert scan_trusted_used(body, menu) == ["agg_new_str_u64"]


def test_trusted_used_word_boundary_not_substring() -> None:
    menu = list_trusted_menu(_FAKE_SPEC)
    body = "agg_add_str_u64_extra(&mut hm, key); hm"
    used = scan_trusted_used(body, menu)
    assert "agg_add_str_u64" not in used
    assert used == ["agg_add_str_u64_extra"]


def test_trusted_used_empty_body() -> None:
    menu = list_trusted_menu(_FAKE_SPEC)
    assert scan_trusted_used("", menu) == []
    assert scan_trusted_used("   \n  // only comments\n", menu) == []


# --- Multi-agg / agg_step surface ---


def test_q1_method_spec_fold_not_arbitrary() -> None:
    out = transpile_sql_to_verus(Q1_LIKE_SQL, {"pre": SEC_SCHEMA["pre"]})
    helpers = _fold_helpers(out)
    assert helpers
    assert _fold_helpers_have_no_arbitrary(out)
    assert "decreases" in out


def test_agg_step_helpers_external_body_not_whole_query_run_query() -> None:
    out = transpile_sql_to_verus(Q1_LIKE_SQL, {"pre": SEC_SCHEMA["pre"]})
    visible = _agent_visible_for_sql(Q1_LIKE_SQL, {"pre": SEC_SCHEMA["pre"]})
    assert "agg_step_str_str__u64_u64_u64" in visible
    assert visible.count("external_body") >= 1
    assert "pub exec fn run_query" not in visible
    assert not _VACUOUS_TRUSTED_RUN_QUERY_RE.search(visible)
    helpers = _fold_helpers(out)
    assert helpers
    assert _fold_helpers_have_no_arbitrary(out)


def test_sec_q1_standin_has_no_admit() -> None:
    from research_loop.bench_standins.sec_q1_runquery import SEC_Q1_RUNQUERY

    body = SEC_Q1_RUNQUERY
    assert "admit(" not in body
    assert "#[verifier::admit" not in body


# --- Holdout shell vs cheat ---


@pytest.mark.parametrize("qnum,sql", SEC_QUERIES, ids=[f"Q{q}" for q, _ in SEC_QUERIES])
def test_holdout_shell_builds_without_vacuous_trusted_run_query(qnum: str, sql: str) -> None:
    result = classify_query(sql, f"Q{qnum}", SEC_SCHEMA)
    assert result.status == "ok_shell", f"Q{qnum}: {result.status} {result.reason}"

    visible = _agent_visible_for_sql(sql, SEC_SCHEMA)
    assert "pub exec fn run_query" not in visible
    assert not _VACUOUS_TRUSTED_RUN_QUERY_RE.search(visible)
    assert "unimplemented!" not in visible

    spec_rs = transpile_sql_to_verus(sql, SEC_SCHEMA)
    helpers = _fold_helpers(spec_rs)
    assert helpers, f"Q{qnum} must emit recursive MethodSpec fold helpers"
    assert _fold_helpers_have_no_arbitrary(spec_rs)


# --- Loud fail preferred (no re-mocking unsupported shapes) ---


def test_in_inner_groupby_still_raises_unsupported() -> None:
    sql = """SELECT e.entity_id, e.name,
       COUNT(DISTINCT e.kind) AS kinds,
       COUNT(*) AS total
FROM events e
WHERE e.entity_id IN (
    SELECT entity_id FROM events
    WHERE year = 2022
    GROUP BY entity_id
    HAVING COUNT(DISTINCT kind) > 1
)
GROUP BY e.entity_id, e.name"""
    schema = {
        "events": {
            "entity_id": "int",
            "name": "string",
            "kind": "string",
            "year": "int",
        },
    }
    with pytest.raises(UnsupportedContractError, match="IN inner GROUP BY"):
        transpile_sql_to_verus(sql, schema)


def test_multi_agg_visible_spec_bridge_is_structural_not_arbitrary() -> None:
    out = transpile_sql_to_verus(Q1_LIKE_SQL, {"pre": SEC_SCHEMA["pre"]})
    bridge = structural_bridge_for_spec_type("Map<(Seq<char>, Seq<char>), (u64, u64, u64)>")
    assert bridge is not None
    visible = prepare_agent_visible_spec(out, bridge.key)
    assert get_bridge(bridge.key) is not None
    helper = re.findall(
        r"pub open spec fn method_spec_helper[\s\S]*?^}",
        visible,
        re.MULTILINE,
    )[0]
    assert "arbitrary()" not in helper
