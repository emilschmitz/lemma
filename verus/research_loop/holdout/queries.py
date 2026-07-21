"""Holdout benchmark query definitions (SQL + data paths + literals)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

HOLDOUT_DIR = Path(__file__).resolve().parent
DATA_DIR = HOLDOUT_DIR / "data"

# Shifted literals (not identical to proved TPC-H fixtures).
H1_LO_DATE = 1_996_0101
H1_HI_DATE = 1_996_1231

H2_LO_DATE = 1_995_0101
H2_HI_DATE = 1_999_1231

H3_REGION = 2

H5_LO_QTY = 5
H5_HI_QTY = 30
H5_LO_DISC = 2
H5_HI_DISC = 4
H5_LO_SHIP = 1_994_0301
H5_HI_SHIP = 1_994_0630

H6_ORDER_BEFORE = 1_994_0315
H6_SHIP_AFTER = 1_994_0315

H7_SHIP_BEFORE = 1_997_0601

H8_LO_DATE = 1_992_0101
H8_HI_DATE = 1_992_0630

H9_LO_DATE = 1_995_0201
H9_HI_DATE = 1_995_0207

H10_LO_DATE = 1_996_0101
H10_HI_DATE = 1_996_1231

H11_REGION = 0

H13_FORM = "8-K"
H13_CIK_PREFIX = "10"

H15_LO_QTY = 8
H15_HI_QTY = 25
H15_LO_DISC = 3
H15_HI_DISC = 5
H15_LO_SHIP = 1_994_0401
H15_HI_SHIP = 1_994_0430

H16_SHIP_BEFORE = 1_997_0801

H17_ORDER_BEFORE = 1_994_0201
H17_SHIP_AFTER = 1_994_0201

H18_SHIPMODE = "RAIL"

H19_LO_DATE = 1_995_0101
H19_HI_DATE = 1_995_1231

H20_PRIORITY = "3-MEDIUM"

H21_LO_DISC = 2
H21_HI_DISC = 4
H21_LO_QTY = 20
H21_HI_QTY = 35
H21_LO_DATE = 1_993_0801
H21_HI_DATE = 1_993_1231

H23_LO_DATE = 1_994_0101
H23_HI_DATE = 1_994_1231
H23_MIN_DISC = 8

H25_LO_QTY = 10
H25_HI_QTY = 40
H25_LO_DISC = 3
H25_HI_DISC = 6
H25_LO_SHIP = 1_995_0601
H25_HI_SHIP = 1_995_0831
H25_RETURNFLAG = "N"


@dataclass(frozen=True)
class HoldoutQuery:
    name: str
    sql: str
    tbl_paths: dict[str, Path]
    description: str


def _tbl(name: str) -> Path:
    return DATA_DIR / name


QUERIES: dict[str, HoldoutQuery] = {
    "H1": HoldoutQuery(
        name="H1",
        description="Selective scalar sum on date-skewed scan (zone-map prune)",
        tbl_paths={"scan_skew": _tbl("scan_skew.tbl")},
        sql=f"""
SELECT SUM(amount) AS total
FROM scan_skew
WHERE event_date >= {H1_LO_DATE} AND event_date <= {H1_HI_DATE}
""".strip(),
    ),
    "H2": HoldoutQuery(
        name="H2",
        description="Group-by small cardinality (region) on scan_skew",
        tbl_paths={"scan_skew": _tbl("scan_skew.tbl")},
        sql=f"""
SELECT region, SUM(amount) AS total
FROM scan_skew
WHERE event_date >= {H2_LO_DATE} AND event_date <= {H2_HI_DATE}
GROUP BY region
ORDER BY region
""".strip(),
    ),
    "H3": HoldoutQuery(
        name="H3",
        description="Zipf inner join sum with region filter",
        tbl_paths={"zipf_left": _tbl("zipf_left.tbl"), "zipf_right": _tbl("zipf_right.tbl")},
        sql=f"""
SELECT SUM(l.amount) AS total
FROM zipf_left l
INNER JOIN zipf_right r ON l.key = r.key AND l.region = r.region
WHERE l.region = {H3_REGION}
""".strip(),
    ),
    "H4": HoldoutQuery(
        name="H4",
        description="String-selective sum (equality + prefix)",
        tbl_paths={"str_filter": _tbl("str_filter.tbl")},
        sql="""
SELECT SUM(amount) AS total
FROM str_filter
WHERE form_type = '10-K'
  AND cik LIKE '00%'
  AND active = 1
""".strip(),
    ),
    "H5": HoldoutQuery(
        name="H5",
        description="TPC-H Q6-like shifted literals on lineitem slice",
        tbl_paths={"lineitem": _tbl("lineitem_slice.tbl")},
        sql=f"""
SELECT SUM(l_extendedprice * l_discount) AS revenue
FROM lineitem
WHERE l_quantity >= {H5_LO_QTY} AND l_quantity <= {H5_HI_QTY}
  AND l_discount >= {H5_LO_DISC} AND l_discount <= {H5_HI_DISC}
  AND l_shipdate >= {H5_LO_SHIP} AND l_shipdate <= {H5_HI_SHIP}
