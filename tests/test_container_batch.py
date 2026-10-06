"""The batch launcher builds one locked, memory-capped command per run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_loop.scripts import container_batch as cb


def test_command_is_locked_capped_and_carries_the_selected_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", "/db.duckdb")
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    monkeypatch.delenv("LEMMA_TPCH_DB", raising=False)
    cmd = cb.command("claude-sonnet-5-5", Path("/q.sql"))
    assert cmd[:3] == ["flock", "/tmp/lemma_timing.lock", "systemd-run"]
    assert "MemoryMax=6G" in cmd and "--setenv=LEMMA_DUCKDB_PATH=/db.duckdb" in cmd and "--setenv=LEMMA_STRING_ENCODING=dict" in cmd
    assert not any(c.startswith("--setenv=LEMMA_TPCH_DB") for c in cmd)
    assert cmd[cmd.index("--agent") + 1] == "claude-sonnet-5-5" and "--allow-override" in cmd and cmd[-1] == "/q.sql"


def test_short_model_names_map_to_slugs_and_logs_are_named_by_model_and_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cb, "OUT", tmp_path)
    (tmp_path / "qX.sql").write_text("SELECT 1")
    calls: list[list[str]] = []

    class R:
        returncode = 0

    monkeypatch.setattr(cb, "refresh_login", lambda: None)
    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or R())
    assert cb.main(["haiku:qX.sql"]) == 0
    assert calls[0][calls[0].index("--agent") + 1] == "claude-haiku-4-5-20251001"
    assert (tmp_path / "haiku_qX.log").is_file()


def test_the_narrow_cells_flag_and_the_assumption_package_reach_the_container_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    monkeypatch.setenv("LEMMA_ASSUMPTION_PACKAGE", "/p/profile.json")
    cmd = cb.command("claude-sonnet-5-5", Path("/q.sql"))
    assert "--setenv=LEMMA_NARROW_CELLS=1" in cmd and "--setenv=LEMMA_ASSUMPTION_PACKAGE=/p/profile.json" in cmd
    monkeypatch.delenv("LEMMA_NARROW_CELLS")
    monkeypatch.delenv("LEMMA_ASSUMPTION_PACKAGE")
    assert not any(c.startswith(("--setenv=LEMMA_NARROW_CELLS", "--setenv=LEMMA_ASSUMPTION_PACKAGE")) for c in cb.command("m", Path("/q.sql")))


def _stub_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: str) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "claude"
    exe.write_text("#!/bin/sh\n" + script)
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    return exe


def test_each_run_is_preceded_by_a_host_login_refresh_that_is_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "claude_calls.txt"
    _stub_claude(tmp_path, monkeypatch, f'echo "$@|$ANTHROPIC_API_KEY|$CLAUDE_CODE_OAUTH_TOKEN|$(pwd)" >> {log}\necho ok\n')
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-the-refresh")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "nor-this")
    monkeypatch.setattr(cb, "OUT", tmp_path)
    (tmp_path / "qA.sql").write_text("SELECT 1")
    (tmp_path / "qB.sql").write_text("SELECT 2")
    real_run = cb.subprocess.run
    agent_runs: list[list[str]] = []

    def fake(cmd, **kw):  # the refresh is the real stub; the container run and the table are recorded, not run
        if cmd[0] == "claude":
            return real_run(cmd, **kw)
        agent_runs.append(cmd)

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(cb.subprocess, "run", fake)
    assert cb.main(["sonnet:qA.sql", "sonnet:qB.sql"]) == 0
    calls = log.read_text().splitlines()
    assert len(calls) == 2 and all(c.startswith("-p reply with the single word ok --model claude-haiku-4-5-20251001 --max-turns 1||") for c in calls)
    assert all(c.endswith("|/tmp") for c in calls)  # neutral cwd, no API key or OAuth token in the environment
    assert json.loads((tmp_path / "sonnet_qA.refresh.json").read_text())["refreshed"] is True and (tmp_path / "sonnet_qB.refresh.json").is_file()
    assert len([c for c in agent_runs if "--agent" in c]) == 2


@pytest.mark.parametrize("script", ["echo 'API Error: 401' >&2\nexit 1\n", "exit 0\n", "sleep 5\necho ok\n"])
def test_a_failed_refresh_stops_the_batch_before_any_container_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: str, capsys: pytest.CaptureFixture) -> None:
    _stub_claude(tmp_path, monkeypatch, script)
    monkeypatch.setattr(cb, "OUT", tmp_path)
    (tmp_path / "qA.sql").write_text("SELECT 1")
    real_run = cb.subprocess.run
    seen: list[list[str]] = []

    def fake(cmd, **kw):
        seen.append(cmd)
        if cmd[0] == "claude":
            kw["timeout"] = 1  # the timeout path without waiting 90 s
            return real_run(cmd, **kw)

    monkeypatch.setattr(cb.subprocess, "run", fake)
    assert cb.main(["sonnet:qA.sql"]) == 2
    assert [c[0] for c in seen] == ["claude"] and not (tmp_path / "sonnet_qA.log").exists() and not (tmp_path / "sonnet_qA.refresh.json").exists()
    assert "log in with `claude` in your terminal" in capsys.readouterr().err
