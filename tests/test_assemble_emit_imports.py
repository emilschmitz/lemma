"""Assemble + emit import dedupe: HashSetWithView must appear exactly once."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from db_extension.workload_config import catalog_assumptions_for_workload
from research_loop.agent_primitives.emit_externs import (
    context_has_hashset_with_view_use,
    emit_agent_externs,
    maybe_emit_agent_externs,
)
from research_loop.assemble_verified_program import (
    _boundary_helpers,
    assemble_verified_program,
)
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.trusted_ret_bridge import get_bridge
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

_HASHSET_WITH_VIEW_USE_RE = re.compile(
    r"^use vstd::hash_set::HashSetWithView;\s*$",
    re.MULTILINE,
)
_CORE_INC_PATH = Path(__file__).resolve().parents[1] / (
    "research_loop/agent_primitives/verus_externs_core.rs.inc"
)


def _hashset_with_view_use_count(text: str) -> int:
    return len(_HASHSET_WITH_VIEW_USE_RE.findall(text))


def _q1_assemble_program(
    monkeypatch: pytest.MonkeyPatch,
    *,
    emit: str | None = None,
    fast_trusteds: str | None = None,
    run_query_body: str | None = None,
) -> str:
    if emit is None:
        monkeypatch.delenv("LEMMA_EMIT_AGENT_PRIMITIVES", raising=False)
    else:
        monkeypatch.setenv("LEMMA_EMIT_AGENT_PRIMITIVES", emit)

    if fast_trusteds is None:
        monkeypatch.delenv("LEMMA_FAST_TRUSTEDS", raising=False)
    else:
        monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", fast_trusteds)

    monkeypatch.delenv("LEMMA_ENABLE_PARALLEL", raising=False)

    spec_rs = transpile_sql_to_verus(
        Q1_LIKE_SQL,
        {"pre": PRE_SCHEMA},
        catalog_assumptions=catalog_assumptions_for_workload("sec"),
    )
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    assert ret_type == "map_str_str__u64_u64_u64"

    bridge = get_bridge(ret_type)
    assert bridge is not None
    body = run_query_body or f"""#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: {bridge.rust_ret})
    requires valid_cols(cols),
    ensures {bridge.ensures}
{{
    HashMapWithView::new()
}}"""

    return assemble_verified_program(
        spec_rs=spec_rs,
        run_query_body=body,
        schema_dict=PRE_SCHEMA,
        ret_type=ret_type,
        default_tbl="/tmp/pre.tbl",
    )


def test_default_rocket_assemble_count_distinct_exactly_one_hashset_with_view_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = _q1_assemble_program(monkeypatch, emit="0", fast_trusteds="0")
    assert _hashset_with_view_use_count(program) == 1
    assert "set_insert_str" in program


def test_emit_agent_primitives_assemble_count_distinct_exactly_one_hashset_with_view_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = _q1_assemble_program(monkeypatch, emit="1", fast_trusteds="0")
    assert _hashset_with_view_use_count(program) == 1
    assert "probe_sum_u64" in program
    assert "build_hashset_u32" in program
    assert "par_sum_u64" not in program


def test_fast_trusteds_assemble_count_distinct_exactly_one_hashset_with_view_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = _q1_assemble_program(monkeypatch, emit="0", fast_trusteds="1")
    assert _hashset_with_view_use_count(program) == 1
    assert "probe_sum_u64" in program
    assert "par_sum_u64" in program
    assert "par_filter_sum_u64" in program


def test_emit_and_fast_trusteds_assemble_count_distinct_exactly_one_hashset_with_view_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = _q1_assemble_program(monkeypatch, emit="1", fast_trusteds="1")
    assert _hashset_with_view_use_count(program) == 1
    assert "probe_sum_u64" in program
    assert "par_sum_u64" in program


def test_spliced_program_never_contains_duplicate_hashset_with_view_use_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    combos = (
        ("0", "0"),
        ("1", "0"),
        ("0", "1"),
        ("1", "1"),
    )
    for emit, fast in combos:
        program = _q1_assemble_program(
            monkeypatch, emit=emit, fast_trusteds=fast
        )
        lines = _HASHSET_WITH_VIEW_USE_RE.findall(program)
        assert len(lines) == 1, f"EMIT={emit} FAST_TRUSTEDS={fast}: {len(lines)} uses"
        assert program.count("use vstd::hash_set::HashSetWithView;") == 1


def test_hashset_u32_keys_from_seq_source_returns_set_not_option_set_new() -> None:
    src = _CORE_INC_PATH.read_text(encoding="utf-8")
    m = re.search(
        r"pub open spec fn hashset_u32_keys_from_seq\(keys: Seq<u32>\) -> Set<u32> \{[\s\S]*?\n\}",
        src,
    )
    assert m is not None, "hashset_u32_keys_from_seq definition missing"
    body = m.group(0)
    assert "-> Set<u32>" in body
    assert "Set::new(|" not in body
    assert "hashset_u32_keys_from_seq_fold" in body
    fold_m = re.search(
        r"pub open spec fn hashset_u32_keys_from_seq_fold[\s\S]*?\n\}",
        src,
    )
    assert fold_m is not None
    fold_body = fold_m.group(0)
    assert "Set::empty()" in fold_body
    assert ".insert(keys[i])" in fold_body


def test_default_rocket_does_not_emit_probe_or_par_unless_referenced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = _q1_assemble_program(monkeypatch, emit="0", fast_trusteds="0")
    assert "probe_sum_u64" not in program
    assert "par_sum_u64" not in program
    assert "build_hashset_u32" not in program


def test_default_rocket_emits_probe_when_run_query_references_build_hashset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = get_bridge("map_str_str__u64_u64_u64")
    assert bridge is not None
    body = f"""#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: {bridge.rust_ret})
    requires valid_cols(cols),
    ensures {bridge.ensures}
{{
    let _ = build_hashset_u32(&cols.adsh, 0);
    HashMapWithView::new()
}}"""
    program = _q1_assemble_program(
        monkeypatch,
        emit="0",
        fast_trusteds="0",
        run_query_body=body,
    )
    assert "build_hashset_u32" in program
    assert _hashset_with_view_use_count(program) == 1


def test_emit_agent_externs_omits_hashset_use_when_boundary_already_has_it() -> None:
    boundary = _boundary_helpers("map_str_str__u64_u64_u64", None)
    assert context_has_hashset_with_view_use(boundary)
    out = emit_agent_externs(context=boundary)
    assert _hashset_with_view_use_count(out) == 0
    assert "build_hashset_u32" in out


def test_emit_agent_externs_prepends_hashset_use_without_boundary_context() -> None:
    out = emit_agent_externs(context="")
    assert _hashset_with_view_use_count(out) == 1
    assert out.startswith("use vstd::hash_set::HashSetWithView;")


def test_maybe_emit_respects_fast_trusteds_without_duplicate_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", "1")
    boundary = _boundary_helpers("map_str_str__u64_u64_u64", None)
    out = maybe_emit_agent_externs(context=boundary)
    assert "probe_sum_u64" in out
    assert _hashset_with_view_use_count(boundary + out) == 1


def test_fast_trusteds_does_not_enable_fold_slot_axiomatic_or_experiment_allow_dirty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", "1")
    monkeypatch.delenv("LEMMA_FOLD_SLOT_AXIOMATIC", raising=False)
    monkeypatch.delenv("LEMMA_EXPERIMENT_ALLOW_DIRTY", raising=False)
    monkeypatch.delenv("LEMMA_EXPERIMENT", raising=False)
    _q1_assemble_program(monkeypatch, emit="0", fast_trusteds="1")
    assert os.environ.get("LEMMA_FOLD_SLOT_AXIOMATIC") is None
    assert os.environ.get("LEMMA_EXPERIMENT_ALLOW_DIRTY") is None
    assert os.environ.get("LEMMA_EXPERIMENT", "0") != "1"


def test_context_has_hashset_with_view_use_detects_boundary_helpers() -> None:
    boundary = _boundary_helpers("map_str_str__u64_u64_u64", None)
    assert context_has_hashset_with_view_use(boundary)
    assert not context_has_hashset_with_view_use("// no hash set import here")


def test_prepare_boundary_and_emit_combined_single_hashset_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEMMA_EMIT_AGENT_PRIMITIVES", "1")
    spec_rs = transpile_sql_to_verus(
        Q1_LIKE_SQL,
        {"pre": PRE_SCHEMA},
        catalog_assumptions=catalog_assumptions_for_workload("sec"),
    )
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    boundary = _boundary_helpers(ret_type, spec_rs)
    agent_externs = maybe_emit_agent_externs("", context=boundary)
    combined = boundary + "\n" + agent_externs
    assert _hashset_with_view_use_count(combined) == 1
