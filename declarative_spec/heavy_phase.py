"""Exclusive heavy phases of a run (data prepare/export, the timed binary run) on the shared machine.

Proving runs in parallel (the model thinks, Verus runs in short capped bursts), but two things must not overlap with anything else:
the data export (1 to 2.5 GB, spiky) and the timed run of the compiled program (a quiet machine gives clean numbers). Both take the machine-wide
lock `/tmp/lemma_timing.lock` exclusively (the same file `scripts/ram/heavy.sh` uses) and wait until memory is available. Verus takes the same lock
SHARED (scripts/ram/verus_guarded.sh), so a heavy phase waits for running proofs to finish and new proofs wait while it runs.
`LEMMA_HEAVY_LOCK_HELD=1` (set by heavy.sh and inside a phase) means the caller already holds the lock: the phase then does nothing.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import sys
import time
from collections.abc import Iterator

LOCK_ENV = "HEAVY_LOCK"
HELD_ENV = "LEMMA_HEAVY_LOCK_HELD"
MIN_AVAIL_ENV = "HEAVY_MIN_AVAIL_MB"
DEFAULT_LOCK = "/tmp/lemma_timing.lock"
DEFAULT_MIN_AVAIL_MB = 3500


def _available_mb() -> int:
    with open("/proc/meminfo") as fh:
        for line in fh:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    raise RuntimeError("MemAvailable not found in /proc/meminfo")


@contextlib.contextmanager
def heavy_phase(name: str) -> Iterator[None]:
    if os.environ.get(HELD_ENV) == "1":
        yield
        return
    fd = os.open(os.environ.get(LOCK_ENV, DEFAULT_LOCK), os.O_CREAT | os.O_RDWR, 0o666)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        need = int(os.environ.get(MIN_AVAIL_ENV, DEFAULT_MIN_AVAIL_MB))
        while (have := _available_mb()) < need:
            print(f"heavy phase {name!r}: waiting for memory ({have} MB available < {need} MB)", file=sys.stderr, flush=True)
            time.sleep(5)
        os.environ[HELD_ENV] = "1"
        try:
            yield
        finally:
            os.environ.pop(HELD_ENV, None)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
