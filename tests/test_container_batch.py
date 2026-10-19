"""The batch launcher builds one locked, memory-capped command per run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import lemma_config
from research_loop.scripts import container_batch as cb


@pytest.fixture
def dev_form(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_ALLOW_DIRTY", "1")  # the positional model:query form needs it


@pytest.fixture(autouse=True)
def _clean_config_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with no LEMMA_* setting in the environment (lemma.toml alone) and a tree that counts as clean."""
    for name in list(__import__("os").environ):
        if name.startswith("LEMMA_") or name in lemma_config.ALIASES:
            monkeypatch.delenv(name)
    monkeypatch.setattr(cb, "preflight_images", lambda models: None)  # no docker here (tests/test_agent_image_check.py covers the preflight)
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


def test_short_model_names_map_to_slugs_and_logs_are_named_by_model_and_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dev_form: None) -> None:
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


def test_the_batch_stops_when_a_run_left_no_refresh_marker_and_clears_stale_markers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, dev_form: None) -> None:
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


def test_a_typo_in_a_lemma_variable_stops_the_batch_before_any_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dev_form: None) -> None:
    monkeypatch.setenv("LEMMA_OFICIAL_ROUNDS", "3")
    ran: list = []
    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    with pytest.raises(lemma_config.ConfigError, match="LEMMA_OFICIAL_ROUNDS"):
        cb.main(["sonnet:q.sql"])
    assert not ran


def test_a_dirty_tree_stops_the_batch_before_any_run(monkeypatch: pytest.MonkeyPatch, dev_form: None) -> None:
    def dirty(root=None):
        raise lemma_config.ConfigError("the git tree has uncommitted changes in tracked files (1)")

    monkeypatch.setattr(lemma_config, "require_clean_tree", dirty)
    ran: list = []
    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    with pytest.raises(lemma_config.ConfigError, match="uncommitted"):
        cb.main(["sonnet:q.sql"])
    assert not ran


def test_a_batch_without_a_database_or_a_package_stops_before_any_run(monkeypatch: pytest.MonkeyPatch, dev_form: None, tmp_path: Path) -> None:
    monkeypatch.setattr(lemma_config, "REQUIRED", ("duckdb_path", "assumption_package"))
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "1")  # the package is required only on the (UNMAINTAINED) assumption-package path
    with pytest.raises(lemma_config.ConfigError, match="duckdb_path has no default"):
        cb.main(["haiku:qX.sql"])
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", "/db.duckdb")
    with pytest.raises(lemma_config.ConfigError, match="assumption_package has no default"):
        cb.main(["haiku:qX.sql"])


# --- experiment batches: refusals before anything launches, the pin, and the dev form ---

import subprocess  # noqa: E402

EXP = """
[settings]
assumptions = true
official_rounds = 3
[[run]]
model = "sonnet"
query = "q1.sql"
duckdb_path = "d.duckdb"
assumption_package = "p.json"
[[run]]
model = "haiku"
query = "q2.sql"
duckdb_path = "d.duckdb"
assumption_package = "p.json"
"""


