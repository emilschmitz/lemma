"""Tests for research_loop/scripts/gcp_experiment_preflight.sh."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "research_loop" / "scripts" / "gcp_experiment_preflight.sh"


def _init_pushed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    origin = tmp_path / "origin.git"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("ok\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(origin)],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo, check=True, capture_output=True)
    return repo


def _run_preflight(
    repo: Path,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    run_env.pop("LEMMA_EXPERIMENT_ALLOW_DIRTY", None)
    run_env.setdefault("LEMMA_PREFLIGHT_SSH", "0")
    if env:
        run_env.update(env)
    return subprocess.run(
        ["bash", str(PREFLIGHT)],
        cwd=repo,
        env=run_env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_preflight_dirty_local_tree_exits_1(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    (repo / "dirty.txt").write_text("x")
    proc = _run_preflight(repo, env={"LEMMA_FAMILY": "r23rocket"})
    assert proc.returncode == 1
    assert "ERROR:" in proc.stderr
    assert "dirty" in proc.stderr.lower()


def test_preflight_allow_dirty_refused(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    proc = _run_preflight(
        repo,
        env={"LEMMA_FAMILY": "r23rocket", "LEMMA_EXPERIMENT_ALLOW_DIRTY": "1"},
    )
    assert proc.returncode == 1
    assert "ALLOW_DIRTY" in proc.stderr


def test_preflight_head_not_on_origin_exits_1(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    (repo / "README.md").write_text("local only\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "unpushed"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    proc = _run_preflight(repo, env={"LEMMA_FAMILY": "r23rocket"})
    assert proc.returncode == 1
    assert "ERROR:" in proc.stderr
    assert "ancestor" in proc.stderr.lower() or "push" in proc.stderr.lower()


def test_preflight_rocket_emit_on_exits_1(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    proc = _run_preflight(
        repo,
        env={
            "LEMMA_FAMILY": "r23rocket",
            "LEMMA_EMIT_AGENT_PRIMITIVES": "1",
            "LEMMA_FAST_TRUSTEDS": "0",
        },
    )
    assert proc.returncode == 1
    assert "ERROR:" in proc.stderr
    assert "rocket" in proc.stderr.lower()


def test_preflight_fast_without_fast_trusteds_exits_1(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    proc = _run_preflight(
        repo,
        env={
            "LEMMA_FAMILY": "r23fast",
            "LEMMA_FAST_TRUSTEDS": "0",
        },
    )
    assert proc.returncode == 1
    assert "ERROR:" in proc.stderr
    assert "fast" in proc.stderr.lower()


def test_preflight_clean_rocket_exits_0(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    proc = _run_preflight(
        repo,
        env={
            "LEMMA_FAMILY": "r23rocket",
            "LEMMA_EMIT_AGENT_PRIMITIVES": "0",
            "LEMMA_FAST_TRUSTEDS": "0",
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert "preflight OK" in proc.stdout
    assert "skipping SSH" in proc.stdout
