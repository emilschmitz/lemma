"""Host fixes from the Haiku diagnosis of the 6 published SEC queries: prompt ending and tools, egress attribution, manifest settings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from declarative_spec.prompt import build_declarative_prompt
from research_loop.scripts.run_container_agent import summarize_run


def _prompt(**kw) -> str:
    return build_declarative_prompt(sql="SELECT 1", spec_path="s", edit_path="e", lemma_index="idx", **kw)


# --- the prompt ends with an imperative, on every iteration ---
def test_first_iteration_prompt_ends_with_the_do_it_now_imperative() -> None:
    text = _prompt()
    tail = text[text.rindex("## Do this now") :]
    assert text.rstrip().endswith(tail.rstrip())
    assert "Never ask the user anything" in tail and "N verified, 0 errors" in tail and "submit_runquery" in tail
    assert "## Previous host error" not in text


def test_retry_prompt_keeps_the_imperative_after_the_host_error() -> None:
    text = _prompt(last_error="verification results:: 3 verified, 1 errors")
    assert text.index("## Previous host error") < text.index("## Do this now")
    assert text.rstrip().endswith("not a result.")


# --- the tools statement is accurate ---
def test_prompt_names_the_mcp_tools_and_says_bash_has_no_network_and_no_verus() -> None:
    text = _prompt()
    assert "mcp__lemma-host__run_runquery" in text and "mcp__lemma-host__submit_runquery" in text
    assert "ToolSearch" in text
    assert "no network" in text and "Verus is not on its PATH" in text
    assert "cannot run Verus or a shell" not in text


# --- egress attribution ---
def _write_run(tmp_path: Path, denied: list[dict], raw: list[dict] | None) -> Path:
    ws = tmp_path / "run" / "workspace"
    (ws / "mcp_results").mkdir(parents=True)
    (ws / "logs").mkdir()
    (ws / "runquery_agent.rs").write_text("")
    (ws / "mcp_results" / "egress_bridge.jsonl").write_text(json.dumps({"host": "api.anthropic.com", "ok": True}) + "\n")
    if denied:
        (ws / "mcp_results" / "egress_denied.jsonl").write_text("".join(json.dumps(d) + "\n" for d in denied))
    if raw is not None:
        (ws / "logs" / "claude_raw.jsonl").write_text("".join(json.dumps(r) + "\n" for r in raw))
    return tmp_path / "run"


def _bash(start: str, end: str | None, tool_id: str = "t1") -> list[dict]:
    recs = [{"type": "assistant", "timestamp": start, "message": {"content": [{"type": "tool_use", "id": tool_id, "name": "Bash", "input": {}}]}}]
    if end:
        recs.append({"type": "user", "timestamp": end, "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id}]}})
    return recs


def test_a_denial_inside_an_agent_bash_call_is_reported_separately_not_as_the_run_flag(tmp_path: Path) -> None:
    denial = {"method": "CONNECT", "host": "registry.npmjs.org", "denied": True, "ts": "2026-10-05T17:34:30Z"}
    out = summarize_run(_write_run(tmp_path, [denial], _bash("2026-10-05T17:34:29.100Z", "2026-10-05T17:34:31.000Z")))
    assert out["egress_denied"] is False
    assert out["egress_denied_in_agent_bash"] == ["registry.npmjs.org"] and out["egress_denied_cli_hosts"] == []


def test_a_denial_outside_any_bash_call_still_sets_the_run_flag(tmp_path: Path) -> None:
    denial = {"method": "CONNECT", "host": "example.org", "denied": True, "ts": "2026-10-05T17:40:00Z"}
    out = summarize_run(_write_run(tmp_path, [denial], _bash("2026-10-05T17:34:29Z", "2026-10-05T17:34:31Z")))
    assert out["egress_denied"] is True and out["egress_denied_cli_hosts"] == ["example.org"] and out["egress_denied_in_agent_bash"] == []


def test_mixed_denials_are_split_and_the_cli_one_keeps_the_flag(tmp_path: Path) -> None:
    denials = [
        {"host": "registry.npmjs.org", "denied": True, "ts": "2026-10-05T17:34:30Z"},
        {"host": "telemetry.example", "denied": True, "ts": "2026-10-05T17:50:00Z"},
    ]
    out = summarize_run(_write_run(tmp_path, denials, _bash("2026-10-05T17:34:29Z", "2026-10-05T17:34:31Z")))
    assert out["egress_denied"] is True
    assert out["egress_denied_in_agent_bash"] == ["registry.npmjs.org"] and out["egress_denied_cli_hosts"] == ["telemetry.example"]


@pytest.mark.parametrize("raw", [None, []])
def test_without_a_raw_stream_every_denial_counts_as_the_run_flag(tmp_path: Path, raw: list | None) -> None:
    denial = {"host": "registry.npmjs.org", "denied": True, "ts": "2026-10-05T17:34:30Z"}
    out = summarize_run(_write_run(tmp_path, [denial], raw))
    assert out["egress_denied"] is True and out["egress_denied_in_agent_bash"] == []


def test_a_denial_during_a_bash_call_that_never_returned_is_attributed_to_it(tmp_path: Path) -> None:
    denial = {"host": "registry.npmjs.org", "denied": True, "ts": "2026-10-05T17:36:00Z"}
    out = summarize_run(_write_run(tmp_path, [denial], _bash("2026-10-05T17:34:29Z", None)))
    assert out["egress_denied"] is False and out["egress_denied_in_agent_bash"] == ["registry.npmjs.org"]


def test_no_denials_means_all_three_fields_are_empty(tmp_path: Path) -> None:
    out = summarize_run(_write_run(tmp_path, [], _bash("2026-10-05T17:34:29Z", "2026-10-05T17:34:31Z")))
    assert out["egress_denied"] is False and out["egress_denied_in_agent_bash"] == [] and out["egress_denied_cli_hosts"] == []


# --- the manifest records the settings the run actually used ---
def test_manifest_records_effective_settings_with_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.run_artifacts import begin_run

    for key in ("LEMMA_STRING_ENCODING", "LEMMA_NARROW_CELLS", "LEMMA_PARALLEL_VSTD", "LEMMA_ENABLE_PARALLEL", "LEMMA_ASSUMPTION_PACKAGE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LEMMA_RESEARCH_LOG", "1")
    run = begin_run(query_id=1, sql_query="SELECT 1", root=tmp_path)
    eff = json.loads((run.path / "manifest.json").read_text())["effective"]
    assert eff["LEMMA_STRING_ENCODING"] == "plain" and eff["LEMMA_NARROW_CELLS"] == "0"
    assert eff["LEMMA_PARALLEL_VSTD"] == "off" and eff["LEMMA_ENABLE_PARALLEL"] == "0" and eff["LEMMA_ASSUMPTION_PACKAGE"] is None
    assert "git_sha" in eff and "git_dirty" in eff


def test_manifest_records_set_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.run_artifacts import begin_run

    for key, val in {
        "LEMMA_STRING_ENCODING": "dict",
        "LEMMA_NARROW_CELLS": "1",
        "LEMMA_PARALLEL_VSTD": "auto",
        "LEMMA_ENABLE_PARALLEL": "1",
        "LEMMA_ASSUMPTION_PACKAGE": "sec_margin_dec",
    }.items():
        monkeypatch.setenv(key, val)
    run = begin_run(query_id=1, sql_query="SELECT 1", root=tmp_path)
    eff = json.loads((run.path / "manifest.json").read_text())["effective"]
    assert (eff["LEMMA_STRING_ENCODING"], eff["LEMMA_NARROW_CELLS"], eff["LEMMA_PARALLEL_VSTD"], eff["LEMMA_ENABLE_PARALLEL"]) == ("dict", "1", "auto", "1")
    assert eff["LEMMA_ASSUMPTION_PACKAGE"] == "sec_margin_dec"


def test_a_launcher_default_package_shows_in_the_selection_and_the_manifest_menu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop import menu_profile
    from research_loop.menu_profile import activate_menu, deactivate_menu, record_effective_axis
    from research_loop.run_artifacts import begin_run

    monkeypatch.delenv("LEMMA_ASSUMPTION_PACKAGE", raising=False)
    monkeypatch.setenv("LEMMA_RESEARCH_LOG", "1")
    deactivate_menu()
    try:
        resolved = activate_menu("adversary_declarative0")
        assert resolved.values["assumption_package"] is None and resolved.sources["assumption_package"] == "unset"
        resolved = record_effective_axis("assumption_package", "sec_margin_dec", "default for db")
        assert resolved.as_dict()["axes"]["assumption_package"] == {"value": "sec_margin_dec", "source": "default for db"}
        assert menu_profile.active_menu() is resolved
        monkeypatch.setenv("LEMMA_ASSUMPTION_PACKAGE", "sec_margin_dec")
        run = begin_run(query_id=1, sql_query="SELECT 1", root=tmp_path)
        manifest = json.loads((run.path / "manifest.json").read_text())
        assert manifest["menu"]["axes"]["assumption_package"]["value"] == manifest["effective"]["LEMMA_ASSUMPTION_PACKAGE"] == "sec_margin_dec"
    finally:
        deactivate_menu()


def test_a_denial_just_after_the_bash_result_is_not_hidden_in_the_bash_bucket(tmp_path: Path) -> None:
    # the bridge floors to the second, so a stamp after the tool_result's second cannot belong to the call
    denial = {"host": "telemetry.example", "denied": True, "ts": "2026-10-05T17:34:32Z"}
    out = summarize_run(_write_run(tmp_path, [denial], _bash("2026-10-05T17:34:29.100Z", "2026-10-05T17:34:31.000Z")))
    assert out["egress_denied"] is True and out["egress_denied_in_agent_bash"] == []


def test_a_floored_stamp_before_the_bash_start_second_still_matches(tmp_path: Path) -> None:
    denial = {"host": "registry.npmjs.org", "denied": True, "ts": "2026-10-05T17:34:29Z"}  # real time 17:34:29.95
    out = summarize_run(_write_run(tmp_path, [denial], _bash("2026-10-05T17:34:29.900Z", "2026-10-05T17:34:31.000Z")))
    assert out["egress_denied_in_agent_bash"] == ["registry.npmjs.org"]
