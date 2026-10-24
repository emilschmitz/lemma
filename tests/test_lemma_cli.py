"""The `lemma` CLI with a stub docker (a script first on PATH) and a stub pipeline. Real-Docker tests: test_lemma_cli_integration.py (-m slow)."""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from lemma_cli import cache, common, duck, optimize as opt, sandbox, setup_cmd
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


@pytest.fixture(autouse=True)
def _restore_auth_env():
    """The CLI exports the saved choices into os.environ (for its child processes); restore them so later test files are unaffected."""
    names = tuple(common.HOME_CONFIG_ENV.values())
    saved = {n: os.environ.get(n) for n in names}
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


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
    monkeypatch.setattr(setup_cmd, "check_prover", lambda: "verus (stub)")
    monkeypatch.setattr(duck, "check", lambda: "duckdb (stub)")
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


def _as_codex(env: Path) -> None:
    (env / "cli_version").write_text(f"codex-cli {sandbox.pinned_version('codex')}")
    (env / "selftest.json").write_text(json.dumps({"direct_blocked": True, "allowed": {"api.openai.com": 200}, "denied": {"example.com": 403, "api.openai.com.example.com": 403}}))


def test_setup_harness_codex_builds_its_image_saves_the_default_model_and_status_shows_it(env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    from research_loop.agent_harness import DEFAULT_MODELS

    (env / "no_image").write_text("")
    _as_codex(env)
    monkeypatch.setenv("CODEX_API_KEY", KEY)
    for name in common.HOME_CONFIG_ENV.values():
        monkeypatch.setenv(name, "")  # registered with monkeypatch, so teardown removes what setup exports
    assert main(["setup", "--harness", "codex", "--auth", "api-key"]) == 0
    assert json.loads(common.config_path().read_text()) == {"agent_auth": "api_key", "harness": "codex", "agent_model": DEFAULT_MODELS["codex"]}
    (build,) = [c for c in calls(env) if c[0] == "build"]
    assert "HARNESS=codex" in build and "lemma-agent:codex" in build and build[build.index("-f") + 1].endswith("Dockerfile.harness")
    state = json.loads(common.state_path().read_text())
    assert state["harness"] == "codex" and state["image"] == "lemma-agent:codex" and state["selftest"]["ok"]
    out = capsys.readouterr().out
    assert "CODEX_API_KEY is set" in out and KEY not in out
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "harness         codex" in out and f"model           {DEFAULT_MODELS['codex']}" in out and "lemma-agent:codex present" in out and "PASSED" in out


def test_setup_harness_codex_without_its_key_is_loud_and_never_uses_the_anthropic_key(env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    _as_codex(env)
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)  # another vendor's key: not a substitute
    for name in common.HOME_CONFIG_ENV.values():
        monkeypatch.setenv(name, "")
    assert main(["setup", "--harness", "codex", "--auth", "api-key"]) == 2
    assert "CODEX_API_KEY is not set" in capsys.readouterr().err and not common.state_path().exists()


def test_setup_refuses_a_model_of_another_vendor(env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    for name in common.HOME_CONFIG_ENV.values():
        monkeypatch.setenv(name, "")
    assert main(["setup", "--harness", "gemini", "--model", "gpt-6.1-sol"]) == 2
    assert "gemini cannot run model 'gpt-6.1-sol'" in capsys.readouterr().err


def test_child_env_keeps_only_the_chosen_harness_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in common.SECRET_ENV:
        monkeypatch.setenv(name, KEY)
    env = opt.child_env("api_key", "codex")
    assert env["CODEX_API_KEY"] == KEY and env["LEMMA_HARNESS"] == "codex"
    assert not [n for n in common.SECRET_ENV if n != "CODEX_API_KEY" and n in env]
    assert not [n for n in common.SECRET_ENV if n in opt.child_env("login", "gemini")]


def test_redact_covers_openai_and_google_key_shapes() -> None:
    out = common.redact("a sk-proj-" + "A" * 40 + " b AIza" + "B" * 35 + " c")
    assert out == "a [REDACTED] b [REDACTED] c"


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
    monkeypatch.setenv("LEMMA_AGENT_AUTH", "")  # registers the variable with monkeypatch first, so teardown removes what setup exports
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
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "1")  # the UNMAINTAINED package path keeps its requirement
    db = make_db(tmp_path)
    assert main(["optimize", "--db", str(db), "--sql", "SELECT SUM(a) FROM t"]) == 2
    assert f"lemma assumptions --db {db.resolve()}" in capsys.readouterr().err


def test_optimize_stops_when_the_package_was_edited_after_approval(env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    ready(env, monkeypatch)
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "1")
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
    a, b = "SELECT  SUM(a)\nFROM t WHERE b = 'X y';", "SELECT SUM(a) FROM t WHERE b = 'X y'"
    assert common.sql_key(a) == common.sql_key(b) and len(common.sql_key(a)) == 64
    assert common.sql_key(a) != common.sql_key("SELECT SUM(a) FROM t WHERE b = 'x y'")


def test_the_cli_key_is_the_key_the_duckdb_extension_looks_up() -> None:
    """The extension normalizes with research_loop.in_duckdb.normalize_sql (case kept): an executor the CLI installs must be found by it."""
    from research_loop import in_duckdb

    for sql in ("SELECT  Region, SUM(qty) AS Q\nFROM orders GROUP BY Region;", "select 1 -- Note\n from t"):
        assert common.sql_key(sql) == in_duckdb.executor_key(sql)
    assert common.sql_key("SELECT A FROM t") != common.sql_key("select a from t")  # case is kept, as DuckDB's result names keep it


def test_params_fill_placeholders_in_order_and_quote_text() -> None:
    assert opt.bind_params("SELECT * FROM t WHERE a > ? AND s = ?", ["5", "o'k"]) == "SELECT * FROM t WHERE a > 5 AND s = 'o''k'"
    assert opt.bind_params("SELECT '?' FROM t WHERE a = ?", ["1"]) == "SELECT '?' FROM t WHERE a = 1"


def test_params_count_mismatch_is_an_error() -> None:
    with pytest.raises(common.CliError, match="fewer"):
        opt.bind_params("SELECT ? , ?", ["1"])
    with pytest.raises(common.CliError, match="more"):
        opt.bind_params("SELECT 1", ["1"])


# --- the executor cache (shared with the DuckDB extension) ---


def fake_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    (run / "workspace" / "mcp_results").mkdir(parents=True, exist_ok=True)
    (run / "workspace" / "context" / "ro").mkdir(parents=True, exist_ok=True)
    (run / "workspace" / "runquery_agent.rs").write_text("// verified body\n")
    (run / "workspace" / "context" / "ro" / "spec.rs").write_text("// spec\n")
    (run / "workspace" / "mcp_results" / "submitted.json").write_text('{"run": {"ok": true}}')
    return run


RECORD = {"db_path": "/d.duckdb", "assumptions": False, "assumption_package_sha256": None, "agent_harness": "claude", "agent_model": "claude-sonnet-5-5", "agent_auth": "api_key", "image_id": "sha256:x", "run_dir": "/r", "speedup": 3.2}


def fake_executor(sql: str) -> Path:
    """What research_loop.in_duckdb.install_executor leaves: lib.so, manifest.json, query.sql under the extension's key."""
    from research_loop import in_duckdb

    dest = cache.executor_dir(common.sql_key(sql))
    shutil.rmtree(dest, ignore_errors=True)  # install_executor replaces an existing executor of the same key
    dest.mkdir(parents=True)
    (dest / "lib.so").write_bytes(b"\x7fELF")
    (dest / "query.sql").write_text(sql + "\n")
    manifest = {"key": dest.name, "sql": sql, "normalized_sql": in_duckdb.normalize_sql(sql), "proof": "41 verified, 0 errors", "in_duckdb": True,
                "assumptions": False, "spec_sha256": "s" * 64, "lib_sha256": "l" * 64}
    (dest / "manifest.json").write_text(json.dumps(manifest))
    return dest


def test_provenance_is_recorded_beside_the_extension_files(env: Path, tmp_path: Path) -> None:
    dest = fake_executor("SELECT SUM(a) FROM t")
    cache.record_provenance(dest, RECORD, fake_run(tmp_path))
    assert sorted(p.name for p in dest.iterdir()) == ["lib.so", "manifest.json", "optimize.json", "proved", "query.sql"]
    assert sorted(p.name for p in (dest / "proved").iterdir()) == ["runquery_agent.rs", "spec.rs", "submitted.json"]
    (listed,) = cache.list_executors()
    assert listed["proof"] == "41 verified, 0 errors" and listed["optimize"]["agent_model"] == "claude-sonnet-5-5" and listed["optimize"]["installed_at"]
    with pytest.raises(KeyError, match="run_dir"):
        cache.record_provenance(dest, {k: v for k, v in RECORD.items() if k != "run_dir"}, fake_run(tmp_path))


def test_list_shows_key_proof_db_and_sql_and_flags_an_old_cli_entry(env: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["list"]) == 0
    assert "no executors installed" in capsys.readouterr().out
    dest = fake_executor("SELECT SUM(a) FROM t")
    cache.record_provenance(dest, RECORD, fake_run(tmp_path))
    old = cache.executor_dir("ab" * 32)
    old.mkdir(parents=True)
    (old / "manifest.json").write_text(json.dumps({"sql_key": "ab" * 32, "sql": "select 1", "binary": None, "lib": "pending"}))
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert f"{dest.name[:12]}  41 verified, 0 errors  created " in out and "db /d.duckdb" in out and "SELECT SUM(a) FROM t" in out
    assert "abababababab  NOT USABLE IN DUCKDB" in out


def test_remove_takes_a_unique_prefix_and_refuses_bad_or_ambiguous_keys(env: Path, capsys: pytest.CaptureFixture) -> None:
    a = fake_executor("SELECT SUM(a) FROM t")
    b = fake_executor("SELECT SUM(b) FROM t")
    assert main(["remove", "abc"]) == 2 and "at least 6 hex" in capsys.readouterr().err
    assert main(["remove", "../../x1"]) == 2
    assert main(["remove", "0" * 12 if not a.name.startswith("0" * 12) else "f" * 12]) == 2 and "no installed executor" in capsys.readouterr().err
    assert main(["remove", a.name[:8]]) == 0
    assert not a.exists() and b.exists() and f"removed {a}" in capsys.readouterr().out


# --- lemma duckdb ---


def fake_binaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """An installed bundle layout: <share>/lemma/src (the source tree) beside <share>/lemma/duckdb/{duckdb, lemma.duckdb_extension}."""
    src = tmp_path / "share" / "lemma" / "src"
    src.mkdir(parents=True)
    cli = src.parent / "duckdb" / "duckdb"
    cli.parent.mkdir()
    cli.write_text("#!/bin/sh\necho \"ARGS $*\"\necho \"HOME=$LEMMA_HOME\"\n")
    cli.chmod(0o755)
    ext = cli.parent / "lemma.duckdb_extension"
    ext.write_bytes(b"ext")
    monkeypatch.setattr(duck, "repo_root", lambda: src)
    return cli, ext


def test_duckdb_args_turn_lemma_mode_on_and_take_an_absolute_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cli, ext = fake_binaries(tmp_path, monkeypatch)
    assert duck.binaries() == (cli, ext)
    monkeypatch.chdir(tmp_path)
    assert duck.cli_args("my.duckdb", cli=cli) == [str(cli), "-cmd", "SET lemma_mode = true", str(tmp_path / "my.duckdb")]
    assert duck.cli_args(None, cli=cli, sql="SELECT 1") == [str(cli), "-cmd", "SET lemma_mode = true", "-c", "SELECT 1"]
    text = duck.own_duckdb_help(ext, "my.duckdb")
    assert "allow_unsigned_extensions': True" in text and f"LOAD '{ext}'" in text and "SET lemma_mode = true" in text and "duckdb -unsigned" in text


def test_lemma_duckdb_runs_our_cli_with_the_lemma_home_and_a_missing_install_says_how(env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture) -> None:
    db = make_db(tmp_path)
    monkeypatch.setattr(duck, "repo_root", lambda: tmp_path / "nowhere" / "src")
    assert main(["duckdb", str(db), "-c", "SELECT 1"]) == 2
    assert "install the release bundle" in capfd.readouterr().err
    fake_binaries(tmp_path, monkeypatch)
    assert main(["duckdb", str(tmp_path / "missing.duckdb"), "-c", "SELECT 1"]) == 2
    assert main(["duckdb", str(db), "-c", "SELECT 1"]) == 0
    out = capfd.readouterr().out
    assert f"ARGS -cmd SET lemma_mode = true {db.resolve()} -c SELECT 1" in out and f"HOME={common.lemma_home()}" in out


def test_setup_stops_when_verus_is_missing_and_says_how_to_get_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "empty_home"))
    with pytest.raises(common.CliError, match=r"Verus not found at .*tools/verus/verus \(binary and vstd/\): unpack Verus 0.2026.07.18.3a4d30b"):
        setup_cmd.check_prover()
    fake = tmp_path / "empty_home" / "tools" / "verus" / "verus"
    (fake.parent / "vstd").mkdir(parents=True)
    fake.write_text("#!/bin/sh\necho 'Verus\n  Version: 0.2025.01.01.0000000'\n")
    fake.chmod(0o755)
    with pytest.raises(common.CliError, match="is not Verus 0.2026.07.18.3a4d30b"):
        setup_cmd.check_prover()


