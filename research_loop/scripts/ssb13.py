"""The 13 standard SSB queries (comma-join form) on the SF1 DuckDB through the declarative path.

    uv run python research_loop/scripts/ssb13.py emit [--tc] [--only ssb_q1_1,ssb_q2_1]

Transpile each (and with ``--tc`` Verus ``--no-verify`` typecheck through the memory guard).
Database research_loop/generated/ssb_sf1.duckdb, package ``ssb_sf1`` (registry), queries in
research_loop/generated/arena/rounds/ssb13/queries/ (written by ssb13_write_queries.py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research_loop" / "scripts"))

DB = ROOT / "research_loop" / "generated" / "ssb_sf1.duckdb"
QDIR = ROOT / "research_loop" / "generated" / "arena" / "rounds" / "ssb13" / "queries"


def main() -> None:
    import duckdb
    from decl_coverage import typecheck
    from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
    from declarative_spec.lemmas import FitRefusal
    from research_loop.assumption_packages import assumption_package

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["emit"])
    ap.add_argument("--tc", action="store_true")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    con = duckdb.connect(str(DB), read_only=True)
    schema = {t: {r[0]: r[1].lower() for r in con.execute(f"describe {t}").fetchall()} for (t,) in con.execute("show tables").fetchall()}
    con.close()
    catalog = assumption_package("ssb_sf1")
    only = set(args.only.split(",")) if args.only else None
    for path in sorted(QDIR.glob("ssb_q*.sql")):
        if only and path.stem not in only:
            continue
        sql = path.read_text().strip()
        try:
            spec = emit_declarative_spec(sql, schema, catalog)
        except (DeclarativeUnsupported, FitRefusal) as exc:
            print(f"{path.stem} REFUSED {type(exc).__name__}: {' '.join(str(exc).split())[:300]}", flush=True)
            continue
        except Exception as exc:  # noqa: BLE001  report a crash loudly
            print(f"{path.stem} CRASH {type(exc).__name__}: {' '.join(str(exc).split())[:300]}", flush=True)
            continue
        if args.tc:
            print(f"{path.stem} emitted typecheck={typecheck(spec)[:400]}", flush=True)
        else:
            print(f"{path.stem} emitted", flush=True)


if __name__ == "__main__":
    main()
