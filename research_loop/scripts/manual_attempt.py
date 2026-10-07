"""Bracket one manual-prover attempt so its row is machine-made.

    manual_attempt.py start WS
    manual_attempt.py end WS --query r1_q02 --attempt 1 --reason done|timeout|stopped [--out arena/results_manual.jsonl]

``end`` builds the row with ``arena_record.row_from_manual`` (checks from ``WS/check_log.jsonl`` between start and end; the setup sha and whether it is the
unmodified baseline sha from ``arena/manual_baseline_sha.txt``) and appends it to the results file. Never edit a row by hand.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
ARENA = Path("/home/emil/projects/lemma-db/research_loop/generated/arena")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["start", "end"])
    ap.add_argument("ws", type=Path)
    ap.add_argument("--query")
    ap.add_argument("--attempt", type=int)
    ap.add_argument("--reason", default="done")
    ap.add_argument("--out", type=Path, default=ARENA / "results_manual.jsonl")
    a = ap.parse_args()
    stamp = a.ws / "attempt_start.json"
    if a.cmd == "start":
        stamp.write_text(json.dumps({"started": time.time()}))
        return 0
    from research_loop.scripts.arena_record import row_from_manual

    started = json.loads(stamp.read_text())["started"]
    sha = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    base_file = ARENA / "manual_baseline_sha.txt"
    baseline = base_file.read_text().strip() if base_file.is_file() else None
    row = row_from_manual(a.ws, query=a.query, attempt=a.attempt, started=started, ended=time.time(), end_reason=a.reason, sha=sha, baseline_sha=baseline)
    with a.out.open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    print(json.dumps(row, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
