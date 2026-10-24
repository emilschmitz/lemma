"""Agent sessions of one query: when a further session starts, and what the run manifest records about each.

Rules (settings in lemma.toml: ``max_iterations``, ``agent_timeout_sec``, ``speed_target``, ``max_idle_sessions``, ``max_budget_usd``):

* A session whose Claude result is an API/auth/connectivity error (``Outcome.infra_error``) ends the query at once: no further session,
  no retry, no other credential. A submit measured in that session (an earlier marked submit) still counts.
* ``max_budget_usd`` > 0: no further session once the spend of the sessions so far reaches it ("budget used"); each session is told the remainder.

* No body has verified and beaten the bar yet: a further session starts while fewer than ``max_iterations`` sessions have run (the old rule).
* A body has: ``speed_target == 1.0`` ends the query at once (the old rule). Otherwise a further session starts, from the best body so far,
  while the best speedup (official or submitted in a session) is below ``speed_target``, the agent time spent is below the per-query budget
  ``max_iterations x agent_timeout_sec``, and fewer than ``max_idle_sessions`` sessions in a row ended without a better speedup.
  Its wall limit is the time left of the budget, so the budget is never exceeded.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_loop.pipeline_log import log_warn


@dataclass
class Outcome:
    """What one session produced (``run_one`` returns it)."""

    success: bool  # the host's official measure of the file it left verified and beat the bar
    speedup: float | None  # best of the official speedup and the speedup of the session's submitted body; None = none
    agent_s: float  # wall seconds the agent ran
    result: dict | None = None  # the loop result for a success
    source: str | None = None  # the file of a success (the base of a continuation session)
    cost_usd: float | None = 0.0  # model spend of the session (total_cost_usd of its stream-json result event); None = the session was killed before that event: unreported
    tokens: dict | None = None  # token totals of the session from the stream's per-message usage (present even when the session was killed)
    infra_error: str | None = None  # "INFRA: agent API error: ..." when the session's result event was an API/auth/connectivity error
    cost_note: str | None = None  # why cost_usd is None when it is not a kill: e.g. "not reported by harness (codex)"; recorded beside it, never a 0


@dataclass
class Sessions:
    max_iterations: int
    budget_s: float
    target: float
    max_idle: int
    budget_usd: float = 0.0  # per-query model spend cap; 0 = none
    records: list[dict[str, Any]] = field(default_factory=list)
    spent_s: float = 0.0
    spent_usd: float = 0.0  # reported spend only; a session with cost_usd None adds nothing (and is logged), it is not counted as 0 in the manifest total
    idle: int = 0
    best: Outcome | None = None
    infra_error: str | None = None  # the first session's infra error: no further session starts

    def best_speedup(self) -> float | None:
        return None if self.best is None else self.best.speedup

    def stop_reason(self) -> str | None:
        """Why no further session starts after the sessions so far, or None when one does."""
        if self.infra_error is not None:
            return self.infra_error
        if self.budget_usd > 0 and self.spent_usd >= self.budget_usd:
            return f"budget used (${self.spent_usd:.2f} of ${self.budget_usd:.2f})"
        if self.best is None:
            return None if len(self.records) < self.max_iterations else f"{self.max_iterations} sessions without a body that beats the bar"
        if self.target <= 1.0:
            return "speed_target 1.0: the first body that beats the bar ends the query"
        speedup = self.best.speedup
        if speedup is not None and speedup >= self.target:
            return f"target reached ({speedup:.2f}x >= {self.target:g}x)"
        if self.spent_s >= self.budget_s:
            return f"per-query budget used ({self.spent_s:.0f} of {self.budget_s:.0f} s)"
        if self.idle >= self.max_idle:
            return f"{self.idle} sessions in a row without a better speedup"
        return None

    def remaining_usd(self) -> float | None:
        """Spend cap left for the next session (``--max-budget-usd``), None without a cap."""
        return None if self.budget_usd <= 0 else self.budget_usd - self.spent_usd

    def timeout_s(self) -> int | None:
        """Wall limit of the next session: the old full session limit until a body has beaten the bar, then what is left of the budget."""
        return None if self.best is None else max(1, int(self.budget_s - self.spent_s))

    def note(self) -> str:
        """The short host message at the start of a continuation session."""
        assert self.best is not None
        left = max(0.0, self.budget_s - self.spent_s) / 60
        return (
            f"Your best submitted body so far runs at {self.best.speedup:.2f}x the reference engine. The target is {self.target:g}x. "
            f"About {left:.0f} minutes are left. The file in place is that body: try a faster verified one, and submit each improvement."
        )

    def add(self, n: int, start: float, end: float, outcome: Outcome) -> None:
        if outcome.infra_error is not None and self.infra_error is None:
            self.infra_error = outcome.infra_error
        improved = outcome.success and outcome.speedup is not None and (self.best_speedup() is None or outcome.speedup > (self.best_speedup() or 0.0))
        if outcome.success and (self.best is None or improved):
            self.best = outcome
        if self.best is not None:
            self.idle = 0 if improved else self.idle + 1
        self.spent_s += outcome.agent_s
        reported = outcome.cost_usd is not None
        if reported:
            self.spent_usd += outcome.cost_usd
        else:
            why = outcome.cost_note or "the session ended without a result event"
            log_warn("sessions", "cost_unreported", f"session {n}: {why}: its cost is unknown and not part of the budget", session=n)
        self.records.append({
            "session": n,
            "start": datetime.fromtimestamp(start, UTC).isoformat(),
            "end": datetime.fromtimestamp(end, UTC).isoformat(),
            "agent_s": round(outcome.agent_s, 1),
            "cost_usd": round(outcome.cost_usd, 6) if reported else None,
            "cost_reported": reported,
            **({"cost_note": outcome.cost_note} if outcome.cost_note is not None else {}),
            "tokens": outcome.tokens or {},
            "output_tokens_partial": bool(outcome.tokens),  # the stream's output_tokens undercounts; the input-side counts are exact
            "success": outcome.success,
            "session_speedup": outcome.speedup,
            "best_speedup": self.best_speedup(),
            **({"infra_error": outcome.infra_error} if outcome.infra_error is not None else {}),
        })


def run_sessions(
    run_one: Callable[[int, str, int | None], Outcome],
    *,
    max_iterations: int,
    agent_timeout_sec: float,
    target: float,
    max_idle: int,
    max_budget_usd: float = 0.0,
    on_record: Callable[[list[dict[str, Any]]], None] | None = None,
    clock: Callable[[], float] = time.time,
) -> Sessions:
    """Run sessions until ``Sessions.stop_reason``; ``run_one(n, host_note, timeout_s)`` runs one (note and timeout are empty/None for a first session
    and for a retry after a body that did not verify)."""
    state = Sessions(max_iterations, max_iterations * agent_timeout_sec, target, max_idle, max_budget_usd)
    n = 0
    while True:
        n += 1
        continuing = state.best is not None
        start = clock()
        outcome = run_one(n, state.note() if continuing else "", state.timeout_s())
        state.add(n, start, clock(), outcome)
        if on_record is not None:
            on_record(state.records)
        reason = state.stop_reason()
        if reason is not None:
            state.records[-1]["stop_reason"] = reason
            if on_record is not None:
                on_record(state.records)
            return state


def record_in_manifest(manifest: Path, records: list[dict[str, Any]]) -> None:
    """Write the per-session records into the run manifest (a run without a manifest, i.e. without the research log, has nowhere to put them)."""
    if manifest.is_file():
        data = json.loads(manifest.read_text())
        data["sessions"] = records
        infra = next((r["infra_error"] for r in records if r.get("infra_error")), None)
        if infra is not None:
            data["infra_error"] = infra  # the query stopped on an agent API/auth/connectivity error, not on the agent
        data["total_cost_usd"] = round(sum(r["cost_usd"] for r in records if r.get("cost_usd") is not None), 6)  # reported sessions only
        data["total_cost_complete"] = all(r.get("cost_reported", True) for r in records)  # False: some session's cost is unknown, the total is a lower bound
        data["total_tokens"] = {k: sum(int((r.get("tokens") or {}).get(k, 0)) for r in records) for k in {k for r in records for k in (r.get("tokens") or {})}}
        manifest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
