"""Local stand-in for the computer → GCP misses.

The remote VM is a second git checkout. ``gcloud`` is a script on ``PATH`` that
runs the preflight SSH command there. No Spot VM is contacted.

Each test is one miss that already showed up when a laptop run was replayed
on GCP: wrong commit, dirty box, patched halt script, rocket flags, a Verus
verdict hidden behind a timeout line, or a missing trace labeled as the agent.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from research_loop.scripts.classify_product_failures import classify_optimizer_log

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "research_loop" / "scripts" / "gcp_experiment_preflight.sh"
HALT_BODY = "#!/bin/bash\necho halt\n"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path, origin: Path) -> None:
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@test")
    _git(path, "config", "user.name", "test")
    halt = path / "research_loop" / "scripts" / "lemma_guest_halt.sh"
    halt.parent.mkdir(parents=True)
    halt.write_text(HALT_BODY)
    _git(path, "add", "research_loop/scripts/lemma_guest_halt.sh")
    _git(path, "commit", "-m", "init")
    if not origin.exists():
        subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    _git(path, "remote", "add", "origin", str(origin))
    _git(path, "push", "-u", "origin", "main")


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _mock_gcloud(bin_dir: Path) -> Path:
    script = bin_dir / "gcloud"
    bin_dir.mkdir()
    script.write_text(
        """#!/bin/bash
set -euo pipefail
if [[ -n "${GCLOUD_LOG:-}" ]]; then
  printf '%s\\n' "$*" >> "$GCLOUD_LOG"
fi
if [[ "${GCLOUD_FAIL:-}" == "1" ]]; then
  echo "mock gcloud ssh failed" >&2
  exit 1
fi
prev=""
cmd=""
for arg in "$@"; do
  if [[ "$prev" == "--command" ]]; then
    cmd="$arg"
  fi
  prev="$arg"
done
if [[ -z "$cmd" ]]; then
  echo "mock gcloud: no --command" >&2
  exit 2
