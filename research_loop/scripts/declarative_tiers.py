"""Tiered query draws for the declarative menu, so the prove rate is measured per shape class.

T1  single table, filter + aggregate (COUNT/SUM/MIN/MAX), no GROUP BY
T2  single table GROUP BY (+ HAVING, ORDER BY, LIMIT)
T3  two tables joined (+ GROUP BY)
T4  EXISTS / IN / scalar subquery / COUNT(DISTINCT)
T5  three or more tables, derived tables, everything else

``tier(sql)`` classifies any SQL. ``seeded_queries(kind, tier, rng)`` yields fresh seeded queries of that tier for the
SEC (synthetic) and TPC-H schemas; the SEC shuffle generator's pool is also classified by ``tier`` and used for T3 to T5.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import sqlglot
from sqlglot import exp

TIERS = ("T1", "T2", "T3", "T4", "T5")


def tier(sql: str) -> str:
    tree = sqlglot.parse_one(sql)
    selects = list(tree.find_all(exp.Select))
    tables = [t for t in tree.find_all(exp.Table)]
    derived = any(isinstance(s.parent, exp.Subquery) and isinstance(s.parent.parent, (exp.From, exp.Join)) for s in selects)
    if derived:
        return "T5"
    nested = len(selects) > 1 or any(tree.find_all(exp.Exists))
    distinct = any(c.args.get("this") is not None and isinstance(c.this, exp.Distinct) for c in tree.find_all(exp.Count))
    if nested or distinct:
        return "T4"
    if len(tables) >= 3:
        return "T5"
    if len(tables) == 2:
        return "T3"
    return "T2" if tree.args.get("group") is not None else "T1"


def _sec(tier_name: str, rng: random.Random) -> list[tuple[str, str]]:
    uom = rng.choice(["USD", "shares", "pure"])
    d0 = rng.choice([20220101, 20220601, 20230101, 20230701])
    stmt = rng.choice(["BS", "IS", "CF", "EQ", "CI", "UN", "SI"])
    line = rng.randint(1, 40)
    k = rng.randint(5, 60)
    fy = rng.choice([2022, 2023, 2024])
    if tier_name == "T1":
        return [
            ("sec_t1_sum", f"SELECT SUM(value) AS total FROM num WHERE uom = '{uom}' AND ddate >= {d0}"),
            ("sec_t1_count", f"SELECT COUNT(*) AS c FROM pre WHERE stmt = '{stmt}' AND line > {line}"),
            ("sec_t1_minmax", f"SELECT MIN(ddate) AS lo, MAX(ddate) AS hi FROM num WHERE uom = '{uom}' AND qtrs = {rng.randint(0, 4)}"),
            ("sec_t1_sum2", f"SELECT SUM(line) AS total FROM pre WHERE stmt = '{stmt}' AND report > {rng.randint(1, 20)}"),
        ]
    if tier_name == "T2":
        return [
            ("sec_t2_uom", f"SELECT uom, COUNT(*) AS c, SUM(value) AS total FROM num WHERE ddate >= {d0} GROUP BY uom ORDER BY c DESC"),
            ("sec_t2_stmt", f"SELECT stmt, COUNT(*) AS c FROM pre WHERE line > {line} GROUP BY stmt HAVING COUNT(*) > {k} ORDER BY c DESC LIMIT 5"),
            ("sec_t2_fy", f"SELECT fy, COUNT(*) AS c FROM sub WHERE cik > {rng.randint(1, 5000)} GROUP BY fy"),
            ("sec_t2_tag", f"SELECT tag, SUM(value) AS total FROM num WHERE uom = '{uom}' GROUP BY tag HAVING COUNT(*) > {k} ORDER BY total DESC LIMIT {rng.choice([10, 50])}"),
        ]
    if tier_name == "T3":
        return [
            ("sec_t3_fy", f"SELECT s.fy, SUM(n.value) AS total FROM num n JOIN sub s ON n.adsh = s.adsh WHERE n.uom = '{uom}' GROUP BY s.fy"),
            ("sec_t3_count", f"SELECT s.fy, COUNT(*) AS c FROM num n JOIN sub s ON n.adsh = s.adsh WHERE s.fy = {fy} AND n.uom = '{uom}' GROUP BY s.fy"),
            ("sec_t3_scalar", f"SELECT SUM(n.value) AS total FROM num n JOIN sub s ON n.adsh = s.adsh WHERE s.fy = {fy} AND n.uom = '{uom}'"),
        ]
    return []


def _tpch(tier_name: str, rng: random.Random) -> list[tuple[str, str]]:
    year = rng.randint(1993, 1997)
    disc = rng.randint(2, 9)
    qty = rng.choice([24, 25])
    delta = rng.randint(60, 120)
    seg = rng.choice(["BUILDING", "AUTOMOBILE", "MACHINERY", "HOUSEHOLD", "FURNITURE"])
    mode = rng.choice(["MAIL", "SHIP", "AIR", "RAIL", "TRUCK", "FOB"])
    if tier_name == "T1":
        return [
            (
                "tpch_t1_q6",
                f"SELECT sum(l_extendedprice * l_discount) AS revenue FROM lineitem WHERE l_shipdate >= date '{year}-01-01' "
                f"AND l_shipdate < date '{year}-01-01' + interval '1' year AND l_discount BETWEEN 0.0{disc} - 0.01 AND 0.0{disc} + 0.01 "
                f"AND l_quantity < {qty}",
            ),
            ("tpch_t1_qty", f"SELECT sum(l_quantity) AS q, count(*) AS c FROM lineitem WHERE l_shipdate >= date '{year}-01-01' AND l_discount > 0.0{disc}"),
        ]
    if tier_name == "T2":
        return [
            (
                "tpch_t2_q1",
                "SELECT l_returnflag, l_linestatus, sum(l_quantity) AS sum_qty, sum(l_extendedprice) AS sum_base_price, "
                "sum(l_extendedprice * (1 - l_discount)) AS sum_disc_price, count(*) AS count_order FROM lineitem "
                f"WHERE l_shipdate <= date '1998-12-01' - interval '{delta}' day GROUP BY l_returnflag, l_linestatus "
                "ORDER BY l_returnflag, l_linestatus",
            ),
            ("tpch_t2_mode", f"SELECT l_shipmode, count(*) AS c, sum(l_quantity) AS q FROM lineitem WHERE l_shipdate >= date '{year}-01-01' GROUP BY l_shipmode"),
        ]
    if tier_name == "T3":
        return [
            (
                "tpch_t3_seg",
                f"SELECT c_mktsegment, sum(o_totalprice) AS total, count(*) AS c FROM orders JOIN customer ON o_custkey = c_custkey "
                f"WHERE o_orderdate < date '{year}-06-01' GROUP BY c_mktsegment",
            ),
            (
                "tpch_t3_prio",
                f"SELECT o_orderpriority, count(*) AS c FROM orders JOIN lineitem ON o_orderkey = l_orderkey "
                f"WHERE l_shipmode = '{mode}' AND o_orderdate >= date '{year}-01-01' GROUP BY o_orderpriority",
            ),
        ]
    return []


def seeded_queries(kind: str, tier_name: str, rng: random.Random) -> list[tuple[str, str]]:
    """Fresh seeded queries of one tier for ``kind`` in {"sec", "tpch"}, shuffled."""
    if kind not in ("sec", "tpch"):
        raise ValueError(f"unknown kind {kind!r}")
    out = (_sec if kind == "sec" else _tpch)(tier_name, rng)
    rng.shuffle(out)
    return out


# ---- seen registry, shape keys, held-out shapes ----------------------------------------------------------------

REGISTRY = Path(__file__).resolve().parents[2] / "research_loop" / "generated" / "decl_rounds" / "seen_queries.jsonl"
HELDOUT_PERCENT = 30


def normalize(sql: str) -> str:
    """Whitespace collapsed, trailing semicolon dropped, literals kept."""
    return " ".join(sql.split()).rstrip(";").strip()


def shape_key(sql: str) -> str:
    """The query with every literal replaced by `?`: two queries with the same shape differ only in constants."""
    tree = sqlglot.parse_one(sql)
    for lit in list(tree.find_all(exp.Literal)):
        lit.replace(exp.Placeholder())
    return " ".join(tree.sql().split())


def is_heldout(shape: str) -> bool:
    """A fixed ~30% of shape keys, by hash: never used to write recipes, fixtures or prompt text."""
    return int(hashlib.sha1(shape.encode()).hexdigest()[:8], 16) % 100 < HELDOUT_PERCENT


def load_registry(path: Path = REGISTRY) -> tuple[set[str], set[str]]:
    """(normalized queries, shape keys) seen so far."""
    queries: set[str] = set()
    shapes: set[str] = set()
    if path.is_file():
        for line in path.read_text().splitlines():
            rec = json.loads(line)
            queries.add(rec["sql"])
            shapes.add(rec["shape"])
    return queries, shapes


def novelty(sql: str, path: Path = REGISTRY) -> dict:
    queries, shapes = load_registry(path)
    return {"new_query": normalize(sql) not in queries, "new_shape": shape_key(sql) not in shapes}


def register(sql: str, why: str, path: Path = REGISTRY) -> None:
    """Record a drawn, proved or fixture-used query (normalized SQL and shape key)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"sql": normalize(sql), "shape": shape_key(sql), "heldout": is_heldout(shape_key(sql)), "why": why}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
