"""Verification limits for the host's `verus` call, and the labels for the ways it can stop.

Both limits are plain verification settings, never a weakening: `--rlimit` caps the Z3 work spent
on one query (a function body or loop), and the wall timeout caps the whole `verus` process.
A bad proof therefore fails in seconds instead of hanging. The measurements behind the defaults
are in `docs/VERUS_SMOOTHNESS.md`.

The values come from `lemma.toml` ([prover]); an unparsable or non-positive value raises (lemma_config): a mistyped limit must not silently become the default.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
from pathlib import Path

import lemma_config

RLIMIT_ENV = lemma_config.env_name("verus_rlimit")
TIMEOUT_ENV = lemma_config.env_name("verus_timeout_sec")
RUN_TIMEOUT_ENV = lemma_config.env_name("run_timeout_sec")
# Verus's own default is 10. 16 because Z3's work depends on the temporary file NAME: a long proof (the top-N join example) passed 1 of 4
# file names at rlimit 3, 4, 6 and 12 and 4 of 4 at 16, 20 and 30 (research_loop/scripts/fixture_rlimit_sweep.sh, FINDINGS F-MAN-9). At 3 the
# same proof passes or fails by luck; 16 removes the lottery at the cost of slower failing proofs.
# verus_timeout_sec covers verification plus the optimized rustc build of the assembled program.
# The compiled, verified binary on the full tables (load + warm-up + the timed repetitions). The reference engine needs milliseconds to a second
# for these queries, so a binary still running after a minute is orders of magnitude past the speed bar. The old limit (300 s) equalled the
# MCP harness wait, so the agent saw only "harness timeout" (no cause) and lost five minutes per such try (SSB Q3.2, 2026-10-10: three of four
# run_runquery calls, 15 of the 25 minutes, were the spec's own nested loops over 6M x 30k rows).
# run_timeout_sec, in lemma.toml.
# Slack on top of the two inner limits, so an inner limit's own message always reaches the agent before the MCP harness gives up.
HARNESS_SLACK_SEC = 60


def verus_rlimit() -> float:
    return float(lemma_config.get("verus_rlimit"))


def verus_timeout_sec() -> int:
    return int(lemma_config.get("verus_timeout_sec"))


def run_timeout_sec() -> int:
    return int(lemma_config.get("run_timeout_sec"))


def declarative_harness_budget_sec() -> int:
    """How long the MCP harness must wait for one declarative run: both inner limits plus slack, so the inner message wins."""
    return verus_timeout_sec() + run_timeout_sec() + HARNESS_SLACK_SEC


def run_timeout_message(timeout_sec: int) -> str:
    """A binary that Verus proved but that did not finish: a speed failure, not a proof error."""
    return (
        f"RUN TIMEOUT: the verified binary did not finish within {timeout_sec}s on the full tables ({RUN_TIMEOUT_ENV}). "
        "Verus proved it (`verification results:: N verified, 0 errors`), so this is not a proof error: the body is far too slow to run. "
        "A loop over one table inside a loop over another costs |T1| * |T2| steps, and the host spec's own nested folds are exactly that, so they "
        "must not be run as the body. Make ONE pass over the largest table and reach the others through small lookup arrays "
        "(index = join key) instead of a nested loop."
    )


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
