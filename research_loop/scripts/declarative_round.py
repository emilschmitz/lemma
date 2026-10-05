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
import re
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
# The local SEC file is SYNTHETIC (holdout/gendb_sec_edgar/synth_tiny.py), not real EDGAR; the DECIMAL variant
# (value as DECIMAL(38,4), derived from the stored doubles) is the default for this menu.
SEC_DB = Path(
    os.environ.get(
        "LEMMA_DUCKDB_PATH",
        MAIN_REPO / "holdout" / "gendb_sec_edgar" / "duckdb" / "sec_edgar_local_dec.duckdb",
    )
)
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
    package = os.environ.get("LEMMA_TPCH_PACKAGE")
    if package:
        # A catalog proposed by the profiler (``assumption_packages.profile``) for this database: row and value caps per column.
        from research_loop.assumption_packages.json_io import load_catalog_json

        return schema, load_catalog_json(package)
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


def sec_package() -> str:
    from research_loop.scripts.declarative_draws import package_for_db

    named = os.environ.get("LEMMA_SEC_PACKAGE")
    if named:  # a profiler-proposed package for this database (``assumption_packages.profile``), by name or JSON path
        return named

    return package_for_db(SEC_DB)


def sec_schema() -> dict:
    from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema

    return load_sec_schema(SEC_DB)


def sec_catalog() -> CatalogAssumptions:
    from research_loop.assumption_packages import assumption_package

    return assumption_package(sec_package())


_AVG = re.compile(r"\bAVG\s*\(", re.I)


def _avg_refusal(kind: str, qid: str, sql: str) -> dict | None:
    """AVG results are DOUBLE in the reference engine: the float idealization agent owns them. They stay in the sample, are recorded with their SQL as pending, and get no prover until that branch lands."""
    if _AVG.search(sql):
        return {"kind": kind, "qid": qid, "sql": " ".join(sql.split()), "refusal": "pending idealization: AVG returns DOUBLE (float agent branch not merged); no prover is launched on it"}
    return None


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
        skipped = _avg_refusal("sec", qid, sql)
        if skipped:
            refused.append(skipped)
            continue
        try:
            emit_declarative_spec(sql, schema, catalog)
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
        skipped = _avg_refusal("tpch", name, sql)
        if skipped:
            refused.append(skipped)
            continue
        try:
            emit_declarative_spec(sql, schema, catalog)
        except (DeclarativeUnsupported, FitRefusal, ValueError) as exc:
            refused.append({"kind": "tpch", "qid": name, "sql": sql, "refusal": str(exc)[:400]})
            continue
        picked.append({"kind": "tpch", "qid": name, "sql": sql})
    return picked, refused


def draw(seed: int, mix: list[str]) -> tuple[list[dict], list[dict]]:
    picked: list[dict] = []
    refused: list[dict] = []
    n_sec, n_tpch = mix.count("sec"), mix.count("tpch")
    if n_sec:
        p, r = draw_sec(seed, n_sec, sec_schema(), sec_catalog())
        picked += p
        refused += r
    if n_tpch:
        p, r = draw_tpch(seed, n_tpch)
        picked += p
        refused += r
    return picked, refused


def draw_tiered(seed: int, tiers: list[str], *, heldout: bool = False) -> tuple[list[dict], list[dict]]:
    """One fresh query per requested tier (see ``declarative_tiers``); the kind alternates with the seed.

    T1 to T3 come from seeded templates on the SEC (synthetic, DECIMAL) and TPC-H schemas; T4 and T5 also from the
    classified SEC shuffle pool. AVG draws stay in the sample as pending idealization and get no prover.

    Novelty: a query already in the seen registry is never drawn again; a candidate with a new SHAPE (literals
    stripped) is preferred. ``heldout`` draws only held-out shapes (the evaluation set: never used for recipes,
    fixtures or prompt text); the default draws only tuned shapes. Every pick is registered.
    """
    from research_loop.scripts import declarative_tiers as tiers_mod
    from research_loop.scripts.declarative_tiers import seeded_queries, tier as classify
    from research_loop.scripts.sqlsmith_trusted_coverage import parse_sql_file

    sec_sch, sec_cat = sec_schema(), sec_catalog()
    tpch_sch, tpch_cat = tpch_schema_and_catalog(ensure_tpch_db())
    ctx = {"sec": (sec_sch, sec_cat), "tpch": (tpch_sch, tpch_cat)}
    picked: list[dict] = []
    refused: list[dict] = []
    for i, tier_name in enumerate(tiers):
        order = ["sec", "tpch"] if (seed + i) % 2 == 0 else ["tpch", "sec"]
        cands: list[tuple[str, str, str]] = []
        for kind in order:
            if tier_name in ("T1", "T2", "T3"):
                for qid, sql in seeded_queries(kind, tier_name, random.Random(seed * 10 + i)):
                    cands.append((kind, qid, sql))
        if tier_name in ("T4", "T5"):
            OUT.mkdir(parents=True, exist_ok=True)
            out_sql = OUT / f"sec_pool_{seed}_{tier_name}.sql"
            subprocess.run(
                [sys.executable, str(MAIN_REPO / "holdout" / "gendb_sec_edgar" / "generate_queries.py"), "--seed", str(seed),
                 "--num-generate", "600", "--num-select", "60", "--db-path", str(SEC_DB), "--output", str(out_sql)],
                check=True,
            )
            pool = parse_sql_file(out_sql)
            random.Random(seed + i).shuffle(pool)
            cands += [("sec", qid, sql.strip()) for qid, sql in pool if classify(sql) == tier_name]
        seen_q, seen_shapes = tiers_mod.load_registry()
        cands = [
            c for c in cands
            if tiers_mod.normalize(c[2]) not in seen_q
            and tiers_mod.is_heldout(tiers_mod.shape_key(c[2])) == heldout
        ]
        cands.sort(key=lambda c: tiers_mod.shape_key(c[2]) in seen_shapes)  # stable: new shapes first
        for kind, qid, sql in cands:
            skipped = _avg_refusal(kind, qid, sql)
            if skipped:
                refused.append({**skipped, "tier": tier_name})
                continue
            schema, catalog = ctx[kind]
            try:
                emit_declarative_spec(sql, schema, catalog)
            except (DeclarativeUnsupported, FitRefusal, ValueError) as exc:
                refused.append({"kind": kind, "qid": qid, "tier": tier_name, "sql": " ".join(sql.split()), "refusal": str(exc)[:400]})
                continue
            nov = tiers_mod.novelty(sql)
            tiers_mod.register(sql, f"drawn seed {seed} {tier_name}{' heldout' if heldout else ''}")
            picked.append(
                {"kind": kind, "qid": qid, "tier": tier_name, "sql": sql, "heldout": heldout, **nov}
            )
            break
    return picked, refused