@pytest.fixture
def batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A committed temp repo with configs/experiments/e.toml as the batch ROOT; subprocess.run records launches and fakes the login marker."""
    monkeypatch.undo()  # drop the autouse stubs: the real tree check is under test
    for name in list(__import__("os").environ):
        if name.startswith("LEMMA_") or name in lemma_config.ALIASES:
            monkeypatch.delenv(name)
    root = tmp_path / "repo"
    (root / "configs" / "experiments").mkdir(parents=True)
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"], ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=root, check=True)
    (root / "configs" / "experiments" / "e.toml").write_text(EXP)
    for name in ("q1.sql", "q2.sql", "p.json"):
        (root / name).write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=root, check=True)
    monkeypatch.setattr(cb, "ROOT", root)
    monkeypatch.setattr(cb, "OUT", tmp_path / "out")
    monkeypatch.setattr(lemma_config, "REQUIRED", ())
    monkeypatch.setattr(cb, "preflight_images", lambda models: None)  # undo() dropped the autouse stub; no docker here
    launches: list[list[str]] = []
    real_run = subprocess.run

    class R:
        returncode = 0

    def fake(cmd, **kw):
        if cmd[0] != "choom":
            return real_run(cmd, **kw)
        launches.append(cmd)
        Path(cmd[cmd.index("--locked-run") + 1]).write_text("{}")
        return R()

    monkeypatch.setattr(cb.subprocess, "run", fake)
    yield root, launches
    lemma_config.clear_experiment()


def test_an_experiment_batch_launches_every_run_with_the_pin(batch) -> None:
    root, launches = batch
    assert cb.main(["--experiment", "configs/experiments/e.toml"]) == 0
    pin = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    assert len(launches) == 2
    for i, cmd in enumerate(launches):
        assert cmd[cmd.index("--pinned-sha") + 1] == pin and cmd[cmd.index("--run-index") + 1] == str(i) and "--agent" not in cmd
        assert cmd[cmd.index("--experiment") + 1] == "configs/experiments/e.toml"
        assert not any(c.startswith("--setenv") for c in cmd)  # nothing is forwarded as environment


@pytest.mark.parametrize("what", ["env", "untracked", "modified_experiment", "dirty_tracked"])
def test_the_batch_refuses_and_launches_nothing(batch, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, what: str) -> None:
    root, launches = batch
    if what == "env":
        monkeypatch.setenv("LEMMA_MAX_ITERATIONS", "4")
    elif what == "untracked":
        (root / "stray.txt").write_text("x")
    elif what == "modified_experiment":
        (root / "configs" / "experiments" / "e.toml").write_text(EXP + "\n# edited\n")
    else:
        (root / "configs" / "experiments" / "e.toml").write_text(EXP)
        (root / "b.txt").write_text("1")
        subprocess.run(["git", "add", "b.txt"], cwd=root, check=True)
    with pytest.raises(lemma_config.ConfigError, match="not replicable") as err:
        cb.main(["--experiment", "configs/experiments/e.toml"])
    assert launches == []
    if what == "env":
        assert "max_iterations" in str(err.value)


def test_the_batch_stops_when_head_moves_after_the_first_run(batch, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    root, launches = batch
    inner = cb.subprocess.run

    def commit_after_first(cmd, **kw):
        out = inner(cmd, **kw)
        if cmd[0] == "choom" and len(launches) == 1:
            (root / "c.txt").write_text("new")
            subprocess.run(["git", "add", "c.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "mid-batch"], cwd=root, check=True)
        return out

    monkeypatch.setattr(cb.subprocess, "run", commit_after_first)
    assert cb.main(["--experiment", "configs/experiments/e.toml"]) == 2
    assert len(launches) == 1 and "pinned at" in capsys.readouterr().err


def test_the_batch_stops_when_a_run_refuses(batch, monkeypatch: pytest.MonkeyPatch) -> None:
    _, launches = batch
    inner = cb.subprocess.run

    class Refused:
        returncode = 3

    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: (inner(cmd, **kw), Refused())[1] if cmd[0] == "choom" else inner(cmd, **kw))
    assert cb.main(["--experiment", "configs/experiments/e.toml"]) == 2 and len(launches) == 1


def test_positional_runs_need_allow_dirty_and_are_not_replicable(batch, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    root, launches = batch
    with pytest.raises(lemma_config.ConfigError, match="allow_dirty"):
        cb.main(["haiku:qX.sql"])
    assert launches == []
    monkeypatch.setenv("LEMMA_ALLOW_DIRTY", "1")
    assert cb.main(["haiku:qX.sql"]) == 0
    assert "--experiment" not in launches[0] and lemma_config.experiment_record() is None  # the child records "replicable": false


def test_the_manifest_of_a_dev_run_is_not_replicable_and_an_experiment_run_is(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, batch) -> None:
    from research_loop import run_artifacts as ra

    root, _ = batch
    monkeypatch.setattr(ra, "effective_settings", lambda sha, dirty: {})
    monkeypatch.setattr(ra, "_write_hardware_profile", lambda run: None)
    monkeypatch.setattr(ra, "emit_query_start", lambda **kw: None)
    ra.set_run_evidence({"data_sha256": "ab", "agent_image_digest": "sha256:cd"})
    dev = ra.begin_run(query_id=1, sql_query="SELECT 1", root=root)._manifest
    assert dev["replicable"] is False and dev["experiment"] is None and dev["data_sha256"] == "ab"
    lemma_config.use_experiment("configs/experiments/e.toml", 0, "f" * 40, root)
    rep = ra.begin_run(query_id=1, sql_query="SELECT 1", root=root)._manifest
    assert rep["replicable"] is True and rep["pinned_sha"] == "f" * 40 and rep["experiment"]["path"] == "configs/experiments/e.toml"
    assert rep["agent_image_digest"] == "sha256:cd" and rep["lemma_config"]["official_rounds"]["source"] == "experiment"
    ra.set_run_evidence({})


def test_the_batch_refuses_a_query_that_is_not_committed(batch) -> None:
    root, launches = batch
    (root / "q1.sql").write_text("changed")
    with pytest.raises(lemma_config.ConfigError, match="q1.sql .*differs from its committed version"):
        cb.main(["--experiment", "configs/experiments/e.toml"])
    subprocess.run(["git", "checkout", "q1.sql"], cwd=root, check=True)
    subprocess.run(["git", "rm", "-q", "--cached", "q1.sql"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "untrack"], cwd=root, check=True)
    with pytest.raises(lemma_config.ConfigError, match="q1.sql .*not tracked"):
        cb.main(["--experiment", "configs/experiments/e.toml"])
    assert launches == []


def test_the_batch_stops_when_a_run_ends_on_an_agent_api_error(batch, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """A run that exits INFRA_EXIT (expired login, proxy refused) stops the batch: the remaining runs are not started."""
    from research_loop.scripts.run_container_agent import INFRA_EXIT

    _, launches = batch
    inner = cb.subprocess.run

    class Infra:
        returncode = INFRA_EXIT

    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: (inner(cmd, **kw), Infra())[1] if cmd[0] == "choom" else inner(cmd, **kw))
    assert cb.main(["--experiment", "configs/experiments/e.toml"]) == 2 and len(launches) == 1
    assert "the agent API failed (INFRA" in capsys.readouterr().err
