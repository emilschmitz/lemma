"""The container launcher reports threads used and the hosts the sandbox reached, from the run directory."""

from __future__ import annotations

import json
from pathlib import Path

from research_loop.scripts.run_container_agent import summarize_run


def _run_dir(tmp_path: Path, body: str, hosts: list[str], denied: str = "") -> Path:
    ws = tmp_path / "run" / "workspace"
    (ws / "mcp_results").mkdir(parents=True)
    (ws / "runquery_agent.rs").write_text(body)
    (ws / "mcp_results" / "egress_bridge.jsonl").write_text("".join(json.dumps({"host": h, "ok": True}) + "\n" for h in hosts))
    if denied:
        (ws / "mcp_results" / "egress_denied.jsonl").write_text(denied)
    return tmp_path / "run"


def test_threads_and_hosts_are_read_from_the_run_directory(tmp_path: Path) -> None:
    out = summarize_run(_run_dir(tmp_path, "let h = vstd::thread::spawn(move || 1);", ["api.anthropic.com", "api.anthropic.com"]))
    assert out["threads_used"] is True and out["egress_hosts"] == ["api.anthropic.com"] and out["egress_denied"] is False


def test_a_sequential_body_a_foreign_host_and_a_missing_run_dir(tmp_path: Path) -> None:
    out = summarize_run(_run_dir(tmp_path, "while i > 0 { i -= 1; }", ["api.anthropic.com", "example.org"], denied='{"host": "example.org"}\n'))
    assert out["threads_used"] is False and out["egress_hosts"] == ["api.anthropic.com", "example.org"] and out["egress_denied"] is True
    assert summarize_run(None) == {"run_dir": None}


def test_new_run_dirs_ignore_the_latest_pointer(tmp_path: Path) -> None:
    from research_loop.scripts.run_container_agent import new_run_dirs

    runs = tmp_path / "runs"
    (runs / "old").mkdir(parents=True)
    before = set(runs.glob("*"))
    (runs / "20261005_new").mkdir()
    (runs / "LATEST").write_text("20261005_new")
    assert new_run_dirs(runs, before) == [runs / "20261005_new"]
    assert new_run_dirs(tmp_path / "missing", set()) == []
