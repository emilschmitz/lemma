"""Model ladder: the same six SEC queries on the declarative path, one model per run.

Usage: ``declarative_ladder.py <model-slug>``. Per-run env only; config.env is not edited.
Results append to ``research_loop/generated/decl_ladder/<model>.jsonl``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db_extension.optimizer import run_optimization_loop
from research_loop.scripts.declarative_draws import beats_duck, resolve_sec_db
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema

QUERIES = [
    "SELECT uom, COUNT(*) AS cnt FROM num GROUP BY uom",
    "SELECT fy, COUNT(*) AS cnt FROM sub GROUP BY fy",
    "SELECT stmt, COUNT(*) AS cnt FROM pre GROUP BY stmt",
    "SELECT qtrs, COUNT(*) AS cnt FROM num GROUP BY qtrs",
    "SELECT uom, SUM(value) AS total FROM num GROUP BY uom",
    "SELECT stmt, COUNT(*) AS cnt FROM pre WHERE line < 5 GROUP BY stmt",
]


def main(model: str) -> int:
    db_path = resolve_sec_db()
    env = {
        "LEMMA_SPEC_STYLE": "declarative",
        "LEMMA_ASSUMPTION_PACKAGE": "sec_margin",
        "LEMMA_MEASURE_DB": str(db_path),
        "LEMMA_FLOAT_ABS_EPS": "1e20",
        "USE_AGENT_DOCKER": "1",
        "AGENT_IMAGE": "lemma-agent:cli",
        "LEMMA_AGENT_BACKEND": "cli",
        "LEMMA_SERIOUS": "1",
        "LEMMA_RESEARCH_LOG": "1",
        "AGENT_CMD": (
            f"agent -p --force --trust --approve-mcps --model {model} "
            '--output-format stream-json --stream-partial-output "$(cat PROMPT.txt)"'
        ),
    }
    os.environ.update(env)
    os.environ.pop("LEMMA_DECL_ROWS", None)
    out = ROOT / "research_loop" / "generated" / "decl_ladder"
    out.mkdir(parents=True, exist_ok=True)
    log = out / f"{model}.jsonl"
    schema = load_sec_schema()
    for index, sql in enumerate(QUERIES, start=1):
        print(f"LADDER model={model} query={index}/{len(QUERIES)} sql={sql}", flush=True)
        t0 = time.time()
        result = run_optimization_loop(sql, schema=schema, workload="sec", use_mock=False, max_iterations=2)
        scored = {
            "status": result.get("status"),
            "latency_us": result.get("best_latency_us"),
            "duck_us": result.get("duck_us"),
        }
        record = {
            "model": model,
            "index": index,
            "sql": sql,
            "start_epoch": t0,
            "wall_s": round(time.time() - t0, 1),
            **scored,
            "beats_duck": beats_duck(scored),
            "error": (result.get("error") or "")[-2000:],
        }
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        print(f"RESULT {json.dumps(record)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