""".strip(),
    ),
    "H6": HoldoutQuery(
        name="H6",
        description="TPC-H Q3-like lineitem join orders with shifted dates",
        tbl_paths={
            "lineitem": _tbl("lineitem_slice.tbl"),
            "orders": _tbl("orders_slice.tbl"),
        },
        sql=f"""
SELECT SUM(l.l_extendedprice) AS revenue
FROM lineitem l
INNER JOIN orders o ON l.l_orderkey = o.o_orderkey
WHERE o.o_orderdate < {H6_ORDER_BEFORE}
  AND l.l_shipdate > {H6_SHIP_AFTER}
""".strip(),
    ),
    "H7": HoldoutQuery(
        name="H7",
        description="Two-key group-by on lineitem slice",
        tbl_paths={"lineitem": _tbl("lineitem_slice.tbl")},
        sql=f"""
SELECT l_returnflag, l_linestatus, SUM(l_quantity) AS sum_qty
FROM lineitem
WHERE l_shipdate <= {H7_SHIP_BEFORE}
GROUP BY l_returnflag, l_linestatus
ORDER BY l_returnflag, l_linestatus
""".strip(),
    ),
    "H8": HoldoutQuery(
        name="H8",
        description="scan_skew COUNT(*) with alternate date window (zone prune)",
        tbl_paths={"scan_skew": _tbl("scan_skew.tbl")},
        sql=f"""
SELECT COUNT(*) AS cnt
FROM scan_skew
WHERE event_date >= {H8_LO_DATE} AND event_date <= {H8_HI_DATE}
""".strip(),
    ),
    "H9": HoldoutQuery(
        name="H9",
        description="scan_skew SUM with very selective tiny date window",
        tbl_paths={"scan_skew": _tbl("scan_skew.tbl")},
        sql=f"""
SELECT SUM(amount) AS total
FROM scan_skew
WHERE event_date >= {H9_LO_DATE} AND event_date <= {H9_HI_DATE}
""".strip(),
    ),
    "H10": HoldoutQuery(
        name="H10",
        description="1M scan_skew selective SUM (MT-friendly scale)",
        tbl_paths={"scan_skew": _tbl("scan_skew_1m.tbl")},
        sql=f"""
SELECT SUM(amount) AS total
FROM scan_skew
WHERE event_date >= {H10_LO_DATE} AND event_date <= {H10_HI_DATE}
""".strip(),
    ),
    "H11": HoldoutQuery(
        name="H11",
        description="Zipf join sum with different region filter",
        tbl_paths={"zipf_left": _tbl("zipf_left.tbl"), "zipf_right": _tbl("zipf_right.tbl")},
        sql=f"""
SELECT SUM(l.amount) AS total
FROM zipf_left l
INNER JOIN zipf_right r ON l.key = r.key AND l.region = r.region
WHERE l.region = {H11_REGION}
""".strip(),
    ),
    "H12": HoldoutQuery(
        name="H12",
        description="Zipf join with small-cardinality group-by on region",
        tbl_paths={"zipf_left": _tbl("zipf_left.tbl"), "zipf_right": _tbl("zipf_right.tbl")},
        sql="""
SELECT l.region, SUM(l.amount) AS total
FROM zipf_left l
INNER JOIN zipf_right r ON l.key = r.key AND l.region = r.region
GROUP BY l.region
ORDER BY l.region
""".strip(),
    ),
    "H13": HoldoutQuery(
        name="H13",
        description="str_filter alternate form_type and CIK prefix",
        tbl_paths={"str_filter": _tbl("str_filter.tbl")},
        sql=f"""
SELECT SUM(amount) AS total
FROM str_filter
WHERE form_type = '{H13_FORM}'
  AND cik LIKE '{H13_CIK_PREFIX}%'
  AND active = 1
""".strip(),
    ),
    "H14": HoldoutQuery(
        name="H14",
        description="str_filter COUNT(*) active rows only",
        tbl_paths={"str_filter": _tbl("str_filter.tbl")},
        sql="""
SELECT COUNT(*) AS cnt
FROM str_filter
WHERE active = 1
""".strip(),
    ),
    "H15": HoldoutQuery(
        name="H15",
        description="TPC-H Q6-like on 1M lineitem with shifted literals",
        tbl_paths={"lineitem": _tbl("lineitem_1m.tbl")},
        sql=f"""
SELECT SUM(l_extendedprice * l_discount) AS revenue
FROM lineitem
WHERE l_quantity >= {H15_LO_QTY} AND l_quantity <= {H15_HI_QTY}
  AND l_discount >= {H15_LO_DISC} AND l_discount <= {H15_HI_DISC}
  AND l_shipdate >= {H15_LO_SHIP} AND l_shipdate <= {H15_HI_SHIP}
