"""The MCP result and compile_and_run: the reduced failure text appears once, host paths stay out."""

from __future__ import annotations

from pathlib import Path

import pytest

from declarative_spec import best_so_far
from declarative_spec.regions import EDIT_END, EDIT_START, HELPERS_END, HELPERS_START

NAME = "declarative_query.rs"


def _assembled() -> str:
    head = "\n".join(f"// host line {i}" for i in range(1, 9))
    return f"{head}\nfn a() {{\n{EDIT_START}\nx\nres\n{EDIT_END}\n}}\n{HELPERS_START}\n{HELPERS_END}\n"


def _agent_file() -> str:
    return f"// spec\n{EDIT_START}\nx\nres\n{EDIT_END}\n{HELPERS_START}\n{HELPERS_END}\n"


def _fake_verus(tmp_path: Path, log: str) -> str:
    script = tmp_path / "fake_verus.sh"
    script.write_text(f"#!/bin/sh\ncat <<'EOF_LOG'\n{log}\nEOF_LOG\nexit 1\n")
    script.chmod(0o755)
    return str(script)


def test_compile_and_run_returns_the_reduced_text_once_and_keeps_the_full_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from declarative_spec.pipeline import compile_and_run

    build = tmp_path / "ws" / "declarative_build"
    log = (
        f"warning: type `Cols_num` should have an upper camel case name\n  --> {build}/{NAME}:3:12\n   |\n3  | struct\n\n"
        f"error: postcondition not satisfied\n   --> {build}/{NAME}:12:5\n    |\n12  |     res\n    |     ^^^\n\n"
        "verification results:: 7 verified, 1 errors\n"
    )
    monkeypatch.setenv("LEMMA_VERUS_BIN", _fake_verus(tmp_path, log))
    res = compile_and_run(_assembled(), work_dir=build, agent_source=_agent_file())
    assert res["compiler_error"] == res["verify_msg"]
    assert res["compiler_error"].startswith("PROOF ERROR: verification results:: 7 verified, 1 errors.")
    assert "Cols_num" not in res["compiler_error"] and str(tmp_path) not in res["compiler_error"]
    assert "runquery_agent.rs:4:5" in res["compiler_error"]
    assert "Cols_num" in (build / "verify_full.log").read_text()  # nothing is lost from the trace


def test_compile_and_run_unparsable_log_is_still_shown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.pipeline import compile_and_run

    monkeypatch.setenv("LEMMA_VERUS_BIN", _fake_verus(tmp_path, "z3 exited with signal 9"))
    res = compile_and_run(_assembled(), work_dir=tmp_path / "b", agent_source=_agent_file())
    assert "z3 exited with signal 9" in res["compiler_error"]


def test_run_solution_does_not_repeat_the_error_and_records_the_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from db_extension.agent import measure_core as mc

    ws = tmp_path
    (ws / "runquery_agent.rs").write_text(f"{EDIT_START}\nx\n{EDIT_END}\n")
    err = "PROOF ERROR: verification results:: 9 verified, 2 errors.\n\nerror: boom\n"
    monkeypatch.setattr(mc, "mcp_iterate_dataset_size", lambda: 50_000)
    monkeypatch.setattr(
        mc,
        "_invoke_harness",
        lambda **_: ({"status": "FAILURE", "proof_verified": False, "latency_us": -1, "compiler_error": err}, 1),
    )
    out = mc.run_solution(path="runquery_agent.rs", query_id=1, ws=ws)
    assert out["ok"] is False
    assert err not in "".join(out["errors"]) and "metrics.compiler_error" in out["errors"][0]
    assert out["metrics"]["compiler_error"] == err
    best = best_so_far.load_best_entry(ws)
    assert (best["verified"], best["errors"]) == (9, 2)
    assert (ws / "mcp_results" / "attempts" / best["file"]).read_text() == (ws / "runquery_agent.rs").read_text()


def test_run_solution_two_checks_best_is_the_better_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from db_extension.agent import measure_core as mc

    ws = tmp_path
    agent = ws / "runquery_agent.rs"
    results = iter(["verification results:: 30 verified, 1 errors", "verification results:: 5 verified, 6 errors"])

    def harness(**_):
        return {"status": "FAILURE", "proof_verified": False, "latency_us": -1, "compiler_error": next(results)}, 1

    monkeypatch.setattr(mc, "_invoke_harness", harness)
    monkeypatch.setattr(mc, "mcp_iterate_dataset_size", lambda: 50_000)
    agent.write_text(f"{EDIT_START}\ngood\n{EDIT_END}\n")
    mc.run_solution(path="runquery_agent.rs", query_id=1, ws=ws)
    agent.write_text(f"{EDIT_START}\nworse\n{EDIT_END}\n")
    mc.run_solution(path="runquery_agent.rs", query_id=1, ws=ws)
    assert "good" in best_so_far.load_best(ws)[1]
    assert best_so_far.restore_best(ws, agent)[0] == "restored" and "good" in agent.read_text()


def test_relativize_paths_only_touches_paths_under_the_workspace(tmp_path: Path) -> None:
    from db_extension.agent.mcp_tool_registry import _relativize_paths

    out = _relativize_paths(
        {"runquery_path": str(tmp_path / "runquery_agent.rs"), "result_path": "/etc/elsewhere.json", "ok": False}, tmp_path
    )
    assert out["runquery_path"] == "runquery_agent.rs"
    assert out["result_path"] == "/etc/elsewhere.json"
    assert _relativize_paths({"result_path": None}, tmp_path) == {"result_path": None}
