"""Declarative emission coverage of a SQL file on the DOUBLE and the DECIMAL SEC schema.

    uv run python -m research_loop.scripts.decl_coverage research_loop/generated/decl_coverage/dec_N.sql

Each query goes through ``emit_declarative_spec`` with the ``sec_margin`` package (DOUBLE schema)
and the ``sec_margin_dec`` package (DECIMAL schema). Emission only: no Verus. Prints emit counts
and the ranked refusal reasons per variant, and writes ``<sql>.coverage.json``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from declarative_spec.emit import emit_declarative_spec
from research_loop.assumption_packages import assumption_package
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema, parse_sql_file

_DEC_DB = ROOT / "holdout" / "gendb_sec_edgar" / "duckdb" / "sec_edgar_local_dec.duckdb"
# The f64 error lemma needs an epsilon; the draws use this one.
FLOAT_ABS_EPS = "1e20"


def reason_class(exc: Exception) -> str:
    """Refusal text with its numbers and names folded away, so equal reasons count together."""
    text = f"{type(exc).__name__}: {exc}".splitlines()[0]
    text = re.sub(r"'[^']*'", "'_'", text)
    return re.sub(r"\d+", "N", text)[:140]


def coverage(queries: list[tuple[str, str]], schema: dict, package: str) -> tuple[list[str], Counter]:
    catalog = assumption_package(package)
    emitted: list[str] = []
    refused: Counter = Counter()
    for qid, sql in queries:
        try:
            emit_declarative_spec(sql, schema, catalog, float_abs_eps=FLOAT_ABS_EPS)
        except Exception as exc:  # every refusal kind is counted by its message
            refused[reason_class(exc)] += 1
        else:
            emitted.append(qid)
    return emitted, refused


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sql", type=Path)
    ap.add_argument("--dec-db", type=Path, default=_DEC_DB)
    args = ap.parse_args()
    queries = parse_sql_file(args.sql)
    report = {}
    for name, schema, package in (
        ("double", load_sec_schema(), "sec_margin"),
        ("decimal", load_sec_schema(args.dec_db), "sec_margin_dec"),
    ):
        emitted, refused = coverage(queries, schema, package)
        report[name] = {"total": len(queries), "emitted": len(emitted), "emitted_ids": emitted, "refusals": refused.most_common()}
        print(f"{name}: emitted {len(emitted)} / {len(queries)}")
        for reason, n in refused.most_common():
            print(f"  {n:4d}  {reason}")
    args.sql.with_suffix(".coverage.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
