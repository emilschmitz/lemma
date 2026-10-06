"""Build arena result rows from run directories. Nothing in a row is typed by hand.

    arena_record.py RUN_DIR --query r1_q03 --attempt 1 [--log LAUNCHER_LOG] [--infra REASON]
    arena_record.py --index arena/attempts_index.json --causes arena/causes.json --out arena/results_container.jsonl

A row's fields come from the run directory (``manifest.json`` effective block, ``workspace/mcp_results``, ``workspace/decl_data/expect.json``,
``workspace/logs``) and, when given, the launcher log (its LAST ``RESULT {...}`` line, and ``<log stem>.refresh.json``). A field that cannot be
derived is None and named in ``notes``. The INDEX only says which run directory is which (query id, attempt number, log, an infra reason);
every pairing is CHECKED against the run (RESULT.run_dir, database and model must match the manifest; no duplicate (query, attempt); no log
used twice). ``infra`` is not a free flag: a run with any run_runquery call, a submit or a proof is never infra. ``causes.json`` holds the written
diagnosis per run directory name under ``cause`` and never overrides a derived field. Never edit a row afterwards: regenerate.

Semantics (each also stated in the row):
* ``proved`` is ANY session's run_runquery that verified (``proved_scope``); ``submitted`` is the host's marker. A proved body that was not
  submitted can still be a failed attempt.
* ``verified_line``: the fastest proved run's summary, else the failing run with the fewest errors, then most verified (a heuristic, across all sessions).
* ``kernel_us`` and ``speedup`` are set only for a SUCCESS result (``kernel_basis`` "scored"), or, for a failed result whose host message gave
  them, marked ``kernel_basis`` "last measured body (below the speed bar)".
* ``rows_match`` is True when the result succeeded or the host refused the body only for speed; False only when the FINAL host result says the
  rows differ; otherwise None with the reason in notes.
* ``error`` is the launcher result's error only when the final status is not SUCCESS; a SUCCESS row never carries one (the launcher keeps the first
  session's error next to the final status).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SPEED_BAR = re.compile(r"proved but below the speed bar: query (\d+) us, DuckDB (\d+) us \((\d+\.\d+)x")
_VERIFIED = re.compile(r"(\d+) verified, (\d+) errors?")


class IndexError_(ValueError):
    """An index entry does not agree with its run directory or with another entry."""


def _result_line(log: Path | None) -> dict | None:
    """The LAST ``RESULT {...}`` line of the launcher log (a reused log keeps earlier ones above it)."""
    if log is None or not log.is_file():
        return None
    found = None
    for line in log.read_text(errors="replace").splitlines():
        if line.startswith("RESULT "):
            found = json.loads(line[len("RESULT ") :])
    return found


def _run_records(run_dir: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((run_dir / "workspace" / "mcp_results" / "runs").glob("*.json"))]


def _verified(rec: dict) -> tuple[int, int] | None:
    metrics = rec.get("metrics") or {}
    for text in (metrics.get("verify_summary"), metrics.get("compiler_error")):
        m = _VERIFIED.search(text or "")
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def _stream_facts(run_dir: Path) -> dict:
    """Sessions (``system`` init events) and agent tool calls from agent_stream.jsonl; a 401 from claude_raw.jsonl."""
    logs = run_dir / "workspace" / "logs"
    sessions = tool_calls = 0
    stream = logs / "agent_stream.jsonl"
    if stream.is_file():
        for line in stream.read_text(errors="replace").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "system" and ev.get("subtype") == "init":
                sessions += 1
            elif ev.get("type") == "tool_call" and ev.get("subtype") == "started":
                tool_calls += 1
    raw = logs / "claude_raw.jsonl"
    auth_401 = raw.is_file() and '"api_error_status":401' in raw.read_text(errors="replace")
    return {"sessions": sessions, "tool_calls": tool_calls, "auth_401": auth_401, "stream_present": stream.is_file()}


def row_from_run(run_dir: Path, *, query: str, attempt: int, log: Path | None = None, infra: str | None = None, cause: str | None = None) -> dict:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    eff = manifest["effective"]
    notes: list[str] = []
    runs = _run_records(run_dir)
    ws = run_dir / "workspace"
    submitted = (ws / "mcp_results" / "submitted.json").is_file()
    proved_runs = [r for r in runs if (r.get("metrics") or {}).get("proof_verified")]
    facts = _stream_facts(run_dir)
    if infra and (runs or submitted or proved_runs):
        raise IndexError_(f"{run_dir.name}: marked infra ({infra!r}) but the agent made {len(runs)} run_runquery calls (submitted={submitted}): that is an attempt, not infra")
    best = None
    if proved_runs:
        best = min(proved_runs, key=lambda r: (r["metrics"].get("latency_us") if (r["metrics"].get("latency_us") or -1) > 0 else 10**18))
    else:
        scored = [(v, r) for r in runs if (v := _verified(r)) is not None]
        if scored:
            best = max(scored, key=lambda t: (-t[0][1], t[0][0]))[1]
    verified = _verified(best) if best else None
    result = _result_line(log)
    if result is not None:
        if result.get("run_dir") and Path(result["run_dir"]) != run_dir:
            raise IndexError_(f"{run_dir.name}: the log {log} reports run_dir {result['run_dir']}")
        if result.get("database") and result["database"] != manifest["duckdb_path"]:
            raise IndexError_(f"{run_dir.name}: log database {result['database']} != manifest {manifest['duckdb_path']}")
        if result.get("model") and result["model"] != manifest["agent_model"]:
            raise IndexError_(f"{run_dir.name}: log model {result['model']} != manifest {manifest['agent_model']}")
    else:
        notes.append("no launcher RESULT line: status, wall_s, final latency and DuckDB time not derivable from a log")
    status = (result or {}).get("status")
    expect_path = ws / "decl_data" / "expect.json"
    expect = json.loads(expect_path.read_text()) if expect_path.is_file() else None
    duck_us = (result or {}).get("duck_us") or ((expect or {}).get("duck_us"))
    if duck_us is None:
        notes.append("duck_allcore_us not derivable (no RESULT line, no expect.json)")
    final_latency = (result or {}).get("latency_us")
    kernel_us = final_latency if status == "SUCCESS" and isinstance(final_latency, int) and final_latency > 0 else None
    kernel_basis = "scored" if kernel_us else None
    speedup = round(duck_us / kernel_us, 3) if kernel_us and duck_us else None
    below_bar = _SPEED_BAR.search((result or {}).get("error") or "")
    if kernel_us is None and below_bar:
        kernel_us, duck_us, speedup = int(below_bar.group(1)), int(below_bar.group(2)), float(below_bar.group(3))
        kernel_basis = "last measured body (below the speed bar)"
        notes.append("kernel_us, duck_allcore_us and speedup are from the host's below-the-speed-bar message (the run is not scored)")
    rows_match = None
    final_error = (result or {}).get("error") or ""
    if status == "SUCCESS" or below_bar:  # the speed message comes after the row check
        rows_match = True
    elif "result rows differ" in final_error:
        rows_match = False
    elif result is None:
        notes.append("rows_match not derivable: no launcher RESULT line (only in-session checks exist)")
    elif not proved_runs:
        notes.append("rows_match not derivable: no run ever verified, so no body reached the row check")
    else:
        notes.append("rows_match not derivable: the final host result is not a row or speed message")
    duck_settings = (expect or {}).get("duck_settings")
    if duck_settings is None:
        notes.append("duck_settings absent from expect.json (run predates the central DuckDB settings or has no prepared data)")
    refresh = None
    if log is not None and (log.parent / f"{log.stem}.refresh.json").is_file():
        refresh = json.loads((log.parent / f"{log.stem}.refresh.json").read_text()).get("refreshed")
    else:
        notes.append("refreshed not derivable (no <log>.refresh.json for this run)")
    if not runs:
        notes.append("no run_runquery calls: the agent never ran a check")
    if facts["sessions"] > 1:
        notes.append(f"{facts['sessions']} agent sessions: wall_s, checks and proved span all of them; the launcher error is from an earlier session")
    if status == "SUCCESS" and final_error:
        notes.append("the launcher RESULT carries an error from an earlier session next to status SUCCESS; dropped from the row")
    error = None if status == "SUCCESS" else (final_error[:300] or None)
    evidence: list[str] = []
    if facts["auth_401"]:
        evidence.append("401 in claude_raw.jsonl")
    if infra and not facts["tool_calls"]:
        evidence.append("no agent tool calls")
    if infra and not evidence:
        notes.append("infra reason is from the index only; the run dir shows no 401 and the agent made tool calls")
    return {
        "track": "container",
        "model": manifest["agent_model"],
        "effort": eff.get("claude_effort") or "unset",
        "query": query,
        "attempt": attempt,
        "run_dir": str(run_dir),
        "sha": manifest["git_sha"][:7],
        "git_dirty": manifest["git_dirty"],
        "proved": bool(proved_runs),
        "proved_scope": "any session: some run_runquery verified (not necessarily the final body)",
        "submitted": submitted,
        "verified_line": f"{verified[0]} verified, {verified[1]} errors" if verified else None,
        "checks": len(runs),
        "sessions": facts["sessions"] or None,
        "wall_s": (result or {}).get("wall_s"),
        "status": status,
        "kernel_us": kernel_us,
        "kernel_basis": kernel_basis,
        "duck_allcore_us": duck_us,
        "speedup": speedup,
        "rows_match": rows_match,
        "env": {k: eff.get(k) for k in ("LEMMA_STRING_ENCODING", "LEMMA_NARROW_CELLS", "LEMMA_PARALLEL_VSTD", "LEMMA_ZERO_COPY", "LEMMA_TARGET_CPU")},
        "database": Path(manifest["duckdb_path"]).name,
        "duck_settings": duck_settings,
        "refreshed": refresh,
        "infra": bool(infra),
        "counts": not infra,
        "infra_reason": infra,
        "infra_evidence": evidence,
        "error": error,
        "cause": cause,
        "notes": notes,
    }


def regenerate(index: Path, causes: Path | None, out: Path) -> list[dict]:
    """Rewrite ``out`` from the index (a list of {query, attempt, run_dir, log?, infra?}); the causes file is keyed by run directory name."""
    cause_map = json.loads(causes.read_text()) if causes and causes.is_file() else {}
    items = json.loads(index.read_text())
    seen: set[tuple[str, int]] = set()
    run_dirs: dict[str, str] = {}
    logs: set[str] = set()
    for item in items:
        key = (item["query"], item["attempt"])
        if key in seen:
            raise IndexError_(f"duplicate (query, attempt) in the index: {key}")
        seen.add(key)
        if run_dirs.setdefault(item["run_dir"], item["query"]) != item["query"]:
            raise IndexError_(f"{item['run_dir']} is listed for two queries")
        if item.get("log"):
            if item["log"] in logs:
                raise IndexError_(f"the log {item['log']} is used by two entries")
            logs.add(item["log"])
    rows = []
    for item in items:
        run_dir = Path(item["run_dir"])
        log = Path(item["log"]) if item.get("log") else None
        rows.append(row_from_run(run_dir, query=item["query"], attempt=item["attempt"], log=log, infra=item.get("infra"), cause=cause_map.get(run_dir.name)))
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return rows


def compare_markdown(rows: list[dict], manifests: list[dict], manual_rows: list[dict] | None = None) -> str:
    """The side-by-side table, derived from the rows (and the round manifests for the shape class); the manual column is empty when it has no rows."""
    info = {q["id"]: q for m in manifests for q in m["queries"]}
    manual = {r["query"]: r for r in (manual_rows or [])}
    lines = [
        "# compare.md (generated by research_loop/scripts/arena_record.py from results_container.jsonl; do not edit)",
        "",
        "Container = Sonnet 5.5 in the Docker container. Speedup = DuckDB all-core median / our proved binary, host official measure. Only SCORED rows (status SUCCESS) carry a speedup;",
        "'last measured' is a proved body the host refused for speed. Infra rows (counts=false) are listed, never counted.",
        "",
        "| query | class | attempts (counting) | container: best outcome | speedup | manual | causes of non-scored attempts |",
        "|---|---|---|---|---|---|---|",
    ]
    for qid in sorted({r["query"] for r in rows}):
        mine = [r for r in rows if r["query"] == qid]
        counting = [r for r in mine if r["counts"]]
        scored = [r for r in counting if r["kernel_basis"] == "scored"]
        measured = [r for r in counting if r["kernel_basis"] and r["kernel_basis"] != "scored"]
        if scored:
            best = max(scored, key=lambda r: r["speedup"] or 0)
            outcome, speed = ("WIN" if (best["speedup"] or 0) > 1 else "scored, below the bar"), f"{best['speedup']}x"
        elif measured:
            best = max(measured, key=lambda r: r["speedup"] or 0)
            outcome, speed = "proved, below the speed bar", f"{best['speedup']}x (last measured)"
        elif any(r["proved"] for r in counting):
            outcome, speed = "proved, never scored", "-"
        else:
            outcome, speed = "no proof", "-"
        causes = "; ".join(f"a{r['attempt']}: {r['cause']}" for r in counting if r["cause"] and r["kernel_basis"] != "scored") or "-"
        shape = info.get(qid, {})
        man = manual.get(qid)
        lines.append(f"| {qid} | {shape.get('recipe', '?')}/{shape.get('tier', '?')} | {len(counting)} ({len(mine)} incl. infra) | {outcome} | {speed} | "
                     f"{('proved ' + str(man.get('speedup')) + 'x') if man and man.get('proved') else ('no row' if not man else 'not proved')} | {causes} |")
    qs = sorted({r["query"] for r in rows})
    wins = [q for q in qs if any(r["counts"] and r["kernel_basis"] == "scored" and (r["speedup"] or 0) > 1 for r in rows if r["query"] == q)]
    lines += ["", f"Container: {len(wins)} of {len(qs)} queries beat all-core DuckDB so far ({', '.join(wins) or 'none'}).",
              "Manual rows: " + (f"{len(manual)}" if manual else "none (results_manual.jsonl absent or empty), so no like-for-like comparison and no stop-rule check.")]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", nargs="?", type=Path)
    ap.add_argument("--query")
    ap.add_argument("--attempt", type=int)
    ap.add_argument("--log", type=Path)
    ap.add_argument("--infra")
    ap.add_argument("--index", type=Path)
    ap.add_argument("--causes", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--compare", type=Path, help="write compare.md here from --out's rows and the round manifests next to it")
    a = ap.parse_args(argv)
    if a.index:
        if not a.out:
            raise SystemExit("--index needs --out")
        rows = regenerate(a.index, a.causes, a.out)
        print(f"wrote {len(rows)} rows to {a.out}")
        if a.compare:
            arena = a.out.parent
            manifests = [json.loads(p.read_text()) for p in sorted((arena / "rounds").glob("r*/manifest.json"))]
            manual_path = arena / "results_manual.jsonl"
            manual_rows = [json.loads(line) for line in manual_path.read_text().splitlines() if line.strip()] if manual_path.is_file() else []
            a.compare.write_text(compare_markdown(rows, manifests, manual_rows))
        return 0
    if a.run_dir is None or a.query is None or a.attempt is None:
        raise SystemExit("need RUN_DIR --query --attempt (or --index --out)")
    print(json.dumps(row_from_run(a.run_dir, query=a.query, attempt=a.attempt, log=a.log, infra=a.infra), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
