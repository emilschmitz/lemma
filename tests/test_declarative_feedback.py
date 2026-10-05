"""What the agent sees on a failed check, best-so-far restarts, and the pinned container-agent settings."""

from __future__ import annotations

from pathlib import Path

import pytest

from declarative_spec import best_so_far
from declarative_spec.drive import _prepare_restart
from declarative_spec.feedback import MAX_ERRORS, TOTAL_CHARS, format_failure, regions_of
from declarative_spec.regions import EDIT_END, EDIT_START, HELPERS_END, HELPERS_START

NAME = "declarative_query.rs"
DIR = Path("/tmp/decl-run-abc123")

HOST_HEAD = "\n".join(f"// host line {i}" for i in range(1, 9))  # lines 1..8
AGENT_BODY = "let mut res = Vec::new();\nres.push(1);\nres"


def _agent_file(pad: int = 0) -> str:
    """The agent's file: some host text, the helpers region, then the edit region at different line numbers."""
    return (
        "\n" * pad
        + "// spec above\n"
        + f"{HELPERS_START}\n{HELPERS_END}\nfn run_query() {{\n{EDIT_START}\n\n{AGENT_BODY}\n{EDIT_END}\n}}\n"
    )


def _assembled(body: str = AGENT_BODY) -> str:
    return f"{HOST_HEAD}\nfn a() {{\n{EDIT_START}\n{body}\n{EDIT_END}\n}}\n{HELPERS_START}\n{HELPERS_END}\n"


def _error(line: int, msg: str = "postcondition not satisfied", path: str | None = None) -> str:
    path = path or f"{DIR}/{NAME}"
    return (
        f"error: {msg}\n   --> {path}:{line}:5\n    |\n{line}  |     res\n    |     ^^^ failed this postcondition\n"
    )


def _camel_warning() -> str:
    return (
        "warning: type `Cols_num` should have an upper camel case name\n"
        f"  --> {DIR}/{NAME}:3:12\n   |\n3  | pub struct Cols_num {{\n   |            ^^^^^^^^ help: convert\n"
        "   = note: `#[warn(non_camel_case_types)]` on by default\n"
    )


def test_summary_first_warnings_dropped_and_paths_gone() -> None:
    assembled = _assembled()
    log = _camel_warning() + "\n" + _error(11) + "\nverification results:: 7 verified, 1 errors\n"
    out = format_failure(log, assembled=assembled, agent_source=_agent_file(), directory=DIR)
    assert out.splitlines()[0] == "PROOF ERROR: verification results:: 7 verified, 1 errors."
    assert "Cols_num" not in out and "non_camel_case" not in out
    assert "/tmp" not in out and str(DIR) not in out
    assert "1 warning(s) in host-owned code omitted" in out
    assert "postcondition not satisfied" in out


def test_warnings_only_log_keeps_summary_and_says_what_was_dropped() -> None:
    log = _camel_warning() + _camel_warning() + "\nverification results:: 5 verified, 0 errors\n"
    out = format_failure(log, assembled=_assembled(), agent_source=_agent_file(), directory=DIR)
    assert out.startswith("PROOF ERROR: verification results:: 5 verified, 0 errors.")
    assert "2 warning(s) in host-owned code omitted" in out
    assert "Cols_num" not in out


def test_warning_inside_agent_region_is_kept() -> None:
    # edit region body starts at assembled line 12 (HOST_HEAD 8 lines + "fn a" + marker): line 12 = "let mut res"
    warn = f"warning: unused variable: `x`\n  --> {DIR}/{NAME}:12:9\n   |\n12 | let x = 1;\n   |     ^ help: prefix\n"
    out = format_failure(warn + "\n" + _error(13), assembled=_assembled(), agent_source=_agent_file(), directory=DIR)
    assert "unused variable" in out
    assert "warning(s) in host-owned" not in out


def test_many_errors_are_first_n_in_source_order_with_omitted_count() -> None:
    lines = [900 - 10 * i for i in range(12)]  # Verus emitted them in a scrambled order
    log = "".join(_error(n, f"error number at {n}") for n in lines)
    log += "error: aborting due to 12 previous errors\n\nverification results:: 3 verified, 12 errors\n"
    out = format_failure(log, assembled=_assembled(), agent_source=_agent_file(), directory=DIR)
    shown = [n for n in sorted(lines)[:MAX_ERRORS]]
    positions = [out.index(f"error number at {n}") for n in shown]
    assert positions == sorted(positions)
    assert f"error number at {max(lines)}" not in out
    assert f"{12 - MAX_ERRORS} more error(s) omitted" in out
    assert "aborting due to" not in out


def test_long_log_stays_bounded_and_keeps_the_first_error() -> None:
    big = "error: huge\n   --> " + f"{DIR}/{NAME}:20:1\n" + "".join(f"    | filler line {i}\n" for i in range(3000))
    out = format_failure(big + _error(30, "second"), assembled=_assembled(), agent_source=_agent_file(), directory=DIR)
    assert len(out) < TOTAL_CHARS + 2000
    assert "error: huge" in out and "block truncated" in out


