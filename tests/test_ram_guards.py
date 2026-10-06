"""The machine-wide memory guards: one heavy job at a time, Verus through the guarded wrapper by default."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from declarative_spec import pipeline

ROOT = Path(__file__).resolve().parents[1]


def test_verus_default_is_the_guarded_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_VERUS_BIN", raising=False)
    assert pipeline._verus_binary() == str(ROOT / "scripts" / "ram" / "verus_guarded.sh")


def test_verus_override_is_respected_on_purpose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_VERUS_BIN", "/opt/verus")
    assert pipeline._verus_binary() == "/opt/verus"


def test_guard_scripts_default_to_one_verus_slot_and_wait_for_memory() -> None:
    text = (ROOT / "scripts" / "ram" / "verus_guarded.sh").read_text()
    assert 'VERUS_SLOTS:-1' in text and "MemAvailable" in text and "MemorySwapMax=0" in text


@pytest.mark.skipif(not Path("/usr/bin/systemd-run").exists(), reason="needs systemd-run")
def test_heavy_runs_the_command_under_the_cap_and_returns_its_status() -> None:
    env = {**os.environ, "HEAVY_MIN_AVAIL_MB": "0", "HEAVY_MEM_MAX": "512M", "HEAVY_LOCK": "/tmp/lemma_test_heavy.lock"}
    ok = subprocess.run([str(ROOT / "scripts/ram/heavy.sh"), "true"], env=env, timeout=60)
    bad = subprocess.run([str(ROOT / "scripts/ram/heavy.sh"), "false"], env=env, timeout=60)
    assert ok.returncode == 0 and bad.returncode == 1


def test_heavy_waits_when_memory_is_short() -> None:
    env = {**os.environ, "HEAVY_MIN_AVAIL_MB": "999999999", "HEAVY_LOCK": "/tmp/lemma_test_heavy.lock"}
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run([str(ROOT / "scripts/ram/heavy.sh"), "true"], env=env, timeout=4, capture_output=True)


@pytest.mark.skipif(not Path("/usr/bin/systemd-run").exists(), reason="needs systemd-run")
def test_heavy_jobs_run_in_the_lemma_slice_and_are_first_to_be_oom_killed() -> None:
    env = {**os.environ, "HEAVY_MIN_AVAIL_MB": "0", "HEAVY_LOCK": "/tmp/lemma_test_heavy.lock"}
    out = subprocess.run(
        [str(ROOT / "scripts/ram/heavy.sh"), "python3", "-u", "-c",
         "print(open('/proc/self/cgroup').read()); print(open('/proc/self/oom_score_adj').read())"],
        env=env, timeout=60, capture_output=True, text=True,
    ).stdout
    assert "lemma.slice" in out and out.strip().endswith("800")


@pytest.mark.skipif(not Path("/usr/bin/systemd-run").exists(), reason="needs systemd-run")
def test_a_job_over_its_cap_is_killed_alone() -> None:
    env = {**os.environ, "HEAVY_MIN_AVAIL_MB": "0", "HEAVY_MEM_MAX": "200M", "HEAVY_LOCK": "/tmp/lemma_test_heavy.lock"}
    r = subprocess.run(
        [str(ROOT / "scripts/ram/heavy.sh"), "python3", "-c",
         "b = bytearray(600 * 1024 * 1024)\nfor i in range(0, len(b), 4096): b[i] = 1"],
        env=env, timeout=60, capture_output=True,
    )
    assert r.returncode != 0
