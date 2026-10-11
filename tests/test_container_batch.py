"""The batch launcher builds one locked, memory-capped command per run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import lemma_config
from research_loop.scripts import container_batch as cb


@pytest.fixture(autouse=True)
def _clean_config_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with no LEMMA_* setting in the environment (lemma.toml alone) and a tree that counts as clean."""
    for name in list(__import__("os").environ):
        if name.startswith("LEMMA_") or name in lemma_config.ALIASES:
            monkeypatch.delenv(name)
    monkeypatch.setattr(lemma_config, "REQUIRED", ())  # duckdb_path / assumption_package have no default; most tests here do not set them
    monkeypatch.setattr(lemma_config, "require_clean_tree", lambda root=None: {"git_sha": "0" * 40, "git_dirty": False, "dirty_files": []})


def test_command_is_locked_capped_and_carries_the_selected_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", "/db.duckdb")
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    monkeypatch.delenv("LEMMA_TPCH_DB", raising=False)
    cmd = cb.command("claude-sonnet-5-5", Path("/q.sql"))
    assert cmd[:4] == ["choom", "-n", "800", "--"] and "flock" not in cmd and cmd[cmd.index("--locked-run") - 1].endswith("container_batch.py")
    assert cmd[cmd.index("--locked-run") + 3] == "systemd-run" and "--slice=lemma.slice" in cmd
    assert "MemoryMax=9G" in cmd and "--setenv=LEMMA_DUCKDB_PATH=/db.duckdb" in cmd and "--setenv=LEMMA_STRING_ENCODING=dict" in cmd
    assert not any(c.startswith("--setenv=LEMMA_TPCH_DB") for c in cmd)  # dead in a container run: no longer forwarded
    # style, menu, sessions and the agent wall are lemma.toml's, not flags of the batch
    assert not {"--max-iterations", "--style", "--menu", "--allow-override"} & set(cmd)
    assert cmd[cmd.index("--agent") + 1] == "claude-sonnet-5-5" and cmd[-1] == "/q.sql"


def test_short_model_names_map_to_slugs_and_logs_are_named_by_model_and_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cb, "OUT", tmp_path)
    (tmp_path / "qX.sql").write_text("SELECT 1")
    calls: list[list[str]] = []

    class R:
        returncode = 0

    def fake(cmd, **kw):
        calls.append(cmd)
        if "--locked-run" in cmd:
            Path(cmd[cmd.index("--locked-run") + 1]).write_text("{}")  # what the locked refresh leaves behind
        return R()

    monkeypatch.setattr(cb.subprocess, "run", fake)
    assert cb.main(["haiku:qX.sql"]) == 0
    assert calls[0][calls[0].index("--agent") + 1] == "claude-haiku-4-5-20251001"
    assert (tmp_path / "haiku_qX.log").is_file()


def test_the_narrow_cells_flag_and_the_assumption_package_reach_the_container_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    monkeypatch.setenv("LEMMA_ASSUMPTION_PACKAGE", "/p/profile.json")
    cmd = cb.command("claude-sonnet-5-5", Path("/q.sql"))
    assert "--setenv=LEMMA_NARROW_CELLS=true" in cmd and "--setenv=LEMMA_ASSUMPTION_PACKAGE=/p/profile.json" in cmd
    monkeypatch.delenv("LEMMA_NARROW_CELLS")
    monkeypatch.delenv("LEMMA_ASSUMPTION_PACKAGE")
    assert not any(c.startswith(("--setenv=LEMMA_NARROW_CELLS", "--setenv=LEMMA_ASSUMPTION_PACKAGE")) for c in cb.command("m", Path("/q.sql")))


def _stub_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "claude"
    exe.write_text("#!/bin/sh\n" + script)
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")


def test_the_refresh_runs_inside_the_lock_before_the_container_command_and_is_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "claude_calls.txt"
    _stub_claude(tmp_path, monkeypatch, f'echo "$@|$ANTHROPIC_API_KEY|$CLAUDE_CODE_OAUTH_TOKEN|$ANTHROPIC_AUTH_TOKEN|$(pwd)" >> {log}\necho ok\n')
    for var in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.setenv(var, "must-not-reach-the-refresh")
    execs: list[list[str]] = []
    monkeypatch.setattr(cb.os, "execvp", lambda f, argv: execs.append(argv))
    marker = tmp_path / "m.refresh.json"
    cb.main(["--locked-run", str(marker), "--", "systemd-run", "x"])
    assert log.read_text().splitlines() == ["-p reply with the single word ok --model claude-haiku-4-5-20251001 --max-turns 1||||/tmp"]  # neutral cwd, no other credential path
    assert json.loads(marker.read_text())["refreshed"] is True and execs == [["systemd-run", "x"]]


