"""Table of real-container runs from their launcher logs: model, proved, threads, official-size time vs the all-core engine, x-factor.

``container_table.py LOG [LOG ...]`` reads the last `RESULT {...}` line of every log (written by ``run_container_agent.py``).
The x-factor is ``duck_us / latency_us`` (all-core DuckDB over the proved body, official size, median of 9). A factor between
0.8 and 1.25 is a TIE, below 0.8 a LOSS, above 1.25 a WIN. A run whose status is not SUCCESS has no timing: it is a miss (not proved,
or proved but below the speed bar, which the launcher reports as FAILED).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TIE_LOW, TIE_HIGH = 0.8, 1.25


def verdict(x: float | None) -> str:
    if x is None:
        return "no timing"
    return "WIN" if x > TIE_HIGH else ("LOSS" if x < TIE_LOW else "TIE")


def row(log: Path) -> dict:
    lines = [ln for ln in log.read_text().splitlines() if ln.startswith("RESULT ")]
    if not lines:
        return {"log": log.name, "status": "NO RESULT LINE (the run did not finish)"}
    rec = json.loads(lines[-1][len("RESULT ") :])
    lat, duck = rec.get("latency_us"), rec.get("duck_us")
    x = duck / lat if isinstance(lat, int) and lat > 0 and isinstance(duck, int) else None
    return {
        "log": log.name,
        "sql": rec.get("sql"),
        "model": rec.get("model"),
        "status": rec.get("status"),
        "threads_used": rec.get("threads_used"),
        "latency_us": lat,
        "duck_us": duck,
        "x_factor": None if x is None else round(x, 2),
        "verdict": verdict(x),
        "egress_hosts": rec.get("egress_hosts"),
        "egress_denied": rec.get("egress_denied"),
        "egress_denied_in_agent_bash": rec.get("egress_denied_in_agent_bash"),
        "wall_s": rec.get("wall_s"),
        "error": (rec.get("error") or "")[:160],
    }


def main(argv: list[str]) -> int:
    print("| log | model | status | threads | body us | all-core duck us | x | verdict | egress |")
    print("|---|---|---|---|---|---|---|---|---|")
    for arg in argv:
        r = row(Path(arg))
        print(
            f"| {r['log']} | {r.get('model')} | {r['status']} | {r.get('threads_used')} | {r.get('latency_us')} | {r.get('duck_us')} "
            f"| {r.get('x_factor')} | {r.get('verdict')} | {r.get('egress_hosts')} denied={r.get('egress_denied')} bash-denied={r.get('egress_denied_in_agent_bash')} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
