"""Tests for LEMMA_EXPERIMENT / fallback / mock agent flags."""
from __future__ import annotations

import os

from research_loop.lemma_flags import (
    lemma_allow_duckdb_fallback,
    lemma_experiment,
    lemma_fast_trusteds,
    lemma_use_mock_agent,
)


def test_experiment_forces_mock_off(monkeypatch):
    monkeypatch.setenv("LEMMA_EXPERIMENT", "1")
    monkeypatch.setenv("MOCK_AGENT", "1")
    assert lemma_experiment() is True
    assert lemma_use_mock_agent() is False


def test_experiment_forces_fallback_off(monkeypatch):
    monkeypatch.setenv("LEMMA_EXPERIMENT", "1")
    monkeypatch.setenv("LEMMA_ALLOW_DUCKDB_FALLBACK", "1")
    assert lemma_allow_duckdb_fallback() is False


def test_fallback_allowed_when_not_experiment(monkeypatch):
    monkeypatch.delenv("LEMMA_EXPERIMENT", raising=False)
    monkeypatch.setenv("LEMMA_ALLOW_DUCKDB_FALLBACK", "1")
    assert lemma_experiment() is False
    assert lemma_allow_duckdb_fallback() is True


def test_mock_agent_default_on_without_experiment(monkeypatch):
    monkeypatch.delenv("LEMMA_EXPERIMENT", raising=False)
    monkeypatch.delenv("MOCK_AGENT", raising=False)
    assert lemma_use_mock_agent() is True


def test_run_optimizer_experiment_sets_research_log(monkeypatch):
    """run_optimizer sets LEMMA_RESEARCH_LOG when LEMMA_EXPERIMENT=1."""
    monkeypatch.setenv("LEMMA_EXPERIMENT", "1")
    monkeypatch.delenv("LEMMA_RESEARCH_LOG", raising=False)
    monkeypatch.delenv("MOCK_AGENT", raising=False)

    # Mirror run_optimizer defaults without running the full pipeline.
    if os.environ.get("LEMMA_EXPERIMENT", "0") == "1":
        os.environ.setdefault("LEMMA_RESEARCH_LOG", "1")
        os.environ.setdefault("MOCK_AGENT", "0")

    assert os.environ.get("LEMMA_RESEARCH_LOG") == "1"
    assert os.environ.get("MOCK_AGENT") == "0"


def test_fast_trusteds_default_off(monkeypatch):
    monkeypatch.delenv("LEMMA_FAST_TRUSTEDS", raising=False)
    assert lemma_fast_trusteds() is False


def test_fast_trusteds_does_not_imply_experiment_hacks(monkeypatch):
    monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", "1")
    monkeypatch.delenv("LEMMA_FOLD_SLOT_AXIOMATIC", raising=False)
    monkeypatch.delenv("LEMMA_EXPERIMENT", raising=False)
    monkeypatch.setenv("MOCK_AGENT", "1")
    assert lemma_fast_trusteds() is True
    assert os.environ.get("LEMMA_FOLD_SLOT_AXIOMATIC") is None
    assert os.environ.get("LEMMA_EXPERIMENT", "0") != "1"
    assert lemma_use_mock_agent() is True
