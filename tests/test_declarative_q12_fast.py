"""TPC-H Q12 fast body (bitset counters + spill map, block-skip scan): the proved body agrees with DuckDB on adversarial data.

The data forces the paths a TPC-H table never reaches: several qualifying lineitem rows per orderkey (the spill map holds the counts beyond the first),
duplicate orders keys (join multiplicity), keys outside the bitset range (negative, >= 2^25, 2^40) and sizes that straddle the 64-row skip block and the 8
workers. Verus only through scripts/ram/verus_guarded.sh (see test_parallel_dict_adversary.run_case).
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from declarative_spec.prompt import _FIXTURES
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions
from tests.test_parallel_dict_adversary import _env, needs_verus, run_case

Q12 = (
    "SELECT l_shipmode, sum(CASE WHEN o_orderpriority = '1-URGENT' OR o_orderpriority = '2-HIGH' THEN 1 ELSE 0 END) AS high_line_count, "
    "sum(CASE WHEN o_orderpriority <> '1-URGENT' AND o_orderpriority <> '2-HIGH' THEN 1 ELSE 0 END) AS low_line_count FROM orders, lineitem "
    "WHERE o_orderkey = l_orderkey AND l_shipmode IN ('MAIL', 'SHIP') AND l_commitdate < l_receiptdate AND l_shipdate < l_commitdate "
    "AND l_receiptdate >= date '1994-01-01' AND l_receiptdate < date '1994-01-01' + interval '1' year GROUP BY l_shipmode ORDER BY l_shipmode"
)
DDL = [
    "CREATE TABLE orders (o_orderkey BIGINT, o_orderpriority VARCHAR)",
    "CREATE TABLE lineitem (l_orderkey BIGINT, l_shipmode VARCHAR, l_commitdate DATE, l_shipdate DATE, l_receiptdate DATE)",
]
SCHEMA = {
    "orders": {"o_orderkey": "BIGINT", "o_orderpriority": "VARCHAR"},
    "lineitem": {
        "l_orderkey": "BIGINT",
        "l_shipmode": "VARCHAR",
        "l_commitdate": "DATE",
        "l_shipdate": "DATE",
        "l_receiptdate": "DATE",
    },
}
KEYS = [-5, 0, 1, 2, 3, 63, 64, 65, 33554431, 33554432, 33554433, 1 << 40]
PRIORITIES = ["1-URGENT", "2-HIGH", "3-MEDIUM", "4-NOT SPECIFIED", "5-LOW"]


def gen(n: int, rng: random.Random) -> dict[str, list[tuple]]:
    pool = KEYS + list(range(4, 12))
    orders = [(rng.choice(pool), rng.choice(PRIORITIES)) for _ in range(n)]
    base = date(1994, 1, 1)
    rows = []
    for _ in range(n):
        receipt = base + timedelta(days=rng.randint(-40, 400))  # some outside 1994
        commit = receipt - timedelta(days=rng.randint(-2, 20))
        ship = commit - timedelta(days=rng.randint(-2, 20))
        rows.append((rng.choice(pool), rng.choice(["MAIL", "SHIP", "AIR", "RAIL"]), commit, ship, receipt))
    return {"orders": orders, "lineitem": rows}


@needs_verus
def test_q12_fast_body_matches_duckdb_on_spill_and_out_of_range_keys(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, True, True)
    text = (_FIXTURES / "hard" / "dict_parallel_q12.rs").read_text()
    cat = CatalogAssumptions(max_rows=1300, tables={"orders": TableAssumptions(max_rows=1300), "lineitem": TableAssumptions(max_rows=1300)})
    sizes = [0, 1, 7, 8, 9, 63, 64, 65, 129, 600, 1300]
    done = run_case(tmp_path, sql=Q12, schema=SCHEMA, catalog=cat, body_text=text, ddl=DDL, gen=gen, sizes=sizes)
    assert done == sizes
