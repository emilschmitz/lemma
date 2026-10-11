"""The Verus limit runs from the call's start (queue wait counts), and every result and message splits wait from run time."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import lemma_config
from declarative_spec import principles as P
from declarative_spec import prompt as pr
from declarative_spec.verus_limits import run_verus, split_wait, timeout_message

ROOT = Path(__file__).resolve().parents[1]


def _fake_guard(tmp_path: Path, wait: int, run: float) -> str:
    """A stand-in for verus_guarded.sh: reports a queue wait, then runs for `run` seconds."""
    d = tmp_path / "g"
    d.mkdir(exist_ok=True)
    g = d / "verus_guarded.sh"
    g.write_text(f"#!/usr/bin/env bash\nsleep {wait}\necho LEMMA_VERUS_QUEUE_WAIT_SEC={wait} >&2\nsleep {run}\necho 'verification results:: 1 verified, 0 errors'\n")
    g.chmod(0o755)
    return str(g)


def test_guard_script_reports_its_queue_wait_before_running_verus() -> None:
    text = (ROOT / "scripts/ram/verus_guarded.sh").read_text()
    assert text.index("LEMMA_VERUS_QUEUE_WAIT_SEC") < text.index("exec systemd-run") and "T0=$SECONDS" in text


def test_split_wait_parses_and_strips_the_marker() -> None:
    assert split_wait("a\nLEMMA_VERUS_QUEUE_WAIT_SEC=42\nb\n") == (42, "a\nb\n")
    assert split_wait("plain") == (None, "plain")


def test_a_finished_call_reports_wait_and_run_separately(tmp_path: Path) -> None:
    r = run_verus([_fake_guard(tmp_path, 2, 1)], timeout=30)
    assert r.wait_sec == 2 and "LEMMA" not in r.stderr  # type: ignore[attr-defined]
    assert 0.5 <= r.run_sec <= 2.5  # type: ignore[attr-defined]


def test_queue_wait_counts_toward_the_limit(tmp_path: Path) -> None:
    # Waits 3s in the queue, then would run 1s: a 2s limit is already spent while queued.
    with pytest.raises(subprocess.TimeoutExpired) as e:
        run_verus([_fake_guard(tmp_path, 3, 1)], timeout=2)
    assert e.value.wait_sec >= 1.5 and e.value.run_sec < 1.0  # type: ignore[attr-defined]


def test_a_timeout_while_queued_says_so_with_the_split() -> None:
    m = timeout_message("", 300, 300.0, 0.0)
    assert "queued" in m and "waited 300s for the Verus slot" in m and "limit 300s" in m and "VERIFY TIMEOUT" in m


def test_a_timeout_while_running_reports_wait_and_run() -> None:
    m = timeout_message("", 300, 40.0, 260.0)
    assert "waited 40s for the Verus slot, Verus ran 260s, limit 300s" in m and "while queued" not in m
    assert "COMPILE TIMEOUT" in timeout_message("verification results:: 1 verified, 0 errors", 300, 5.0, 295.0)


def _prompt() -> str:
    return "\n".join(pr._verus_queue_lines())


@pytest.mark.parametrize("slots,expect", [(1, "1 Verus run executes at a time"), (2, "2 Verus runs execute at the same time")])
def test_prompt_follows_verus_slots(monkeypatch: pytest.MonkeyPatch, slots: int, expect: str) -> None:
    monkeypatch.setenv("LEMMA_VERUS_SLOTS", str(slots))
    t = _prompt()
    assert expect in t and "wait in a queue" in t and "counts toward" in t


@pytest.mark.parametrize("sec", [120, 777])
def test_prompt_follows_verus_timeout(monkeypatch: pytest.MonkeyPatch, sec: int) -> None:
    monkeypatch.setenv("LEMMA_VERUS_TIMEOUT_SEC", str(sec))
    assert f"{sec}s limit" in _prompt()


@pytest.mark.parametrize("mode", ["full", "principles", "none"])
def test_full_prompt_states_the_queue_in_every_examples_mode(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv("LEMMA_EXAMPLES", mode)
    monkeypatch.setenv("LEMMA_VERUS_SLOTS", "3")
    monkeypatch.setenv("LEMMA_VERUS_TIMEOUT_SEC", "345")
    text = pr.build_declarative_prompt(sql="select 1", spec_path="s", edit_path="e", lemma_index="i")
    assert "3 Verus runs execute at the same time" in text and "345s limit" in text
