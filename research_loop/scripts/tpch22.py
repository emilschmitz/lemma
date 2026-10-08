"""The 22 TPC-H queries as written, on the SF1 DuckDB, through the declarative path.

    uv run python research_loop/scripts/tpch22.py setup   # save queries + manifest, time each in DuckDB (run under scripts/ram/heavy.sh)
    uv run python research_loop/scripts/tpch22.py emit [--tc] [--only 3,5]   # transpile (and Verus --no-verify typecheck) each

Database research_loop/generated/tpch_sf1.duckdb, package ``tpch_sf1`` (registry), queries in
research_loop/generated/arena/rounds/tpch22/queries/q01..q22.sql.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research_loop" / "scripts"))

DB = ROOT / "research_loop" / "generated" / "tpch_sf1.duckdb"
PACKAGE = "tpch_sf1"
OUT = ROOT / "research_loop" / "generated" / "arena" / "rounds" / "tpch22"
QDIR = OUT / "queries"


def setup() -> None:
    import duckdb

    QDIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB), read_only=True)
    con.execute("LOAD tpch")
    con.execute("SET memory_limit='3GB'")
    con.execute("SET threads=8")
    qs = con.execute("select query_nr, query from tpch_queries() order by query_nr").fetchall()
    timings = {}
    for nr, q in qs:
        path = QDIR / f"q{nr:02d}.sql"
        path.write_text(q.strip().rstrip(";") + "\n")
        sql = path.read_text()
        con.execute(sql).fetchall()  # warm
        t0 = time.perf_counter()
        rows = len(con.execute(sql).fetchall())
        timings[f"q{nr:02d}"] = {"rows": rows, "hot_ms": round((time.perf_counter() - t0) * 1000, 1)}
    manifest = {
        "scale_factor": 1,
        "duckdb_version": duckdb.__version__,
        "db": str(DB.relative_to(ROOT)),
        "package": PACKAGE,
        "git_sha": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip(),
        "query_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:16] for p in sorted(QDIR.glob("q*.sql"))},
        "timing": "1 warm run, threads=8, memory_limit=3GB",
        "queries": timings,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    for k, v in timings.items():
        print(k, v)


def schema_and_catalog():
    import duckdb
    from research_loop.assumption_packages import assumption_package

    con = duckdb.connect(str(DB), read_only=True)
    schema = {
        t: {r[0]: r[1].lower() for r in con.execute(f"describe {t}").fetchall()}
        for (t,) in con.execute("show tables").fetchall()
    }
    con.close()
    return schema, assumption_package(PACKAGE)


def emit(args) -> None:
    from decl_coverage import typecheck as _typecheck
    from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
    from declarative_spec.lemmas import FitRefusal

    schema, catalog = schema_and_catalog()
    for claim in args.unique:  # a user-approved unique key the package does not carry (table.column)
        table, column = claim.split(".")
        ta = catalog.tables[table]
        catalog = dataclasses.replace(
            catalog,
            tables={**catalog.tables, table: dataclasses.replace(ta, unique_keys=(*ta.unique_keys, (column,)))},
        )
    only = {int(x) for x in args.only.split(",")} if args.only else set(range(1, 23))
    ok = 0
    for nr in sorted(only):
        sql = (QDIR / f"q{nr:02d}.sql").read_text().strip()
        try:
            spec = emit_declarative_spec(sql, schema, catalog)
        except (DeclarativeUnsupported, FitRefusal) as exc:
            print(f"q{nr:02d} REFUSED {type(exc).__name__}: {' '.join(str(exc).split())[:300]}", flush=True)
            continue
        except Exception as exc:  # noqa: BLE001  report a crash loudly
            print(f"q{nr:02d} CRASH {type(exc).__name__}: {' '.join(str(exc).split())[:300]}", flush=True)
            continue
        if args.tc:
            verdict = _typecheck(spec)
            print(f"q{nr:02d} emitted typecheck={verdict[:400]}", flush=True)
            ok += verdict == "OK"
        else:
            print(f"q{nr:02d} emitted", flush=True)
            ok += 1
    print(f"{ok}/{len(only)} {'emit+typecheck' if args.tc else 'emit'}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["setup", "emit"])
    p.add_argument("--tc", action="store_true")
    p.add_argument("--only", default="")
    p.add_argument("--unique", action="append", default=[], help="claim table.column as a unique key (Q15: supplier.s_suppkey)")
    args = p.parse_args()
    setup() if args.cmd == "setup" else emit(args)


if __name__ == "__main__":
    main()
