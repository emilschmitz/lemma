"""Heavy phases (export, timed run) take the machine lock exclusively; the Verus guard takes it shared."""

from __future__ import annotations

import fcntl
import os
import subprocess
from pathlib import Path

import pytest

from declarative_spec.heavy_phase import HELD_ENV, LOCK_ENV, MIN_AVAIL_ENV, heavy_phase

ROOT = Path(__file__).resolve().parents[1]


def test_a_phase_skips_the_lock_when_the_caller_holds_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(LOCK_ENV, str(tmp_path / "lock"))
    monkeypatch.setenv(HELD_ENV, "1")
    with heavy_phase("x"):
        assert not (tmp_path / "lock").exists()


def test_a_phase_is_exclusive_and_marks_itself_held(tmp_path, monkeypatch) -> None:
    lock = tmp_path / "lock"
    monkeypatch.setenv(LOCK_ENV, str(lock))
    monkeypatch.setenv(MIN_AVAIL_ENV, "0")
    monkeypatch.delenv(HELD_ENV, raising=False)
    with heavy_phase("x"):
        assert os.environ[HELD_ENV] == "1"
        fd = os.open(lock, os.O_RDWR)
        with pytest.raises(BlockingIOError):
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)  # nobody else, not even a shared holder, while it runs
        os.close(fd)
    assert HELD_ENV not in os.environ


@pytest.mark.skipif(not Path("/usr/bin/systemd-run").exists(), reason="needs systemd-run")
def test_the_verus_guard_waits_while_a_heavy_phase_holds_the_lock(tmp_path) -> None:
    lock = tmp_path / "lock"
    holder = os.open(lock, os.O_CREAT | os.O_RDWR)
    fcntl.flock(holder, fcntl.LOCK_EX)
    env = {**os.environ, "HEAVY_LOCK": str(lock), "VERUS_MIN_AVAIL_MB": "0", "LEMMA_VERUS_REAL": "/bin/true"}
    env.pop(HELD_ENV, None)
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run([str(ROOT / "scripts/ram/verus_guarded.sh"), "x"], env=env, timeout=3, capture_output=True)
    fcntl.flock(holder, fcntl.LOCK_UN)
    done = subprocess.run([str(ROOT / "scripts/ram/verus_guarded.sh"), "x"], env=env, timeout=30, capture_output=True)
    assert done.returncode == 0
    os.close(holder)
