"""`lemma` against the REAL local Docker and the existing lemma-agent:claude image. Opt in: `uv run pytest -m slow tests/test_lemma_cli_integration.py -s`.

Real here: docker, the image, the egress bridge, the sandbox settings, the sandbox self-test (a non-allowlisted host must be refused,
the model API host must be reachable), the profiler, the assumption check, the cache. Stubbed: only the LLM agent session
(``optimize.run_pipeline``). A dummy API key (never a real one) is set and every file and output of each run is searched for it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lemma_cli import common, optimize as opt, sandbox
from lemma_cli.main import main

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not (sandbox.shutil.which("docker") and sandbox.image_exists()), reason="needs docker and the lemma-agent:claude image"),
]
KEY = "sk-ant-api03-INTEGRATIONCANARY-9f8e7d6c5b4a-notarealkey"
ROOT = common.repo_root()


@pytest.fixture
def fresh_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Empty HOME and LEMMA_HOME (empty executor cache, no config, no state), the dummy key in the environment, no LEMMA_* variable."""
    for name in list(os.environ):
        if name.startswith("LEMMA_") or name in common.SECRET_ENV:
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("LEMMA_HOME", str(tmp_path / "lemma_home"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    return tmp_path


def user_db(tmp_path: Path) -> Path:
    import duckdb

    path = tmp_path / "shop.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE orders(id INTEGER, qty INTEGER, region VARCHAR)")
    con.execute("INSERT INTO orders SELECT i, i % 9, CASE WHEN i % 2 = 0 THEN 'eu' ELSE 'us' END FROM range(1000) r(i)")
    con.close()
    return path


def all_text(*roots: Path) -> str:
    return "\n".join(p.read_bytes().decode("latin-1") for root in roots for p in root.rglob("*") if p.is_file() and not p.is_symlink())


def test_real_setup_runs_the_real_sandbox_selftest_and_is_idempotent(fresh_user: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["setup", "--auth", "api-key"]) == 0
    out = capsys.readouterr()
    print(out.out)
    assert "READY" in out.out and "sandbox self-test: no direct network" in out.out and "Claude Code 2.1.289" in out.out
    state = json.loads(common.state_path().read_text())
    seen = state["selftest"]["observed"]
    print("observed in the container:", seen)
    assert seen["direct_blocked"] is True
    assert seen["denied"] == {"example.com": 403, "api.anthropic.com.example.com": 403}
    assert seen["allowed"] == {"api.anthropic.com": 200}
    before = sandbox.image_digest()
    assert main(["setup", "--auth", "api-key"]) == 0  # second run: same image id (nothing rebuilt), still ready
    assert sandbox.image_digest() == before and "READY" in capsys.readouterr().out


def test_the_selftest_is_not_vacuous_a_widened_allowlist_makes_it_fail() -> None:
    result = sandbox.selftest(allowlist=("anthropic.com", "example.com"))
    print("problems:", result["problems"])
    assert result["ok"] is False and any("example.com was NOT blocked" in p for p in result["problems"])


def test_a_key_is_handed_to_a_container_by_name_and_login_mode_never_passes_it(fresh_user: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.agent_sandbox import CLAUDE_IMAGE, claude_docker_args

    check = ["sh", "-c", 'if [ -n "$ANTHROPIC_API_KEY" ]; then echo present; else echo absent; fi']

    def inside(args: list[str]) -> str:
        assert not any(KEY in a for a in args)  # the docker command line never carries the value
        done = subprocess.run(["docker", "run", "--rm", "--network", "none", *args, "--entrypoint", check[0], CLAUDE_IMAGE, *check[1:]], capture_output=True, text=True, check=True)
        return done.stdout.strip()

    monkeypatch.setenv("LEMMA_AGENT_AUTH", "api_key")
    assert inside(claude_docker_args()) == "present"  # by name: docker copied the value from this process's environment
    (tmp := fresh_user / "home" / ".claude").mkdir()
    (tmp / ".credentials.json").write_text("{}")
    monkeypatch.setenv("LEMMA_AGENT_AUTH", "login")
    assert inside(claude_docker_args()) == "absent"  # the key is in the environment, the user chose login: it stays out


def test_fresh_user_walkthrough_from_zero_with_only_the_llm_session_stubbed(fresh_user: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """The README quick start in order, in an empty HOME/LEMMA_HOME: setup -> assumptions (answered on stdin of a real process) -> optimize -> status."""
    home, lemma_home = fresh_user / "home", fresh_user / "lemma_home"
    assert not lemma_home.exists()
    assert main(["setup", "--auth", "api-key"]) == 0
    db = user_db(fresh_user)
    env = {**os.environ}
    done = subprocess.run([sys.executable, "-m", "lemma_cli.main", "assumptions", "--db", str(db)], input="y\n" * 200, capture_output=True, text=True, env=env, cwd=fresh_user, check=False)
    print(done.stdout[-600:])
    assert done.returncode == 0, done.stderr
    # optimize before approval would have stopped; now it passes the gate. The agent session is the one stub.
    run_dir = fresh_user / "stub_run"
    (run_dir / "workspace" / "mcp_results").mkdir(parents=True)
    (run_dir / "workspace" / "runquery_agent.rs").write_text("// body the (stub) agent wrote\n")
    exe = run_dir / "out" / "q"
    exe.parent.mkdir()
    exe.write_bytes(b"\x7fELF" + b"\0" * 60)
    exe.chmod(0o755)
    calls: list[dict] = []

    def stub_session(sql: str, db_path: Path, package: Path, mode: str, log: Path) -> dict:
        calls.append({"sql": sql, "mode": mode, "package": str(package)})
        opt.child_env(mode)  # the real environment rules still apply (api_key needs the variable)
        return {"status": "SUCCESS", "run_dir": str(run_dir), "model": "claude-sonnet-5-5", "git_sha": "0" * 40, "official": {"speedup": 1.7}}

    monkeypatch.setattr(opt, "run_pipeline", stub_session)
    assert main(["optimize", "--db", str(db), "--sql", "SELECT region, SUM(qty) AS q FROM orders GROUP BY region"]) == 0
    assert calls[0]["mode"] == "api_key" and "group by region" in calls[0]["sql"]
    executor = next((lemma_home / "executors").iterdir())
    assert sorted(p.name for p in executor.iterdir()) == ["executor", "manifest.json", "proved", "query.sql"]
    assert main(["status"]) == 0
    status = capsys.readouterr().out
    print(status)
    assert "PASSED" in status and "1 cached" in status and "auth            api_key" in status
    # Secret-leak sweep: every file the run wrote (home, lemma home, the db dir) and every byte it printed.
    sweep = all_text(lemma_home, home, fresh_user / "stub_run")
    assert len(sweep) > 1000 and KEY not in sweep
    assert KEY not in status and KEY not in done.stdout and KEY not in done.stderr
    assert KEY not in capsys.readouterr().err
