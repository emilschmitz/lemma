"""run_container_agent takes the SQL from --query-sql or --query-file, exactly one."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_loop.scripts import run_container_agent as rca


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def fake_run(menu, style, sql, **kw):
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
