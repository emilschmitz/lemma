"""run_container_agent takes the SQL from --query-sql or --query-file, exactly one."""

from __future__ import annotations

from pathlib import Path

import pytest

import lemma_config
from research_loop.scripts import run_container_agent as rca


@pytest.fixture(autouse=True)
def _tree_counts_as_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lemma_config, "require_clean_tree", lambda root=None: {"git_sha": "0" * 40, "git_dirty": False, "dirty_files": []})
    monkeypatch.setattr(lemma_config, "REQUIRED", ())  # duckdb_path / assumption_package have no default; these tests do not run a database
    lemma_config.clear_cli()


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def fake_run(menu, style, sql, **kw):  # noqa: ARG001
        seen.append(sql)
        return {"status": "SUCCESS"}

    monkeypatch.setattr(rca, "run", fake_run)
    return seen


def test_query_file_is_read_and_stripped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "q.sql"
    f.write_text("SELECT 1\n")
    seen = _capture(monkeypatch)
    assert rca.main(["--style", "declarative", "--menu", "adversary_declarative0", "--query-file", str(f)]) == 0
    assert seen == ["SELECT 1"]


def test_exactly_one_of_the_two_query_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _capture(monkeypatch)
    f = tmp_path / "q.sql"
    f.write_text("SELECT 1")
    with pytest.raises(SystemExit):
        rca.main(["--style", "declarative", "--menu", "adversary_declarative0"])
    with pytest.raises(SystemExit):
        rca.main(["--style", "declarative", "--menu", "adversary_declarative0", "--query-sql", "SELECT 2", "--query-file", str(f)])
    seen = _capture(monkeypatch)
    assert rca.main(["--style", "declarative", "--menu", "adversary_declarative0", "--query-sql", "SELECT 2"]) == 0 and seen == ["SELECT 2"]


def test_a_success_carries_no_error_from_an_earlier_session() -> None:
    hist = [{"error": "agent timed out (AGENT_TIMEOUT_SEC): exit -9.  No submit."}, {"error": ""}]
    assert rca.verdict_error({"status": "SUCCESS", "error": "", "history": hist}) == ""


def test_a_failure_reports_its_error_or_the_last_iteration_error() -> None:
    assert rca.verdict_error({"status": "FAILED", "error": "proved but below the speed bar", "history": []}) == "proved but below the speed bar"
    hist = [{"error": "first"}, {"error": "second"}, {}]
    assert rca.verdict_error({"status": "FAILED", "error": "", "history": hist}) == "second"


# --- lemma.toml is the single source: flags, recorded config, dirty tree ---


def _capture_kwargs(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    seen: list[dict] = []

    def fake_run(menu, style, sql, **kw):
        seen.append({"menu": menu, "style": style, **kw})
        return {"status": "SUCCESS"}

    monkeypatch.setattr(rca, "run", fake_run)
    return seen


def test_flags_beat_the_environment_and_the_environment_beats_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture_kwargs(monkeypatch)
    base = ["--query-sql", "SELECT 1"]
    assert rca.main(base) == 0 and seen[-1]["max_iterations"] == 2 and seen[-1]["agent"] == "claude-sonnet-5-5" and seen[-1]["style"] == "declarative"  # lemma.toml
    monkeypatch.setenv("LEMMA_MAX_ITERATIONS", "3")
    assert rca.main(base) == 0 and seen[-1]["max_iterations"] == 3  # environment over file
    assert rca.main([*base, "--max-iterations", "1", "--agent", "claude-haiku-4-5-20251001"]) == 0
    assert seen[-1]["max_iterations"] == 1 and seen[-1]["agent"] == "claude-haiku-4-5-20251001"  # flag over environment
    assert lemma_config.resolve("max_iterations").source == "cli"


def test_an_unknown_lemma_variable_stops_the_launcher_before_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture_kwargs(monkeypatch)
    monkeypatch.setenv("LEMMA_MAX_ITERATION", "3")
    with pytest.raises(lemma_config.ConfigError, match="LEMMA_MAX_ITERATION"):
        rca.main(["--query-sql", "SELECT 1"])
    assert not seen


def test_a_dirty_tree_stops_the_launcher_before_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # the autouse "clean" patch off: the real check, with the git state faked dirty
    monkeypatch.setattr(lemma_config, "REQUIRED", ())
    seen = _capture_kwargs(monkeypatch)
    monkeypatch.setattr(lemma_config, "git_state", lambda root=None: {"git_sha": "a" * 40, "git_dirty": True, "dirty_files": [" M x.py"]})
    with pytest.raises(lemma_config.ConfigError, match="uncommitted changes in tracked files"):
        rca.main(["--query-sql", "SELECT 1"])
    assert not seen
    monkeypatch.setenv("LEMMA_ALLOW_DIRTY", "1")
    assert rca.main(["--query-sql", "SELECT 1"]) == 0 and len(seen) == 1


def test_the_result_and_the_run_record_the_effective_config_and_git_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    from db_extension import optimizer
    from research_loop import agent_sandbox, menu_profile
    from research_loop.scripts import declarative_draws, sqlsmith_trusted_coverage

    db = tmp_path / "x.duckdb"
    db.write_text("")
    monkeypatch.setattr(os, "environ", os.environ.copy())  # run() exports the config into the environment: keep that inside this test
    monkeypatch.setattr(declarative_draws, "resolve_sec_db", lambda: db)
    monkeypatch.setattr(declarative_draws, "package_for_db", lambda p: "sec_margin_dec")
    monkeypatch.setattr(sqlsmith_trusted_coverage, "load_sec_schema", lambda p=None: {})
    monkeypatch.setattr(agent_sandbox, "claude_docker_args", lambda: [])
    monkeypatch.setattr(optimizer, "run_optimization_loop", lambda sql, **kw: {"status": "SUCCESS", "history": []})
    monkeypatch.setattr(lemma_config, "git_state", lambda root=None: {"git_sha": "b" * 40, "git_dirty": False, "dirty_files": []})
    monkeypatch.delenv("LEMMA_ASSUMPTION_PACKAGE", raising=False)  # tests/conftest.py pins prove_loop
    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "3")
    lemma_config.set_cli("max_iterations", 1, "--max-iterations")
    try:
        rec = rca.run("adversary_declarative0", "declarative", "SELECT 1", agent="claude-sonnet-5-5", max_iterations=1, allow_override=True)
    finally:
        menu_profile.deactivate_menu()
    assert set(rec["config"]) == set(lemma_config.schema()) and rec["git_sha"] == "b" * 40 and rec["git_dirty"] is False
    assert rec["config"]["official_rounds"]["value"] == 3 and rec["config"]["official_rounds"]["source"] == "env"
    assert rec["config"]["max_iterations"]["source"] == "cli" and rec["config"]["agent_timeout_sec"] == {"section": "agent", "value": 750, "source": "file", "origin": "lemma.toml"}


def test_the_launcher_stops_without_a_database_or_a_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lemma_config, "REQUIRED", ("duckdb_path", "assumption_package"))
    for name in ("LEMMA_DUCKDB_PATH", "LEMMA_ASSUMPTION_PACKAGE"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(lemma_config.ConfigError, match="duckdb_path has no default"):
        rca.main(["--query-sql", "SELECT 1"])
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", "/db.duckdb")
    with pytest.raises(lemma_config.ConfigError, match="assumption_package has no default"):
        rca.main(["--query-sql", "SELECT 1"])
    seen = _capture(monkeypatch)
    rca.main(["--query-sql", "SELECT 1", "--assumption-package", "auto"])  # a flag supplies it
    assert seen == ["SELECT 1"]
