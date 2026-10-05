"""Fixes from the adversary review of the feedback / best-so-far change."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from declarative_spec import best_so_far
from declarative_spec.feedback import MAX_ERRORS, format_failure
from declarative_spec.regions import EDIT_END, EDIT_START

NAME = "declarative_query.rs"
DIR = Path("/tmp/decl-run-x")


def _assembled() -> str:
    head = "\n".join(f"// host {i}" for i in range(1, 21))  # lines 1..20
    return f"{head}\n{EDIT_START}\nlet a = 1;\nres\n{EDIT_END}\n"  # body lines 22, 23


AGENT = f"// s\n{EDIT_START}\nlet a = 1;\nres\n{EDIT_END}\n"


def _err(line: int, msg: str) -> str:
    return f"error: {msg}\n   --> {DIR}/{NAME}:{line}:1\n    |\n{line}  | code\n    |\n\n"


def _m(v: int | None, e: int | None) -> dict:
    text = "stub rustc error" if v is None else f"verification results:: {v} verified, {e} errors"
    return {"proof_verified": False, "status": "FAILURE", "compiler_error": text}


def test_agent_region_error_is_not_pushed_out_by_host_errors() -> None:
    log = "".join(_err(n, f"host error {n}") for n in range(1, 15)) + _err(23, "agent error")
    out = format_failure(log, assembled=_assembled(), agent_source=AGENT, directory=DIR)
    assert "agent error" in out and "runquery_agent.rs:4:1" in out
    assert out.count("host error") == MAX_ERRORS - 1


def test_agent_errors_fill_the_cap_first_but_display_in_source_order() -> None:
    log = _err(23, "second agent") + _err(22, "first agent")
    out = format_failure(log, assembled=_assembled(), agent_source=AGENT, directory=DIR)
    assert out.index("first agent") < out.index("second agent")


def test_vstd_snippet_gutter_is_not_rewritten() -> None:
    log = (
        f"error: precondition not satisfied\n   --> {DIR}/{NAME}:23:1\n    |\n23  | res\n    |\n"
        "   ::: /home/emil/tools/verus/source/vstd/seq.rs:17:5\n    |\n17  | requires x\n    |\n"
    )
    out = format_failure(log, assembled=_assembled(), agent_source=AGENT, directory=DIR)
    assert "\n17  | requires x" in out and "vstd/seq.rs:17:5" in out
    assert "\n4  | res" in out  # the assembled snippet is still mapped


def test_scrub_does_not_mangle_code_in_snippets() -> None:
    log = f"error: x\n   --> {DIR}/{NAME}:23:1\n    |\n23  | let q = (a)/b/c;\n"
    out = format_failure(log, assembled=_assembled(), agent_source=AGENT, directory=DIR)
    assert "(a)/b/c" in out


def test_no_tally_attempts_are_never_best(tmp_path: Path) -> None:
    best_so_far.record_attempt(tmp_path, "STUB", _m(None, None), origin="t")
    best_so_far.record_attempt(tmp_path, "ALMOST", _m(None, None), origin="t")
    assert best_so_far.load_best_entry(tmp_path) is None
    agent = tmp_path / "a.rs"
    agent.write_text("ALMOST+")
    assert best_so_far.restore_best(tmp_path, agent) == ("none", None)
    assert agent.read_text() == "ALMOST+"


def test_a_tally_attempt_beats_earlier_no_tally_ones(tmp_path: Path) -> None:
    best_so_far.record_attempt(tmp_path, "STUB", _m(None, None), origin="t")
    best_so_far.record_attempt(tmp_path, "GOOD", _m(10, 3), origin="t")
    assert best_so_far.load_best(tmp_path)[1] == "GOOD"


def test_same_file_later_gets_a_tally(tmp_path: Path) -> None:
    best_so_far.record_attempt(tmp_path, "F", _m(None, None), origin="mcp")  # timeout: no tally
    entry = best_so_far.record_attempt(tmp_path, "F", _m(40, 0), origin="host-final")
    assert entry["verified"] == 40 and best_so_far.load_best(tmp_path)[1] == "F"


def test_tampered_best_json_is_refused(tmp_path: Path) -> None:
    best_so_far.record_attempt(tmp_path, "GOOD", _m(10, 3), origin="t")
    secret = tmp_path / "secret.txt"
    secret.write_text("host secret")
    path = tmp_path / "mcp_results" / "attempts" / "best.json"
    entry = json.loads(path.read_text())
    entry["file"] = "../../secret.txt"
    path.write_text(json.dumps(entry))
    agent = tmp_path / "a.rs"
    agent.write_text("mine")
    with pytest.raises(ValueError):
        best_so_far.restore_best(tmp_path, agent)
    assert agent.read_text() == "mine"


def test_modified_attempt_file_or_symlink_is_refused(tmp_path: Path) -> None:
    best_so_far.record_attempt(tmp_path, "GOOD", _m(10, 3), origin="t")
    f = tmp_path / "mcp_results" / "attempts" / "001.rs"
    f.write_text("EVIL")
    with pytest.raises(ValueError):
        best_so_far.load_best(tmp_path)
    f.unlink()
    f.symlink_to(tmp_path / "elsewhere")
    (tmp_path / "elsewhere").write_text("GOOD")
    with pytest.raises(ValueError):
        best_so_far.load_best(tmp_path)


def test_lost_index_never_reuses_an_attempt_number(tmp_path: Path) -> None:
    best_so_far.record_attempt(tmp_path, "ONE", _m(10, 3), origin="t")
    (tmp_path / "mcp_results" / "attempts" / "index.json").unlink()
    entry = best_so_far.record_attempt(tmp_path, "TWO", _m(20, 1), origin="t")
    assert entry["file"] == "002.rs" and (tmp_path / "mcp_results" / "attempts" / "001.rs").read_text() == "ONE"


@pytest.mark.parametrize("junk", ["{", "{}", "[]", "null"])
def test_garbage_best_json_is_treated_as_absent(tmp_path: Path, junk: str) -> None:
    best_so_far.record_attempt(tmp_path, "ONE", _m(10, 3), origin="t")
    (tmp_path / "mcp_results" / "attempts" / "best.json").write_text(junk)
    assert best_so_far.load_best_entry(tmp_path) is None
    best_so_far.record_attempt(tmp_path, "TWO", _m(5, 5), origin="t")  # recording still works


def test_crlf_source_round_trips(tmp_path: Path) -> None:
    src = "a\r\nb\r\n"
    best_so_far.record_attempt(tmp_path, src, _m(10, 1), origin="t")
    agent = tmp_path / "a.rs"
    agent.write_text("other")
    assert best_so_far.restore_best(tmp_path, agent)[0] == "restored"
    assert agent.read_bytes() == src.encode()


def test_prepare_restart_survives_a_tampered_store(tmp_path: Path) -> None:
    from declarative_spec.drive import _prepare_restart

    (tmp_path / "context" / "ro").mkdir(parents=True)
    best_so_far.record_attempt(tmp_path, "GOOD", _m(10, 3), origin="t")
    (tmp_path / "mcp_results" / "attempts" / "001.rs").write_text("EVIL")
    agent = tmp_path / "runquery_agent.rs"
    agent.write_text("mine")
    record: dict = {}
    note = _prepare_restart(tmp_path, agent, "mine", record)
    assert "integrity check" in note and agent.read_text() == "mine" and "unusable" in record["restart"]


def test_help_snippet_after_a_vstd_span_is_still_rewritten() -> None:
    log = (
        f"error: x\n   --> {DIR}/{NAME}:23:1\n    |\n23  | res\n    |\n"
        "   ::: /home/emil/tools/verus/source/vstd/seq.rs:17:5\n    |\n17  | requires x\n    |\n"
        f"help: try this\n   --> {DIR}/{NAME}:23:1\n    |\n23  | res2\n"
    )
    out = format_failure(log, assembled=_assembled(), agent_source=AGENT, directory=DIR)
    assert "\n17  | requires x" in out and "\n4  | res2" in out
