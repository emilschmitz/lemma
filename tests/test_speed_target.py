"""speed_target / max_idle_sessions (session scheduling), required settings, tracked-only git_dirty, mode-consistent host messages, partial verification."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

import lemma_config as lc
from declarative_spec import pipeline
from declarative_spec import sessions as S
from declarative_spec.sessions import Outcome, run_sessions
from declarative_spec.verus_limits import timeout_message


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    lc.clear_cli()
    for name in list(os.environ):
        if name.startswith("LEMMA_") or name in lc.ALIASES:
            monkeypatch.delenv(name)


# ---- session scheduling with a fake agent runner -------------------------------------------------------------------


def _drive(outcomes: list[Outcome], *, target: float, max_idle: int = 2, max_iterations: int = 2, timeout: float = 750.0):
    calls: list[tuple[int, str, int | None]] = []
    it = iter(outcomes)

    def run_one(n: int, note: str, limit: int | None) -> Outcome:
        calls.append((n, note, limit))
        return next(it)

    state = run_sessions(run_one, max_iterations=max_iterations, agent_timeout_sec=timeout, target=target, max_idle=max_idle)
    return state, calls


def ok(speedup: float, agent_s: float = 100.0) -> Outcome:
    return Outcome(True, speedup, agent_s, {"speedup": speedup}, f"src{speedup}")


def bad(agent_s: float = 100.0) -> Outcome:
    return Outcome(False, None, agent_s)


def test_an_early_end_below_the_target_starts_another_session_from_the_best_with_a_note() -> None:
    state, calls = _drive([ok(2.0), ok(12.0)], target=10.0, max_iterations=2)
    assert [c[0] for c in calls] == [1, 2]
    assert calls[0][1] == "" and calls[0][2] is None  # first session: no note, the full session limit
    note = calls[1][1]
    assert "2.00x" in note and "10x" in note and "minutes are left" in note
    assert calls[1][2] == 1400  # the time left of the 1500 s budget
    assert state.best.speedup == 12.0 and "target reached" in state.records[-1]["stop_reason"]


def test_reaching_the_target_stops_at_once() -> None:
    state, calls = _drive([ok(10.0)], target=10.0)
    assert len(calls) == 1 and "target reached" in state.records[0]["stop_reason"]


def test_two_idle_sessions_in_a_row_stop() -> None:
    state, calls = _drive([ok(2.0), ok(1.5), bad(), ok(3.0)], target=10.0, max_idle=2, max_iterations=10)
    assert len(calls) == 3 and "without a better speedup" in state.records[-1]["stop_reason"]
    assert state.best.speedup == 2.0  # a slower or failed later session never replaces the best


def test_an_improvement_resets_the_idle_count() -> None:
    state, calls = _drive([ok(2.0), bad(), ok(4.0), bad(), bad()], target=10.0, max_idle=2, max_iterations=10)
    assert len(calls) == 5 and state.best.speedup == 4.0


def test_the_budget_stops_and_caps_the_last_session() -> None:
    state, calls = _drive([ok(2.0, 700), ok(3.0, 700), ok(4.0, 100)], target=10.0, max_iterations=2, timeout=750)  # budget 1500
    assert [c[2] for c in calls] == [None, 800, 100]
    assert len(calls) == 3 and "budget used" in state.records[-1]["stop_reason"]


def test_target_1_reproduces_the_old_rule() -> None:
    state, calls = _drive([ok(1.2)], target=1.0)
    assert len(calls) == 1 and state.best is not None
    state, calls = _drive([bad(), ok(1.2)], target=1.0)  # a further session only after one that did not verify
    assert len(calls) == 2
    state, calls = _drive([bad(), bad(), ok(5.0)], target=1.0, max_iterations=2)  # and never more than max_iterations of them
    assert len(calls) == 2 and state.best is None


def test_sessions_without_a_body_that_beats_the_bar_get_no_note_and_the_full_limit() -> None:
    state, calls = _drive([bad(), bad()], target=10.0, max_iterations=2)
    assert [c[1:] for c in calls] == [("", None), ("", None)]


def test_records_have_start_end_and_best_speedup_and_land_in_the_manifest(tmp_path: Path) -> None:
    state, _ = _drive([ok(2.0), ok(12.0)], target=10.0)
    assert all({"session", "start", "end", "best_speedup", "agent_s"} <= set(r) for r in state.records)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"run_id": "x"}))
    S.record_in_manifest(manifest, state.records)
    data = json.loads(manifest.read_text())
    assert data["run_id"] == "x" and [r["best_speedup"] for r in data["sessions"]] == [2.0, 12.0]


# ---- settings ------------------------------------------------------------------------------------------------------


def test_speed_target_and_idle_keys_have_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    assert lc.get("speed_target") == 10.0 and lc.get("max_idle_sessions") == 2
    monkeypatch.setenv("LEMMA_SPEED_TARGET", "0.5")
    with pytest.raises(lc.ConfigError, match=">= 1.0"):
        lc.get("speed_target")
    monkeypatch.setenv("LEMMA_SPEED_TARGET", "1")
    assert lc.get("speed_target") == 1.0
    monkeypatch.setenv("LEMMA_MAX_IDLE_SESSIONS", "0")
    with pytest.raises(lc.ConfigError):
        lc.get("max_idle_sessions")


def test_duckdb_path_and_assumption_package_have_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(lc.ConfigError, match="duckdb_path has no default"):
        lc.get("duckdb_path")
    with pytest.raises(lc.ConfigError, match="has no default"):
        lc.require_run_settings()
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", "/x.duckdb")
    with pytest.raises(lc.ConfigError, match="assumption_package has no default"):
        lc.require_run_settings()
    monkeypatch.setenv("LEMMA_ASSUMPTION_PACKAGE", "auto")  # "auto" stays valid as an explicit value
    lc.require_run_settings()
    assert lc.effective()["duckdb_path"].value == "/x.duckdb"


def test_new_defaults_are_dict_and_join_chain() -> None:
    assert lc.get("string_encoding") == "dict" and lc.get("join_chain") is True


def test_a_query_without_unique_keys_keeps_the_general_form_under_the_default() -> None:
    from declarative_spec.emit import emit_declarative_spec
    from tests.test_join_chain import SCHEMA, STAR, _catalog, _params

    spec = emit_declarative_spec(STAR, SCHEMA, _catalog(unique=False))
    assert _params(spec)[:3] == ["da", "fact", "db"]  # FROM order, no chain
    spec = emit_declarative_spec(STAR, SCHEMA, _catalog())
    assert _params(spec)[0] == "fact"  # the default chains when the keys are declared


# ---- git_dirty: tracked changes only -------------------------------------------------------------------------------


def _repo(path: Path) -> Path:
    path.mkdir()
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"], ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=path, check=True)
    (path / "a.txt").write_text("1")
    subprocess.run(["git", "add", "a.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=path, check=True)
    return path


def test_untracked_files_do_not_make_the_manifest_dirty_but_are_counted(tmp_path: Path) -> None:
    from research_loop import run_artifacts as ra

    repo = _repo(tmp_path / "r")
    (repo / "artifacts.tar.gz").write_text("untracked")
    assert ra._git_dirty(repo) is False and ra._git_untracked_count(repo) == 1


def test_a_tracked_change_makes_the_manifest_dirty(tmp_path: Path) -> None:
    from research_loop import run_artifacts as ra

    repo = _repo(tmp_path / "r")
    (repo / "a.txt").write_text("2")
    assert ra._git_dirty(repo) is True and ra._git_untracked_count(repo) == 0


# ---- host messages are self-contained and name the lemma.toml key --------------------------------------------------


@pytest.mark.parametrize("mode", ["none", "principles", "full"])
def test_the_verify_timeout_message_points_at_no_prompt_section(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv("LEMMA_EXAMPLES", mode)
    msg = timeout_message("", 300)
    assert "verus_timeout_sec" in msg and "300s" in msg and "LEMMA_VERUS_TIMEOUT_SEC" not in msg
    assert "guidance" not in msg and "see the" not in msg.lower() and "section" not in msg


# ---- prompt ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["none", "principles", "full"])
def test_the_prompt_has_the_speed_target_and_the_partial_tool_in_every_mode(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    from tests.test_declarative_prompt_kinds import STAR, _prompt

    monkeypatch.setenv("LEMMA_SPEED_TARGET", "7")
    text = _prompt(monkeypatch, STAR, mode)
    assert "## Target speedup" in text and "7x the reference engine" in text and "Keep a copy of the last submitted file" in text
    assert "`verify_functions`" in text and "does not count as a submission" in text


# ---- partial verification -------------------------------------------------------------------------------------------


def _fake_verus(tmp_path: Path) -> str:
    path = tmp_path / "fake_verus"
    path.write_text(
        "#!/usr/bin/env python3\nimport sys\n"
        "name = sys.argv[sys.argv.index('--verify-function') + 1]\n"
        "assert '--verify-root' in sys.argv\n"
        "if name == 'broken_helper':\n"
        "    print('error: assertion failed'); print('verification results:: 0 verified, 1 errors'); sys.exit(1)\n"
        "print('verification results:: 3 verified, 0 errors')\n"
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def _partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, names: list[str]) -> dict:
    monkeypatch.setattr(pipeline, "_verus_binary", lambda: _fake_verus(tmp_path))
    monkeypatch.setattr(pipeline, "_admit_and_assemble", lambda spec, src, bins, bar: ("// assembled\n", "body", ""))
    return pipeline.verify_functions_only(spec_rs="", agent_source="// agent\n", names=names, work_dir=tmp_path / "w")


def test_partial_verify_of_a_correct_helper_reports_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = _partial(tmp_path, monkeypatch, ["good_helper"])
    assert out["all_verified"] is True and out["functions"][0]["summary"].endswith("3 verified, 0 errors")
    assert out["label"].startswith("partial check: not a proof of run_query")


def test_partial_verify_reports_a_broken_helper_among_good_ones(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = _partial(tmp_path, monkeypatch, ["good_helper", "broken_helper"])
    assert out["all_verified"] is False
    assert [f["verified"] for f in out["functions"]] == [True, False] and "0 verified, 1 errors" in out["functions"][1]["error"]


def test_a_host_admission_error_is_reported_without_running_verus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "_admit_and_assemble", lambda *a: ("", "", "assume( is forbidden"))
    out = pipeline.verify_functions_only(spec_rs="", agent_source="", names=["f"], work_dir=tmp_path / "w")
    assert out["all_verified"] is False and out["error"] == "assume( is forbidden"


def test_a_partial_run_id_cannot_be_submitted_and_is_flagged_in_the_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import db_extension.verus_bridge as vb
    from db_extension.agent import measure_core as mc
    from db_extension.agent.extract import wrap_body_with_markers
    from db_extension.agent.mcp_tool_registry import dispatch_host_tool
    from db_extension.agent.measure_core import MeasureContext

    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(mc, "mcp_iterate_dataset_size", lambda: 50_000)
    (tmp_path / "runquery_agent.rs").write_text(wrap_body_with_markers("let x = 1;"))
    monkeypatch.setattr(vb, "invoke_partial_verify", lambda **kw: {"label": pipeline.PARTIAL_LABEL, "all_verified": True, "functions": [{"name": "h", "verified": True}]})
    ctx = MeasureContext(query_id=1, workspace=tmp_path, sql="SELECT 1", schema={"V": "bigint"})
    out = dispatch_host_tool("verify_functions", {"names": ["h"]}, ctx)
    assert out["partial"] is True and out["ok"] is False and out["partial_all_verified"] is True and out["label"].startswith("partial check")
    stored = mc.load_run(out["run_id"], ws=tmp_path)
    assert stored["partial"] is True and stored["metrics"]["proof_verified"] is False
    refused = dispatch_host_tool("submit_runquery", {"run_id": out["run_id"]}, ctx)
    assert refused["ok"] is False and "partial check" in refused["error"]
    assert mc.get_submitted(ws=tmp_path) is None


def test_partial_check_needs_function_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from db_extension.agent import measure_core as mc

    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    out = mc.verify_functions_solution(names=[], query_id=1, ws=tmp_path, sql="x", schema={})
    assert out["ok"] is False and "names" in out["error"]


def test_none_mode_below_bar_feedback_has_no_strategy_advice(monkeypatch) -> None:
    from declarative_spec import pipeline
    assert "telescope" not in pipeline.PARALLEL_HINT_NONE and "dense" not in pipeline.PARALLEL_HINT_NONE
    assert "single-threaded" in pipeline.PARALLEL_HINT_NONE


def test_speed_advice_is_kept_outside_none_mode() -> None:
    from declarative_spec import pipeline
    assert "dense" in pipeline._SPEED_ADVICE and "telescope" in pipeline.PARALLEL_HINT_PRINCIPLES


def test_host_replaces_a_file_it_cannot_open_for_writing(tmp_path) -> None:
    import os, stat
    from declarative_spec.drive import _replace_text
    f = tmp_path / "runquery_agent.rs"
    f.write_text("old")
    f.chmod(stat.S_IRUSR)  # like a root-owned file written by the container: not writable by the host
    _replace_text(f, "best body")
    assert f.read_text() == "best body"
    assert not any(p.name.startswith(".runquery_agent.rs.host-") for p in tmp_path.iterdir())


def test_replace_text_creates_a_missing_file(tmp_path) -> None:
    from declarative_spec.drive import _replace_text
    f = tmp_path / "new.rs"
    _replace_text(f, "x")
    assert f.read_text() == "x"


# ---- max_budget_usd: per-query spend cap ---------------------------------------------------------------------------


def _raw(path: Path, *costs: float) -> Path:
    path.write_text("".join(json.dumps({"type": "result", "total_cost_usd": c}) + "\n" for c in costs) + json.dumps({"type": "assistant"}) + "\n")
    return path


def test_claude_cmd_carries_the_remaining_budget() -> None:
    from research_loop.agent_sandbox import claude_agent_cmd, cmd_with_budget

    cmd = cmd_with_budget(claude_agent_cmd("m"), 12.5)
    assert cmd.startswith("claude -p --max-budget-usd 12.5000 --model m")
    assert cmd_with_budget(claude_agent_cmd("m"), 0.25).count("--max-budget-usd") == 1


def test_no_budget_flag_for_zero_cap_or_non_claude_cmd() -> None:
    from research_loop.agent_sandbox import claude_agent_cmd, cmd_with_budget

    assert cmd_with_budget(claude_agent_cmd("m"), 0) == claude_agent_cmd("m")
    assert "--max-budget-usd" not in cmd_with_budget("agent -p --model x < PROMPT.txt", 5.0)


def test_remaining_budget_decreases_across_sessions(tmp_path: Path) -> None:
    from research_loop.agent_sandbox import claude_spend_usd

    raw = tmp_path / "claude_raw.jsonl"
    assert claude_spend_usd(raw) == 0.0
    _raw(raw, 3.5)
    assert 20.0 - claude_spend_usd(raw) == 16.5
    _raw(raw, 3.5, 4.0)
    assert 20.0 - claude_spend_usd(raw) == 12.5
    state = S.Sessions(2, 1500.0, 10.0, 2, 20.0)
    assert state.remaining_usd() == 20.0
    state.add(1, 0.0, 1.0, Outcome(False, None, 1.0, cost_usd=7.5))
    assert state.remaining_usd() == 12.5
    assert S.Sessions(2, 1500.0, 10.0, 2, 0.0).remaining_usd() is None


def test_scheduler_stops_when_the_budget_is_used() -> None:
    outcomes = [Outcome(False, None, 10.0, cost_usd=12.0), Outcome(False, None, 10.0, cost_usd=9.0), Outcome(False, None, 10.0)]
    it = iter(outcomes)
    state = run_sessions(lambda n, note, t: next(it), max_iterations=5, agent_timeout_sec=750.0, target=10.0, max_idle=2, max_budget_usd=20.0)
    assert len(state.records) == 2 and "budget used" in state.records[-1]["stop_reason"]
    it = iter([Outcome(True, 2.0, 10.0, {}, "s", cost_usd=25.0)])
    state = run_sessions(lambda n, note, t: next(it), max_iterations=3, agent_timeout_sec=750.0, target=10.0, max_idle=2, max_budget_usd=20.0)
    assert len(state.records) == 1 and "budget used" in state.records[-1]["stop_reason"]


def test_zero_cap_never_stops_on_spend() -> None:
    it = iter([Outcome(False, None, 1.0, cost_usd=500.0), Outcome(False, None, 1.0, cost_usd=500.0)])
    state = run_sessions(lambda n, note, t: next(it), max_iterations=2, agent_timeout_sec=750.0, target=10.0, max_idle=2, max_budget_usd=0.0)
    assert len(state.records) == 2 and "budget used" not in state.records[-1]["stop_reason"]


def test_manifest_records_session_costs_and_total(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    it = iter([Outcome(False, None, 1.0, cost_usd=1.25), Outcome(False, None, 1.0, cost_usd=2.0)])
    state = run_sessions(lambda n, note, t: next(it), max_iterations=2, agent_timeout_sec=750.0, target=10.0, max_idle=2, max_budget_usd=20.0)
    S.record_in_manifest(manifest, state.records)
    data = json.loads(manifest.read_text())
    assert [r["cost_usd"] for r in data["sessions"]] == [1.25, 2.0] and data["total_cost_usd"] == 3.25
    manifest.write_text("{}")
    S.record_in_manifest(manifest, [{"session": 1, "cost_usd": 0.5}])
    assert json.loads(manifest.read_text())["total_cost_usd"] == 0.5


def test_budget_and_timeout_settings_are_loaded() -> None:
    assert lc.get("agent_timeout_sec") == 1800 and lc.get("max_budget_usd") == 20.0
    assert lc.get("max_iterations") * lc.get("agent_timeout_sec") == 3600
    with pytest.raises(lc.ConfigError):
        lc.set_cli("max_budget_usd", -1.0)
        lc.get("max_budget_usd")


def test_token_totals_count_each_message_once(tmp_path) -> None:
    import json
    from research_loop.agent_sandbox import claude_tokens
    raw = tmp_path / "claude_raw.jsonl"
    u = {"input_tokens": 2, "output_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 50}
    lines = [{"type": "assistant", "message": {"id": "m1", "usage": u}}, {"type": "assistant", "message": {"id": "m1", "usage": u}},
             {"type": "assistant", "message": {"id": "m2", "usage": u}}]
    raw.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    assert claude_tokens(raw) == {"input_tokens": 4, "output_tokens": 20, "cache_creation_input_tokens": 200, "cache_read_input_tokens": 100}


def test_token_totals_present_without_a_result_event(tmp_path) -> None:
    import json
    from research_loop.agent_sandbox import claude_spend_usd, claude_tokens
    raw = tmp_path / "claude_raw.jsonl"
    raw.write_text(json.dumps({"type": "assistant", "message": {"id": "m1", "usage": {"output_tokens": 7}}}) + "\n")
    assert claude_spend_usd(raw) == 0.0 and claude_tokens(raw)["output_tokens"] == 7


def test_session_budget_reaches_the_claude_command() -> None:
    from research_loop.agent_sandbox import apply_session_budget, claude_agent_cmd
    cmd = apply_session_budget(claude_agent_cmd("claude-opus-5-5"), {"SESSION_MAX_BUDGET_USD": "18.7500"})
    assert cmd.startswith("claude -p --max-budget-usd 18.7500 ")


def test_session_budget_absent_or_non_claude_leaves_the_command() -> None:
    from research_loop.agent_sandbox import apply_session_budget, claude_agent_cmd, default_agent_cmd
    assert "--max-budget-usd" not in apply_session_budget(claude_agent_cmd("claude-opus-5-5"), {})
    assert apply_session_budget(default_agent_cmd(), {"SESSION_MAX_BUDGET_USD": "5"}) == default_agent_cmd()
