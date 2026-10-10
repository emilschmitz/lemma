"""A verified binary that does not finish is a SPEED failure with its own message, and it reaches the agent before the MCP harness gives up."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from declarative_spec import pipeline
from declarative_spec.verus_limits import (
    DEFAULT_RUN_TIMEOUT_SEC,
    DEFAULT_TIMEOUT_SEC,
    HARNESS_SLACK_SEC,
    RUN_TIMEOUT_ENV,
    TIMEOUT_ENV,
    declarative_harness_budget_sec,
    run_timeout_sec,
)


def _fake_verus_that_builds(tmp_path: Path, binary_body: str) -> str:
    """A `verus` that prints a clean proof result and writes the compiled program `declarative_query` next to the source."""
    path = tmp_path / "fake_verus"
    program = "#!/bin/sh\n" + binary_body
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import os, stat, sys\n"
        "print('verification results:: 3 verified, 0 errors')\n"
        "out = os.path.join(os.getcwd(), 'declarative_query')\n"
        f"open(out, 'w').write({program!r})\n"
        "os.chmod(out, os.stat(out).st_mode | stat.S_IEXEC)\n"
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


@pytest.fixture(autouse=True)
def _own_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEAVY_LOCK", str(tmp_path / "lock"))
    monkeypatch.setenv("HEAVY_MIN_AVAIL_MB", "1")


def test_run_timeout_default_override_and_bad_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(RUN_TIMEOUT_ENV, raising=False)
    assert run_timeout_sec() == DEFAULT_RUN_TIMEOUT_SEC
    monkeypatch.setenv(RUN_TIMEOUT_ENV, "7")
    assert run_timeout_sec() == 7
    for bad in ("0", "-1", "soon"):
        monkeypatch.setenv(RUN_TIMEOUT_ENV, bad)
        with pytest.raises(ValueError):
            run_timeout_sec()


def test_a_proved_binary_that_does_not_finish_says_run_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "_verus_binary", lambda: _fake_verus_that_builds(tmp_path, "sleep 30\n"))
    monkeypatch.setenv(RUN_TIMEOUT_ENV, "1")
    metrics = pipeline.compile_and_run("// program", work_dir=tmp_path / "w")
    assert metrics["status"] == "FAILURE"
    assert metrics["proof_verified"] is True  # the proof is fine; the run is what failed
    assert metrics["compiler_error"].startswith("RUN TIMEOUT: ")
    assert "1s" in metrics["compiler_error"] and "not a proof error" in metrics["compiler_error"]


def test_a_binary_inside_the_run_limit_still_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "_verus_binary", lambda: _fake_verus_that_builds(tmp_path, "echo QUERY_LATENCY_US: 5\n"))
    monkeypatch.setenv(RUN_TIMEOUT_ENV, "20")
    metrics = pipeline.compile_and_run("// program", work_dir=tmp_path / "w")
    assert metrics["status"] == "SUCCESS" and metrics["latency_us"] == 5


def test_the_harness_waits_longer_than_both_inner_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    from db_extension.agent import measure_core

    monkeypatch.delenv(RUN_TIMEOUT_ENV, raising=False)
    monkeypatch.delenv(TIMEOUT_ENV, raising=False)
    wait = measure_core._harness_timeout_sec()
    assert wait == DEFAULT_TIMEOUT_SEC + DEFAULT_RUN_TIMEOUT_SEC + HARNESS_SLACK_SEC == declarative_harness_budget_sec()
    # a raised inner limit raises the wait with it, so the inner message can never lose the race
    monkeypatch.setenv(RUN_TIMEOUT_ENV, "200")
    assert measure_core._harness_timeout_sec() == DEFAULT_TIMEOUT_SEC + 200 + HARNESS_SLACK_SEC
