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


def _read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as f:  # no newline translation: the hash is of the exact text
        return f.read()


def _read_json(path: Path, default):
    """The agent can write these files; unreadable JSON counts as absent rather than aborting the run."""
    try:
        return json.loads(_read(path)) if path.is_file() else default
    except (ValueError, OSError):
        return default


def _read_index(ws: Path) -> list[dict]:
    index = _read_json(ws / "mcp_results" / ATTEMPTS / "index.json", [])
    return [e for e in index if isinstance(e, dict) and {"n", "sha", "file", "score"} <= e.keys()] if isinstance(index, list) else []


def record_attempt(ws: Path, source: str, metrics: dict, *, origin: str) -> dict:
    """Store the agent file and its tally; update `best.json` when strictly better. Returns the index entry."""
    d = attempts_dir(ws)
    index = _read_index(ws)
    digest = sha(source)
    t = _tally_of(metrics)
    for entry in index:
        if entry["sha"] == digest:
            if entry["score"][0] == 0 and t is not None:
                # The first check of this file produced no tally (timeout, build error); a later one did: keep that one.
                entry.update(
                    score=list(score(metrics)),
                    verified=t[0],
                    errors=t[1],
                    proof_verified=bool(metrics.get("proof_verified")),
                    status=metrics.get("status"),
                    error_excerpt=str(metrics.get("compiler_error") or ""),
                )
                (d / "index.json").write_text(json.dumps(index, indent=2) + "\n")
                _maybe_best(ws, d, entry)
            return entry
    used = [int(m.group(1)) for f in d.glob("*.rs") if (m := re.fullmatch(r"(\d+)\.rs", f.name))]
    n = max([len(index), *used]) + 1  # never reuse a number, even if index.json was lost
    (d / f"{n:03d}.rs").write_text(source)
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
    _maybe_best(ws, d, entry)
    return entry


def _maybe_best(ws: Path, d: Path, entry: dict) -> None:
    """Only a check with a Verus tally can be best: a file with no tally is unranked, never a restore target."""
    if entry["score"][0] == 0:
        return
    best = load_best_entry(ws)
    if best is None or tuple(entry["score"]) > tuple(best["score"]):
        (d / "best.json").write_text(json.dumps(entry, indent=2) + "\n")


def load_best_entry(ws: Path) -> dict | None:
    entry = _read_json(ws / "mcp_results" / ATTEMPTS / "best.json", None)
    if not isinstance(entry, dict) or not {"n", "sha", "file", "score"} <= entry.keys():
        return None
    return entry


def load_best(ws: Path) -> tuple[dict, str] | None:
    entry = load_best_entry(ws)
    if entry is None:
        return None
    # best.json lives in the agent-writable workspace: take only a plain `NNN.rs` file whose text matches the recorded hash.
    if not re.fullmatch(r"\d{3,}\.rs", entry["file"]):
        raise ValueError(f"best.json names an unexpected file: {entry['file']!r}")
    path = ws / "mcp_results" / ATTEMPTS / entry["file"]
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"best attempt file is not a plain file: {path}")
    text = _read(path)
    if sha(text) != entry["sha"]:
        raise ValueError(f"best attempt file {entry['file']} does not match its recorded hash (tampered?)")
    return entry, text


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
    if agent_path.is_file() and sha(_read(agent_path)) == entry["sha"]:
        return "kept", entry
    agent_path.write_text(text)
    return "restored", entry
