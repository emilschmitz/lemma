"""One adversary_declarative0 round: three fresh queries through the real declarative loop.

``declarative_round.py --seed N [--model M] [--mix sec,sec,tpch]``

* Draws fresh queries from the seed: GenDB-shaped SEC queries (the shuffle generator) and
  TPC-H-shaped queries (seeded parameter variants of Q1/Q3/Q6/Q9/Q18/...). A query the declarative
  emitter refuses is skipped and recorded with its refusal reason (a coverage task).
* Runs each through ``run_optimization_loop`` under the ``adversary_declarative0`` menu with the
  Claude Code agent in the Docker sandbox. Credentials come from the launching shell only
  (``ANTHROPIC_API_KEY`` or ``LEMMA_CLAUDE_CONFIG_DIR``); the run fails loudly without them.
* Appends one JSON record per query to ``research_loop/generated/decl_rounds/round_<seed>.jsonl``
  with status, latency, DuckDB all-thread and one-thread times, speedups, the speed bar and the
  run directory (the traces).

``--draw-only`` stops after the draw and the emit check.
"""

from __future__ import annotations

import argparse
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

from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.lemmas import FitRefusal
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions
from research_loop.trust_configs import apply_trust_config

MAIN_REPO = Path("/home/emil/projects/lemma-db")
SEC_DB = MAIN_REPO / "holdout" / "gendb_sec_edgar" / "duckdb" / "sec_edgar_local.duckdb"
TPCH_SF = float(os.environ.get("LEMMA_TPCH_SF", "1"))
TPCH_DB = Path(os.environ.get("LEMMA_TPCH_DB", ROOT / "research_loop" / "generated" / f"tpch_sf{TPCH_SF:g}.duckdb"))
OUT = ROOT / "research_loop" / "generated" / "decl_rounds"
HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-5-5"

_SEGMENTS = ["BUILDING", "AUTOMOBILE", "MACHINERY", "HOUSEHOLD", "FURNITURE"]
_MODES = ["MAIL", "SHIP", "AIR", "RAIL", "TRUCK", "FOB", "REG AIR"]


def tpch_variants(rng: random.Random) -> list[tuple[str, str]]:
    """Seeded TPC-H-shaped queries (name, sql). The emitter decides which ones are supported."""
    year = rng.randint(1993, 1997)
    disc = rng.randint(2, 9)
    qty = rng.choice([24, 25])
    delta = rng.randint(60, 120)
    seg = rng.choice(_SEGMENTS)
    day = rng.randint(1, 31)
    mode = rng.choice(_MODES)
    month = rng.randint(1, 12)
    return [
        (
            "tpch_q6_var",
            f"SELECT sum(l_extendedprice * l_discount) AS revenue FROM lineitem "
            f"WHERE l_shipdate >= date '{year}-01-01' AND l_shipdate < date '{year}-01-01' + interval '1' year "
            f"AND l_discount BETWEEN 0.0{disc} - 0.01 AND 0.0{disc} + 0.01 AND l_quantity < {qty}",
        ),
        (
            "tpch_q1_var",
            "SELECT l_returnflag, l_linestatus, sum(l_quantity) AS sum_qty, sum(l_extendedprice) AS sum_base_price, "
            "sum(l_extendedprice * (1 - l_discount)) AS sum_disc_price, "
            "sum(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge, count(*) AS count_order "
            f"FROM lineitem WHERE l_shipdate <= date '1998-12-01' - interval '{delta}' day "
            "GROUP BY l_returnflag, l_linestatus ORDER BY l_returnflag, l_linestatus",
        ),
        (
            "tpch_q3_var",
            "SELECT l_orderkey, sum(l_extendedprice * (1 - l_discount)) AS revenue, o_orderdate, o_shippriority "
            f"FROM customer, orders, lineitem WHERE c_mktsegment = '{seg}' AND c_custkey = o_custkey "
            f"AND l_orderkey = o_orderkey AND o_orderdate < date '1995-03-{day:02d}' "
            f"AND l_shipdate > date '1995-03-{day:02d}' "
            "GROUP BY l_orderkey, o_orderdate, o_shippriority ORDER BY revenue DESC, o_orderdate LIMIT 10",
        ),
        (
            "tpch_q12_shape",
            "SELECT l_shipmode, count(*) AS cnt, sum(l_quantity) AS qty FROM lineitem "
            f"WHERE l_shipmode = '{mode}' AND l_receiptdate >= date '{year}-{month:02d}-01' "
            f"AND l_receiptdate < date '{year}-{month:02d}-01' + interval '1' year GROUP BY l_shipmode",
        ),
        (
            "tpch_q18_shape",
            "SELECT l_orderkey, sum(l_quantity) AS total_qty FROM lineitem GROUP BY l_orderkey "
            f"HAVING sum(l_quantity) > {rng.randint(280, 310)} ORDER BY total_qty DESC LIMIT 100",
        ),
        (
            "tpch_q9_shape",
            "SELECT n_name, sum(l_extendedprice * (1 - l_discount) - ps_supplycost * l_quantity) AS profit "
            "FROM supplier, lineitem, partsupp, nation WHERE s_suppkey = l_suppkey AND ps_suppkey = l_suppkey "
            "AND ps_partkey = l_partkey AND s_nationkey = n_nationkey GROUP BY n_name",
        ),
    ]


