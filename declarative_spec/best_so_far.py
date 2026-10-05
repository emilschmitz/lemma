"""Best-so-far agent file across checks and sessions, so a later session never starts from a worse file.

Every check (an MCP `run_runquery`, and the host's own final check of a session) records the exact
agent file it ran and the Verus tally. The best file is the one that proved, else the one with the
fewest errors, then the most verified functions. A strictly better attempt replaces the best; a tie
keeps the earlier one. A check with no `verification results::` line (rustc error, admission
refusal, timeout) ranks below every check that has one.

Restoring writes the best file back to the agent's path. It is the agent's own text, and every later
check goes through the same host admission as any other edit: restoring cannot admit anything the
host would refuse.

Layout, under `<workspace>/mcp_results/attempts/`: `NNN.rs` (the agent file), `index.json`
(one record per distinct file) and `best.json` (the index entry that is currently best).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ATTEMPTS = "attempts"
_TALLY = re.compile(r"verification results:: (\d+) verified, (\d+) errors")


def attempts_dir(ws: Path) -> Path:
    d = ws / "mcp_results" / ATTEMPTS
    d.mkdir(parents=True, exist_ok=True)
    return d


def sha(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def tally(text: str) -> tuple[int, int] | None:
    """(verified, errors) from the last `verification results::` line, else None."""
    found = _TALLY.findall(text or "")
    return None if not found else (int(found[-1][0]), int(found[-1][1]))


def _tally_of(metrics: dict) -> tuple[int, int] | None:
    return tally(str(metrics.get("verify_summary") or "") + "\n" + str(metrics.get("compiler_error") or ""))


def score(metrics: dict) -> tuple[int, int, int, int]:
    """Higher is better: (has tally, proved, -errors, verified)."""
    proved = bool(metrics.get("proof_verified"))
    t = _tally_of(metrics)
    if t is None:
        return (0, int(proved), 0, 0)
    verified, errors = t
    return (1, int(proved), -errors, verified)


def _read_index(ws: Path) -> list[dict]:
    path = ws / "mcp_results" / ATTEMPTS / "index.json"
    return json.loads(path.read_text()) if path.is_file() else []


def record_attempt(ws: Path, source: str, metrics: dict, *, origin: str) -> dict:
    """Store the agent file and its tally; update `best.json` when strictly better. Returns the index entry."""
    d = attempts_dir(ws)
    index = _read_index(ws)
    digest = sha(source)
    for entry in index:
        if entry["sha"] == digest:
            return entry  # the same file was already checked; the first tally stands
    n = len(index) + 1
    (d / f"{n:03d}.rs").write_text(source)
    t = _tally_of(metrics)
    entry = {
        "n": n,
        "sha": digest,
        "file": f"{n:03d}.rs",
        "origin": origin,
        "score": list(score(metrics)),
        "verified": None if t is None else t[0],
        "errors": None if t is None else t[1],
        "proof_verified": bool(metrics.get("proof_verified")),
        "status": metrics.get("status"),
        "error_excerpt": str(metrics.get("compiler_error") or ""),
    }
    index.append(entry)
    (d / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    best = load_best_entry(ws)
    if best is None or tuple(entry["score"]) > tuple(best["score"]):
        (d / "best.json").write_text(json.dumps(entry, indent=2) + "\n")
    return entry


def load_best_entry(ws: Path) -> dict | None:
    path = ws / "mcp_results" / ATTEMPTS / "best.json"
    return json.loads(path.read_text()) if path.is_file() else None


def load_best(ws: Path) -> tuple[dict, str] | None:
    entry = load_best_entry(ws)
    if entry is None:
        return None
    return entry, (ws / "mcp_results" / ATTEMPTS / entry["file"]).read_text()


def last_entry(ws: Path) -> dict | None:
    index = _read_index(ws)
    return index[-1] if index else None


def restore_best(ws: Path, agent_path: Path) -> tuple[str, dict | None]:
    """Put the best recorded file on `agent_path` unless it already holds exactly that text.

    Returns ("none" | "kept" | "restored", best entry). "kept": the file on disk is the best file.
    """
    loaded = load_best(ws)
    if loaded is None:
        return "none", None
    entry, text = loaded
    if agent_path.is_file() and sha(agent_path.read_text()) == entry["sha"]:
        return "kept", entry
    agent_path.write_text(text)
    return "restored", entry
