#!/usr/bin/env python3
"""DuckDB baselines for standin TPC-H SQL on SF1 lineitem (same box as Verus standins)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb

ROOT = Path.home() / "lemma"
LOG = Path.home() / "phase1_logs"
LI = ROOT / "data/tpch-sf1/lineitem.tbl"
OUT = LOG / "duckdb_sf1_standin_ref.json"
WARMUPS, RUNS = 2, 5

QUERIES = {
    "Q1": """SELECT l_returnflag, l_linestatus, SUM(l_quantity) AS sum_qty
FROM lineitem WHERE l_shipdate <= 19980902
GROUP BY l_returnflag, l_linestatus""",
    "Q6": """SELECT SUM(l_extendedprice * l_discount) AS revenue
FROM lineitem
WHERE l_quantity >= 1 AND l_quantity <= 50
  AND l_discount >= 1 AND l_discount <= 5
  AND l_shipdate >= 19960101 AND l_shipdate <= 19961231""",
}


def main() -> None:
    LOG.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("PRAGMA threads=1")
    con.execute(
        f"""
        CREATE TABLE lineitem AS
        SELECT * FROM read_csv(
          '{LI}',
          delim='|',
          header=true,
          auto_detect=true
        )
        """
    )
    n = con.execute("SELECT count(*) FROM lineitem").fetchone()[0]
    results: dict = {"scale": "sf1", "rows": n, "threads": 1, "queries": {}}
    for name, sql in QUERIES.items():
        for _ in range(WARMUPS):
            con.execute(sql).fetchall()
        times: list[float] = []
        rows = None
        for _ in range(RUNS):
            t0 = time.perf_counter()
            rows = con.execute(sql).fetchall()
            times.append((time.perf_counter() - t0) * 1e6)
        times.sort()
        med = times[len(times) // 2]
        results["queries"][name] = {
            "median_us": med,
            "median_ms": med / 1000,
            "times_us": times,
            "nrows": len(rows or []),
        }
        print(f"{name}\t{med:.0f}us\t{med / 1000:.3f}ms\tnrows={len(rows or [])}")
    OUT.write_text(json.dumps(results, indent=2) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
