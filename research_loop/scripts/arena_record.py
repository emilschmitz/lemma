"""Build arena result rows from run directories. Nothing in a row is typed by hand.

    arena_record.py RUN_DIR --query r1_q03 --attempt 1 [--log LAUNCHER_LOG] [--infra REASON]
    arena_record.py --index arena/attempts_index.json --causes arena/causes.json --out arena/results_container.jsonl

A row's fields come from the run directory (``manifest.json`` effective block, ``workspace/mcp_results``, ``workspace/decl_data/expect.json``) and,
when given, the launcher log (its ``RESULT {...}`` line, and ``<log stem>.refresh.json``). A field that cannot be derived is None and named in
``notes``. The INDEX only says which run directory is which (query id, attempt number, log, an explicit infra flag); ``causes.json`` holds the
written diagnosis per run id under ``cause`` and never overrides a derived field. Never edit a row afterwards: regenerate.

``verified_line`` is the fastest proved run's summary, else the failing run with the fewest errors (then most verified): a heuristic, named here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SPEED_BAR = re.compile(r"proved but below the speed bar: query (\d+) us, DuckDB (\d+) us \((\d+\.\d+)x")
_VERIFIED = re.compile(r"(\d+) verified, (\d+) errors?")


def _result_line(log: Path | None) -> dict | None:
    if log is None or not log.is_file():
        return None
    for line in log.read_text(errors="replace").splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT ") :])
    return None


def _run_records(run_dir: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((run_dir / "workspace" / "mcp_results" / "runs").glob("*.json"))]


def _verified(rec: dict) -> tuple[int, int] | None:
    metrics = rec.get("metrics") or {}
    for text in (metrics.get("verify_summary"), metrics.get("compiler_error")):
        m = _VERIFIED.search(text or "")
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def row_from_run(run_dir: Path, *, query: str, attempt: int, log: Path | None = None, infra: str | None = None, cause: str | None = None) -> dict:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    eff = manifest["effective"]
    notes: list[str] = []
    runs = _run_records(run_dir)
    ws = run_dir / "workspace"
    submitted = (ws / "mcp_results" / "submitted.json").is_file()
    proved_runs = [r for r in runs if (r.get("metrics") or {}).get("proof_verified")]
    best = None
    if proved_runs:
        best = min(proved_runs, key=lambda r: (r["metrics"].get("latency_us") if (r["metrics"].get("latency_us") or -1) > 0 else 10**18))
    else:
        scored = [(v, r) for r in runs if (v := _verified(r)) is not None]
        if scored:
            best = max(scored, key=lambda t: (t[0][0] - 1000 * t[0][1]))[1]
    verified = _verified(best) if best else None
    result = _result_line(log)
    if result is None:
        notes.append("no launcher RESULT line: status, wall_s, final latency and DuckDB time not derivable from a log")
    expect_path = ws / "decl_data" / "expect.json"
    expect = json.loads(expect_path.read_text()) if expect_path.is_file() else None
    duck_us = (result or {}).get("duck_us") or ((expect or {}).get("duck_us"))
    if duck_us is None:
        notes.append("duck_allcore_us not derivable (no RESULT line, no expect.json)")
    final_latency = (result or {}).get("latency_us")
    kernel_us = final_latency if isinstance(final_latency, int) and final_latency > 0 else None
    speedup = round(duck_us / kernel_us, 3) if kernel_us and duck_us else None
    below_bar = _SPEED_BAR.search((result or {}).get("error") or "")
    if kernel_us is None and below_bar:  # the host measured the body and refused it for speed: the numbers are in its message
        kernel_us, duck_us, speedup = int(below_bar.group(1)), int(below_bar.group(2)), float(below_bar.group(3))
        notes.append("kernel_us, duck_allcore_us and speedup taken from the host's below-the-speed-bar message (the run is not scored)")
    # What the in-session / final host checks said about the rows.
    rows_match = None
    texts = [((r.get("metrics") or {}).get("compiler_error") or "") for r in runs]
    if submitted or kernel_us or below_bar:  # the speed message comes after the row check
        rows_match = True
    elif any("result rows differ" in t for t in texts):
        rows_match = False
    elif proved_runs:
        notes.append("rows_match not derivable (proved, no submit, no row message)")
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
        "submitted": submitted,
        "verified_line": f"{verified[0]} verified, {verified[1]} errors" if verified else None,
        "checks": len(runs),
        "wall_s": (result or {}).get("wall_s"),
        "status": (result or {}).get("status"),
        "kernel_us": kernel_us,
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
        "error": ((result or {}).get("error") or "")[:300] or None,
        "cause": cause,
        "notes": notes,
    }


def regenerate(index: Path, causes: Path | None, out: Path) -> list[dict]:
    """Rewrite ``out`` from the index (a list of {query, attempt, run_dir, log?, infra?}); the causes file is keyed by run directory name."""
    cause_map = json.loads(causes.read_text()) if causes and causes.is_file() else {}
    rows = []
    for item in json.loads(index.read_text()):
        run_dir = Path(item["run_dir"])
        log = Path(item["log"]) if item.get("log") else None
        rows.append(row_from_run(run_dir, query=item["query"], attempt=item["attempt"], log=log, infra=item.get("infra"), cause=cause_map.get(run_dir.name)))
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return rows


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
    a = ap.parse_args(argv)
    if a.index:
        if not a.out:
            raise SystemExit("--index needs --out")
        rows = regenerate(a.index, a.causes, a.out)
        print(f"wrote {len(rows)} rows to {a.out}")
        return 0
    if not (a.run_dir and a.query and a.attempt):
        raise SystemExit("need RUN_DIR --query --attempt (or --index --out)")
    print(json.dumps(row_from_run(a.run_dir, query=a.query, attempt=a.attempt, log=a.log, infra=a.infra), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
