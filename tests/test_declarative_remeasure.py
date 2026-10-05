"""The re-measure wrapper: prepare + transplant + check, one result line per run with the data label."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_loop.scripts import declarative_remeasure as rm


class _R:
    def __init__(self, out: str = "", code: int = 0) -> None:
        self.stdout, self.stderr, self.returncode = out, "", code


def test_a_successful_remeasure_appends_one_regen_checked_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sql = tmp_path / "q.sql"
    sql.write_text("SELECT 1\n")
    monkeypatch.setattr(rm, "RESULTS", tmp_path / "results.jsonl")
    monkeypatch.setattr(rm, "MANUAL", tmp_path / "manual")
    calls: list[list[str]] = []

    def fake(args: list[str]) -> _R:
        calls.append(args)
        return _R(json.dumps({"status": "SUCCESS", "speedup": 2.5, "latency_us": 10}) + "\nrest") if "check" in args else _R()

    monkeypatch.setattr(rm, "_run", fake)
    monkeypatch.setattr("sys.argv", ["x", "--src", "S", "--kind", "sec", "--sql-file", str(sql), "--name", "n1", "--data", "real SEC test"])
    assert rm.main() == 0
    assert [c[1] for c in calls] == ["prepare", "S", "check"]  # prepare, transplant (src first), check
    row = json.loads((tmp_path / "results.jsonl").read_text())
    assert row["regen_checked"] is True and row["data"] == "real SEC test" and row["speedup"] == 2.5 and row["sql"] == "SELECT 1"


def test_a_failing_step_stops_and_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sql = tmp_path / "q.sql"
    sql.write_text("SELECT 1\n")
    monkeypatch.setattr(rm, "RESULTS", tmp_path / "results.jsonl")
    monkeypatch.setattr(rm, "MANUAL", tmp_path / "manual")
    monkeypatch.setattr(rm, "_run", lambda args: _R("boom", 1) if "check" in args else _R())
    monkeypatch.setattr("sys.argv", ["x", "--src", "S", "--kind", "sec", "--sql-file", str(sql), "--name", "n2", "--data", "d"])
    with pytest.raises(SystemExit, match="step failed"):
        rm.main()
    assert not (tmp_path / "results.jsonl").exists()