def backfill_registry() -> None:
    """Register every query drawn so far (saved draws) and the queries behind fixtures, and report contamination."""
    from research_loop.scripts import declarative_tiers as tiers_mod

    known, _ = tiers_mod.load_registry()
    for path in sorted(OUT.glob("draw_*.json")):
        for job in json.loads(path.read_text())["picked"]:
            if tiers_mod.normalize(job["sql"]) not in known:
                tiers_mod.register(job["sql"], f"backfill {path.name} {job['qid']}")
                known.add(tiers_mod.normalize(job["sql"]))
    for sql, why in _FIXTURE_QUERIES:
        if tiers_mod.normalize(sql) not in known:
            tiers_mod.register(sql, why)
            known.add(tiers_mod.normalize(sql))
        if tiers_mod.is_heldout(tiers_mod.shape_key(sql)):
            print(f"CONTAMINATED: fixture shape is in the held-out set: {why}", flush=True)


# Queries behind recipes and fixtures: their shapes are tuned shapes and must not be held-out.
_FIXTURE_QUERIES = [
    (
        "SELECT stmt, rfile, COUNT(*) AS cnt, COUNT(DISTINCT adsh) AS num_filings FROM pre WHERE stmt IS NOT NULL "
        "GROUP BY stmt, rfile ORDER BY cnt DESC",
        "fixture hard/string_tuple_count_distinct_sorted.rs",
    ),
    (
        "SELECT sum(l_extendedprice * l_discount) AS revenue FROM lineitem WHERE l_shipdate >= date '1994-01-01' "
        "AND l_shipdate < date '1994-01-01' + interval '1' year AND l_discount BETWEEN 0.09 - 0.01 AND 0.09 + 0.01 "
        "AND l_quantity < 25",
        "fixture ungrouped_decimal_product_sum.rs",
    ),
    (
        "SELECT MIN(ddate) AS lo, MAX(ddate) AS hi FROM num WHERE uom = 'pure' AND qtrs = 3",
        "fixture ungrouped_minmax_string_filter.rs",
    ),
    (
        "SELECT l_returnflag, l_linestatus, sum(l_quantity) AS sum_qty, sum(l_extendedprice) AS sum_base_price, "
        "sum(l_extendedprice * (1 - l_discount)) AS sum_disc_price, count(*) AS count_order FROM lineitem "
        "WHERE l_shipdate <= date '1998-12-01' - interval '90' day GROUP BY l_returnflag, l_linestatus "
        "ORDER BY l_returnflag, l_linestatus",
        "fixture hard/group_decimal_sums_string_keys_sorted.rs",
    ),
]


def agent_env(model: str) -> dict[str, str]:
    from research_loop.scripts.declarative_ladder import agent_env as ladder_env

    return ladder_env(model)


def run_query_job(job: dict, model: str, max_iterations: int) -> dict:
    from db_extension.optimizer import run_optimization_loop
    from research_loop.agent_sandbox import claude_docker_args
    os.environ.update(agent_env(model))
    claude_docker_args()  # raises before any work when no credentials are set
    for key in ("LEMMA_DECL_ROWS", "LEMMA_DECL_SEED", "LEMMA_ASSUMPTION_PACKAGE"):
        os.environ.pop(key, None)
    kwargs: dict = {"max_iterations": max_iterations, "use_mock": False}
    if job["kind"] == "sec":
        os.environ["LEMMA_MEASURE_DB"] = str(SEC_DB)
        os.environ["LEMMA_ASSUMPTION_PACKAGE"] = sec_package()
        kwargs.update(schema=sec_schema(), workload="sec")
    else:
        schema, catalog = tpch_schema_and_catalog(TPCH_DB)
        os.environ["LEMMA_MEASURE_DB"] = str(TPCH_DB)
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
    ap.add_argument("--heldout", action="store_true", help="with --tiers: draw held-out shapes only (evaluation set)")
    ap.add_argument("--backfill-registry", action="store_true")
    ap.add_argument("--tiers", help="comma-separated tiers T1..T5: one fresh query per tier (replaces --mix)")
    ap.add_argument("--max-iterations", type=int, default=2)
    ap.add_argument("--draw-only", action="store_true")
    ap.add_argument("--only", help="comma-separated qids to run (after the draw)")
    args = ap.parse_args()
    if args.backfill_registry:
        backfill_registry()
        return 0
    mix = args.mix.split(",")
    picked, refused = draw_tiered(args.seed, args.tiers.split(","), heldout=args.heldout) if args.tiers else draw(args.seed, mix)
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
