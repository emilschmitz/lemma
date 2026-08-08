"""Tests for LEMMA_EXPERIMENT git cleanliness gate."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from research_loop.run_artifacts import assert_experiment_git_clean, begin_run


def test_assert_experiment_git_clean_fails_on_dirty_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "dirty.txt").write_text("x")
    monkeypatch.setenv("LEMMA_EXPERIMENT", "1")
    monkeypatch.delenv("LEMMA_EXPERIMENT_ALLOW_DIRTY", raising=False)
    with pytest.raises(SystemExit, match="clean git working tree"):
        assert_experiment_git_clean(tmp_path)


def test_assert_experiment_git_clean_allows_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "dirty.txt").write_text("x")
    monkeypatch.setenv("LEMMA_EXPERIMENT", "1")
    monkeypatch.setenv("LEMMA_EXPERIMENT_ALLOW_DIRTY", "1")
    assert_experiment_git_clean(tmp_path)


def test_begin_run_records_git_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init", "--allow-empty"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LEMMA_EXPERIMENT", "1")
    run = begin_run(query_id=1, sql_query="SELECT 1", root=tmp_path)
    manifest = __import__("json").loads((run.path / "manifest.json").read_text())
    assert manifest["git_dirty"] is False
    assert manifest["git_commit"] == manifest["git_sha"]
    assert len(manifest["git_commit"]) >= 7
