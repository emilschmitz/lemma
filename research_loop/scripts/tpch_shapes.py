"""Official TPC-H query texts (default substitution parameters) and an emit-coverage report for the declarative path.

``tpch_shapes.py [--db research_loop/generated/tpch_sf3.duckdb] [--dict]``: for every query print whether ``emit_declarative_spec`` accepts it
(under the active LEMMA_* environment) or the refusal reason, so the shapes that can be proved are known before a prover is launched.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QUERIES: dict[str, str] = {
    "Q1": """SELECT l_returnflag, l_linestatus, sum(l_quantity) AS sum_qty, sum(l_extendedprice) AS sum_base_price,
sum(l_extendedprice * (1 - l_discount)) AS sum_disc_price, sum(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge,
count(*) AS count_order FROM lineitem WHERE l_shipdate <= date '1998-12-01' - interval '90' day
GROUP BY l_returnflag, l_linestatus ORDER BY l_returnflag, l_linestatus""",
    "Q3": """SELECT l_orderkey, sum(l_extendedprice * (1 - l_discount)) AS revenue, o_orderdate, o_shippriority
FROM customer, orders, lineitem WHERE c_mktsegment = 'BUILDING' AND c_custkey = o_custkey AND l_orderkey = o_orderkey
AND o_orderdate < date '1995-03-15' AND l_shipdate > date '1995-03-15'
GROUP BY l_orderkey, o_orderdate, o_shippriority ORDER BY revenue DESC, o_orderdate LIMIT 10""",
    "Q4": """SELECT o_orderpriority, count(*) AS order_count FROM orders WHERE o_orderdate >= date '1993-07-01'
AND o_orderdate < date '1993-07-01' + interval '3' month AND EXISTS (SELECT * FROM lineitem WHERE l_orderkey = o_orderkey AND l_commitdate < l_receiptdate)
GROUP BY o_orderpriority ORDER BY o_orderpriority""",
    "Q6": """SELECT sum(l_extendedprice * l_discount) AS revenue FROM lineitem WHERE l_shipdate >= date '1994-01-01'
AND l_shipdate < date '1994-01-01' + interval '1' year AND l_discount BETWEEN 0.06 - 0.01 AND 0.06 + 0.01 AND l_quantity < 24""",
    "Q12": """SELECT l_shipmode, sum(CASE WHEN o_orderpriority = '1-URGENT' OR o_orderpriority = '2-HIGH' THEN 1 ELSE 0 END) AS high_line_count,
sum(CASE WHEN o_orderpriority <> '1-URGENT' AND o_orderpriority <> '2-HIGH' THEN 1 ELSE 0 END) AS low_line_count
FROM orders, lineitem WHERE o_orderkey = l_orderkey AND l_shipmode IN ('MAIL', 'SHIP') AND l_commitdate < l_receiptdate AND l_shipdate < l_commitdate
AND l_receiptdate >= date '1994-01-01' AND l_receiptdate < date '1994-01-01' + interval '1' year GROUP BY l_shipmode ORDER BY l_shipmode""",
    "Q14": """SELECT 100.00 * sum(CASE WHEN p_type LIKE 'PROMO%' THEN l_extendedprice * (1 - l_discount) ELSE 0 END) / sum(l_extendedprice * (1 - l_discount)) AS promo_revenue
FROM lineitem, part WHERE l_partkey = p_partkey AND l_shipdate >= date '1995-09-01' AND l_shipdate < date '1995-09-01' + interval '1' month""",
    "Q18": """SELECT c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice, sum(l_quantity) FROM customer, orders, lineitem
WHERE o_orderkey IN (SELECT l_orderkey FROM lineitem GROUP BY l_orderkey HAVING sum(l_quantity) > 300) AND c_custkey = o_custkey AND o_orderkey = l_orderkey
GROUP BY c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice ORDER BY o_totalprice DESC, o_orderdate LIMIT 100""",
    "Q19": """SELECT sum(l_extendedprice * (1 - l_discount)) AS revenue FROM lineitem, part WHERE
(p_partkey = l_partkey AND p_brand = 'Brand#12' AND p_container IN ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG') AND l_quantity >= 1 AND l_quantity <= 1 + 10
AND p_size BETWEEN 1 AND 5 AND l_shipmode IN ('AIR', 'AIR REG') AND l_shipinstruct = 'DELIVER IN PERSON')
OR (p_partkey = l_partkey AND p_brand = 'Brand#23' AND p_container IN ('MED BAG', 'MED BOX', 'MED PKG', 'MED PACK') AND l_quantity >= 10 AND l_quantity <= 10 + 10
AND p_size BETWEEN 1 AND 10 AND l_shipmode IN ('AIR', 'AIR REG') AND l_shipinstruct = 'DELIVER IN PERSON')""",
}


def coverage(db: Path) -> dict[str, str]:
    from declarative_spec.emit import emit_declarative_spec
    from research_loop.scripts.declarative_round import tpch_schema_and_catalog

    schema, catalog = tpch_schema_and_catalog(db)
    out: dict[str, str] = {}
    for name, sql in QUERIES.items():
        try:
            emit_declarative_spec(" ".join(sql.split()), schema, catalog)
            out[name] = "emits"
        except Exception as exc:  # noqa: BLE001 - the report names every refusal and crash with its message
            out[name] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(ROOT / "research_loop" / "generated" / "tpch_sf1.duckdb"))
    a = ap.parse_args()
    if not Path(a.db).is_file():
        raise SystemExit(f"TPC-H database missing at {a.db}")
    print(f"env: LEMMA_STRING_ENCODING={os.environ.get('LEMMA_STRING_ENCODING', 'plain')} LEMMA_PARALLEL_VSTD={os.environ.get('LEMMA_PARALLEL_VSTD', '')}")
    for name, result in coverage(Path(a.db)).items():
        print(f"{name}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
