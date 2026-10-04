"""Model ladder: the same six SEC queries on the declarative path, one model per run.

Usage: ``declarative_ladder.py <model-slug>``. Per-run env only; config.env is not edited.
Results append to ``research_loop/generated/decl_ladder/<model>.jsonl``.
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
from research_loop.agent_sandbox import CLAUDE_IMAGE, claude_agent_cmd, claude_docker_args
from research_loop.scripts.declarative_draws import beats_duck, resolve_sec_db
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

ROWS = 2_000_000
SEED = 1616
_TABLES = ("t", "u", "src", "fact")
_COLS = ("k", "bucket", "code", "grp", "slot", "kind")
_ALIASES = ("cnt", "n", "c")
_DOMAINS = (16, 32, 64, 128, 256)
_SEC_JOINS = [
    "SELECT s.fy, COUNT(*) AS cnt FROM num n JOIN sub s ON n.adsh = s.adsh GROUP BY s.fy",
    "SELECT s.fy, SUM(n.value) AS total FROM num n JOIN sub s ON n.adsh = s.adsh GROUP BY s.fy",
]


def synthetic_group_counts() -> list[dict]:
    """Four fixed group-count shapes on generated tables (the shapes that proved in earlier draws)."""
    rng = random.Random(SEED)
    out = []
    for _ in range(4):
        table = rng.choice(_TABLES)
        column = rng.choice(_COLS)
        domain = rng.choice(_DOMAINS)
        alias = rng.choice(_ALIASES)
        out.append(
            {
                "sql": f"SELECT {column}, COUNT(*) AS {alias} FROM {table} GROUP BY {column}",
                "schema": {table: {column: "ubigint"}},
                "catalog": CatalogAssumptions(
                    tables={
                        table: TableAssumptions(
                            max_rows=ROWS,
                            columns={column: ColumnAssumption(max_value_exclusive=domain)},
                        )
                    }
                ),
                "decl_seed": str(rng.randrange(1, 1_000_000)),
            }
        )
    return out


def agent_env(model: str) -> dict[str, str]:
    """Per-run agent env. ``claude-*`` slugs run Claude Code, everything else the Cursor agent."""
    env = {
        "LEMMA_SPEC_STYLE": "declarative",
        "USE_AGENT_DOCKER": "1",
        "LEMMA_AGENT_BACKEND": "cli",
        "LEMMA_SERIOUS": "1",
        "LEMMA_RESEARCH_LOG": "1",
    }
    if model.startswith("claude-"):
        env.update(AGENT_IMAGE=CLAUDE_IMAGE, AGENT_ENV="", AGENT_CMD=claude_agent_cmd(model))
    else:
        env.update(
            AGENT_IMAGE="lemma-agent:cli",
            AGENT_CMD=(
                f"agent -p --force --trust --approve-mcps --model {model} "
                '--output-format stream-json --stream-partial-output "$(cat PROMPT.txt)"'
            ),
        )
    return env


def run_ladder(model: str, indices: tuple[int, ...] | None = None) -> list[dict]:
    """All six queries, or only the 1-based ``indices`` (plumbing runs)."""
    db_path = resolve_sec_db()
    os.environ.update(agent_env(model))
    if model.startswith("claude-"):
        claude_docker_args()  # raises before any work when no credentials are set
    os.environ.pop("LEMMA_DECL_ROWS", None)
    out = ROOT / "research_loop" / "generated" / "decl_ladder"
    out.mkdir(parents=True, exist_ok=True)
    log = out / f"{model}.jsonl"
    sec_schema = load_sec_schema()
    jobs = synthetic_group_counts() + [{"sql": sql, "sec": True} for sql in _SEC_JOINS]
    records = []
    for index, job in enumerate(jobs, start=1):
        if indices is not None and index not in indices:
            continue
        sql = job["sql"]
        kwargs: dict = {"max_iterations": 2, "use_mock": False}
        if job.get("sec"):
            os.environ["LEMMA_MEASURE_DB"] = str(db_path)
            os.environ["LEMMA_ASSUMPTION_PACKAGE"] = "sec_margin"
            os.environ["LEMMA_FLOAT_ABS_EPS"] = "1e20"
            os.environ.pop("LEMMA_DECL_ROWS", None)
            os.environ.pop("LEMMA_DECL_SEED", None)
            kwargs.update(schema=sec_schema, workload="sec")
        else:
            os.environ.pop("LEMMA_MEASURE_DB", None)
            os.environ.pop("LEMMA_ASSUMPTION_PACKAGE", None)
            os.environ["LEMMA_DECL_ROWS"] = str(ROWS)
            os.environ["LEMMA_DECL_SEED"] = job["decl_seed"]
            kwargs.update(schema=job["schema"], catalog_assumptions=job["catalog"], dataset_size=ROWS)
        print(f"LADDER model={model} query={index}/{len(jobs)} sql={sql}", flush=True)
        t0 = time.time()
        result = run_optimization_loop(sql, **kwargs)
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
        records.append(record)
    return records


def main(model: str) -> int:
    run_ladder(model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