fi
bash -lc "$cmd"
"""
    )
    script.chmod(0o755)
    return script


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    origin = tmp_path / "origin.git"
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    _init_repo(local, origin)
    subprocess.run(
        ["git", "clone", str(origin), str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    return local, remote


def _preflight(
    local: Path,
    *,
    env: dict[str, str] | None = None,
    expect_sha: str | None = "HEAD",
) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    run_env.pop("LEMMA_EXPERIMENT_ALLOW_DIRTY", None)
    run_env.setdefault("LEMMA_PREFLIGHT_SSH", "0")
    run_env.setdefault("LEMMA_FAMILY", "r32rocket")
    run_env.setdefault("LEMMA_EMIT_AGENT_PRIMITIVES", "0")
    run_env.setdefault("LEMMA_FAST_TRUSTEDS", "0")
    if env:
        run_env.update(env)
    cmd = ["bash", str(PREFLIGHT)]
    if expect_sha == "HEAD":
        cmd.extend(["--expect-sha", _head(local)])
    elif expect_sha is not None:
        cmd.extend(["--expect-sha", expect_sha])
    return subprocess.run(
        cmd,
        cwd=local,
        env=run_env,
        capture_output=True,
        text=True,
        check=False,
    )


def _ssh_env(tmp_path: Path, remote: Path, **extra: str) -> dict[str, str]:
    log = tmp_path / "gcloud.log"
    bindir = tmp_path / "bin"
    _mock_gcloud(bindir)
    env = {
        "PATH": f"{bindir}:{os.environ.get('PATH', '')}",
        "LEMMA_PREFLIGHT_SSH": "1",
        "LEMMA_REMOTE_HOST": "mock-vm",
        "LEMMA_GCP_ZONE": "us-east1-c",
        "LEMMA_REMOTE_REPO": str(remote),
        "GCLOUD_LOG": str(log),
    }
    env.update(extra)
    return env


def test_expect_sha_omitted_exits_1(tmp_path: Path) -> None:
    local, _remote = _pair(tmp_path)
    proc = _preflight(local, expect_sha=None)
    assert proc.returncode == 1
    assert "expect-sha" in proc.stderr or "commit hash" in proc.stderr


def test_expect_sha_too_short_exits_1(tmp_path: Path) -> None:
    local, _remote = _pair(tmp_path)
    proc = _preflight(local, expect_sha="abc")
    assert proc.returncode == 1
    assert "7 characters" in proc.stderr


def test_expect_sha_not_head_exits_1(tmp_path: Path) -> None:
    local, _remote = _pair(tmp_path)
    (local / "later.txt").write_text("x\n")
    _git(local, "add", "later.txt")
    _git(local, "commit", "-m", "later")
    _git(local, "push", "origin", "main")
    parent = _git(local, "rev-parse", "HEAD~1").stdout.strip()
    proc = _preflight(local, expect_sha=parent)
    assert proc.returncode == 1
    assert "not HEAD" in proc.stderr


def test_expect_sha_matches_head_rocket_exits_0(tmp_path: Path) -> None:
    local, _remote = _pair(tmp_path)
    proc = _preflight(local)
    assert proc.returncode == 0, proc.stderr
    assert "preflight OK" in proc.stdout
    assert _head(local) in proc.stdout


def test_remote_sha_mismatch_exits_1(tmp_path: Path) -> None:
    local, remote = _pair(tmp_path)
    (local / "later.txt").write_text("x\n")
    _git(local, "add", "later.txt")
    _git(local, "commit", "-m", "later")
    _git(local, "push", "origin", "main")
    proc = _preflight(local, env=_ssh_env(tmp_path, remote))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "remote HEAD" in proc.stderr


def test_remote_sha_match_exits_0(tmp_path: Path) -> None:
    local, remote = _pair(tmp_path)
    proc = _preflight(local, env=_ssh_env(tmp_path, remote))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "remote preflight OK" in proc.stdout


def test_remote_dirty_worktree_exits_1(tmp_path: Path) -> None:
    local, remote = _pair(tmp_path)
    (remote / "dirty.txt").write_text("x\n")
    proc = _preflight(local, env=_ssh_env(tmp_path, remote))
    assert proc.returncode == 1
    assert "dirty" in proc.stderr.lower()


def test_remote_halt_script_missing_exits_1(tmp_path: Path) -> None:
    local, remote = _pair(tmp_path)
    _git(local, "rm", "research_loop/scripts/lemma_guest_halt.sh")
    _git(local, "commit", "-m", "drop halt")
    _git(local, "push", "origin", "main")
    _git(remote, "pull", "--ff-only")
    proc = _preflight(local, env=_ssh_env(tmp_path, remote))
    assert proc.returncode == 1, proc.stderr
    assert "missing" in proc.stderr.lower()


def test_remote_halt_wrapper_exits_1(tmp_path: Path) -> None:
    local, remote = _pair(tmp_path)
    halt = remote / "research_loop" / "scripts" / "lemma_guest_halt.sh"
    halt.write_text("# wrapper patched in place\n#!/bin/bash\necho halt\n")
    proc = _preflight(local, env=_ssh_env(tmp_path, remote))
    assert proc.returncode == 1, proc.stderr
    assert "wrapper" in proc.stderr.lower()


def test_remote_halt_differs_from_git_exits_1(tmp_path: Path) -> None:
    local, remote = _pair(tmp_path)
    halt = remote / "research_loop" / "scripts" / "lemma_guest_halt.sh"
    halt.write_text("#!/bin/bash\necho patched\n")
    proc = _preflight(local, env=_ssh_env(tmp_path, remote))
    assert proc.returncode == 1
    assert "differs" in proc.stderr.lower() or "patched" in proc.stderr.lower()


def test_mock_gcloud_ssh_failure_exits_1(tmp_path: Path) -> None:
    local, remote = _pair(tmp_path)
    proc = _preflight(local, env=_ssh_env(tmp_path, remote, GCLOUD_FAIL="1"))
    assert proc.returncode == 1
    assert "remote preflight failed" in proc.stderr


def test_ssh_off_does_not_call_gcloud(tmp_path: Path) -> None:
    local, remote = _pair(tmp_path)
    (local / "later.txt").write_text("x\n")
    _git(local, "add", "later.txt")
    _git(local, "commit", "-m", "later")
    _git(local, "push", "origin", "main")
    env = _ssh_env(tmp_path, remote)
    env["LEMMA_PREFLIGHT_SSH"] = "0"
    proc = _preflight(local, env=env)
    assert proc.returncode == 0, proc.stderr
    assert "skipping SSH" in proc.stdout
    log = Path(env["GCLOUD_LOG"])
    assert not log.exists() or log.read_text() == ""


def test_rocket_fast_on_exits_1(tmp_path: Path) -> None:
    local, _remote = _pair(tmp_path)
    proc = _preflight(local, env={"LEMMA_FAST_TRUSTEDS": "1"})
    assert proc.returncode == 1
    assert "FAST" in proc.stderr


def test_rocket_emit_and_fast_on_exits_1(tmp_path: Path) -> None:
    local, _remote = _pair(tmp_path)
    proc = _preflight(
        local,
        env={"LEMMA_EMIT_AGENT_PRIMITIVES": "1", "LEMMA_FAST_TRUSTEDS": "1"},
    )
    assert proc.returncode == 1
    assert "rocket" in proc.stderr.lower()


def test_proved_then_pin_timeout_is_execute() -> None:
    text = """
