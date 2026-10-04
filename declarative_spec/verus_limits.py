"""Verification limits for the host's `verus` call, and the labels for the ways it can stop.

Both limits are plain verification settings, never a weakening: `--rlimit` caps the Z3 work spent
on one query (a function body or loop), and the wall timeout caps the whole `verus` process.
A bad proof therefore fails in seconds instead of hanging. The measurements behind the defaults
are in `docs/VERUS_SMOOTHNESS.md`.

An unparsable env value raises: a mistyped limit must not silently become the default.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
from pathlib import Path

RLIMIT_ENV = "LEMMA_VERUS_RLIMIT"
TIMEOUT_ENV = "LEMMA_VERUS_TIMEOUT_SEC"
# Verus's own default is 10. Every reference and hard proof in the measurement uses far less.
DEFAULT_RLIMIT = 3.0
# Covers verification plus the optimized rustc build of the assembled program.
DEFAULT_TIMEOUT_SEC = 300


def verus_rlimit() -> float:
    value = float(os.environ.get(RLIMIT_ENV, DEFAULT_RLIMIT))
    if value <= 0:
        raise ValueError(f"{RLIMIT_ENV} must be positive, got {value}")
    return value


def verus_timeout_sec() -> int:
    value = int(os.environ.get(TIMEOUT_ENV, DEFAULT_TIMEOUT_SEC))
    if value <= 0:
        raise ValueError(f"{TIMEOUT_ENV} must be positive, got {value}")
    return value


def verus_limit_args() -> list[str]:
    return ["--rlimit", f"{verus_rlimit():g}"]


_RLIMIT_HIT = "Resource limit (rlimit) exceeded"


def timeout_message(partial_output: str, timeout_sec: int) -> str:
    """A wall timeout is not a proof error. Say which phase it hit."""
    if "verification results::" in partial_output:
        return (
            f"COMPILE TIMEOUT: Verus finished verifying but the build did not finish within "
            f"{timeout_sec}s ({TIMEOUT_ENV}). This is not a proof error."
        )
    return (
        f"VERIFY TIMEOUT: Verus did not finish verifying within {timeout_sec}s ({TIMEOUT_ENV}). "
        "This is not a proof error: no `verification results::` line was printed. "
        "Remove the slow part of the proof (see the Z3 smoothness guidance) rather than waiting longer."
    )


def failure_prefix(log: str) -> str:
    """One loud line in front of a failed Verus log that says what kind of failure it is."""
    hits = log.count(_RLIMIT_HIT)
    if hits:
        return (
            f"RLIMIT: Z3 ran out of resources on {hits} query(ies) ({_RLIMIT_HIT}, --rlimit "
            f"{verus_rlimit():g}). Verus finished, so this is a proof error, not a wall timeout. "
            "Typical cause: a quantifier with a two-term trigger, or a quantifier over `res@`.\n"
        )
    m = re.search(r"verification results:: (\d+) verified, (\d+) errors", log)
    if m:
        return f"PROOF ERROR: {m.group(0)}.\n"
    return ""


def run_verus(cmd: list[str], *, timeout: int, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run `verus`, and on a wall timeout kill its whole process group.

    `subprocess.run(timeout=...)` kills only the parent. Verus's Z3 child then keeps a core and
    gigabytes of memory until it finishes, which can be minutes. Raises `TimeoutExpired` carrying
    the partial output so the caller can say which phase was cut off.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd, start_new_session=True
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, err = proc.communicate()
        raise subprocess.TimeoutExpired(cmd, timeout, output=out, stderr=err) from None
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
