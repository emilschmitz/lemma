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


def _combo_sec(tier_name: str, rng: random.Random) -> list[tuple[str, str]]:
    """Structural variety: aggregate, column, predicate form and group column are drawn, so shapes differ (not only literals)."""
    num_aggs = ["SUM(value)", "MIN(value)", "MAX(value)", "COUNT(*)", "MIN(ddate)", "MAX(ddate)", "SUM(qtrs)"]
    num_preds = [
        f"uom = '{rng.choice(['USD', 'shares', 'pure'])}'",
        f"ddate >= {rng.choice([20220101, 20230101])} AND ddate < {rng.choice([20231231, 20240331])}",
        f"qtrs = {rng.randint(0, 4)} AND uom <> '{rng.choice(['USD', 'pure'])}'",
        f"value > {rng.choice([100, 5000, 250000])}",
        f"uom = '{rng.choice(['USD', 'shares'])}' AND value BETWEEN {rng.choice([10, 1000])} AND {rng.choice([50000, 900000])}",
    ]
    pre_aggs = ["COUNT(*)", "SUM(line)", "MIN(line)", "MAX(report)", "SUM(report)"]
    pre_preds = [
        f"stmt = '{rng.choice(['BS', 'IS', 'CF', 'EQ'])}'",
        f"line BETWEEN {rng.randint(1, 10)} AND {rng.randint(11, 40)}",
        f"stmt <> '{rng.choice(['UN', 'SI'])}' AND report > {rng.randint(1, 20)}",
        f"inpth = {rng.randint(0, 1)} AND line > {rng.randint(1, 30)}",
    ]
    out: list[tuple[str, str]] = []
    if tier_name == "T1":
        for i in range(4):
            if i % 2 == 0:
                aggs = ", ".join(f"{a} AS a{j}" for j, a in enumerate(rng.sample(num_aggs, rng.choice([1, 2]))))
                out.append((f"sec_c1_num{i}", f"SELECT {aggs} FROM num WHERE {rng.choice(num_preds)}"))
            else:
                aggs = ", ".join(f"{a} AS a{j}" for j, a in enumerate(rng.sample(pre_aggs, rng.choice([1, 2]))))
                out.append((f"sec_c1_pre{i}", f"SELECT {aggs} FROM pre WHERE {rng.choice(pre_preds)}"))
    elif tier_name == "T2":
        keys_num = ["uom", "qtrs", "tag"]
        keys_pre = ["stmt", "report", "inpth", "rfile"]
        for i in range(4):
            if i % 2 == 0:
                k = rng.choice(keys_num)
                a = rng.choice(num_aggs)
                having = f" HAVING COUNT(*) > {rng.randint(1, 50)}" if rng.random() < 0.5 else ""
                order = f" ORDER BY {k}" if rng.random() < 0.5 else ""
                out.append((f"sec_c2_num{i}", f"SELECT {k}, {a} AS a FROM num WHERE {rng.choice(num_preds)} GROUP BY {k}{having}{order}"))
            else:
                k = rng.choice(keys_pre)
                a = rng.choice(pre_aggs)
                out.append((f"sec_c2_pre{i}", f"SELECT {k}, {a} AS a, COUNT(*) AS c FROM pre WHERE {rng.choice(pre_preds)} GROUP BY {k}"))
    elif tier_name == "T3":
        keys = ["s.fy", "s.fp", "s.form", "s.countryba"]
        for i in range(3):
            k = rng.choice(keys)
            a = rng.choice(["SUM(n.value)", "COUNT(*)", "MAX(n.value)", "MIN(n.ddate)", "SUM(n.qtrs)"])
            pr = rng.choice([f"n.uom = '{rng.choice(['USD', 'shares', 'pure'])}'", f"s.fy = {rng.choice([2022, 2023, 2024])}", f"n.qtrs = {rng.randint(0, 4)} AND s.fy >= 2023"])
            grouped = rng.random() < 0.7
            sel = f"{k}, " if grouped else ""
            grp = f" GROUP BY {k}" if grouped else ""
            out.append((f"sec_c3_{i}", f"SELECT {sel}{a} AS a FROM num n JOIN sub s ON n.adsh = s.adsh WHERE {pr}{grp}"))
    return out


def _combo_tpch(tier_name: str, rng: random.Random) -> list[tuple[str, str]]:
    li_aggs = ["sum(l_quantity)", "sum(l_extendedprice)", "min(l_extendedprice)", "max(l_discount)", "count(*)", "sum(l_extendedprice * (1 - l_discount))", "sum(l_extendedprice * l_tax)"]
    li_preds = [
        f"l_shipdate >= date '{rng.randint(1993, 1997)}-0{rng.randint(1, 9)}-01'",
        f"l_shipdate < date '{rng.randint(1994, 1998)}-01-01' AND l_quantity < {rng.randint(10, 40)}",
        f"l_discount BETWEEN 0.0{rng.randint(1, 4)} AND 0.0{rng.randint(5, 9)}",
        f"l_returnflag = '{rng.choice(['R', 'A', 'N'])}' AND l_tax < 0.0{rng.randint(3, 8)}",
        f"l_shipmode = '{rng.choice(['MAIL', 'AIR', 'SHIP', 'RAIL'])}'",
    ]
    out: list[tuple[str, str]] = []
    if tier_name == "T1":
        for i in range(3):
            aggs = ", ".join(f"{a} AS a{j}" for j, a in enumerate(rng.sample(li_aggs, rng.choice([1, 2]))))
            out.append((f"tpch_c1_{i}", f"SELECT {aggs} FROM lineitem WHERE {rng.choice(li_preds)}"))
    elif tier_name == "T2":
        keys = ["l_returnflag", "l_linestatus", "l_shipmode", "l_shipinstruct"]
        for i in range(3):
            k = rng.choice(keys)
            a = rng.choice(li_aggs)
            order = f" ORDER BY {k}" if rng.random() < 0.5 else ""
            out.append((f"tpch_c2_{i}", f"SELECT {k}, {a} AS a, count(*) AS c FROM lineitem WHERE {rng.choice(li_preds)} GROUP BY {k}{order}"))
    elif tier_name == "T3":
        for i in range(3):
            k = rng.choice(["c_mktsegment", "o_orderpriority", "o_orderstatus"])
            a = rng.choice(["sum(o_totalprice)", "count(*)", "max(o_totalprice)", "min(o_orderdate)"])
            if k == "c_mktsegment":
                out.append((f"tpch_c3_{i}", f"SELECT {k}, {a} AS a FROM orders JOIN customer ON o_custkey = c_custkey WHERE o_orderdate < date '{rng.randint(1994, 1998)}-01-01' GROUP BY {k}"))
            else:
                la = rng.choice(["sum(l_quantity)", "count(*)", "max(l_extendedprice)", "min(l_shipdate)"])
                out.append((f"tpch_c3_{i}", f"SELECT {k}, {la} AS a FROM orders JOIN lineitem ON o_orderkey = l_orderkey WHERE o_orderdate >= date '{rng.randint(1993, 1997)}-01-01' GROUP BY {k}"))
    return out


def seeded_queries(kind: str, tier_name: str, rng: random.Random) -> list[tuple[str, str]]:
    """Fresh seeded queries of one tier for ``kind`` in {"sec", "tpch"}, shuffled."""
    if kind not in ("sec", "tpch"):
        raise ValueError(f"unknown kind {kind!r}")
    out = (_sec if kind == "sec" else _tpch)(tier_name, rng) + (_combo_sec if kind == "sec" else _combo_tpch)(tier_name, rng)
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
