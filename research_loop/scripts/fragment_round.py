"""Save a drawn query file as an arena round: ``queries/q001.sql ...`` and ``manifest.json``.

    uv run python -m research_loop.scripts.fragment_round draw.sql --seed 4242 --level full --db DB --package PKG --out ROUND_DIR

The manifest records the seed, level, database, package, git sha and, per query, the grammar level, transpile status and
the constructs it uses. No query is chosen or dropped here; the funnel (transpile, typecheck) is reported next to it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_loop.scripts.fragment_coverage import funnel, run
from research_loop.scripts.fragment_gen import provenance
from research_loop.scripts.sqlsmith_trusted_coverage import parse_sql_file


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("draw", type=Path)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--level", required=True)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--package", required=True)
    ap.add_argument("--typecheck", type=int, default=0, help="how many transpiled queries to Verus-typecheck (--no-verify)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    queries = parse_sql_file(args.draw)
    (args.out / "queries").mkdir(parents=True, exist_ok=True)
    for i, (_qid, sql) in enumerate(queries, 1):
        (args.out / "queries" / f"q{i:03d}.sql").write_text(sql.rstrip(";") + ";\n")
    rows = run(queries, args.db, args.package, args.typecheck)
    (args.out / "manifest.json").write_text(
        json.dumps(
            {**provenance(args.db, args.package, args.level, args.seed, n=len(queries)),
             "funnel": funnel(rows).splitlines(),
             "queries": [{"file": f"q{i:03d}.sql", **{k: r[k] for k in ("level", "transpile", "reason", "typecheck", "features") if k in r}} for i, r in enumerate(rows, 1)]},
            indent=1,
        )
    )
    print(funnel(rows))


if __name__ == "__main__":
    main()
