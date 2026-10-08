"""Parallel DuckDB candidate filtering for generate_queries shuffle."""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import duckdb


def extract_features(sql: str, exec_time_ms: float, row_count: int, col_count: int) -> dict:
    """Extract structural features from a SQL query."""
    sql_upper = sql.upper()

    join_count = len(re.findall(r"\bJOIN\b", sql_upper))

    if exec_time_ms < 100:
        time_bucket = "fast"
    elif exec_time_ms < 1000:
        time_bucket = "medium"
    elif exec_time_ms < 10000:
        time_bucket = "slow"
    else:
        time_bucket = "very_slow"

    if join_count == 0:
        join_bucket = "0_joins"
    elif join_count == 1:
        join_bucket = "1_join"
    elif join_count == 2:
        join_bucket = "2_joins"
    else:
        join_bucket = "3plus_joins"

    tables = set()
    for t in ["sub", "num", "tag", "pre"]:
        if re.search(r"\b" + t + r"\b", sql, re.IGNORECASE):
            tables.add(t)

    features = {
        "join_count": join_count,
        "join_bucket": join_bucket,
        "has_group_by": bool(re.search(r"\bGROUP\s+BY\b", sql_upper)),
        "has_subquery": sql_upper.count("SELECT") > 1,
        "has_order_by": bool(re.search(r"\bORDER\s+BY\b", sql_upper)),
        "has_having": bool(re.search(r"\bHAVING\b", sql_upper)),
        "has_distinct": bool(re.search(r"\bDISTINCT\b", sql_upper)),
        "has_aggregation": bool(re.search(r"\b(COUNT|SUM|AVG|MIN|MAX)\s*\(", sql_upper)),
        "num_tables": len(tables),
        "tables": tables,
        "time_bucket": time_bucket,
        "exec_time_ms": exec_time_ms,
        "row_count": row_count,
        "col_count": col_count,
    }

    feature_set = set()
    feature_set.add(f"time:{time_bucket}")
    feature_set.add(f"joins:{join_bucket}")
    feature_set.add(f"tables:{len(tables)}")
    if features["has_group_by"]:
        feature_set.add("group_by")
    if features["has_subquery"]:
        feature_set.add("subquery")
    if features["has_order_by"]:
        feature_set.add("order_by")
    if features["has_having"]:
        feature_set.add("having")
    if features["has_distinct"]:
        feature_set.add("distinct")
    if features["has_aggregation"]:
        feature_set.add("aggregation")
    for t in tables:
        feature_set.add(f"uses:{t}")

    features["feature_set"] = feature_set
    return features


def resolve_shuffle_filter_workers() -> int:
    """Worker count for parallel DuckDB candidate filtering."""
    env = os.environ.get("LEMMA_SHUFFLE_FILTER_WORKERS")
    if env is not None and env.strip() != "":
        return max(1, int(env))
    return min(os.cpu_count() or 8, 32)


def _filter_one_query(args: tuple[str, str, int]) -> dict:
    """Execute one candidate SQL; each worker opens its own read-only connection."""
    sql, db_path, query_timeout = args
    try:
        con = duckdb.connect(db_path, read_only=True)
        # DuckDB's default memory_limit is ~80% of system RAM: with several workers a draw was OOM-killed under a 4 GB cap.
        con.execute(f"PRAGMA memory_limit='{os.environ.get('LEMMA_FILTER_DUCK_MEMORY', '1GB')}'")
        con.execute('PRAGMA threads=2')
        try:
            start = time.perf_counter()
            result = con.execute(sql)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            elapsed_ms = (time.perf_counter() - start) * 1000
        finally:
            con.close()

        if elapsed_ms > query_timeout * 1000:
            return {"status": "timeout"}

        row_count = len(rows)
        col_count = len(columns)

        if row_count == 0:
            return {"status": "empty"}
        if row_count > 100000:
            return {"status": "too_large"}

        features = extract_features(sql, elapsed_ms, row_count, col_count)
        return {"status": "ok", "sql": sql, "features": features}
    except Exception:
        return {"status": "error"}


def filter_query_candidates(
    unique_queries: list[str],
    db_path: Path,
    query_timeout: int,
    *,
    workers: int | None = None,
) -> tuple[list[tuple[str, dict]], dict[str, int]]:
    """Filter unique queries in parallel; preserve input order for valid candidates."""
    n_workers = workers if workers is not None else resolve_shuffle_filter_workers()
    db_str = str(db_path)
    work = [(sql, db_str, query_timeout) for sql in unique_queries]

    print(
        f"\nFiltering queries in parallel (workers={n_workers}, "
        f"timeout={query_timeout}s per query)..."
    )

    counts = {"errors": 0, "timeouts": 0, "empty": 0, "too_large": 0}
    candidates: list[tuple[str, dict]] = []

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        results = list(executor.map(_filter_one_query, work))

    for i, result in enumerate(results):
        if (i + 1) % 200 == 0:
            print(
                f"  Evaluated {i + 1}/{len(unique_queries)} "
                f"(valid: {len(candidates)}, errors: {counts['errors']}, "
                f"empty: {counts['empty']}, too_large: {counts['too_large']})"
            )

        status = result["status"]
        if status == "ok":
            candidates.append((result["sql"], result["features"]))
        elif status == "error":
            counts["errors"] += 1
        elif status in counts:
            counts[status] += 1

    return candidates, counts
