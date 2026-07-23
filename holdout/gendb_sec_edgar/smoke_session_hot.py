#!/usr/bin/env python3
"""GenDB-style session-hot smoke on tiny synthetic SEC-EDGAR DuckDB.

Protocol (one process, DB open once):
  1. Open DB → OPEN_US (diagnostic)
  2. Per query: cold run → COLD_QUERY_US; 2 untimed warmups; median of 5 → SESSION_HOT_US
Engine: DuckDB SQL baseline only (Lemma skipped — join queries not in scope).
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DB = SCRIPT_DIR / "duckdb" / "sec_edgar_tiny.duckdb"
QUERIES_SQL = SCRIPT_DIR / "queries.sql"
OUT_JSON = SCRIPT_DIR / "results" / "smoke_tiny_session_hot.json"

PROTOCOL = (
    "one process; open once; per query: cold query; 2 untimed warmups; "
    "median of 5 timed queries → SESSION_HOT_US (primary, GenDB-comparable); "
    "QUERY_US = SESSION_HOT_US"
)

SMOKE2_SQL = """
SELECT s.form, COUNT(*) AS cnt, SUM(n.value) AS total_value
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD' AND n.value IS NOT NULL
GROUP BY s.form
ORDER BY total_value DESC
""".strip()


def extract_q1(queries_path: Path) -> str:
    text = queries_path.read_text()
    m = re.search(
        r"-- Q1:.*?(\nSELECT[\s\S]*?;\n)(?=\n-- Q2:)",
        text,
        flags=re.MULTILINE,
    )
    if not m:
        raise ValueError(f"could not parse Q1 from {queries_path}")
    return m.group(1).strip()


def result_fingerprint(rows: list[tuple], columns: list[str]) -> dict[str, object]:
    payload = json.dumps([list(r) for r in rows], sort_keys=False, default=str)
    return {
        "columns": columns,
        "row_count": len(rows),
        "checksum_sha256": hashlib.sha256(payload.encode()).hexdigest(),
        "preview": [dict(zip(columns, row, strict=True)) for row in rows[:3]],
    }


def timed_query(con: duckdb.DuckDBPyConnection, sql: str) -> tuple[list[tuple], list[str], int]:
    t0 = time.perf_counter()
    cur = con.execute(sql)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    elapsed_us = int((time.perf_counter() - t0) * 1_000_000)
    return rows, cols, elapsed_us


def run_query_protocol(
    con: duckdb.DuckDBPyConnection, sql: str
) -> tuple[dict[str, int], dict[str, object]]:
    _, _, cold_us = timed_query(con, sql)
    for _ in range(2):
        timed_query(con, sql)
    samples: list[int] = []
    last_rows: list[tuple] = []
    last_cols: list[str] = []
    for _ in range(5):
        last_rows, last_cols, us = timed_query(con, sql)
        samples.append(us)
    session_hot_us = int(statistics.median(samples))
    metrics = {
        "COLD_QUERY_US": cold_us,
        "SESSION_HOT_US": session_hot_us,
        "QUERY_US": session_hot_us,
        "timed_samples_us": samples,
    }
    return metrics, result_fingerprint(last_rows, last_cols)


def table_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in ["sub", "pre", "num", "tag"]:
        counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return counts


def main() -> None:
    db_path = DEFAULT_DB
    if not db_path.is_file():
        print(f"Missing {db_path}; run synth_tiny.py first.", file=sys.stderr)
        raise SystemExit(1)

    q1_sql = extract_q1(QUERIES_SQL)
    query_specs = [
        ("Q1", q1_sql),
        ("SMOKE2", SMOKE2_SQL),
    ]

    t_open = time.perf_counter()
    con = duckdb.connect(str(db_path), read_only=True)
    open_us = int((time.perf_counter() - t_open) * 1_000_000)
    row_counts = table_counts(con)

    print(f"ENGINE: duckdb_sql")
    print(f"DB: {db_path}")
    print(f"OPEN_US: {open_us}")
    print(f"PROTOCOL: {PROTOCOL}")

    results: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol": PROTOCOL,
        "engine": "duckdb_sql",
        "lemma": "not_run_complex_sql",
        "data": {
            "synthetic": True,
            "duckdb_path": str(db_path),
            "row_counts": row_counts,
        },
        "OPEN_US": open_us,
        "queries": {},
    }

    queries_out: dict[str, object] = {}
    for label, sql in query_specs:
        metrics, fingerprint = run_query_protocol(con, sql)
        block = {
            "sql": sql,
            **metrics,
            "result": fingerprint,
        }
        queries_out[label] = block
        print(
            f"{label}: COLD={metrics['COLD_QUERY_US']}µs "
            f"SESSION_HOT={metrics['SESSION_HOT_US']}µs "
            f"rows={fingerprint['row_count']}"
        )

    con.close()
    results["queries"] = queries_out

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(results, indent=2) + "\n")
    print(f"Wrote {OUT_JSON}")


if __name__ == "__main__":
    try:
        main()
    except ImportError:
        print("duckdb not installed; run: uv sync --group dev", file=sys.stderr)
        raise
