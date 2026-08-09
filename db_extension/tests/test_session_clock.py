"""Tests for agent session wall-clock (session_clock.json + check_session_time)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from db_extension.agent.session_clock import (
    CHECK_SCRIPT_NAME,
    END_SESSION_NAME,
    attach_session,
    clock_path,
    clock_submit_ends,
    read_session_status,
    session_budget_prompt_section,
    start_session_clock,
    write_check_script,
)


def test_start_session_clock_writes_stamp_and_script(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_TIMEOUT_SEC", "120")
    end_path = tmp_path / END_SESSION_NAME
    end_path.parent.mkdir(parents=True)
    end_path.write_text('{"reason": "submit"}')

    payload = start_session_clock(tmp_path, budget_sec=90, submit_ends=True)

    assert clock_path(tmp_path).is_file()
    assert (tmp_path / CHECK_SCRIPT_NAME).is_file()
    assert not end_path.is_file()
    assert payload["budget_sec"] == 90
    assert payload["submit_ends_session"] is True
    on_disk = json.loads(clock_path(tmp_path).read_text())
    assert on_disk["budget_sec"] == 90
    assert on_disk["deadline_unix"] == pytest.approx(payload["start_unix"] + 90)


def test_read_session_status_remaining_and_expired(tmp_path: Path) -> None:
    start = 1_000_000.0
    budget = 60
    clock_path(tmp_path).write_text(
        json.dumps(
            {
                "start_unix": start,
                "deadline_unix": start + budget,
                "budget_sec": budget,
                "submit_ends_session": False,
            }
        )
    )

    mid = read_session_status(tmp_path, now=start + 25.5)
    assert mid["ok"] is True
    assert mid["elapsed_sec"] == 25.5
    assert mid["remaining_sec"] == 34.5
    assert mid["expired"] is False

    done = read_session_status(tmp_path, now=start + budget + 1)
    assert done["remaining_sec"] == 0.0
    assert done["expired"] is True


def test_attach_session_adds_session_key(tmp_path: Path) -> None:
    start_session_clock(tmp_path, budget_sec=30, submit_ends=False)
    out = attach_session(tmp_path, {"ok": True, "phase": "validated"})
    assert "session" in out
    assert out["ok"] is True
    assert out["session"]["ok"] is True
    assert out["session"]["budget_sec"] == 30


def test_clock_submit_ends_prefers_stamp_over_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_SUBMIT_ENDS_SESSION", "1")
    clock_path(tmp_path).write_text(
        json.dumps({"submit_ends_session": False, "start_unix": 0, "deadline_unix": 1})
    )
    assert clock_submit_ends(tmp_path) is False

    monkeypatch.setenv("AGENT_SUBMIT_ENDS_SESSION", "0")
    clock_path(tmp_path).write_text(
        json.dumps({"submit_ends_session": True, "start_unix": 0, "deadline_unix": 1})
    )
    assert clock_submit_ends(tmp_path) is True


def test_write_check_script_runnable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_TIMEOUT_SEC", "45")
    start_session_clock(tmp_path, budget_sec=45, submit_ends=False)
    script = write_check_script(tmp_path)

    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["ok"] is True
    assert "remaining_sec" in out
    assert out["remaining_sec"] > 0


def test_session_budget_prompt_section_submit_ends_on() -> None:
    text = session_budget_prompt_section(budget_sec=600, submit_ends=True)
    assert "600" in text
    assert "Submit ends the session" in text
    assert "AGENT_SUBMIT_ENDS_SESSION=1" in text
    assert "faster than" in text
    assert "check_session_time" in text
    assert "session_status" in text


def test_session_budget_prompt_section_submit_ends_off() -> None:
    text = session_budget_prompt_section(budget_sec=300, submit_ends=False)
    assert "300" in text
    assert "Submit does not end the session" in text
    assert "AGENT_SUBMIT_ENDS_SESSION=0" in text
    assert "faster than" in text
    assert "no further improvement" in text
    assert "keep running" in text
    assert "check_session_time" in text
    assert "session_status" in text
