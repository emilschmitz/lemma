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


def _head(repo: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _run_preflight(
    repo: Path,
    *,
    env: dict[str, str] | None = None,
    expect_sha: str | None = "HEAD",
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    run_env.pop("LEMMA_EXPERIMENT_ALLOW_DIRTY", None)
    run_env.setdefault("LEMMA_PREFLIGHT_SSH", "0")
    if env:
        run_env.update(env)
    cmd = ["bash", str(PREFLIGHT)]
    if expect_sha == "HEAD":
        cmd.extend(["--expect-sha", _head(repo)])
    elif expect_sha is not None:
        cmd.extend(["--expect-sha", expect_sha])
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(
        cmd,
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


def test_preflight_wait_disabled_exits_1(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    proc = _run_preflight(
        repo,
        env={
            "LEMMA_FAMILY": "r23rocket",
            "LEMMA_EMIT_AGENT_PRIMITIVES": "0",
            "LEMMA_FAST_TRUSTEDS": "0",
            "LEMMA_WAIT_FOR_WRAPPER": "0",
        },
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "WAIT_FOR_WRAPPER" in proc.stderr
    assert "overlap" in proc.stderr.lower() or "wait" in proc.stderr.lower()


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


def test_preflight_unknown_family_exits_1(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    proc = _run_preflight(repo, env={"LEMMA_FAMILY": "r23unknown"})
    assert proc.returncode == 1
    assert "ERROR:" in proc.stderr
    assert "unknown" in proc.stderr.lower() or "LEMMA_FAMILY" in proc.stderr
    assert "mid" in proc.stderr.lower()


def test_preflight_empty_family_exits_1(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    proc = _run_preflight(repo, env={"LEMMA_FAMILY": ""})
    assert proc.returncode == 1
    assert "ERROR:" in proc.stderr


def test_preflight_missing_family_exits_1(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    run_env = os.environ.copy()
    run_env.pop("LEMMA_EXPERIMENT_ALLOW_DIRTY", None)
    run_env.setdefault("LEMMA_PREFLIGHT_SSH", "0")
    run_env.pop("LEMMA_FAMILY", None)
    proc = subprocess.run(
        ["bash", str(PREFLIGHT), "--expect-sha", _head(repo)],
        cwd=repo,
        env=run_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "ERROR:" in proc.stderr


def test_preflight_sloppy_emit_off_exits_1(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    proc = _run_preflight(
        repo,
        env={
            "LEMMA_FAMILY": "r23sloppy",
            "LEMMA_EMIT_AGENT_PRIMITIVES": "0",
            "LEMMA_FAST_TRUSTEDS": "0",
        },
    )
    assert proc.returncode == 1
    assert "ERROR:" in proc.stderr
    assert "sloppy" in proc.stderr.lower() or "EMIT" in proc.stderr


def test_preflight_sloppy_emit_on_fast_off_exits_0(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    proc = _run_preflight(
        repo,
        env={
            "LEMMA_FAMILY": "r23sloppy",
            "LEMMA_EMIT_AGENT_PRIMITIVES": "1",
            "LEMMA_FAST_TRUSTEDS": "0",
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert "preflight OK" in proc.stdout


def test_preflight_sloppy_emit_on_fast_on_exits_1(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    proc = _run_preflight(
        repo,
        env={
            "LEMMA_FAMILY": "r23sloppy",
            "LEMMA_EMIT_AGENT_PRIMITIVES": "1",
            "LEMMA_FAST_TRUSTEDS": "1",
        },
    )
    assert proc.returncode == 1
    assert "ERROR:" in proc.stderr


def test_preflight_fast_with_fast_trusteds_exits_0(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    proc = _run_preflight(
        repo,
        env={
            "LEMMA_FAMILY": "r23fast",
            "LEMMA_FAST_TRUSTEDS": "1",
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert "preflight OK" in proc.stdout


def test_preflight_mid_without_vector_scan_exits_1(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    proc = _run_preflight(
        repo,
        env={
            "LEMMA_FAMILY": "r26mid",
            "LEMMA_FAST_TRUSTEDS": "1",
            "LEMMA_EMIT_AGENT_PRIMITIVES": "0",
            "LEMMA_ENABLE_VECTOR_SCAN": "0",
            "LEMMA_ENABLE_SPILL_HASH": "1",
        },
    )
    assert proc.returncode == 1
    assert "ERROR:" in proc.stderr
    assert "VECTOR" in proc.stderr or "vector" in proc.stderr.lower()


def test_preflight_mid_without_spill_hash_exits_1(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    proc = _run_preflight(
        repo,
        env={
            "LEMMA_FAMILY": "r26mid",
            "LEMMA_FAST_TRUSTEDS": "1",
            "LEMMA_EMIT_AGENT_PRIMITIVES": "0",
            "LEMMA_ENABLE_VECTOR_SCAN": "1",
            "LEMMA_ENABLE_SPILL_HASH": "0",
        },
    )
    assert proc.returncode == 1
    assert "ERROR:" in proc.stderr
    assert "SPILL" in proc.stderr or "spill" in proc.stderr.lower()


def test_preflight_mid_emit_on_exits_1(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    proc = _run_preflight(
        repo,
        env={
            "LEMMA_FAMILY": "r26mid",
            "LEMMA_FAST_TRUSTEDS": "1",
            "LEMMA_EMIT_AGENT_PRIMITIVES": "1",
            "LEMMA_ENABLE_VECTOR_SCAN": "1",
            "LEMMA_ENABLE_SPILL_HASH": "1",
        },
    )
    assert proc.returncode == 1
    assert "ERROR:" in proc.stderr
    assert "mid" in proc.stderr.lower() or "EMIT" in proc.stderr


def test_preflight_mid_with_flags_exits_0(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    proc = _run_preflight(
        repo,
        env={
            "LEMMA_FAMILY": "r26mid",
            "LEMMA_FAST_TRUSTEDS": "1",
            "LEMMA_EMIT_AGENT_PRIMITIVES": "0",
            "LEMMA_ENABLE_VECTOR_SCAN": "1",
            "LEMMA_ENABLE_SPILL_HASH": "1",
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert "preflight OK" in proc.stdout
    assert "mid" in proc.stdout.lower()


def test_preflight_alive_overnight_lock_exits_1(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    lock = tmp_path / "overnight.pid"
    lock.write_text(str(os.getpid()))
    proc = _run_preflight(
        repo,
        env={
            "LEMMA_FAMILY": "r23rocket",
            "LEMMA_OVERNIGHT_LOCK_FILE": str(lock),
        },
    )
    assert proc.returncode == 1
    assert "ERROR:" in proc.stderr
    assert "lock" in proc.stderr.lower() or "overnight" in proc.stderr.lower()


def test_preflight_dead_overnight_lock_does_not_block(tmp_path: Path) -> None:
    repo = _init_pushed_repo(tmp_path)
    lock = tmp_path / "overnight.pid"
    lock.write_text("999999999")
    proc = _run_preflight(
        repo,
        env={
            "LEMMA_FAMILY": "r23rocket",
            "LEMMA_OVERNIGHT_LOCK_FILE": str(lock),
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert "preflight OK" in proc.stdout


def test_lemma_guest_halt_is_not_wrapper() -> None:
    halt = ROOT / "research_loop" / "scripts" / "lemma_guest_halt.sh"
    text = halt.read_text(encoding="utf-8")
    first = text.splitlines()[0]
    assert first.startswith("#!")
    assert "wrapper" not in text.lower()
