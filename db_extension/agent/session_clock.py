"""Agent session wall-clock: stamp at start, query remaining time.

Host is the source of truth. Workspace file ``session_clock.json`` + script
``check_session_time`` let the agent inspect the budget; MCP responses can
attach the same snapshot.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

CLOCK_NAME = "session_clock.json"
CHECK_SCRIPT_NAME = "check_session_time"
END_SESSION_NAME = "mcp_results/end_session"


def _truthy(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


def submit_ends_session() -> bool:
    return _truthy(os.environ.get("AGENT_SUBMIT_ENDS_SESSION", "0"))


def agent_timeout_sec() -> int:
    raw = (os.environ.get("AGENT_TIMEOUT_SEC") or "600").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 600


def clock_path(workspace: Path) -> Path:
    return workspace / CLOCK_NAME


def write_check_script(workspace: Path) -> Path:
    """Install a small stdlib script the agent can run: ``python3 check_session_time``."""
    workspace.mkdir(parents=True, exist_ok=True)
    script = workspace / CHECK_SCRIPT_NAME
    script.write_text(
        """#!/usr/bin/env python3
\"\"\"Print agent session budget / time remaining (reads session_clock.json).\"\"\"
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

clock = Path(__file__).resolve().parent / "session_clock.json"
if not clock.is_file():
    print("session_clock.json missing (session not started)", file=sys.stderr)
    sys.exit(2)
data = json.loads(clock.read_text())
now = time.time()
deadline = float(data["deadline_unix"])
remaining = max(0.0, deadline - now)
elapsed = max(0.0, now - float(data["start_unix"]))
out = {
    "ok": True,
    "budget_sec": data.get("budget_sec"),
    "elapsed_sec": round(elapsed, 3),
    "remaining_sec": round(remaining, 3),
    "deadline_unix": deadline,
    "submit_ends_session": bool(data.get("submit_ends_session")),
    "expired": remaining <= 0,
}
print(json.dumps(out, indent=2))
sys.exit(0 if remaining > 0 else 1)
"""
    )
    script.chmod(script.stat().st_mode | 0o111)
    return script


def start_session_clock(
    workspace: Path,
    *,
    budget_sec: int | None = None,
    submit_ends: bool | None = None,
) -> dict[str, Any]:
    """Stamp session_clock.json at agent start (overwrites prior stamp)."""
    workspace.mkdir(parents=True, exist_ok=True)
    write_check_script(workspace)
    # Clear prior end-session sentinel so a new iteration is not killed immediately.
    end_path = workspace / END_SESSION_NAME
    if end_path.is_file():
        end_path.unlink()
    budget = int(budget_sec) if budget_sec is not None else agent_timeout_sec()
    ends = submit_ends_session() if submit_ends is None else bool(submit_ends)
    start = time.time()
    payload = {
        "start_unix": start,
        "deadline_unix": start + budget,
        "budget_sec": budget,
        "submit_ends_session": ends,
        "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start)),
    }
    clock_path(workspace).write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def clock_submit_ends(workspace: Path) -> bool:
    """Whether this session should end on submit (stamp wins over env)."""
    path = clock_path(workspace)
    if path.is_file():
        try:
            return bool(json.loads(path.read_text()).get("submit_ends_session"))
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return submit_ends_session()


def read_session_status(workspace: Path, *, now: float | None = None) -> dict[str, Any]:
    """Current budget snapshot; ok=False if clock missing."""
    path = clock_path(workspace)
    if not path.is_file():
        return {
            "ok": False,
            "error": "session_clock.json missing (session not started)",
            "budget_sec": agent_timeout_sec(),
            "submit_ends_session": submit_ends_session(),
        }
    data = json.loads(path.read_text())
    ts = time.time() if now is None else now
    deadline = float(data["deadline_unix"])
    start = float(data["start_unix"])
    remaining = max(0.0, deadline - ts)
    return {
        "ok": True,
        "budget_sec": int(data.get("budget_sec", agent_timeout_sec())),
        "elapsed_sec": round(max(0.0, ts - start), 3),
        "remaining_sec": round(remaining, 3),
        "deadline_unix": deadline,
        "start_unix": start,
        "submit_ends_session": bool(data.get("submit_ends_session")),
        "expired": remaining <= 0,
        "started_at_utc": data.get("started_at_utc"),
    }


def attach_session(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Copy payload and add ``session`` status (cheap piggyback on MCP results)."""
    out = dict(payload)
    out["session"] = read_session_status(workspace)
    return out


def request_end_session(workspace: Path, *, reason: str = "submit") -> Path:
    """Host-side signal that the agent session should stop (submit-ends mode)."""
    path = workspace / END_SESSION_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "reason": reason,
                "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            indent=2,
        )
        + "\n"
    )
    return path


def end_session_requested(workspace: Path) -> bool:
    return (workspace / END_SESSION_NAME).is_file()


def session_budget_prompt_section(*, budget_sec: int, submit_ends: bool) -> str:
    """Prompt text: budget always; submit semantics depend on flag (host-enforced)."""
    check = (
        f"Check time left anytime: `python3 {CHECK_SCRIPT_NAME}` "
        f"(or MCP `session_status`). MCP validate/run/submit responses also include "
        f"`session.remaining_sec`."
    )
    submit_when = (
        "Call `submit_runquery(run_id=...)` when a run is **verified** and **faster than** "
        "your current official mark (or is your first verified success). Re-submit whenever "
        "you beat the marked run."
    )
    stop = (
        "If you expect **no further improvement**, **stop** (exit). Otherwise **keep running** "
        "within the budget."
    )
    if submit_ends:
        mode = (
            f"**Submit ends the session** (`AGENT_SUBMIT_ENDS_SESSION=1`): a successful "
            f"`submit_runquery` locks that run as official and the host **ends the session**. "
            f"Wall-clock budget: **{budget_sec} seconds**. {submit_when} Because submit ends "
            f"the session, only submit when that best is what you want locked. Until then keep "
            f"iterating."
        )
    else:
        mode = (
            f"**Submit does not end the session** (`AGENT_SUBMIT_ENDS_SESSION=0`): "
            f"Wall-clock budget: **{budget_sec} seconds** (host ends the session when it "
            f"expires). {submit_when} {stop}"
        )
    return f"## Session budget\n{mode}\n{check}\n"
