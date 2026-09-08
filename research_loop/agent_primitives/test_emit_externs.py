"""Tests for LEMMA_FAST_TRUSTEDS and emit_agent_externs wiring."""

from __future__ import annotations

import os

from research_loop.agent_primitives.emit_externs import (
    emit_agent_externs,
    lemma_emit_agent_primitives,
    maybe_emit_agent_externs,
)
from research_loop.lemma_flags import lemma_fast_trusteds


def test_fast_trusteds_default_off(monkeypatch):
    monkeypatch.delenv("LEMMA_FAST_TRUSTEDS", raising=False)
    assert lemma_fast_trusteds() is False


def test_fast_trusteds_on(monkeypatch):
    monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", "1")
    assert lemma_fast_trusteds() is True


def test_fast_trusteds_emits_core_and_parallel(monkeypatch):
    monkeypatch.delenv("LEMMA_EMIT_AGENT_PRIMITIVES", raising=False)
    monkeypatch.delenv("LEMMA_ENABLE_PARALLEL", raising=False)
    monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", "1")
    out = maybe_emit_agent_externs("")
    assert "probe_sum_u64" in out
    assert "par_sum_u64" in out
    assert "par_filter_sum_u64" in out


def test_emit_agent_primitives_core_only_without_parallel(monkeypatch):
    monkeypatch.setenv("LEMMA_EMIT_AGENT_PRIMITIVES", "1")
    monkeypatch.delenv("LEMMA_ENABLE_PARALLEL", raising=False)
    monkeypatch.delenv("LEMMA_FAST_TRUSTEDS", raising=False)
    assert lemma_emit_agent_primitives() is True
    out = emit_agent_externs()
    assert "probe_sum_u64" in out
    assert "par_sum_u64" not in out


def test_fast_trusteds_does_not_imply_experiment_hacks(monkeypatch):
    monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", "1")
    monkeypatch.delenv("LEMMA_FOLD_SLOT_AXIOMATIC", raising=False)
    monkeypatch.delenv("LEMMA_EXPERIMENT", raising=False)
    monkeypatch.setenv("MOCK_AGENT", "1")
    assert os.environ.get("LEMMA_FOLD_SLOT_AXIOMATIC") is None
    assert os.environ.get("LEMMA_EXPERIMENT", "0") != "1"
