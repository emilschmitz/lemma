"""Tests for LEMMA_FAST_TRUSTEDS and emit_agent_externs wiring."""

from __future__ import annotations

import os
import re

import pytest

from research_loop.agent_primitives.emit_externs import (
    context_has_hashset_with_view_use,
    emit_agent_externs,
    lemma_emit_agent_primitives,
    maybe_emit_agent_externs,
    run_query_references_agent_primitives,
)
from research_loop.assemble_verified_program import _boundary_helpers
from research_loop.lemma_flags import lemma_fast_trusteds

_HASHSET_USE_RE = re.compile(
    r"^use vstd::hash_set::HashSetWithView;\s*$",
    re.MULTILINE,
)
_CORE_INC = (
    __import__("pathlib").Path(__file__).resolve().parent / "verus_externs_core.rs.inc"
)


def _hashset_use_count(text: str) -> int:
    return len(_HASHSET_USE_RE.findall(text))


def test_fast_trusteds_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_FAST_TRUSTEDS", raising=False)
    assert lemma_fast_trusteds() is False


def test_fast_trusteds_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", "1")
    assert lemma_fast_trusteds() is True


def test_emit_agent_primitives_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_EMIT_AGENT_PRIMITIVES", raising=False)
    assert lemma_emit_agent_primitives() is False


def test_emit_agent_primitives_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_EMIT_AGENT_PRIMITIVES", "1")
    assert lemma_emit_agent_primitives() is True


def test_fast_trusteds_emits_core_and_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_EMIT_AGENT_PRIMITIVES", raising=False)
    monkeypatch.delenv("LEMMA_ENABLE_PARALLEL", raising=False)
    monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", "1")
    out = maybe_emit_agent_externs("")
    assert "probe_sum_u64" in out
    assert "par_sum_u64" in out
    assert "par_filter_sum_u64" in out
    assert "par_probe_sum_u64" in out
    assert "par_equijoin_pairs_str" in out
    assert "serial_eq_pairs_str_spec" in out
    assert "thread::scope" in out or "available_parallelism" in out


def test_emit_agent_primitives_core_only_without_parallel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEMMA_EMIT_AGENT_PRIMITIVES", "1")
    monkeypatch.delenv("LEMMA_ENABLE_PARALLEL", raising=False)
    monkeypatch.delenv("LEMMA_FAST_TRUSTEDS", raising=False)
    assert lemma_emit_agent_primitives() is True
    out = emit_agent_externs()
    assert "probe_sum_u64" in out
    assert "par_sum_u64" not in out


def test_fast_trusteds_does_not_imply_experiment_hacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", "1")
    monkeypatch.delenv("LEMMA_FOLD_SLOT_AXIOMATIC", raising=False)
    monkeypatch.delenv("LEMMA_EXPERIMENT", raising=False)
    monkeypatch.setenv("MOCK_AGENT", "1")
    assert os.environ.get("LEMMA_FOLD_SLOT_AXIOMATIC") is None
    assert os.environ.get("LEMMA_EXPERIMENT", "0") != "1"


def test_maybe_emit_empty_without_flags_or_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LEMMA_EMIT_AGENT_PRIMITIVES", raising=False)
    monkeypatch.delenv("LEMMA_FAST_TRUSTEDS", raising=False)
    assert maybe_emit_agent_externs("") == ""
    assert maybe_emit_agent_externs("// trivial run_query") == ""


def test_maybe_emit_on_primitive_reference_without_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LEMMA_EMIT_AGENT_PRIMITIVES", raising=False)
    monkeypatch.delenv("LEMMA_FAST_TRUSTEDS", raising=False)
    body = "let s = build_hashset_u32(&keys, 4);"
    assert run_query_references_agent_primitives(body)
    out = maybe_emit_agent_externs(body)
    assert "build_hashset_u32" in out


def test_emit_agent_externs_single_hashset_use_without_context() -> None:
    out = emit_agent_externs(context="")
    assert _hashset_use_count(out) == 1


def test_emit_agent_externs_skips_hashset_use_when_context_has_import() -> None:
    boundary = _boundary_helpers("map_str_str__u64_u64_u64", None)
    out = emit_agent_externs(context=boundary)
    assert _hashset_use_count(out) == 0
    assert _hashset_use_count(boundary + out) == 1


def test_context_has_hashset_with_view_use() -> None:
    assert context_has_hashset_with_view_use("use vstd::hash_set::HashSetWithView;\n")
    assert not context_has_hashset_with_view_use("HashSetWithView::new()")


def test_hashset_u32_keys_from_seq_uses_fold_not_set_new_predicate() -> None:
    src = _CORE_INC.read_text(encoding="utf-8")
    assert "pub open spec fn hashset_u32_keys_from_seq(keys: Seq<u32>) -> Set<u32>" in src
    assert "Set::new(|k: u32|" not in src
    assert "hashset_u32_keys_from_seq_fold" in src
    assert "Set::empty()" in src


def test_enable_parallel_flag_adds_par_externs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_EMIT_AGENT_PRIMITIVES", "1")
    monkeypatch.setenv("LEMMA_ENABLE_PARALLEL", "1")
    monkeypatch.delenv("LEMMA_FAST_TRUSTEDS", raising=False)
    out = emit_agent_externs()
    assert "par_sum_u64" in out


def test_run_query_references_agent_primitives_symbol_set() -> None:
    assert run_query_references_agent_primitives("probe_sum_u64(&a, &b, &set)")
    assert run_query_references_agent_primitives("decode_dict_str(&c, &d, i)")
    assert not run_query_references_agent_primitives("HashMapWithView::new()")