verification results:: 127 verified, 0 errors
TIMEOUT after 600s
latency_us=-1
"""
    out = classify_optimizer_log(text)
    assert out["step"] == 7
    assert out["class"] == "failed to execute"


def test_verus_errors_beat_timeout_line() -> None:
    text = """
verification results:: 126 verified, 6 errors
error[E0425]: cannot find function `lemma_rem_cap_native_add_fits` in this scope
   --> custom_query.rs:2694:5
LEMMA_TRACE_RUN_QUERY_LINE=2974
TIMEOUT after 600s
"""
    out = classify_optimizer_log(text)
    assert out["step"] == 4
    assert out["class"] == "assemble"


def test_docker_sigkill_without_verus_is_timeout_not_agent() -> None:
    text = """
agent_docker_end: exit=-9 timed_out=False
CUSTOM_PIPELINE_FAILED
"""
    out = classify_optimizer_log(text)
    assert out["step"] == 3
    assert out["class"] == "infra"
    assert "timeout" in out.get("detail", "")


def test_docker_sigkill_after_verus_errors_keeps_the_errors() -> None:
    text = """
verification results:: 119 verified, 5 errors
error: cannot use while in proof mode
   --> custom_query.rs:3063:9
LEMMA_TRACE_RUN_QUERY_LINE=2581
agent_docker_end: exit=-9 timed_out=False
"""
    out = classify_optimizer_log(text)
    assert out["class"] == "agent stupidity"
    assert out["step"] == 3


def test_host_lemma_above_run_query_is_assemble() -> None:
    text = """
LEMMA_TRACE_RUN_QUERY_LINE=2974
error: assertion failed
   --> custom_query.rs:2724:5
verification results:: 126 verified, 6 errors
"""
    out = classify_optimizer_log(text)
    assert out["step"] == 4
    assert out["class"] == "assemble"
    assert "host lemma" in out.get("detail", "")


def test_error_inside_run_query_is_agent() -> None:
    text = """
LEMMA_TRACE_RUN_QUERY_LINE=2581
error: cannot use while in proof mode
   --> custom_query.rs:3063:13
verification results:: 119 verified, 5 errors
"""
    out = classify_optimizer_log(text)
    assert out["step"] == 3
    assert out["class"] == "agent stupidity"


def test_missing_traces_are_not_agent_stupidity() -> None:
    text = """
FAILED
    no marked submit
    LEFTOVER_VERIFY_MISSING (no leftover verify_error_custom.log)
"""
    out = classify_optimizer_log(text)
    assert out["class"] == "infra"
    assert out["class"] != "agent stupidity"
    assert "harvest" in out.get("detail", "")


def test_omitted_lemma_e0425_is_assemble() -> None:
    text = """
error[E0425]: cannot find function `lemma_rem_cap_native_add_fits` in this scope
   --> custom_query.rs:2694:5
"""
    out = classify_optimizer_log(text)
    assert out["step"] == 4
    assert out["class"] == "assemble"