@pytest.mark.parametrize("script", ["echo 'API Error: 401' >&2\nexit 1\n", "exit 0\n", "sleep 5\necho ok\n"])
def test_a_failed_refresh_never_reaches_the_container_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: str, capsys: pytest.CaptureFixture) -> None:
    _stub_claude(tmp_path, monkeypatch, script)
    real_run = cb.subprocess.run
    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: real_run(cmd, **{**kw, "timeout": 1}))
    execs: list = []
    monkeypatch.setattr(cb.os, "execvp", lambda f, argv: execs.append(argv))
    marker = tmp_path / "m.refresh.json"
    assert cb.main(["--locked-run", str(marker), "--", "systemd-run"]) == 2
    assert not marker.exists() and not execs and "log in with `claude` in your terminal" in capsys.readouterr().err


def test_the_batch_stops_when_a_run_left_no_refresh_marker_and_clears_stale_markers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(cb, "OUT", tmp_path)
    (tmp_path / "qA.sql").write_text("SELECT 1")
    (tmp_path / "sonnet_qA.refresh.json").write_text('{"refreshed": true}')  # left by an earlier batch
    ran: list[list[str]] = []
    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: ran.append(cmd))  # the locked command fails before writing a marker
    assert cb.main(["sonnet:qA.sql"]) == 2
    assert not (tmp_path / "sonnet_qA.refresh.json").exists() and len(ran) == 1 and "no login refresh happened" in capsys.readouterr().err


def test_the_join_chain_flag_reaches_the_run_only_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_JOIN_CHAIN", raising=False)
    assert not any(c.startswith("--setenv=LEMMA_JOIN_CHAIN") for c in cb.command("claude-sonnet-5-5", Path("/q.sql")))
    monkeypatch.setenv("LEMMA_JOIN_CHAIN", "1")
    assert "--setenv=LEMMA_JOIN_CHAIN=true" in cb.command("claude-sonnet-5-5", Path("/q.sql"))


# --- the batch forwards the effective config, nothing ad hoc ---


def test_with_no_override_nothing_is_forwarded_and_the_scope_cap_comes_from_lemma_toml() -> None:
    cmd = cb.command("claude-sonnet-5-5", Path("/q.sql"))
    assert not any(c.startswith("--setenv") for c in cmd)  # the child reads lemma.toml itself
    assert f"MemoryMax={lemma_config.default('scope_memory_max')}" in cmd


def test_every_non_file_value_is_forwarded_with_its_origin_and_no_other_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "3")
    monkeypatch.setenv("AGENT_TIMEOUT_SEC", "100")  # an old spelling is forwarded under its new name
    cmd = cb.command("claude-sonnet-5-5", Path("/q.sql"))
    setenvs = dict(c[len("--setenv="):].split("=", 1) for c in cmd if c.startswith("--setenv="))
    assert setenvs["LEMMA_OFFICIAL_ROUNDS"] == "3" and setenvs["LEMMA_AGENT_TIMEOUT_SEC"] == "100"
    assert json.loads(setenvs["LEMMA_CONFIG_ORIGIN"]) == {"official_rounds": "env", "agent_timeout_sec": "env"}
    assert set(setenvs) == {"LEMMA_OFFICIAL_ROUNDS", "LEMMA_AGENT_TIMEOUT_SEC", "LEMMA_CONFIG_ORIGIN"}


def test_a_typo_in_a_lemma_variable_stops_the_batch_before_any_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_OFICIAL_ROUNDS", "3")
    ran: list = []
    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    with pytest.raises(lemma_config.ConfigError, match="LEMMA_OFICIAL_ROUNDS"):
        cb.main(["sonnet:q.sql"])
    assert not ran


def test_a_dirty_tree_stops_the_batch_before_any_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def dirty(root=None):
        raise lemma_config.ConfigError("the git tree has uncommitted changes in tracked files (1)")

    monkeypatch.setattr(lemma_config, "require_clean_tree", dirty)
    ran: list = []
    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    with pytest.raises(lemma_config.ConfigError, match="uncommitted"):
        cb.main(["sonnet:q.sql"])
    assert not ran


def test_a_batch_without_a_database_or_a_package_stops_before_any_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(lemma_config, "REQUIRED", ("duckdb_path", "assumption_package"))
    with pytest.raises(lemma_config.ConfigError, match="duckdb_path has no default"):
        cb.main(["haiku:qX.sql"])
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", "/db.duckdb")
    with pytest.raises(lemma_config.ConfigError, match="assumption_package has no default"):
        cb.main(["haiku:qX.sql"])
