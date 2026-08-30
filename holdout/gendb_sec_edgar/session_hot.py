#!/usr/bin/env python3
"""GenDB-style session-hot DuckDB SQL baseline.

Protocol (one process, DB open once):
  1. Open DB → OPEN_US (diagnostic)
  2. Per query: cold run → COLD_QUERY_US; 2 untimed warmups; median of 5 → SESSION_HOT_US

Engine: DuckDB SQL only (Lemma native SESSION_HOT_US not measured here).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb

SCRIPT_DIR = Path(__file__).resolve().parent

PROTOCOL = (
    "one process; open once; per query: cold query; 2 untimed warmups; "
    "median of 5 timed queries → SESSION_HOT_US (primary, GenDB-comparable); "
    "QUERY_US = SESSION_HOT_US"
)


def parse_queries(queries_path: Path) -> dict[str, str]:
    """Parse a SQL file into {Q<id>: sql} using `-- QN:` comment headers."""
    content = queries_path.read_text()
    queries: dict[str, str] = {}
    parts = re.split(r"--\s*(Q\d+):\s*([^\n]*)\n", content)
    i = 1
    while i + 2 <= len(parts):
        name = parts[i].strip()
        sql = parts[i + 2].strip()
        sql = re.sub(r"--[^\n]*$", "", sql, flags=re.MULTILINE).strip()
        sql = sql.rstrip(";").strip()
        if sql:
            queries[name] = sql
        i += 3
    return queries


def detect_synthetic(db_path: Path, synthetic_flag: bool | None) -> bool:
    if synthetic_flag is not None:
        return synthetic_flag
    if "tiny" in str(db_path).lower():
        return True
    env = os.environ.get("LEMMA_SESSION_HOT_SYNTHETIC", "")
    return env.lower() in ("1", "true", "yes")


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
) -> tuple[dict[str, int | list[int]], dict[str, object]]:
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
    metrics: dict[str, int | list[int]] = {
        "COLD_QUERY_US": cold_us,
        "SESSION_HOT_US": session_hot_us,
        "QUERY_US": session_hot_us,
        "timed_samples_us": samples,
    }
    return metrics, result_fingerprint(last_rows, last_cols)


def table_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in ["sub", "pre", "num", "tag"]:
        row = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_name = ?",
            [table],
        ).fetchone()
        if row and row[0]:
            count_row = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            if count_row is not None:
                counts[table] = count_row[0]
    return counts


def run_session_hot(
    db_path: Path,
    query_specs: list[tuple[str, str]],
    *,
    synthetic: bool | None = None,
    hardware_hint: str | None = None,
    lemma_note: str = "not_run_complex_sql",
) -> dict[str, object]:
    if not db_path.is_file():
        raise FileNotFoundError(f"database not found: {db_path}")

    t_open = time.perf_counter()
    con = duckdb.connect(str(db_path), read_only=True)
    open_us = int((time.perf_counter() - t_open) * 1_000_000)
    row_counts = table_counts(con)

    print("ENGINE: duckdb_sql")
    print(f"DB: {db_path}")
    print(f"OPEN_US: {open_us}")
    print(f"PROTOCOL: {PROTOCOL}")

    results: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol": PROTOCOL,
        "engine": "duckdb_sql",
        "lemma": lemma_note,
        "data": {
            "synthetic": detect_synthetic(db_path, synthetic),
            "duckdb_path": str(db_path),
            "row_counts": row_counts,
        },
        "OPEN_US": open_us,
        "queries": {},
    }
    if hardware_hint:
        results["hardware_hint"] = hardware_hint

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
    return results


def write_results(results: dict[str, object], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2) + "\n")
    print(f"Wrote {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="GenDB-style session-hot DuckDB baseline")
    parser.add_argument(
        "--db",
        type=Path,
        default=SCRIPT_DIR / "duckdb" / "sec_edgar_tiny.duckdb",
        help="Path to DuckDB database",
    )
    parser.add_argument(
        "--sql",
        type=Path,
        default=SCRIPT_DIR / "queries.sql",
        help="SQL file with -- QN: labeled queries",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=SCRIPT_DIR / "results" / "session_hot.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        default=None,
        help="Mark run as synthetic (default: auto from path or env)",
    )
    parser.add_argument(
        "--not-synthetic",
        action="store_true",
        help="Mark run as non-synthetic full SEC",
    )
    parser.add_argument(
        "--hardware-hint",
        type=str,
        default=None,
        help="Optional hardware description for JSON metadata",
    )
    args = parser.parse_args()

    if not args.sql.is_file():
        print(f"Missing SQL file: {args.sql}", file=sys.stderr)
        raise SystemExit(1)

    queries = parse_queries(args.sql)
    if not queries:
        print(f"No -- QN: queries found in {args.sql}", file=sys.stderr)
        raise SystemExit(1)

    query_specs = sorted(queries.items(), key=lambda item: int(item[0][1:]))
    print(f"Queries: {', '.join(label for label, _ in query_specs)}")

    synthetic_flag: bool | None = None
    if args.synthetic:
        synthetic_flag = True
    elif args.not_synthetic:
        synthetic_flag = False

    try:
        results = run_session_hot(
            args.db,
            query_specs,
            synthetic=synthetic_flag,
            hardware_hint=args.hardware_hint,
        )
        write_results(results, args.out)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    try:
        main()
    except ImportError:
        print("duckdb not installed; run: uv sync --group dev", file=sys.stderr)
        raise
