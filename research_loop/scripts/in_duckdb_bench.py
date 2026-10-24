"""Time the in-DuckDB path (``lemma_query``: scan + copy + checks + proved run_query + rows back) against DuckDB, interleaved.

    LEMMA_IN_DUCKDB=true uv run python -m research_loop.scripts.in_duckdb_bench --db research_loop/generated/tpch_sf1.duckdb \
        --home /path/to/lemma_home (--sql "SELECT ..." [--sql ...] | --all)

Each SQL must already have an executor in ``<home>/executors`` (``research_loop.in_duckdb.install_executor``). Runs as one
heavy phase (no export or proof at the same time). Prints one JSON line per query (``official_measure.measure_in_duckdb``),
plus ``lemma_last_query()`` timings of one extra cold call (input cache emptied first: scan, executor load+checks, run_query, total)
and of the warm call right after it (inputs from the input cache), and ``lemma_cache_stats()``. The measure's top-level medians and
``verdict`` are the cold ones; ``warm`` holds the repeated-call medians.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "db_extension" / "duckdb_ext" / "build" / "release" / "extension" / "lemma" / "lemma.duckdb_extension"


def main() -> None:
    import duckdb

    from declarative_spec.heavy_phase import heavy_phase
    from research_loop import official_measure
    from research_loop.decl_query_measure import duck_settings

    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--sql", action="append", default=[])
    ap.add_argument("--all", action="store_true", help="every executor installed in --home")
    ap.add_argument("--extension", type=Path, default=EXTENSION)
    ap.add_argument("--rounds", type=int, default=None)
    ap.add_argument("--bindings", help="a query template's bindings, JSON list of {name: value}: round i binds bindings[i %% len]")
    args = ap.parse_args()
    bindings = json.loads(args.bindings) if args.bindings else None
    work = Path(tempfile.mkdtemp(prefix="in-duckdb-bench-"))
    sqls = list(args.sql)
    if args.all:
        sqls += [json.loads(m.read_text())["sql"] for m in sorted((args.home / "executors").glob("*/manifest.json"))]
    if not sqls:
        ap.error("give --sql or --all")
    for sql in sqls:
        bar = {"sql": sql, "db_path": str(args.db), "duck_settings": duck_settings(work)}
        if bindings:
            bar["template_bindings"] = bindings
        with heavy_phase("measure"):
            out = official_measure.measure_in_duckdb(bar, work, extension=args.extension, home=args.home, k=args.rounds)
        con = duckdb.connect(str(args.db), read_only=True, config={"allow_unsigned_extensions": "true"})
        con.execute(f"LOAD '{args.extension}'")
        con.execute(f"SET lemma_home = '{args.home}'")
        query = official_measure.lemma_query_sql(sql, bindings[0] if bindings else None)
        names = ("scan", "executor_load_and_checks", "run_query", "total_in_init", "rows", "cache", "cache_bytes")
        last = "SELECT scan_us, load_us, run_us, total_us, rows, cache, cache_bytes FROM lemma_last_query()"
        con.execute(official_measure.CLEAR_CACHE_SQL).fetchall()
        con.execute(query).fetchall()  # cold: the input cache is empty, the inputs are scanned (and stored)
        cold = con.execute(last).fetchone()
        con.execute(query).fetchall()  # warm: the same call again, inputs from the cache
        warm = con.execute(last).fetchone()
        cur = con.execute("SELECT * FROM lemma_cache_stats()")
        stats = dict(zip((d[0] for d in cur.description), cur.fetchone(), strict=True))
        con.close()
        out["split_us"] = dict(zip(names, cold, strict=True))  # the cold call ("scan" = scan + store into the cache)
        out["split_us_warm"] = dict(zip(names, warm, strict=True))  # "scan" = plan + copy of the cached inputs
        out["cache_stats"] = stats
        out["sql"] = sql
        print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
