"""A small TPC-H DuckDB file for differential tests of the declarative emitter.

Rows are a deterministic slice of DuckDB's own ``dbgen`` at SF 0.01 (native types: DECIMAL(15,2), DATE, VARCHAR), plus a
few planted rows that make selective predicates (TPC-H Q19's three disjuncts) hit. Nothing here is engine code.
``None`` from ``build_mini_tpch`` means the DuckDB ``tpch`` extension is not installed (tests then skip).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

# part keys kept; every lineitem of a kept part is kept (Q14, Q19). Customers / orders for Q3 are a separate slice.
PART_MAX = 150
CUSTOMER_MAX = 80

# (partkey, brand, container, size) planted for TPC-H Q19: one part per disjunct plus near misses.
_PLANT_PARTS = [
    (9001, "Brand#12", "SM BOX", 3),
    (9002, "Brand#23", "MED PKG", 7),
    (9003, "Brand#34", "LG CASE", 12),
    (9004, "Brand#12", "LG CASE", 3),  # right brand, wrong container for it
    (9005, "Brand#23", "MED BAG", 11),  # size 11 > 10: outside the second disjunct
]
# (orderkey, partkey, linenumber, quantity, extendedprice, discount, shipmode, shipinstruct)
_PLANT_LINES = [
    (900001, 9001, 1, 5, 1000.50, 0.05, "AIR", "DELIVER IN PERSON"),  # disjunct 1
    (900001, 9001, 2, 11, 999.00, 0.00, "AIR REG", "DELIVER IN PERSON"),  # qty 11 = 1 + 10: still disjunct 1
    (900001, 9001, 3, 12, 500.00, 0.10, "AIR", "DELIVER IN PERSON"),  # qty 12: no disjunct
    (900002, 9002, 1, 15, 2000.25, 0.07, "AIR", "DELIVER IN PERSON"),  # disjunct 2
    (900002, 9002, 2, 15, 2000.25, 0.07, "TRUCK", "DELIVER IN PERSON"),  # wrong ship mode
    (900003, 9003, 1, 25, 3000.75, 0.02, "AIR REG", "DELIVER IN PERSON"),  # disjunct 3
    (900003, 9003, 2, 25, 3000.75, 0.02, "AIR REG", "COLLECT COD"),  # wrong instruction
    (900004, 9004, 1, 5, 700.00, 0.03, "AIR", "DELIVER IN PERSON"),  # wrong container for Brand#12
    (900004, 9005, 2, 12, 800.00, 0.04, "AIR", "DELIVER IN PERSON"),  # size 11 outside disjunct 2
]


def build_mini_tpch(path: Path, kind: str = "part") -> Path | None:
    """Write the mini database to ``path`` and return it, or None when the tpch extension is unavailable.

    ``kind="part"``: ``part`` + its ``lineitem`` rows + the planted Q19 rows (TPC-H Q14, Q19).
    ``kind="customer"``: ``customer`` + their ``orders`` + those orders' ``lineitem`` rows (TPC-H Q3)."""
    src = duckdb.connect()
    try:
        src.execute("INSTALL tpch")
        src.execute("LOAD tpch")
    except duckdb.Error:
        src.close()
        return None
    src.execute("CALL dbgen(sf=0.01)")
    path.unlink(missing_ok=True)
    src.execute(f"ATTACH '{path}' AS mini")
    if kind == "customer":
        src.execute(
            f"CREATE TABLE mini.customer AS SELECT * FROM customer WHERE c_custkey <= {CUSTOMER_MAX} ORDER BY c_custkey"
        )
        src.execute(
            "CREATE TABLE mini.orders AS SELECT * FROM orders WHERE o_custkey IN (SELECT c_custkey FROM mini.customer) "
            "AND o_orderdate < DATE '1995-06-01' ORDER BY o_orderkey"
        )
        src.execute(
            "CREATE TABLE mini.lineitem AS SELECT * FROM lineitem WHERE l_orderkey IN (SELECT o_orderkey FROM mini.orders) "
            "AND l_shipdate > DATE '1995-01-01' ORDER BY l_orderkey, l_linenumber"
        )
        src.close()
        return path
    src.execute(f"CREATE TABLE mini.part AS SELECT * FROM part WHERE p_partkey <= {PART_MAX} ORDER BY p_partkey")
    src.execute(
        f"CREATE TABLE mini.lineitem AS SELECT * FROM lineitem WHERE l_partkey <= {PART_MAX} "
        "ORDER BY l_orderkey, l_linenumber"
    )
    for key, brand, container, size in _PLANT_PARTS:
        src.execute(
            "INSERT INTO mini.part VALUES (?, 'plant', 'm', ?, 'T', ?, ?, 10.00, 'c')", [key, brand, size, container]
        )
    for okey, pkey, line, qty, price, disc, mode, instruct in _PLANT_LINES:
        src.execute(
            "INSERT INTO mini.lineitem VALUES (?, ?, 1, ?, ?, ?, ?, 0.01, 'N', 'O', DATE '1995-09-10', "
            "DATE '1995-09-12', DATE '1995-09-14', ?, ?, 'c')",
            [okey, pkey, line, qty, price, disc, instruct, mode],
        )
    src.close()
    return path