def test_rlimit_message_survives_with_summary_first() -> None:
    log = _error(11, "Resource limit (rlimit) exceeded") + "\nverification results:: 4 verified, 1 errors\n"
    out = format_failure(log, assembled=_assembled(), agent_source=_agent_file(), directory=DIR)
    lines = out.splitlines()
    assert lines[0].startswith("PROOF ERROR: verification results:: 4 verified, 1 errors")
    assert lines[2].startswith("RLIMIT:")


def test_edit_region_line_is_mapped_to_the_agent_file() -> None:
    assembled, agent = _assembled(), _agent_file(pad=40)
    # assembled body lines are 11..13 (line 13 is the third); in the agent file the body starts after "// spec above", helpers, run_query, marker, blank
    first_body_line_in_agent = agent.splitlines().index("let mut res = Vec::new();") + 1
    out = format_failure(_error(13), assembled=assembled, agent_source=agent, directory=DIR)
    assert f"runquery_agent.rs:{first_body_line_in_agent + 2}:5" in out
    assert "(AGENT_EDIT body)" in out
    assert f"\n{first_body_line_in_agent + 2}  |" in out  # gutter rewritten too


def test_host_line_is_marked_not_editable_and_gutter_not_confusable() -> None:
    out = format_failure(_error(5), assembled=_assembled(), agent_source=_agent_file(), directory=DIR)
    assert "generated program line 5:5  (host-owned code, not editable)" in out
    assert "host  |" in out  # gutter shows `host`, not a number that could be mistaken for an agent line


def test_region_not_verbatim_falls_back_to_region_relative_line() -> None:
    drifted = _agent_file().replace("res.push(1);", "res.push(2);")
    out = format_failure(_error(13), assembled=_assembled(), agent_source=drifted, directory=DIR)
    assert "AGENT_EDIT body line 3:5" in out and "runquery_agent.rs:" not in out


def test_unusual_paths_are_scrubbed() -> None:
    odd = "error: bad\n   --> /home/emil/tools/verus/source/vstd/seq.rs:77:3\n    = note: from /opt/some dir/x.rs\n"
    out = format_failure(odd + _error(13), assembled=_assembled(), agent_source=_agent_file(), directory=DIR)
    assert "/home/emil" not in out and "vstd/seq.rs:77:3" in out
    odd2 = "error: spaced\n   --> /var/tmp/with-dash_1/deep/path/declarative_query.rs:13:1\n"  # other dir, same file name
    out2 = format_failure(odd2, assembled=_assembled(), agent_source=_agent_file(), directory=DIR)
    assert "/var/tmp" not in out2 and "runquery_agent.rs" in out2


def test_unrecognised_output_is_shown_not_swallowed() -> None:
    out = format_failure("thread 'main' panicked at z3 crashed\n" + "x" * 5000, assembled=_assembled())
    assert "panicked at z3 crashed" in out and "middle omitted" in out
    assert out.rstrip().endswith("x")


def test_regions_helper_reports_both_regions() -> None:
    names = [r.name for r in regions_of(_assembled(), _agent_file())]
    assert names == ["AGENT_EDIT body"]  # empty helpers region has no lines to map


# ---------------------------------------------------------------- best-so-far


def _m(verified: int | None, errors: int | None, proved: bool = False, status: str = "FAILURE") -> dict:
    err = "rustc error: mode" if verified is None else f"PROOF ERROR: verification results:: {verified} verified, {errors} errors."
    return {"proof_verified": proved, "status": status, "compiler_error": err}


def test_fewest_errors_then_most_verified_wins_and_ties_keep_the_earlier(tmp_path: Path) -> None:
    ws = tmp_path
    best_so_far.record_attempt(ws, "a", _m(15, 10), origin="t")
    best_so_far.record_attempt(ws, "b", _m(12, 1), origin="t")
    assert best_so_far.load_best_entry(ws)["file"] == "002.rs"  # fewer errors beats more verified
    best_so_far.record_attempt(ws, "c", _m(40, 1), origin="t")
    assert best_so_far.load_best_entry(ws)["file"] == "003.rs"  # same errors, more verified
    best_so_far.record_attempt(ws, "d", _m(40, 1), origin="t")
    assert best_so_far.load_best_entry(ws)["file"] == "003.rs"  # tie keeps the earlier
    best_so_far.record_attempt(ws, "e", _m(None, None), origin="t")
    assert best_so_far.load_best_entry(ws)["file"] == "003.rs"  # no tally never displaces one


def test_proved_beats_everything_and_same_file_is_not_rescored(tmp_path: Path) -> None:
    ws = tmp_path
    best_so_far.record_attempt(ws, "a", _m(50, 1), origin="t")
    best_so_far.record_attempt(ws, "ok", _m(20, 0, proved=True, status="SUCCESS"), origin="t")
    assert best_so_far.load_best(ws)[1] == "ok"
    again = best_so_far.record_attempt(ws, "a", _m(99, 0), origin="t")
    assert again["n"] == 1 and best_so_far.load_best(ws)[1] == "ok"


