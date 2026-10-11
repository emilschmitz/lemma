"""Write the 13 standard SSB queries (O'Neil et al., comma-join form) and time them in DuckDB."""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import duckdb

Q = {
"ssb_q1_1": """select sum(lo_extendedprice*lo_discount) as revenue
from lineorder, date
where lo_orderdate = d_datekey and d_year = 1993 and lo_discount between 1 and 3 and lo_quantity < 25""",
"ssb_q1_2": """select sum(lo_extendedprice*lo_discount) as revenue
from lineorder, date
where lo_orderdate = d_datekey and d_yearmonthnum = 199401 and lo_discount between 4 and 6 and lo_quantity between 26 and 35""",
"ssb_q1_3": """select sum(lo_extendedprice*lo_discount) as revenue
from lineorder, date
where lo_orderdate = d_datekey and d_weeknuminyear = 6 and d_year = 1994 and lo_discount between 5 and 7 and lo_quantity between 26 and 35""",
"ssb_q2_1": """select sum(lo_revenue), d_year, p_brand1
from lineorder, date, part, supplier
where lo_orderdate = d_datekey and lo_partkey = p_partkey and lo_suppkey = s_suppkey and p_category = 'MFGR#12' and s_region = 'AMERICA'
group by d_year, p_brand1
order by d_year, p_brand1""",
"ssb_q2_2": """select sum(lo_revenue), d_year, p_brand1
from lineorder, date, part, supplier
where lo_orderdate = d_datekey and lo_partkey = p_partkey and lo_suppkey = s_suppkey and p_brand1 between 'MFGR#2221' and 'MFGR#2228' and s_region = 'ASIA'
group by d_year, p_brand1
order by d_year, p_brand1""",
"ssb_q2_3": """select sum(lo_revenue), d_year, p_brand1
from lineorder, date, part, supplier
where lo_orderdate = d_datekey and lo_partkey = p_partkey and lo_suppkey = s_suppkey and p_brand1 = 'MFGR#2239' and s_region = 'EUROPE'
group by d_year, p_brand1
order by d_year, p_brand1""",
"ssb_q3_1": """select c_nation, s_nation, d_year, sum(lo_revenue) as revenue
from customer, lineorder, supplier, date
where lo_custkey = c_custkey and lo_suppkey = s_suppkey and lo_orderdate = d_datekey and c_region = 'ASIA' and s_region = 'ASIA' and d_year >= 1992 and d_year <= 1997
group by c_nation, s_nation, d_year
order by d_year asc, revenue desc""",
"ssb_q3_2": """select c_city, s_city, d_year, sum(lo_revenue) as revenue
from customer, lineorder, supplier, date
where lo_custkey = c_custkey and lo_suppkey = s_suppkey and lo_orderdate = d_datekey and c_nation = 'UNITED STATES' and s_nation = 'UNITED STATES' and d_year >= 1992 and d_year <= 1997
group by c_city, s_city, d_year
order by d_year asc, revenue desc""",
"ssb_q3_3": """select c_city, s_city, d_year, sum(lo_revenue) as revenue
from customer, lineorder, supplier, date
where lo_custkey = c_custkey and lo_suppkey = s_suppkey and lo_orderdate = d_datekey and (c_city = 'UNITED KI1' or c_city = 'UNITED KI5') and (s_city = 'UNITED KI1' or s_city = 'UNITED KI5') and d_year >= 1992 and d_year <= 1997
group by c_city, s_city, d_year
order by d_year asc, revenue desc""",
"ssb_q3_4": """select c_city, s_city, d_year, sum(lo_revenue) as revenue
from customer, lineorder, supplier, date
where lo_custkey = c_custkey and lo_suppkey = s_suppkey and lo_orderdate = d_datekey and (c_city = 'UNITED KI1' or c_city = 'UNITED KI5') and (s_city = 'UNITED KI1' or s_city = 'UNITED KI5') and d_yearmonth = 'Dec1997'
group by c_city, s_city, d_year
order by d_year asc, revenue desc""",
"ssb_q4_1": """select d_year, c_nation, sum(lo_revenue - lo_supplycost) as profit
from date, customer, supplier, part, lineorder
where lo_custkey = c_custkey and lo_suppkey = s_suppkey and lo_partkey = p_partkey and lo_orderdate = d_datekey and c_region = 'AMERICA' and s_region = 'AMERICA' and (p_mfgr = 'MFGR#1' or p_mfgr = 'MFGR#2')
group by d_year, c_nation
order by d_year, c_nation""",
"ssb_q4_2": """select d_year, s_nation, p_category, sum(lo_revenue - lo_supplycost) as profit
from date, customer, supplier, part, lineorder
where lo_custkey = c_custkey and lo_suppkey = s_suppkey and lo_partkey = p_partkey and lo_orderdate = d_datekey and c_region = 'AMERICA' and s_region = 'AMERICA' and (d_year = 1997 or d_year = 1998) and (p_mfgr = 'MFGR#1' or p_mfgr = 'MFGR#2')
group by d_year, s_nation, p_category
order by d_year, s_nation, p_category""",
"ssb_q4_3": """select d_year, s_city, p_brand1, sum(lo_revenue - lo_supplycost) as profit
from date, customer, supplier, part, lineorder
where lo_custkey = c_custkey and lo_suppkey = s_suppkey and lo_partkey = p_partkey and lo_orderdate = d_datekey and c_region = 'AMERICA' and s_nation = 'UNITED STATES' and (d_year = 1997 or d_year = 1998) and p_category = 'MFGR#14'
group by d_year, s_city, p_brand1
order by d_year, s_city, p_brand1""",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    qdir = a.out / "queries"
    qdir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(a.db), read_only=True)
    con.execute("SET memory_limit='8GB'")
    con.execute("SET threads TO 8")
    res = {}
    for name, sql in Q.items():
        (qdir / f"{name}.sql").write_text(sql + "\n")
        ts = []
        rows = 0
        for _ in range(4):  # first run warms, median of the next 3
            t = time.perf_counter()
            rows = len(con.execute(sql).fetchall())
            ts.append((time.perf_counter() - t) * 1000)
        res[name] = {"rows": rows, "median_ms": round(statistics.median(ts[1:]), 2), "runs_ms": [round(x, 2) for x in ts[1:]]}
        print(name, res[name])
    (a.out / "manifest.json").write_text(json.dumps({
        "source": "standard SSB (O'Neil et al.) comma-join form, 13 queries; research_loop/ssb_queries.py is the flat-table variant and differs",
        "db": str(a.db),
        "duckdb": {"version": duckdb.__version__, "threads": 8, "memory_limit": "8GB", "protocol": "1 warm-up + median of 3"},
        "queries": res,
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
