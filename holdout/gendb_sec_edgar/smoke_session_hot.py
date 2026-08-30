#!/usr/bin/env python3
"""GenDB-style session-hot smoke on tiny synthetic SEC-EDGAR DuckDB.

Default (no args): tiny DB, Q1 from queries.sql, plus SMOKE2 join query.
Writes holdout/gendb_sec_edgar/results/smoke_tiny_session_hot.json.

For arbitrary SQL files use session_hot.py (--db, --sql, --out).
"""

from __future__ import annotations

import sys
from pathlib import Path

from session_hot import parse_queries, run_session_hot, write_results

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DB = SCRIPT_DIR / "duckdb" / "sec_edgar_tiny.duckdb"
QUERIES_SQL = SCRIPT_DIR / "queries.sql"
OUT_JSON = SCRIPT_DIR / "results" / "smoke_tiny_session_hot.json"

SMOKE2_SQL = """
SELECT s.form, COUNT(*) AS cnt, SUM(n.value) AS total_value
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD' AND n.value IS NOT NULL
GROUP BY s.form
ORDER BY total_value DESC
""".strip()


def main() -> None:
    if not DEFAULT_DB.is_file():
        print(f"Missing {DEFAULT_DB}; run synth_tiny.py first.", file=sys.stderr)
        raise SystemExit(1)

    queries = parse_queries(QUERIES_SQL)
    if "Q1" not in queries:
        raise ValueError(f"could not parse Q1 from {QUERIES_SQL}")

    query_specs = [
        ("Q1", queries["Q1"]),
        ("SMOKE2", SMOKE2_SQL),
    ]

    results = run_session_hot(DEFAULT_DB, query_specs, synthetic=True)
    write_results(results, OUT_JSON)


if __name__ == "__main__":
    try:
        main()
    except ImportError:
        print("duckdb not installed; run: uv sync --group dev", file=sys.stderr)
        raise
