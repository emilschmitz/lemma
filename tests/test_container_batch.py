"""The batch launcher builds one locked, memory-capped command per run."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_loop.scripts import container_batch as cb


def test_command_is_locked_capped_and_carries_the_selected_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", "/db.duckdb")
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    monkeypatch.delenv("LEMMA_TPCH_DB", raising=False)
    cmd = cb.command("claude-sonnet-5-5", Path("/q.sql"))
    assert cmd[:6] == ["flock", "/tmp/lemma_timing.lock", "choom", "-n", "800", "--"] and cmd[6] == "systemd-run" and "--slice=lemma.slice" in cmd
    assert "MemoryMax=6G" in cmd and "--setenv=LEMMA_DUCKDB_PATH=/db.duckdb" in cmd and "--setenv=LEMMA_STRING_ENCODING=dict" in cmd
    assert not any(c.startswith("--setenv=LEMMA_TPCH_DB") for c in cmd)
    assert cmd[cmd.index("--agent") + 1] == "claude-sonnet-5-5" and "--allow-override" in cmd and cmd[-1] == "/q.sql"


def test_short_model_names_map_to_slugs_and_logs_are_named_by_model_and_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cb, "OUT", tmp_path)
    (tmp_path / "qX.sql").write_text("SELECT 1")
    calls: list[list[str]] = []

    class R:
        returncode = 0

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