def tpch_schema_and_catalog(db: Path) -> tuple[dict, CatalogAssumptions]:
    import duckdb

    con = duckdb.connect(str(db), read_only=True)
    try:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        schema = {t: {r[0]: r[1] for r in con.execute(f"DESCRIBE {t}").fetchall()} for t in tables}
        rows = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
    finally:
        con.close()
    # Measured row counts are the caps (no margin): an honest catalog of this database.
    catalog = CatalogAssumptions(
        max_rows=max(rows.values()), tables={t: TableAssumptions(max_rows=n) for t, n in rows.items()}
    )
    return schema, catalog


def ensure_tpch_db() -> Path:
    if not TPCH_DB.is_file():
        from scripts.export_tpch import export_tpch_duckdb

        print(f"generating TPC-H SF{TPCH_SF:g} at {TPCH_DB}", flush=True)
        export_tpch_duckdb(TPCH_SF, TPCH_DB)
    return TPCH_DB


def sec_catalog() -> CatalogAssumptions:
    from research_loop.assumption_packages import assumption_package

    return assumption_package("sec_margin")


def sec_float_abs_eps() -> str:
    """The realistic default epsilon for SEC queries (relative 1e-9 of the largest allowed float sum)."""
    from declarative_spec.float_eps import default_float_abs_eps
    from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema

    return default_float_abs_eps(sec_catalog(), load_sec_schema())


def draw_sec(seed: int, count: int, schema: dict, catalog: CatalogAssumptions) -> tuple[list[dict], list[dict]]:
    """``count`` emit-able SEC queries from the shuffle generator, plus the refusals met on the way."""
    from research_loop.scripts.sqlsmith_trusted_coverage import parse_sql_file

    OUT.mkdir(parents=True, exist_ok=True)
    out_sql = OUT / f"sec_pool_{seed}.sql"
    subprocess.run(
        [
            sys.executable,
            str(MAIN_REPO / "holdout" / "gendb_sec_edgar" / "generate_queries.py"),
            "--seed", str(seed), "--num-generate", "600", "--num-select", "24",
            "--db-path", str(SEC_DB), "--output", str(out_sql),
        ],
        check=True,
    )
    pool = parse_sql_file(out_sql)
    random.Random(seed).shuffle(pool)
    picked: list[dict] = []
    refused: list[dict] = []
    for qid, sql in pool:
        if len(picked) == count:
            break
        try:
            emit_declarative_spec(sql, schema, catalog, float_abs_eps=sec_float_abs_eps())
        except (DeclarativeUnsupported, FitRefusal, ValueError) as exc:
            refused.append({"kind": "sec", "qid": qid, "sql": " ".join(sql.split()), "refusal": str(exc)[:400]})
            continue
        picked.append({"kind": "sec", "qid": qid, "sql": sql.strip()})
    return picked, refused


def draw_tpch(seed: int, count: int) -> tuple[list[dict], list[dict]]:
    db = ensure_tpch_db()
    schema, catalog = tpch_schema_and_catalog(db)
    variants = tpch_variants(random.Random(seed))
    random.Random(seed + 1).shuffle(variants)
    picked: list[dict] = []
    refused: list[dict] = []
    for name, sql in variants:
        if len(picked) == count:
            break
        try:
            emit_declarative_spec(sql, schema, catalog)
        except (DeclarativeUnsupported, FitRefusal, ValueError) as exc:
            refused.append({"kind": "tpch", "qid": name, "sql": sql, "refusal": str(exc)[:400]})
            continue
        picked.append({"kind": "tpch", "qid": name, "sql": sql})
    return picked, refused