def test_restore_never_overwrites_a_file_that_is_already_the_best(tmp_path: Path) -> None:
    agent = tmp_path / "runquery_agent.rs"
    best_so_far.record_attempt(tmp_path, "good", _m(30, 1), origin="t")
    agent.write_text("good")
    assert best_so_far.restore_best(tmp_path, agent)[0] == "kept"
    agent.write_text("Vec::new() stub")
    assert best_so_far.restore_best(tmp_path, agent)[0] == "restored" and agent.read_text() == "good"


def test_no_attempt_means_nothing_is_touched(tmp_path: Path) -> None:
    agent = tmp_path / "runquery_agent.rs"
    agent.write_text("whatever")
    assert best_so_far.restore_best(tmp_path, agent) == ("none", None)
    assert agent.read_text() == "whatever"


def test_prepare_restart_restores_best_and_says_so(tmp_path: Path) -> None:
    (tmp_path / "context" / "ro").mkdir(parents=True)
    agent = tmp_path / "runquery_agent.rs"
    best_so_far.record_attempt(tmp_path, "BEST", _m(31, 1), origin="mcp:x")
    broke = f"{EDIT_START}\nlet v = Vec::new();\n{EDIT_END}\n"
    agent.write_text(broke)
    record: dict = {}
    note = _prepare_restart(tmp_path, agent, broke, record)
    assert agent.read_text() == "BEST" and record["restart"] == "restored"
    assert "31 verified, 1 errors" in note and "worse file" in note
    assert (tmp_path / "context" / "ro" / "previous_attempt.rs").read_text() == broke
    assert "let v = Vec::new();" in note  # the previous body is in the prompt text
    assert "First errors of the best attempt" in note


def test_prepare_restart_when_last_file_is_the_best(tmp_path: Path) -> None:
    (tmp_path / "context" / "ro").mkdir(parents=True)
    agent = tmp_path / "runquery_agent.rs"
    agent.write_text("BEST")
    best_so_far.record_attempt(tmp_path, "BEST", _m(31, 1), origin="mcp:x")
    note = _prepare_restart(tmp_path, agent, "BEST", {})
    assert "already is that best attempt" in note and agent.read_text() == "BEST"


def test_prepare_restart_without_any_tally_leaves_the_file(tmp_path: Path) -> None:
    (tmp_path / "context" / "ro").mkdir(parents=True)
    agent = tmp_path / "runquery_agent.rs"
    agent.write_text("last")
    note = _prepare_restart(tmp_path, agent, "last", {})
    assert "no best attempt to restore" in note and agent.read_text() == "last"


# ---------------------------------------------------------------- container agent settings


def test_effort_flag_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.agent_sandbox import claude_agent_cmd

    monkeypatch.delenv("LEMMA_CLAUDE_EFFORT", raising=False)
    assert "--effort high " in claude_agent_cmd("claude-haiku-4-5-20251001")
    monkeypatch.setenv("LEMMA_CLAUDE_EFFORT", "medium")
    assert "--effort medium " in claude_agent_cmd("claude-haiku-4-5-20251001")
    monkeypatch.setenv("LEMMA_CLAUDE_EFFORT", "none")
    assert "--effort" not in claude_agent_cmd("claude-haiku-4-5-20251001")


def test_bad_effort_and_thinking_values_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.agent_sandbox import claude_agent_cmd, claude_thinking_tokens

    monkeypatch.setenv("LEMMA_CLAUDE_EFFORT", "ultra")
    with pytest.raises(ValueError):
        claude_agent_cmd("m")
    monkeypatch.setenv("LEMMA_CLAUDE_THINKING_TOKENS", "-5")
    with pytest.raises(ValueError):
        claude_thinking_tokens()
    monkeypatch.setenv("LEMMA_CLAUDE_THINKING_TOKENS", "8000")
    assert claude_thinking_tokens() == 8000


def test_manifest_records_the_effective_claude_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.run_artifacts import effective_settings

    monkeypatch.delenv("LEMMA_CLAUDE_EFFORT", raising=False)
    monkeypatch.delenv("LEMMA_CLAUDE_THINKING_TOKENS", raising=False)
    eff = effective_settings("sha", False)
    assert eff["claude_effort"] == "high" and eff["claude_max_thinking_tokens"] is None
    assert eff["claude_enable_tool_search"] == "false"
    monkeypatch.setenv("LEMMA_CLAUDE_EFFORT", "low")
    monkeypatch.setenv("LEMMA_CLAUDE_THINKING_TOKENS", "4000")
    eff = effective_settings("sha", False)
    assert eff["claude_effort"] == "low" and eff["claude_max_thinking_tokens"] == 4000