""".strip(),
    ),
    "H16": HoldoutQuery(
        name="H16",
        description="TPC-H Q1-like group-by on 1M lineitem slice",
        tbl_paths={"lineitem": _tbl("lineitem_1m.tbl")},
        sql=f"""
SELECT l_returnflag, l_linestatus, SUM(l_quantity) AS sum_qty
FROM lineitem
WHERE l_shipdate <= {H16_SHIP_BEFORE}
GROUP BY l_returnflag, l_linestatus
ORDER BY l_returnflag, l_linestatus
""".strip(),
    ),
    "H17": HoldoutQuery(
        name="H17",
        description="1M lineitem join orders Q3-like shifted dates",
        tbl_paths={
            "lineitem": _tbl("lineitem_1m.tbl"),
            "orders": _tbl("orders_1m.tbl"),
        },
        sql=f"""
SELECT SUM(l.l_extendedprice) AS revenue
FROM lineitem l
INNER JOIN orders o ON l.l_orderkey = o.o_orderkey
WHERE o.o_orderdate < {H17_ORDER_BEFORE}
  AND l.l_shipdate > {H17_SHIP_AFTER}
""".strip(),
    ),
    "H18": HoldoutQuery(
        name="H18",
        description="lineitem shipmode equality filter SUM extendedprice",
        tbl_paths={"lineitem": _tbl("lineitem_1m.tbl")},
        sql=f"""
SELECT SUM(l_extendedprice) AS total
FROM lineitem
WHERE l_shipmode = '{H18_SHIPMODE}'
""".strip(),
    ),
    "H19": HoldoutQuery(
        name="H19",
        description="orders SUM o_totalprice with orderdate range",
        tbl_paths={"orders": _tbl("orders_1m.tbl")},
        sql=f"""
SELECT SUM(o_totalprice) AS total
FROM orders
WHERE o_orderdate >= {H19_LO_DATE} AND o_orderdate <= {H19_HI_DATE}
""".strip(),
    ),
    "H20": HoldoutQuery(
        name="H20",
        description="orders filter by orderpriority SUM o_totalprice",
        tbl_paths={"orders": _tbl("orders_1m.tbl")},
        sql=f"""
SELECT SUM(o_totalprice) AS total
FROM orders
WHERE o_orderpriority = '{H20_PRIORITY}'
""".strip(),
    ),
    "H21": HoldoutQuery(
        name="H21",
        description="SSB flat selective SUM revenue (Q1.1-ish shifted)",
        tbl_paths={"ssb_flat": _tbl("ssb_flat_500k.tbl")},
        sql=f"""
SELECT SUM(lo_revenue) AS total
FROM ssb_flat
WHERE lo_discount >= {H21_LO_DISC} AND lo_discount <= {H21_HI_DISC}
  AND lo_quantity >= {H21_LO_QTY} AND lo_quantity <= {H21_HI_QTY}
  AND lo_orderdate >= {H21_LO_DATE} AND lo_orderdate <= {H21_HI_DATE}
""".strip(),
    ),
    "H22": HoldoutQuery(
        name="H22",
        description="SSB flat group-by orderpriority SUM revenue",
        tbl_paths={"ssb_flat": _tbl("ssb_flat_500k.tbl")},
        sql="""
SELECT lo_orderpriority, SUM(lo_revenue) AS total
FROM ssb_flat
GROUP BY lo_orderpriority
ORDER BY lo_orderpriority
""".strip(),
    ),
    "H23": HoldoutQuery(
        name="H23",
        description="SSB flat selective year + high discount SUM revenue",
        tbl_paths={"ssb_flat": _tbl("ssb_flat_500k.tbl")},
        sql=f"""
SELECT SUM(lo_revenue) AS total
FROM ssb_flat
WHERE lo_orderdate >= {H23_LO_DATE} AND lo_orderdate <= {H23_HI_DATE}
  AND lo_discount >= {H23_MIN_DISC}
""".strip(),
    ),
    "H24": HoldoutQuery(
        name="H24",
        description="orders large-cardinality group-by orderkey mod 1000",
        tbl_paths={"orders": _tbl("orders_1m.tbl")},
        sql="""
SELECT o_orderkey % 1000 AS bucket, SUM(o_totalprice) AS total
FROM orders
GROUP BY bucket
ORDER BY bucket
""".strip(),
    ),
    "H25": HoldoutQuery(
        name="H25",
        description="Multi-predicate lineitem filter SUM extendedprice",
        tbl_paths={"lineitem": _tbl("lineitem_1m.tbl")},
        sql=f"""
SELECT SUM(l_extendedprice) AS total
FROM lineitem
WHERE l_quantity >= {H25_LO_QTY} AND l_quantity <= {H25_HI_QTY}
  AND l_discount >= {H25_LO_DISC} AND l_discount <= {H25_HI_DISC}
  AND l_shipdate >= {H25_LO_SHIP} AND l_shipdate <= {H25_HI_SHIP}
  AND l_returnflag = '{H25_RETURNFLAG}'
""".strip(),
    ),
}

QUERY_ORDER = [f"H{i}" for i in range(1, 26)]
