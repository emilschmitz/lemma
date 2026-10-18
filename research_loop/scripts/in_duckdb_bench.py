"""Time the in-DuckDB path (``lemma_query``: scan + copy + checks + proved run_query + rows back) against DuckDB, interleaved.

    LEMMA_IN_DUCKDB=true uv run python -m research_loop.scripts.in_duckdb_bench --db research_loop/generated/tpch_sf1.duckdb \
        --home /path/to/lemma_home (--sql "SELECT ..." [--sql ...] | --all)

Each SQL must already have an executor in ``<home>/executors`` (``research_loop.in_duckdb.install_executor``). Runs as one
heavy phase (no export or proof at the same time). Prints one JSON line per query (``official_measure.measure_in_duckdb``),
plus ``lemma_last_query()`` timings of one extra call (scan, executor load+checks, run_query, total).
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
    args = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="in-duckdb-bench-"))
    sqls = list(args.sql)
    if args.all:
        sqls += [json.loads(m.read_text())["sql"] for m in sorted((args.home / "executors").glob("*/manifest.json"))]
    if not sqls:
        ap.error("give --sql or --all")
    for sql in sqls:
        bar = {"sql": sql, "db_path": str(args.db), "duck_settings": duck_settings(work)}
        with heavy_phase("measure"):
            out = official_measure.measure_in_duckdb(bar, work, extension=args.extension, home=args.home, k=args.rounds)
        con = duckdb.connect(str(args.db), read_only=True, config={"allow_unsigned_extensions": "true"})
        con.execute(f"LOAD '{args.extension}'")
        con.execute(f"SET lemma_home = '{args.home}'")
        con.execute(official_measure.lemma_query_sql(sql)).fetchall()
        split = con.execute("SELECT scan_us, load_us, run_us, total_us, rows FROM lemma_last_query()").fetchone()
        con.close()
        out["split_us"] = dict(zip(("scan", "executor_load_and_checks", "run_query", "total_in_init", "rows"), split, strict=True))
        out["sql"] = sql
        print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