def draw(seed: int, mix: list[str]) -> tuple[list[dict], list[dict]]:
    sec_schema = None
    picked: list[dict] = []
    refused: list[dict] = []
    n_sec, n_tpch = mix.count("sec"), mix.count("tpch")
    if n_sec:
        from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema

        sec_schema = load_sec_schema()
        p, r = draw_sec(seed, n_sec, sec_schema, sec_catalog())
        picked += p
        refused += r
    if n_tpch:
        p, r = draw_tpch(seed, n_tpch)
        picked += p
        refused += r
    return picked, refused


def agent_env(model: str) -> dict[str, str]:
    from research_loop.scripts.declarative_ladder import agent_env as ladder_env

    return ladder_env(model)


def run_query_job(job: dict, model: str, max_iterations: int) -> dict:
    from db_extension.optimizer import run_optimization_loop
    from research_loop.agent_sandbox import claude_docker_args
    from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema

    os.environ.update(agent_env(model))
    claude_docker_args()  # raises before any work when no credentials are set
    for key in ("LEMMA_DECL_ROWS", "LEMMA_DECL_SEED", "LEMMA_ASSUMPTION_PACKAGE"):
        os.environ.pop(key, None)
    kwargs: dict = {"max_iterations": max_iterations, "use_mock": False}
    if job["kind"] == "sec":
        os.environ["LEMMA_MEASURE_DB"] = str(SEC_DB)
        os.environ["LEMMA_ASSUMPTION_PACKAGE"] = "sec_margin"
        os.environ["LEMMA_FLOAT_ABS_EPS"] = sec_float_abs_eps()
        kwargs.update(schema=load_sec_schema(), workload="sec")
    else:
        schema, catalog = tpch_schema_and_catalog(TPCH_DB)
        os.environ["LEMMA_MEASURE_DB"] = str(TPCH_DB)
        os.environ.pop("LEMMA_FLOAT_ABS_EPS", None)
        kwargs.update(schema=schema, catalog_assumptions=catalog)
    runs_dir = ROOT / "research_loop" / "runs"
    before = set(runs_dir.glob("*")) if runs_dir.is_dir() else set()
    t0 = time.time()
    result = run_optimization_loop(job["sql"], **kwargs)
    after = set(runs_dir.glob("*")) if runs_dir.is_dir() else set()
    run_dirs = sorted(str(p) for p in after - before)
    return {
        "model": model,
        "wall_s": round(time.time() - t0, 1),
        "status": result.get("status"),
        "latency_us": result.get("best_latency_us"),
        "duck_us": result.get("duck_us"),
        "history": result.get("history"),
        "error": (result.get("error") or "")[-2000:],
        "run_dirs": run_dirs,
        "result_keys": sorted(result),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--model", default=HAIKU)
    ap.add_argument("--mix", default="sec,sec,tpch")
    ap.add_argument("--max-iterations", type=int, default=2)
    ap.add_argument("--draw-only", action="store_true")
    ap.add_argument("--only", help="comma-separated qids to run (after the draw)")
    args = ap.parse_args()
    mix = args.mix.split(",")
    picked, refused = draw(args.seed, mix)
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / f"round_{args.seed}.jsonl"
    for r in refused:
        print(f"REFUSED {json.dumps(r)}", flush=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "refused", **r}) + "\n")
    for job in picked:
        print(f"DRAWN {job['kind']} {job['qid']}: {' '.join(job['sql'].split())}", flush=True)
    (OUT / f"draw_{args.seed}.json").write_text(json.dumps({"picked": picked, "refused": refused}, indent=1))
    if args.draw_only:
        return 0
    only = set(args.only.split(",")) if args.only else None
    with apply_trust_config("adversary_declarative0"):
        for job in picked:
            if only is not None and job["qid"] not in only:
                continue
            record = {"event": "run", "seed": args.seed, **job, **run_query_job(job, args.model, args.max_iterations)}
            with log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
            print(f"RESULT {job['qid']} {record['status']} latency={record['latency_us']} duck={record['duck_us']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
