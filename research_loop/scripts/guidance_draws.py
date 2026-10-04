"""Paired fresh draws: prescribed join menu vs optional tips.

Each draw samples 6 GenDB SEC queries with a new seed. Every query is run
twice with Grok 4.7 (CLI), once with the join menu in the prompt and once
with optional notes only. The proof bar does not change. A row is recorded
even when the agent fails, so the arms stay paired.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db_extension.optimizer import run_optimization_loop
from research_loop.scripts.declarative_draws import (
    resolve_sec_db,
    sample_gendb_queries,
)
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema

DRAWS = 2
ARMS = ("prescribe", "tips")
_OUT = ROOT / "harvest" / "guidance_draws"


def _arm_env(arm: str, db_path: Path) -> None:
    os.environ["LEMMA_AGENT_GUIDANCE"] = arm
    os.environ["LEMMA_AGENT_BACKEND"] = "cli"
    os.environ["USE_AGENT_DOCKER"] = "0"
    os.environ["LEMMA_SPEC_STYLE"] = "recursive"
    os.environ["LEMMA_FAST_TRUSTEDS"] = "0"
    os.environ["LEMMA_ASSUMPTION_PACKAGE"] = "sec_margin"
    os.environ["LEMMA_DUCKDB_PATH"] = str(db_path)
    os.environ["LEMMA_MEASURE_DB"] = str(db_path)
    os.environ["LEMMA_RESEARCH_LOG"] = "1"
    os.environ["MAX_ITERATIONS"] = "1"
    os.environ.setdefault("AGENT_TIMEOUT_SEC", "600")


def _one_query(seed: int, index: int, qid: str, sql: str, schema: dict, arm: str) -> dict:
    print(
        f"ARM arm={arm} seed={seed} query={index} qid={qid} sql={' '.join(sql.split())}",
        flush=True,
    )
    t0 = time.perf_counter()
    try:
        result = run_optimization_loop(
            sql,
            schema=schema,
            workload="sec",
            use_mock=False,
            max_iterations=1,
            dataset_size=50_000,
        )
        error = (result.get("error") or "")[-2000:]
        status = result.get("status")
        latency = result.get("best_latency_us")
        duck = result.get("duck_us")
    except Exception as exc:
        status, latency, duck, error = "FAILED", None, None, str(exc)[-2000:]
    record = {
        "seed": seed,
        "index": index,
        "qid": qid,
        "arm": arm,
        "sql": sql,
        "status": status,
        "latency_us": latency,
        "duck_us": duck,
        "elapsed_s": int(time.perf_counter() - t0),
        "error": error,
    }
    print(
        f"RESULT arm={arm} seed={seed} query={index} status={status} "
        f"latency={latency} duck={duck} elapsed_s={record['elapsed_s']}",
        flush=True,
    )
    return record


def main() -> int:
    db_path = resolve_sec_db()
    schema = load_sec_schema()
    _OUT.mkdir(parents=True, exist_ok=True)
    rng = random.SystemRandom()
    log_path = _OUT / "draws.jsonl"
    for draw in range(1, DRAWS + 1):
        seed = rng.randrange(1, 1_000_000_000)
        sql_path = _OUT / f"queries_{seed}.sql"
        print(f"DRAW {draw}/{DRAWS} seed={seed}", flush=True)
        queries = sample_gendb_queries(seed=seed, db_path=db_path, output=sql_path)
        for index, (qid, sql) in enumerate(queries, start=1):
            for arm in ARMS:
                _arm_env(arm, db_path)
                record = _one_query(seed, index, qid, sql, schema, arm)
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record) + "\n")
    print(f"DRAWS_DONE log={log_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
