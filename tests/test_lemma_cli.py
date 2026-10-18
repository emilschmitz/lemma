"""The `lemma` CLI with a stub docker (a script first on PATH) and a stub pipeline. Real-Docker tests: test_lemma_cli_integration.py (-m slow)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from lemma_cli import cache, common, optimize as opt, sandbox, setup_cmd
from lemma_cli.assumptions import approved_package, assumptions, package_dir
from lemma_cli.main import main

KEY = "sk-ant-api03-DUMMYDUMMYDUMMY-leak-canary-0123456789"  # recognisable dummy; never a real key
FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ["FAKE_DOCKER_DIR"]
args = sys.argv[1:]
open(d + "/calls.log", "a").write(json.dumps(args) + "\n")
flag = lambda n: os.path.exists(d + "/" + n)
if args[0] == "info":
    if flag("info_fail"):
        print("permission denied while trying to connect to the docker API", file=sys.stderr); sys.exit(1)
    print("99.0.0")
elif args[0] == "image":
    if args[1] == "inspect":
        if flag("no_image") and not flag("built"):
            sys.exit(1)
        print("sha256:" + "ab" * 32)
elif args[0] == "build":
    open(d + "/built", "w").write("1")
elif args[0] == "run":
    if "/bin/bash" in args:
        print("TOOLS " + open(d + "/tools.json").read())
        print("CLI " + open(d + "/cli_version").read().strip())
    elif "python" in args:
        print("SELFTEST " + open(d + "/selftest.json").read())
else:
    sys.exit(3)
'''
GOOD_SELFTEST = {"direct_blocked": True, "allowed": {"api.anthropic.com": 200}, "denied": {"example.com": 403, "api.anthropic.com.example.com": 403}}


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh user: empty HOME and LEMMA_HOME, a stub docker with an image, no credentials, no LEMMA_*/secret variables."""
    from declarative_spec.prompt import ADVERTISED_TOOLS

    for name in list(os.environ):
        if name.startswith("LEMMA_") or name in common.SECRET_ENV:
            monkeypatch.delenv(name)
    fake = tmp_path / "fake_docker"
    fake.mkdir()
    (fake / "tools.json").write_text(json.dumps(list(ADVERTISED_TOOLS)))
    (fake / "cli_version").write_text(f"{sandbox.pinned_claude_version()} (Claude Code)")
    (fake / "selftest.json").write_text(json.dumps(GOOD_SELFTEST))
    binary = tmp_path / "bin"
    binary.mkdir()
    exe = binary / "docker"
    exe.write_text(FAKE_DOCKER)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    claude = binary / "claude"
    claude.write_text("#!/bin/sh\nexit 0\n")
    claude.chmod(0o755)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LEMMA_HOME", str(tmp_path / "lemma_home"))
    monkeypatch.setenv("FAKE_DOCKER_DIR", str(fake))
    monkeypatch.setenv("PATH", f"{binary}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(setup_cmd, "ensure_libduckdb", lambda: "present")
    return fake


def calls(fake: Path) -> list[list[str]]:
    log = fake / "calls.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def login(tmp_path_home: str | None = None) -> None:
    (Path(os.environ["HOME"]) / ".claude" / ".credentials.json").write_text("{}")


def everything_written(*roots: Path) -> str:
    return "\n".join(p.read_text(errors="replace") for root in roots for p in root.rglob("*") if p.is_file())


# --- setup: docker and idempotence ---


def test_setup_without_docker_says_install_docker(env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert main(["setup"]) == 2
    assert "docker not found" in capsys.readouterr().err


def test_setup_with_unreachable_daemon_names_the_group_fix(env: Path, capsys: pytest.CaptureFixture) -> None:
    (env / "info_fail").write_text("")
    assert main(["setup"]) == 2
    err = capsys.readouterr().err
    assert "not reachable" in err and "docker group" in err


def test_setup_builds_a_missing_image_once_with_the_pinned_build_args(env: Path) -> None:
    (env / "no_image").write_text("")
    login()
    assert main(["setup"]) == 0
    assert main(["setup"]) == 0
    builds = [c for c in calls(env) if c[0] == "build"]
    assert len(builds) == 1  # second run: image exists, verified, not rebuilt
    assert "INSTALL_CLAUDE_CODE=1" in builds[0] and "lemma-agent:claude" in builds[0]


def test_setup_is_idempotent_and_writes_the_same_state(env: Path) -> None:
    login()
    assert main(["setup"]) == 0
    first = json.loads(common.state_path().read_text())
    assert main(["setup"]) == 0
    second = json.loads(common.state_path().read_text())
    assert [c for c in calls(env) if c[0] == "build"] == []
    assert first["selftest"]["ok"] and {k: v for k, v in first.items() if k != "selftest"} == {k: v for k, v in second.items() if k != "selftest"}


def test_dockerfile_pins_claude_code_to_the_version_of_the_current_image() -> None:
    assert sandbox.pinned_claude_version() == "2.1.289"
    assert "claude-code@2.1.289" in (common.repo_root() / "docker" / "agent" / "Dockerfile").read_text()


# --- setup: the sandbox self-test ---


def test_setup_fails_when_a_non_allowlisted_host_is_reachable(env: Path, capsys: pytest.CaptureFixture) -> None:
    login()
    (env / "selftest.json").write_text(json.dumps({**GOOD_SELFTEST, "denied": {"example.com": 200, "api.anthropic.com.example.com": 403}}))
    assert main(["setup"]) == 2
    assert "example.com was NOT blocked" in capsys.readouterr().err
    assert not common.state_path().exists()  # no "ready" state is recorded


def test_setup_fails_when_the_container_has_network_or_the_model_api_is_unreachable(env: Path, capsys: pytest.CaptureFixture) -> None:
    login()
    (env / "selftest.json").write_text(json.dumps({**GOOD_SELFTEST, "direct_blocked": False}))
    assert main(["setup"]) == 2
    assert "network is not off" in capsys.readouterr().err
    (env / "selftest.json").write_text(json.dumps({**GOOD_SELFTEST, "allowed": {"api.anthropic.com": 502}}))
    assert main(["setup"]) == 2
    assert "not reachable through the bridge" in capsys.readouterr().err


def test_setup_rebuilds_nothing_when_the_cli_version_differs_unless_the_image_can_be_built(env: Path, capsys: pytest.CaptureFixture) -> None:
    login()
    (env / "cli_version").write_text("2.0.0 (Claude Code)")
    assert main(["setup"]) == 2  # the stub image never gets the pinned version, so the rebuild also fails loudly
    assert "pins 2.1.289" in capsys.readouterr().err
    assert len([c for c in calls(env) if c[0] == "build"]) == 1


# --- credentials ---


def test_login_setup_without_a_login_says_how_to_log_in(env: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["setup"]) == 2
    assert "claude login" in capsys.readouterr().err


def test_api_key_setup_without_the_variable_stops_and_does_not_use_the_login(env: Path, capsys: pytest.CaptureFixture) -> None:
    login()  # a login exists, and must NOT be used instead
    assert main(["setup", "--auth", "api-key"]) == 2
    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY is not set" in err
    assert not common.state_path().exists()


def test_the_auth_choice_is_saved_and_an_environment_variable_beats_it(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    assert main(["setup", "--auth", "api-key"]) == 0
    assert json.loads(common.config_path().read_text()) == {"agent_auth": "api_key"}
    monkeypatch.delenv("LEMMA_AGENT_AUTH")  # the setup call exported it into this process
    assert common.apply_home_config() == str(common.config_path()) and os.environ["LEMMA_AGENT_AUTH"] == "api_key"
    monkeypatch.setenv("LEMMA_AGENT_AUTH", "login")
    assert common.apply_home_config().startswith("environment")


def test_child_env_login_drops_the_key_and_api_key_keeps_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    assert "ANTHROPIC_API_KEY" not in opt.child_env("login") and opt.child_env("login")["LEMMA_AGENT_AUTH"] == "login"
    assert opt.child_env("api_key")["ANTHROPIC_API_KEY"] == KEY
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(common.CliError, match="not set"):
        opt.child_env("api_key")


def test_redact_removes_the_environment_key_and_anything_key_shaped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "custom-token-value-xyz")
    out = common.redact(f"boom custom-token-value-xyz and {KEY}")
    assert "custom-token-value-xyz" not in out and KEY not in out and out.count("[REDACTED]") == 2


def test_an_error_message_carrying_the_key_is_redacted_on_screen(env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setattr(setup_cmd.sandbox, "check_docker", lambda: (_ for _ in ()).throw(common.CliError(f"daemon said: bad header {KEY}")))
    assert main(["setup"]) == 2
    err = capsys.readouterr().err
    assert KEY not in err and "[REDACTED]" in err


# --- assumptions and the optimize gate ---


def make_db(tmp_path: Path) -> Path:
    import duckdb

    path = tmp_path / "user.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t(a INTEGER, b INTEGER)")
    con.execute("INSERT INTO t SELECT i, i % 7 FROM range(100) r(i)")
    con.close()
    return path


def ready(env: Path, monkeypatch: pytest.MonkeyPatch, auth: str = "api_key") -> None:
    if auth == "api_key":
        monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
        assert main(["setup", "--auth", "api-key"]) == 0
    else:
        login()
        assert main(["setup"]) == 0


def test_optimize_without_an_assumption_package_stops_with_the_exact_command(env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    ready(env, monkeypatch)
    db = make_db(tmp_path)
    assert main(["optimize", "--db", str(db), "--sql", "SELECT SUM(a) FROM t"]) == 2
    assert f"lemma assumptions --db {db.resolve()}" in capsys.readouterr().err


def test_optimize_stops_when_the_package_was_edited_after_approval(env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    ready(env, monkeypatch)
    db = make_db(tmp_path)
    assert assumptions(str(db), ask=lambda _p: "y") == 0
    assert approved_package(db.resolve()).is_file()
    package = package_dir(db.resolve()) / "package.json"
    package.write_text(package.read_text() + " ")  # any edit voids the approval
    assert main(["optimize", "--db", str(db), "--sql", "SELECT SUM(a) FROM t"]) == 2
    assert "lemma assumptions --db" in capsys.readouterr().err


def test_optimize_before_setup_points_to_setup(env: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["optimize", "--db", str(make_db(tmp_path)), "--sql", "SELECT 1"]) == 2
    assert "lemma setup" in capsys.readouterr().err


def test_assumptions_records_an_approval_only_after_every_claim_is_answered_y(env: Path, tmp_path: Path) -> None:
    db = make_db(tmp_path).resolve()
    asked: list[str] = []
    assert assumptions(str(db), ask=lambda p: asked.append(p) or "y") == 0
    report = json.loads((package_dir(db) / "report.json").read_text())["report"]
    assert len(asked) >= len(report) > 0  # one question per claim, at least
    approval = json.loads((package_dir(db) / "approved.json").read_text())
    assert approval["db_path"] == str(db) and approval["approved_claims"] == len(report)


def test_assumptions_stops_on_the_first_refusal_and_records_nothing(env: Path, tmp_path: Path) -> None:
    db = make_db(tmp_path).resolve()
    answers = iter(["y", "n"])
    assert assumptions(str(db), ask=lambda _p: next(answers)) == 1
    assert not (package_dir(db) / "approved.json").exists()
    with pytest.raises(common.CliError, match="no approved"):
        approved_package(db)


def test_assumptions_needs_a_terminal_there_is_no_blanket_yes(env: Path, tmp_path: Path) -> None:
    db = make_db(tmp_path).resolve()

    def eof(_p: str) -> str:
        raise EOFError

    with pytest.raises(common.CliError, match="interactive terminal"):
        assumptions(str(db), ask=eof)
    from lemma_cli.main import build_parser

    flags = {o for a in build_parser()._subparsers._group_actions[0].choices["assumptions"]._actions for o in a.option_strings}
    assert not {"--yes", "-y", "--approve-all"} & flags


# --- sql key, params ---


def test_same_sql_modulo_layout_has_the_same_key_and_literals_stay_significant() -> None:
    a, b = "SELECT  SUM(a)\nFROM t WHERE b = 'X y';", "select sum(a) from t where b = 'X y'"
    assert common.sql_key(a) == common.sql_key(b) and len(common.sql_key(a)) == 64
    assert common.sql_key(a) != common.sql_key("select sum(a) from t where b = 'x y'")


def test_params_fill_placeholders_in_order_and_quote_text() -> None:
    assert opt.bind_params("SELECT * FROM t WHERE a > ? AND s = ?", ["5", "o'k"]) == "SELECT * FROM t WHERE a > 5 AND s = 'o''k'"
    assert opt.bind_params("SELECT '?' FROM t WHERE a = ?", ["1"]) == "SELECT '?' FROM t WHERE a = 1"


def test_params_count_mismatch_is_an_error() -> None:
    with pytest.raises(common.CliError, match="fewer"):
        opt.bind_params("SELECT ? , ?", ["1"])
    with pytest.raises(common.CliError, match="more"):
        opt.bind_params("SELECT 1", ["1"])


# --- cache layout and manifest ---


def fake_run(tmp_path: Path, binary: bool) -> Path:
    run = tmp_path / "run"
    (run / "workspace" / "mcp_results").mkdir(parents=True, exist_ok=True)
    (run / "workspace" / "context" / "ro").mkdir(parents=True, exist_ok=True)
    (run / "workspace" / "runquery_agent.rs").write_text("// verified body\n")
    (run / "workspace" / "context" / "ro" / "spec.rs").write_text("// spec\n")
    (run / "workspace" / "mcp_results" / "submitted.json").write_text('{"run": {"ok": true}}')
    if binary:
        exe = run / "bin" / "q"
        exe.parent.mkdir(exist_ok=True)
        exe.write_bytes(b"\x7fELF" + b"\0" * 60)
        exe.chmod(0o755)
    return run


RECORD = {"db_path": "/d.duckdb", "assumption_package_sha256": "p" * 64, "agent_model": "claude-sonnet-5-5", "agent_auth": "api_key", "image_id": "sha256:x", "git_sha": "a" * 40, "run_dir": "/r", "speedup": 3.2}


def test_cache_layout_and_manifest_fields(env: Path, tmp_path: Path) -> None:
    sql = "SELECT SUM(a) FROM t;"
    dest = cache.install(sql, RECORD, fake_run(tmp_path, binary=True))
    key = common.sql_key(sql)
    assert dest == common.lemma_home() / "executors" / key
    assert sorted(p.name for p in dest.iterdir()) == ["executor", "manifest.json", "proved", "query.sql"]
    assert sorted(p.name for p in (dest / "proved").iterdir()) == ["runquery_agent.rs", "spec.rs", "submitted.json"]
    manifest = json.loads((dest / "manifest.json").read_text())
    assert set(cache.MANIFEST_FIELDS) <= set(manifest)
    assert manifest["sql_key"] == key and manifest["binary"] == "executor" and manifest["lib"] == "pending" and len(manifest["binary_sha256"]) == 64
    assert (dest / "query.sql").read_text().strip() == "select sum(a) from t"


def test_cache_without_a_binary_is_marked_and_reinstall_replaces(env: Path, tmp_path: Path) -> None:
    sql = "select 1 from t"
    dest = cache.install(sql, RECORD, fake_run(tmp_path, binary=False))
    manifest = json.loads((dest / "manifest.json").read_text())
    assert manifest["binary"] is None and manifest["binary_sha256"] is None and not (dest / "executor").exists()
    cache.install(sql, {**RECORD, "speedup": 9.0}, fake_run(tmp_path, binary=True))
    assert json.loads((dest / "manifest.json").read_text())["speedup"] == 9.0 and (dest / "executor").is_file()
    assert [m["sql_key"] for m in cache.list_executors()] == [common.sql_key(sql)]


# --- the pipeline child process (a stub run_container_agent.py: the only thing stubbed is the LLM session) ---

STUB_PIPELINE = '''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
out = Path(os.environ["STUB_OUT"]); out.mkdir(exist_ok=True)
(out / "seen.json").write_text(json.dumps({"has_key": "ANTHROPIC_API_KEY" in os.environ, "auth": os.environ.get("LEMMA_AGENT_AUTH"), "argv_has_key": any("sk-ant" in a for a in args)}))
run = out / ("run_" + Path(args[args.index("--query-file") + 1]).stem[:8])
(run / "workspace" / "mcp_results").mkdir(parents=True, exist_ok=True)
(run / "workspace" / "runquery_agent.rs").write_text("body")
print("noise line that mentions " + os.environ.get("ANTHROPIC_API_KEY", "no key"))
print("RESULT " + json.dumps({"status": os.environ.get("STUB_STATUS", "SUCCESS"), "run_dir": str(run), "model": "claude-sonnet-5-5", "git_sha": "f" * 40, "official": {"speedup": 2.5}, "error": "stub failure"}))
'''


@pytest.fixture
def pipeline(env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "stub_repo"
    (repo / "research_loop" / "scripts").mkdir(parents=True)
    (repo / "research_loop" / "scripts" / "run_container_agent.py").write_text(STUB_PIPELINE)
    monkeypatch.setattr(opt, "repo_root", lambda: repo)
    monkeypatch.setenv("STUB_OUT", str(tmp_path / "stub_out"))
    return tmp_path / "stub_out"


def test_optimize_api_key_runs_the_pipeline_with_the_key_in_the_child_and_installs(env: Path, pipeline: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    ready(env, monkeypatch)
    db = make_db(tmp_path)
    assert assumptions(str(db), ask=lambda _p: "y") == 0
    assert main(["optimize", "--db", str(db), "--sql", "SELECT SUM(a) FROM t"]) == 0
    seen = json.loads((pipeline / "seen.json").read_text())
    assert seen == {"has_key": True, "auth": "api_key", "argv_has_key": False}
    manifest = json.loads(next((common.lemma_home() / "executors").glob("*/manifest.json")).read_text())
    assert manifest["agent_auth"] == "api_key" and manifest["speedup"] == 2.5 and manifest["db_path"] == str(db.resolve())
    assert KEY not in capsys.readouterr().out
    assert main(["optimize", "--db", str(db), "--sql", "select sum(a) from t;"]) == 0  # same key: cache hit, no second run
    assert "already optimized" in capsys.readouterr().out


def test_optimize_login_mode_refreshes_the_login_and_strips_the_key(env: Path, pipeline: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ready(env, monkeypatch, auth="login")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)  # present in the shell, but the user chose login
    refreshed: list[bool] = []
    from research_loop.scripts import container_batch

    monkeypatch.setattr(container_batch, "refresh_login", lambda: refreshed.append(True))
    db = make_db(tmp_path)
    assert assumptions(str(db), ask=lambda _p: "y") == 0
    assert main(["optimize", "--db", str(db), "--sql", "SELECT 2 FROM t"]) == 0
    assert refreshed == [True]
    assert json.loads((pipeline / "seen.json").read_text()) == {"has_key": False, "auth": "login", "argv_has_key": False}


def test_a_failed_pipeline_installs_nothing_and_says_why(env: Path, pipeline: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    ready(env, monkeypatch)
    monkeypatch.setenv("STUB_STATUS", "FAILED")
    db = make_db(tmp_path)
    assert assumptions(str(db), ask=lambda _p: "y") == 0
    assert main(["optimize", "--db", str(db), "--sql", "SELECT 3 FROM t"]) == 2
    assert "stub failure" in capsys.readouterr().err
    assert cache.list_executors() == []


# --- queue ---


def queue_files(names: list[str], sidecar: dict[str, str] | None = None) -> None:
    q = opt.queue_dir()
    q.mkdir(parents=True)
    for n in names:
        (q / n).write_text(f"SELECT '{n}' FROM t")
    for n, db in (sidecar or {}).items():
        (q / n).with_suffix(".json").write_text(json.dumps({"db": db}))


def test_queue_processes_files_in_name_order_and_moves_them_to_done(env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    done: list[str] = []
    monkeypatch.setattr(opt, "optimize_one", lambda sql, db, force=False: done.append(sql))
    queue_files(["0003-c.sql", "0001-a.sql", "0002-b.sql"])
    assert opt.process_queue(str(make_db(tmp_path))) == 0
    assert [s.split("'")[1] for s in done] == ["0001-a.sql", "0002-b.sql", "0003-c.sql"]
    assert sorted(p.name for p in (opt.queue_dir() / "done").iterdir()) == ["0001-a.sql", "0002-b.sql", "0003-c.sql"]
    assert list(opt.queue_dir().glob("*.sql")) == []


def test_queue_failure_is_quarantined_with_its_reason_and_the_rest_still_run(env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def one(sql: str, db: Path, force: bool = False) -> None:
        seen.append(sql)
        if "0001" in sql:
            raise common.CliError(f"proof failed with {KEY}")

    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setattr(opt, "optimize_one", one)
    queue_files(["0001-a.sql", "0002-b.sql"])
    assert opt.process_queue(str(make_db(tmp_path))) == 1
    assert len(seen) == 2
    err = (opt.queue_dir() / "failed" / "0001-a.sql.err").read_text()
    assert "proof failed" in err and KEY not in err
    assert (opt.queue_dir() / "done" / "0002-b.sql").is_file()


def test_queue_sidecar_names_the_database_and_a_missing_database_is_a_failure(env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[Path] = []
    monkeypatch.setattr(opt, "optimize_one", lambda sql, db, force=False: used.append(db))
    db = make_db(tmp_path)
    queue_files(["0001-a.sql", "0002-b.sql"], sidecar={"0001-a.sql": str(db)})
    assert opt.process_queue(None) == 1  # 0002 has no database
    assert used == [db.resolve()] and (opt.queue_dir() / "failed" / "0002-b.sql.err").is_file()


# --- the key never reaches a file the run writes ---


def test_the_key_value_appears_in_no_file_log_or_output_of_a_full_run(env: Path, pipeline: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    assert main(["setup", "--auth", "api-key"]) == 0
    db = make_db(tmp_path)
    assert assumptions(str(db), ask=lambda _p: "y") == 0
    assert main(["optimize", "--db", str(db), "--sql", "SELECT SUM(a) FROM t"]) == 0
    queue_files(["0001-q.sql"])
    (opt.queue_dir() / "0001-q.sql").write_text("SELECT MAX(a) FROM t")
    assert main(["optimize", "--queue", "--db", str(db)]) == 0
    assert main(["status"]) == 0
    captured = capsys.readouterr()
    written = everything_written(common.lemma_home(), env, tmp_path / "stub_out")
    # the walk covered the cache (two executors), the pipeline logs, the saved config and state, the docker call log and the stub child's files
    assert len(list((common.lemma_home() / "executors").glob("*/manifest.json"))) == 2 and len(list((common.lemma_home() / "logs").glob("*.log"))) == 2
    assert (common.lemma_home() / "config.json").is_file() and (env / "calls.log").is_file() and "has_key" in written
    assert KEY not in written and KEY not in captured.out and KEY not in captured.err


def test_the_pipeline_log_redacts_a_key_the_child_prints(env: Path, pipeline: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ready(env, monkeypatch)
    db = make_db(tmp_path)
    assert assumptions(str(db), ask=lambda _p: "y") == 0
    assert main(["optimize", "--db", str(db), "--sql", "SELECT 7 FROM t"]) == 0
    log = next((common.lemma_home() / "logs").glob("*.log")).read_text()
    assert "noise line that mentions [REDACTED]" in log and KEY not in log


def test_status_reports_auth_image_selftest_and_executors(env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    ready(env, monkeypatch)
    cache.install("select 1 from t", RECORD, fake_run(tmp_path, binary=False))
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "auth            api_key" in out and "PASSED" in out and "lemma-agent:claude present" in out and "1 cached" in out and "duckdb (python) 1.5.6" in out