# --- the pipeline child process (a stub run_container_agent.py: the only thing stubbed is the LLM session) ---

STUB_PIPELINE = '''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
out = Path(os.environ["STUB_OUT"]); out.mkdir(exist_ok=True)
(out / "seen.json").write_text(json.dumps({"has_key": "ANTHROPIC_API_KEY" in os.environ, "auth": os.environ.get("LEMMA_AGENT_AUTH"), "argv_has_key": any("sk-ant" in a for a in args)}))
(out / "argv.json").write_text(json.dumps(args))
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
    out = tmp_path / "stub_out"

    def fake_install(run_dir: Path) -> Path:
        """research_loop.in_duckdb_install_run.install_run: re-emits the spec from the run, verifies, compiles lib.so (mocked)."""
        argv = json.loads((out / "argv.json").read_text())
        (out / "installed_from").write_text(str(run_dir))
        if os.environ.get("STUB_INSTALL_FAIL"):
            raise RuntimeError("library did not verify and compile (exit 1): verification results:: 3 verified, 1 errors")
        return fake_executor(Path(argv[argv.index("--query-file") + 1]).read_text().strip())

    monkeypatch.setattr(opt, "install_in_duckdb", fake_install)
    return out


def test_optimize_api_key_runs_the_pipeline_with_the_key_in_the_child_and_installs(env: Path, pipeline: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    ready(env, monkeypatch)
    db = make_db(tmp_path)
    assert assumptions(str(db), ask=lambda _p: "y") == 0
    assert main(["optimize", "--db", str(db), "--sql", "SELECT SUM(a) FROM t"]) == 0
    seen = json.loads((pipeline / "seen.json").read_text())
    assert seen == {"has_key": True, "auth": "api_key", "argv_has_key": False}
    made = json.loads(next((common.lemma_home() / "executors").glob("*/optimize.json")).read_text())
    assert made["agent_auth"] == "api_key" and made["speedup"] == 2.5 and made["db_path"] == str(db.resolve())
    assert Path((pipeline / "installed_from").read_text()).name.startswith("run_")  # the proved run is what gets installed
    out = capsys.readouterr().out
    assert KEY not in out
    assert "PROVED  41 verified, 0 errors (Verus)" in out and f"lemma duckdb {db.resolve()}" in out and "lemma_last_query()" in out
    assert main(["optimize", "--db", str(db), "--sql", "SELECT  SUM(a)\n FROM t;"]) == 0  # same key: cache hit, no second run
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


def test_optimize_needs_no_package_when_assumptions_are_off(env: Path, pipeline: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """The default (assumptions = false): no `lemma assumptions` step, no --assumption-package to the pipeline, the manifest says so."""
    ready(env, monkeypatch)
    assert "LEMMA_ASSUMPTIONS" not in os.environ
    db = make_db(tmp_path)
    assert main(["optimize", "--db", str(db), "--sql", "SELECT SUM(a) FROM t"]) == 0
    argv = json.loads((pipeline / "argv.json").read_text())
    assert "--assumption-package" not in argv and "--duckdb-path" in argv
    made = json.loads(next((common.lemma_home() / "executors").glob("*/optimize.json")).read_text())
    assert made["assumptions"] is False and made["assumption_package_sha256"] is None
    assert main(["optimize", "--db", str(db), "SELECT SUM(a) FROM t"]) == 2  # a positional argument is a .sql FILE
    sql_file = tmp_path / "q.sql"
    sql_file.write_text("SELECT SUM(a)\nFROM t;\n")
    assert main(["optimize", "--db", str(db), str(sql_file)]) == 0
    assert "already optimized" in capsys.readouterr().out


def test_an_executor_made_under_a_package_is_redone_without_one(env: Path, pipeline: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    ready(env, monkeypatch)
    db = make_db(tmp_path)
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "1")
    assert assumptions(str(db), ask=lambda _p: "y") == 0
    assert main(["optimize", "--db", str(db), "--sql", "SELECT 9 FROM t"]) == 0
    assert "--assumption-package" in json.loads((pipeline / "argv.json").read_text())
    monkeypatch.delenv("LEMMA_ASSUMPTIONS")
    capsys.readouterr()
    assert main(["optimize", "--db", str(db), "--sql", "SELECT 9 FROM t"]) == 0
    assert "already optimized" not in capsys.readouterr().out
    assert "--assumption-package" not in json.loads((pipeline / "argv.json").read_text())


def test_a_declined_pipeline_installs_nothing_and_says_declined(env: Path, pipeline: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    ready(env, monkeypatch)
    monkeypatch.setenv("STUB_STATUS", "DECLINED")
    db = make_db(tmp_path)
    assert main(["optimize", "--db", str(db), "--sql", "SELECT 4 FROM t"]) == 2
    assert "not optimized: DECLINED" in capsys.readouterr().err
    assert cache.list_executors() == []


def test_a_failed_pipeline_installs_nothing_and_says_why(env: Path, pipeline: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    ready(env, monkeypatch)
    monkeypatch.setenv("STUB_STATUS", "FAILED")
    db = make_db(tmp_path)
    assert assumptions(str(db), ask=lambda _p: "y") == 0
    assert main(["optimize", "--db", str(db), "--sql", "SELECT 3 FROM t"]) == 2
    assert "stub failure" in capsys.readouterr().err
    assert cache.list_executors() == []


def test_a_proof_whose_in_duckdb_install_fails_installs_nothing_and_says_so(env: Path, pipeline: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    ready(env, monkeypatch)
    monkeypatch.setenv("STUB_INSTALL_FAIL", "1")
    db = make_db(tmp_path)
    assert main(["optimize", "--db", str(db), "--sql", "SELECT 5 FROM t"]) == 2
    err = capsys.readouterr().err
    assert "proved, but the in-DuckDB install failed, nothing installed" in err and "3 verified, 1 errors" in err
    assert cache.list_executors() == []


def test_bench_prints_cold_and_warm_against_duckdb(env: Path, pipeline: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    ready(env, monkeypatch)
    seen: list[tuple[str, Path]] = []

    def fake_bench(sql: str, db: Path) -> dict:
        seen.append((sql, db))
        return {"cold": {"ours_median_us": 1500, "duck_median_us": 3000, "speedup": 2.0, "rounds": [1] * 5},
                "warm": {"ours_median_us": 400, "duck_median_us": 3000, "speedup": 7.5, "rounds": [1] * 5}}

    monkeypatch.setattr(opt, "bench", fake_bench)
    db = make_db(tmp_path)
    assert main(["optimize", "--db", str(db), "--sql", "SELECT 6 FROM t"]) == 0
    assert seen == []  # only with --bench
    assert main(["optimize", "--db", str(db), "--sql", "SELECT 7 FROM t", "--bench"]) == 0
    assert seen == [("SELECT 7 FROM t", db.resolve())]
    assert "cold 1.5 ms vs DuckDB 3.0 ms (2.00x); warm 400 us (7.50x)" in capsys.readouterr().out
    assert main(["optimize", "--db", str(db), "--sql", "SELECT 6 FROM t", "--bench"]) == 0  # already installed: no pipeline run, still timed
    out = capsys.readouterr().out
    assert "already optimized" in out and "(2.00x)" in out and seen[-1] == ("SELECT 6 FROM t", db.resolve())


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
    fake_executor("SELECT 1 FROM t")
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "auth            api_key" in out and "PASSED" in out and "lemma-agent:claude present" in out and "1 cached" in out and "duckdb (python) 1.5.6" in out

