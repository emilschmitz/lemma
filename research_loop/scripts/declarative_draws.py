"""Three consecutive fresh GenDB SEC draws on the declarative path.

Each draw is the overnight shuffle: ``generate_queries.py`` with a new seed,
a pool of 600, and a diversity sample of 6. Each query goes through
``run_optimization_loop`` with ``LEMMA_SPEC_STYLE=declarative``. A query
counts only when the proved binary is faster than DuckDB on that SQL.
A draw counts only when all six do. The streak resets when a draw misses.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db_extension.optimizer import run_optimization_loop
from research_loop.assumption_packages.check import check_package
from research_loop.scripts.sqlsmith_trusted_coverage import (
    decimal_columns,
    load_sec_schema,
    parse_sql_file,
)

DRAWS = 3
NUM_GENERATE = 600
NUM_SELECT = 6
_GEN = ROOT / "holdout" / "gendb_sec_edgar" / "generate_queries.py"
_DEFAULT_DB = ROOT / "holdout" / "gendb_sec_edgar" / "duckdb" / "sec_edgar_dec.duckdb"
_OUT = ROOT / "harvest" / "decl_draws"


def resolve_sec_db() -> Path:
    raw = os.environ.get("LEMMA_DUCKDB_PATH", "").strip()
    path = Path(raw) if raw else _DEFAULT_DB
    if not path.is_file():
        raise SystemExit(f"ERROR: SEC DuckDB missing at {path}; cannot generate shuffle.")
    return path


def package_for_db(db_path: Path) -> str:
    """The assumption package for this database file: the DECIMAL one when the file has DECIMAL columns."""
    return "sec_margin_dec" if decimal_columns(db_path) else "sec_margin"


def gendb_sample_command(*, seed: int, db_path: Path, output: Path) -> list[str]:
    """Same flags as ``overnight_lemma.sh`` (pool 600, select 6), with this seed."""
    return [
        sys.executable,
        str(_GEN),
        "--seed",
        str(seed),
        "--num-generate",
        str(NUM_GENERATE),
        "--num-select",
        str(NUM_SELECT),
        "--db-path",
        str(db_path),
        "--output",
        str(output),
    ]


def sample_gendb_queries(*, seed: int, db_path: Path, output: Path) -> list[tuple[str, str]]:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(gendb_sample_command(seed=seed, db_path=db_path, output=output), check=True)
    pairs = parse_sql_file(output)
    if len(pairs) != NUM_SELECT:
        raise SystemExit(f"ERROR: shuffle {output} has {len(pairs)} queries, expected {NUM_SELECT}")
    return pairs


def beats_duck(record: dict) -> bool:
    duck = record.get("duck_us")
    latency = record.get("latency_us")
    return (
        record.get("status") == "SUCCESS"
        and isinstance(duck, int)
        and isinstance(latency, int)
        and 0 <= latency < duck
    )


def _one_draw(seed: int, db_path: Path) -> bool:
    sql_path = _OUT / f"queries_{seed}.sql"
    print(
        f"SHUFFLE seed={seed} num_generate={NUM_GENERATE} num_select={NUM_SELECT} db={db_path}",
        flush=True,
    )
    queries = sample_gendb_queries(seed=seed, db_path=db_path, output=sql_path)
    schema = load_sec_schema(db_path)
    package = package_for_db(db_path)
    check_package(package, str(db_path))
    os.environ["LEMMA_SPEC_STYLE"] = "declarative"
    os.environ["LEMMA_ASSUMPTION_PACKAGE"] = package
    os.environ["LEMMA_MEASURE_DB"] = str(db_path)
    os.environ.pop("LEMMA_DECL_ROWS", None)
    ok_all = True
    log_path = _OUT / f"draw_{seed}.jsonl"
    for index, (qid, sql) in enumerate(queries, start=1):
        one_line = " ".join(sql.split())
        print(f"DRAW seed={seed} query={index}/{NUM_SELECT} qid={qid} sql={one_line}", flush=True)
        result = run_optimization_loop(
            sql,
            schema=schema,
            workload="sec",
            use_mock=False,
            max_iterations=2,
        )
        record = {
            "seed": seed,
            "index": index,
            "qid": qid,
            "sql": sql,
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
        if not beats_duck(record):
            ok_all = False
            break
    print(f"DRAW_DONE seed={seed} ok={ok_all}", flush=True)
    return ok_all


def main() -> int:
    db_path = resolve_sec_db()
    streak = 0
    rng = random.SystemRandom()
    while streak < DRAWS:
        seed = rng.randrange(1, 1_000_000_000)
        print(f"STREAK {streak}/{DRAWS} starting seed={seed} db={db_path}", flush=True)
        t0 = time.perf_counter()
        won = _one_draw(seed, db_path)
        print(f"DRAW_ELAPSED_S {int(time.perf_counter() - t0)}", flush=True)
        if won:
            streak += 1
            print(f"STREAK_NOW {streak}/{DRAWS}", flush=True)
        else:
            print("STREAK_RESET 0", flush=True)
            return 1
    print("THREE_DRAWS_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
