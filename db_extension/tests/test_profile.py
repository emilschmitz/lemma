"""Tests for agent data profile markdown."""
from __future__ import annotations

from pathlib import Path

import pytest

from db_extension.agent.profile import build_data_profile


@pytest.fixture
def tiny_csv(tmp_path: Path) -> Path:
    p = tmp_path / "sample.tbl"
    p.write_text("id|amount\n1|10\n2|20\n")
    return p


def test_profile_none_duck_explain_includes_summarize_explain(
    tiny_csv: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEMMA_AGENT_DUCK_EXPLAIN", "1")
    md = build_data_profile(tiny_csv, "SELECT SUM(amount) FROM sample", "none")
    assert "## SUMMARIZE" in md
    assert "## EXPLAIN" in md or "EXPLAIN (target SQL)" in md
    assert "## Target SQL" in md
    assert "## Column types" not in md


def test_profile_none_without_duck_explain_is_minimal(
    tiny_csv: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEMMA_AGENT_DUCK_EXPLAIN", "0")
    md = build_data_profile(tiny_csv, "SELECT 1", "none")
    assert "SUMMARIZE" not in md
    assert "EXPLAIN" not in md
    assert "Target SQL (reference)" in md
