"""A pool of non-trivial queries of one grammar level, selected mechanically.

    uv run python -m research_loop.scripts.fragment_pool --level med --sql draws.sql [more.sql ...] --db sec_edgar_dec.duckdb \\
        --package sec_margin_dec --want 40 --out research_loop/generated/arena/rounds/g1m --seed 1

A candidate is kept when ALL hold, checked in this order and recorded in ``manifest.json``:
  1. its smallest grammar level is the requested one (``med`` also demands exactly 2 tables);
  2. it transpiles and the assembled program Verus-typechecks (``--no-verify``, a diverging body; nothing is proved);
  3. the largest table it reads has at least ``--min-fact-rows`` rows;
  4. DuckDB (all cores, hot: one warm-up run, then the median of 3) takes at least ``--min-ms``;
  5. it is not a near-duplicate of one already kept: same tables, group columns, filter columns and aggregate
     (kind, column) signature.
Nothing here looks at whether a query is easy to prove. Timing bursts take the machine's exclusive timing lock
(``/tmp/lemma_timing.lock``) one query at a time, so a running batch is delayed by seconds, never starved.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import statistics
import sys
import time
from pathlib import Path

import duckdb
import sqlglot
from sqlglot import exp

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.fragment import fragment_level
from research_loop.assumption_packages import assumption_package
from research_loop.scripts.fragment_coverage import STUB, transpile, typecheck
from research_loop.scripts.fragment_gen import features, provenance, schema_from_db
from research_loop.scripts.sqlsmith_trusted_coverage import parse_sql_file

import lemma_config

LOCK = Path(lemma_config.get("heavy_lock"))


def signature(sql: str) -> tuple:
    """Tables, group columns, filter columns, aggregate (kind, column): what makes two queries near-duplicates."""
    tree = sqlglot.parse_one(sql)
    tables = tuple(sorted(t.name.lower() for t in tree.find_all(exp.Table)))
    group = tuple(sorted(c.name.lower() for g in (tree.args.get("group") or exp.Group()).expressions for c in g.find_all(exp.Column)))
    where = tree.args.get("where")
    filt = tuple(sorted({c.name.lower() for c in where.find_all(exp.Column)})) if where else ()
    aggs = tuple(sorted((type(a).__name__, tuple(sorted(c.name.lower() for c in a.find_all(exp.Column)))) for a in tree.find_all(exp.AggFunc)))
    return tables, group, filt, aggs


def timed(db: Path, sql: str, timeout: float = 60.0) -> tuple[float, int]:
    """(median ms of 3 hot runs on all cores, rows returned). Holds the exclusive timing lock for the burst."""
    # under scripts/ram/heavy.sh the caller already holds the exclusive lock (taking it again would wait on itself)
    handle = open(os.devnull) if os.environ.get("LEMMA_HEAVY_LOCK_HELD") == "1" else LOCK.open("w")
    with handle:
        if handle.name != os.devnull:
            fcntl.flock(handle, fcntl.LOCK_EX)
        while int(next(line for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable")).split()[1]) // 1024 < 4000:
            time.sleep(10)
        con = duckdb.connect(str(db), read_only=True)
        con.execute(f"SET threads={os.cpu_count()}; SET memory_limit='2GB';")
        con.execute(sql).fetchall()  # warm-up
        runs = []
        for _ in range(3):
            t0 = time.perf_counter()
            rows = con.execute(sql).fetchall()
            runs.append((time.perf_counter() - t0) * 1000)
        con.close()
    return statistics.median(runs), len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--level", choices=("high", "med"), required=True)
    ap.add_argument("--sql", type=Path, nargs="+", required=True)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--package", required=True)
    ap.add_argument("--want", type=int, required=True)
    ap.add_argument("--min-fact-rows", type=int, default=100_000)
    ap.add_argument("--min-ms", type=float, default=20.0)
    ap.add_argument("--seed", type=int, required=True, help="recorded in the manifest (the seed the candidate files were drawn with)")
    ap.add_argument("--source", default="fragment_gen", help="where the candidates came from, recorded in the manifest")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    schema, catalog = schema_from_db(args.db), assumption_package(args.package)
    nullable = {(t, c) for t, ta in catalog.tables.items() for c, ca in ta.columns.items() if ca.nullable}
    con = duckdb.connect(str(args.db), read_only=True)
    rows_of = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in schema}
    con.close()
    (args.out / "queries").mkdir(parents=True, exist_ok=True)
    seen: set[tuple] = set()
    kept: list[dict] = []
    funnel: dict[str, int] = {}

    def drop(why: str) -> None:
        funnel[why] = funnel.get(why, 0) + 1

    candidates = [(f"{p.name}:{qid}", sql) for p in args.sql for qid, sql in parse_sql_file(p)]
    for name, sql in candidates:
        if len(kept) >= args.want:
            break
        funnel["candidates"] = funnel.get("candidates", 0) + 1
        level, _ = fragment_level(sql, schema, nullable)
        tables = [t.name.lower() for t in sqlglot.parse_one(sql).find_all(exp.Table)]
        if level != args.level or (args.level == "med" and len(tables) != 2):
            drop("wrong_level")
            continue
        sig = signature(sql)
        if sig in seen:
            drop("near_duplicate")
            continue
        fact = max(rows_of[t] for t in tables)
        if fact < args.min_fact_rows:
            drop("fact_table_too_small")
            continue
        spec, reason = transpile(sql, schema, catalog)
        if spec is None:
            drop("transpile_refused")
            continue
        passed, _ = typecheck(assemble_declarative_program(spec, STUB))
        if not passed:
            drop("typecheck_failed")
            continue
        ms, nrows = timed(args.db, sql.rstrip(";") + ";")
        if ms < args.min_ms:
            drop("duckdb_under_min_ms")
            continue
        seen.add(sig)
        feats = sorted(features(sql))
        kept.append({"file": f"q{len(kept) + 1:03d}.sql", "source": name, "level": level, "tables": tables, "fact_rows": fact, "duckdb_ms": round(ms, 1), "rows_returned": nrows, "transpile": "ok", "typecheck": "ok", "shape": feats})
        (args.out / "queries" / kept[-1]["file"]).write_text(sql.rstrip(";") + ";\n")
        print(f"kept {len(kept)}/{args.want} {ms:.0f} ms {nrows} rows {name}", flush=True)
    (args.out / "manifest.json").write_text(
        json.dumps(
            {**provenance(args.db, args.package, args.level, args.seed, source=args.source,
                          filter={"min_fact_rows": args.min_fact_rows, "min_duckdb_ms": args.min_ms,
                                  "dedupe": "tables, group columns, filter columns, aggregate (kind, column)"}),
             "funnel": funnel, "queries": kept},
            indent=1,
        )
    )
    print(json.dumps({"kept": len(kept), "funnel": funnel}))


if __name__ == "__main__":
    main()
