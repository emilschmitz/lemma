"""Re-measure a proved body on a freshly prepared workspace: prepare, transplant, check (which regenerates and compares the spec).

``declarative_remeasure.py --src SRC_WS --kind sec|tpch --sql-file F --name NAME --data "real SEC 39.4M num, dict"``

The environment of the launching shell (LEMMA_DUCKDB_PATH / LEMMA_TPCH_DB, LEMMA_STRING_ENCODING, LEMMA_PARALLEL_VSTD, ...) selects the data
and the spec flavour. The result line (status, medians, speedups, the data label, the SQL) is appended to
``research_loop/generated/decl_results.jsonl``: every number claimed in the LOG comes from such a line, i.e. from a check run that
passed the spec regeneration. Needs the same memory care as ``declarative_manual.py`` (run it under ``systemd-run --scope -p MemoryMax=..``).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANUAL = ROOT / "research_loop" / "generated" / "manual"
RESULTS = ROOT / "research_loop" / "generated" / "decl_results.jsonl"
KEYS = ("status", "proof_verified", "latency_us", "latency_best_us", "duck_us", "duck1_us", "speedup", "speedup_best", "speedup_1t", "verify_summary")


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, check=False, env={**os.environ, "PYTHONPATH": str(ROOT)})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, help="workspace holding the proved body")
    ap.add_argument("--kind", required=True, choices=["sec", "tpch"])
    ap.add_argument("--sql-file", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--data", required=True, help="the data label written next to the result (e.g. 'real SEC 39.4M num, dict')")
    a = ap.parse_args()
    ws = MANUAL / a.name
    script = str(ROOT / "research_loop" / "scripts" / "declarative_manual.py")
    steps = [
        [script, "prepare", "--kind", a.kind, "--sql-file", a.sql_file, "--ws", str(ws)],
        [str(ROOT / "research_loop" / "scripts" / "declarative_transplant.py"), a.src, str(ws)],
        [script, "check", "--ws", str(ws)],
    ]
    out = None
    for step in steps:
        out = _run(step)
        if out.returncode != 0:
            print(out.stdout[-2000:] + out.stderr[-2000:])
            raise SystemExit(f"step failed: {step[0]} {step[1] if len(step) > 1 else ''}")
    first = (out.stdout.splitlines() or ["{}"])[0]
    record = json.loads(first)
    row = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "name": a.name,
        "data": a.data,
        "sql": Path(a.sql_file).read_text().strip(),
        "env": {k: os.environ[k] for k in ("LEMMA_STRING_ENCODING", "LEMMA_PARALLEL_VSTD") if k in os.environ},
        "regen_checked": True,
        **{k: record.get(k) for k in KEYS},
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    print(json.dumps(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
