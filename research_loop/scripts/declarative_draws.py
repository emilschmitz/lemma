"""Three consecutive fresh draws of six declarative group-counts.

Each query goes through ``run_optimization_loop`` with ``LEMMA_SPEC_STYLE=declarative``.
Success is a proved binary whose median is faster than DuckDB on the same rows.
A draw counts only when all six succeed. The streak resets when a draw misses.
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
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
)

ROWS = int(os.environ.get("LEMMA_DECL_ROWS", "2000000"))
DRAWS = 3
PER_DRAW = 6
_TABLES = ("t", "u", "src", "fact")
_COLS = ("k", "bucket", "code", "grp", "slot", "kind")
_ALIASES = ("cnt", "n", "c")
_DOMAINS = (16, 32, 64, 128, 256)
_OUT = ROOT / "harvest" / "decl_draws"


def _query(rng: random.Random) -> tuple[str, dict, CatalogAssumptions, int]:
    table = rng.choice(_TABLES)
    column = rng.choice(_COLS)
    domain = rng.choice(_DOMAINS)
    alias = rng.choice(_ALIASES)
    sql = f"SELECT {column}, COUNT(*) AS {alias} FROM {table} GROUP BY {column}"
    schema = {table: {column: "ubigint"}}
    catalog = CatalogAssumptions(
        tables={
            table: TableAssumptions(
                max_rows=ROWS,
                columns={column: ColumnAssumption(max_value_exclusive=domain)},
            )
        },
    )
    return sql, schema, catalog, domain


def _one_draw(seed: int) -> bool:
    rng = random.Random(seed)
    _OUT.mkdir(parents=True, exist_ok=True)
    log_path = _OUT / f"draw_{seed}.jsonl"
    ok_all = True
    for index in range(1, PER_DRAW + 1):
        sql, schema, catalog, domain = _query(rng)
        os.environ["LEMMA_DECL_SEED"] = str(rng.randrange(1, 1_000_000))
        os.environ["LEMMA_DECL_ROWS"] = str(ROWS)
        os.environ["LEMMA_SPEC_STYLE"] = "declarative"
        print(f"DRAW seed={seed} query={index}/{PER_DRAW} domain={domain} sql={sql}", flush=True)
        result = run_optimization_loop(
            sql,
            schema=schema,
            catalog_assumptions=catalog,
            use_mock=False,
            max_iterations=2,
            dataset_size=ROWS,
        )
        record = {
            "seed": seed,
            "index": index,
            "sql": sql,
            "domain": domain,
            "status": result.get("status"),
            "latency_us": result.get("best_latency_us"),
            "duck_us": result.get("duck_us"),
            "error": (result.get("error") or "")[-2000:],
        }
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        print(
            f"RESULT seed={seed} query={index} status={record['status']} "
            f"latency={record['latency_us']} duck={record['duck_us']}",
            flush=True,
        )
        if record["status"] != "SUCCESS":
            ok_all = False
            break
    print(f"DRAW_DONE seed={seed} ok={ok_all}", flush=True)
    return ok_all


def main() -> int:
    streak = 0
    rng = random.SystemRandom()
    while streak < DRAWS:
        seed = rng.randrange(1, 1_000_000_000)
        print(f"STREAK {streak}/{DRAWS} starting seed={seed} rows={ROWS}", flush=True)
        t0 = time.perf_counter()
        won = _one_draw(seed)
        print(f"DRAW_ELAPSED_S {int(time.perf_counter() - t0)}", flush=True)
        if won:
            streak += 1
            print(f"STREAK_NOW {streak}/{DRAWS}", flush=True)
        else:
            streak = 0
            print("STREAK_RESET 0", flush=True)
            return 1
    print("THREE_DRAWS_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
