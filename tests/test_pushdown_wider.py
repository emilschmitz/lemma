"""Pushdown through LEFT JOIN and subqueries (declarative_spec/pushdown.py rules R1-R6), checked against DuckDB.

For each shape: plan the pushdown, build the executor's inputs as the export would (each table filtered by its pushed predicate,
or whole), run the ORIGINAL query on those inputs and on the full tables, and require the same result (as a multiset). The data
is small, seeded, and has NULLs in the filtered and joined columns. SQL here are fixtures (SEC / TPC-H shapes), not engine code.
"""

from __future__ import annotations

import random

import duckdb
import pytest

from declarative_spec.pushdown import plan_pushdown

SEC = {
    "num": {"adsh": "varchar", "tag": "varchar", "version": "varchar", "ddate": "integer", "uom": "varchar", "value": "decimal(38,4)"},
    "pre": {"adsh": "varchar", "tag": "varchar", "version": "varchar", "stmt": "varchar"},
    "sub": {"adsh": "varchar", "cik": "integer", "name": "varchar", "fy": "integer"},
}
TPCH = {
    "customer": {"c_custkey": "bigint", "c_name": "varchar"},
    "orders": {"o_orderkey": "bigint", "o_custkey": "bigint", "o_orderdate": "date", "o_totalprice": "decimal(15,2)"},
    "lineitem": {"l_orderkey": "bigint", "l_quantity": "decimal(15,2)"},
}


def _sec_db() -> duckdb.DuckDBPyConnection:
    rng = random.Random(7)
    con = duckdb.connect()
    con.execute("CREATE TABLE sub (adsh VARCHAR, cik INTEGER, name VARCHAR, fy INTEGER)")
    con.execute("CREATE TABLE num (adsh VARCHAR, tag VARCHAR, version VARCHAR, ddate INTEGER, uom VARCHAR, value DECIMAL(38,4))")
    con.execute("CREATE TABLE pre (adsh VARCHAR, tag VARCHAR, version VARCHAR, stmt VARCHAR)")
    adshs = [f"a{i}" for i in range(40)]
    con.executemany("INSERT INTO sub VALUES (?, ?, ?, ?)", [(a, i % 13, f"co{i % 17}", rng.choice([2021, 2022, 2023, None])) for i, a in enumerate(adshs)])
    tags = [f"t{i}" for i in range(6)]
    nums = []
    for _ in range(1500):
        nums.append((
            rng.choice(adshs), rng.choice(tags), rng.choice(["v1", "v2"]), rng.choice([20221231, 20230615, 20231231, 20240101, None]),
            rng.choice(["USD", "pure", "shares", None]), rng.choice([None, round(rng.uniform(-50, 1000), 2)]),
        ))
    con.executemany("INSERT INTO num VALUES (?, ?, ?, ?, ?, ?)", nums)
    pres = [(rng.choice(adshs), rng.choice(tags), rng.choice(["v1", "v2"]), rng.choice(["BS", "IS", "CF", None])) for _ in range(300)]
    con.executemany("INSERT INTO pre VALUES (?, ?, ?, ?)", pres)
    return con


def _tpch_db() -> duckdb.DuckDBPyConnection:
    rng = random.Random(11)
    con = duckdb.connect()
    con.execute("CREATE TABLE customer (c_custkey BIGINT, c_name VARCHAR)")
    con.execute("CREATE TABLE orders (o_orderkey BIGINT, o_custkey BIGINT, o_orderdate DATE, o_totalprice DECIMAL(15,2))")
    con.execute("CREATE TABLE lineitem (l_orderkey BIGINT, l_quantity DECIMAL(15,2))")
    con.executemany("INSERT INTO customer VALUES (?, ?)", [(i, f"c{i}") for i in range(30)])
    con.executemany(
        "INSERT INTO orders VALUES (?, ?, DATE '1994-01-01' + ?::INTEGER, ?)",
        [(o, rng.randrange(30), rng.randrange(1500), round(rng.uniform(1, 9999), 2)) for o in range(200)],
    )
    con.executemany("INSERT INTO lineitem VALUES (?, ?)", [(rng.randrange(200), rng.randrange(1, 50)) for _ in range(1200)])
    return con


def _check(con: duckdb.DuckDBPyConnection, sql: str, schema: dict) -> dict[str, tuple[int, int]]:
    """Same result on the pushed-down inputs as on the full tables; returns table -> (full rows, delivered rows)."""
    plan = plan_pushdown(sql, schema, dialect="duckdb")
    assert plan.refused is None, plan.refused
    con.execute("ATTACH ':memory:' AS pushed")
    sizes = {}
    for table in schema:
        where = plan.where(table)
        con.execute(f"CREATE TABLE pushed.{table} AS SELECT * FROM memory.main.{table}" + (f" WHERE {where}" if where else ""))
        full = con.execute(f"SELECT count(*) FROM memory.main.{table}").fetchone()[0]
        sizes[table] = (full, con.execute(f"SELECT count(*) FROM pushed.{table}").fetchone()[0])
    expected = con.execute(sql).fetchall()
    con.execute("USE pushed")
    got = con.execute(sql).fetchall()
    con.execute("USE memory")
    assert expected, "the fixture data must give a non-empty answer"
    assert sorted(map(repr, got)) == sorted(map(repr, expected))
    return sizes


def _sql(plan, table: str) -> list[str]:
    return [f.sql for f in plan.pushed.get(table, [])]


# ---- LEFT JOIN ----------------------------------------------------------------------------------------------------------------

Q24_SHAPE = """
SELECT n.tag, n.version, COUNT(*) AS cnt, SUM(n.value) AS total
FROM num n
LEFT JOIN pre p ON n.tag = p.tag AND n.version = p.version AND n.adsh = p.adsh
WHERE n.uom = 'USD' AND n.ddate BETWEEN 20230101 AND 20231231 AND n.value IS NOT NULL AND p.adsh IS NULL
GROUP BY n.tag, n.version
HAVING COUNT(*) > 1
"""


def test_left_join_anti_join_pushes_the_preserved_side_and_never_the_is_null_on_the_other() -> None:
    plan = plan_pushdown(Q24_SHAPE, SEC, dialect="duckdb")
    assert _sql(plan, "num") == ["\"uom\" = 'USD'", '"ddate" BETWEEN 20230101 AND 20231231', 'NOT "value" IS NULL']
    assert "pre" not in plan.pushed and any("p.adsh IS NULL" in k and "null-supplying" in k for k in plan.kept)
    sizes = _check(_sec_db(), Q24_SHAPE, SEC)
    assert sizes["num"][1] < sizes["num"][0] and sizes["pre"][1] == sizes["pre"][0]


def test_pushing_the_anti_joins_is_null_would_change_the_answer() -> None:
    """The refusal is load-bearing: exporting only pre rows with adsh IS NULL (none) turns every num row into an anti-join hit."""
    con = _sec_db()
    full = con.execute(Q24_SHAPE).fetchall()
    con.execute("CREATE TABLE pre2 AS SELECT * FROM pre WHERE adsh IS NULL")
    wrong = con.execute(Q24_SHAPE.replace("LEFT JOIN pre p", "LEFT JOIN pre2 p")).fetchall()
    assert sorted(map(repr, wrong)) != sorted(map(repr, full))


LEFT_ON_ONLY = """
SELECT n.tag, COUNT(p.adsh) AS matched, COUNT(*) AS c
FROM num n
LEFT JOIN pre p ON n.adsh = p.adsh AND n.tag = p.tag AND p.stmt = 'BS' AND n.uom = 'USD'
WHERE n.ddate >= 20230101
GROUP BY n.tag
"""


def test_left_join_on_conjunct_on_the_null_supplying_side_is_pushed_and_one_on_the_preserved_side_is_not() -> None:
    plan = plan_pushdown(LEFT_ON_ONLY, SEC, dialect="duckdb")
    assert _sql(plan, "pre") == ["\"stmt\" = 'BS'"]
    assert _sql(plan, "num") == ['"ddate" >= 20230101']  # n.uom = 'USD' is in the ON: num rows failing it are kept, NULL-extended
    assert any("n.uom = 'USD'" in k and "not the null-supplying side" in k for k in plan.kept)
    sizes = _check(_sec_db(), LEFT_ON_ONLY, SEC)
    assert sizes["pre"][1] < sizes["pre"][0] and sizes["num"][1] < sizes["num"][0]


def test_a_where_conjunct_on_the_null_supplying_side_is_not_pushed_even_without_is_null() -> None:
    sql = "SELECT n.tag, COUNT(*) AS c FROM num n LEFT JOIN pre p ON n.adsh = p.adsh WHERE p.stmt = 'BS' OR p.stmt IS NULL GROUP BY n.tag"
    plan = plan_pushdown(sql, SEC, dialect="duckdb")
    assert plan.pushed == {}
    _check(_sec_db(), sql, SEC)


def test_an_inner_join_after_a_left_join_keeps_its_table_restrictable() -> None:
    sql = (
        "SELECT s.name, COUNT(p.adsh) AS c FROM num n LEFT JOIN pre p ON n.adsh = p.adsh AND p.stmt = 'IS' "
        "JOIN sub s ON n.adsh = s.adsh AND s.fy = 2022 WHERE n.uom = 'USD' GROUP BY s.name"
    )
    plan = plan_pushdown(sql, SEC, dialect="duckdb")
    assert _sql(plan, "sub") == ['"fy" = 2022'] and _sql(plan, "pre") == ["\"stmt\" = 'IS'"] and _sql(plan, "num") == ["\"uom\" = 'USD'"]
    _check(_sec_db(), sql, SEC)


# ---- subqueries ---------------------------------------------------------------------------------------------------------------

Q3_SHAPE = """
SELECT s.name, s.cik, SUM(n.value) AS total_value
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD' AND s.fy = 2022 AND n.value IS NOT NULL
GROUP BY s.name, s.cik
HAVING SUM(n.value) > (
    SELECT AVG(sub_total) FROM (
        SELECT SUM(n2.value) AS sub_total
        FROM num n2
        JOIN sub s2 ON n2.adsh = s2.adsh
        WHERE n2.uom = 'USD' AND s2.fy = 2022 AND n2.value IS NOT NULL
        GROUP BY s2.cik
    ) avg_sub
)
"""


def test_scalar_subquery_in_having_reading_the_same_tables_with_the_same_filters_q3_shape() -> None:
    plan = plan_pushdown(Q3_SHAPE, SEC, dialect="duckdb")
    assert _sql(plan, "num") == ["\"uom\" = 'USD'", 'NOT "value" IS NULL'] and _sql(plan, "sub") == ['"fy" = 2022']
    sizes = _check(_sec_db(), Q3_SHAPE, SEC)
    assert sizes["num"][1] < sizes["num"][0] and sizes["sub"][1] < sizes["sub"][0]


Q18_SHAPE = """
SELECT c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice, SUM(l_quantity) AS q
FROM customer, orders, lineitem
WHERE o_orderkey IN (SELECT l_orderkey FROM lineitem WHERE l_quantity > 10 GROUP BY l_orderkey HAVING SUM(l_quantity) > 60)
  AND o_orderdate >= DATE '1995-01-01' AND c_custkey = o_custkey AND o_orderkey = l_orderkey
GROUP BY c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice
"""


def test_in_subquery_q18_shape_pushes_the_outer_only_table_and_refuses_the_shared_one() -> None:
    plan = plan_pushdown(Q18_SHAPE, TPCH, dialect="duckdb")
    assert _sql(plan, "orders") == ["\"o_orderdate\" >= CAST('1995-01-01' AS DATE)"]
    # lineitem is read by the outer block (no conjunct of its own) and by the subquery (l_quantity > 10): one file serves both.
    assert "lineitem" not in plan.pushed and any(k.startswith("table lineitem: nothing pushed") for k in plan.kept)
    sizes = _check(_tpch_db(), Q18_SHAPE, TPCH)
    assert sizes["orders"][1] < sizes["orders"][0]


def test_tpch_q18_as_written_pushes_nothing_and_is_not_refused() -> None:
    sql = Q18_SHAPE.replace(" WHERE l_quantity > 10", "").replace("AND o_orderdate >= DATE '1995-01-01' ", "")
    plan = plan_pushdown(sql, TPCH, dialect="duckdb")
    assert plan.refused is None and plan.pushed == {}


def test_same_table_in_outer_and_subquery_with_one_unfiltered_read_is_refused_for_that_table() -> None:
    sql = "SELECT n.tag, COUNT(*) AS c FROM num n WHERE n.value < 800 AND n.value > (SELECT AVG(value) FROM num) GROUP BY n.tag"
    plan = plan_pushdown(sql, SEC, dialect="duckdb")
    assert plan.pushed == {} and any(k.startswith("table num: nothing pushed") for k in plan.kept)
    _check(_sec_db(), sql, SEC)


def test_pushing_the_outer_filter_into_a_shared_table_would_change_the_answer() -> None:
    """The refusal above is load-bearing: AVG over only the rows below 800 differs from AVG over every row."""
    sql = "SELECT n.tag, COUNT(*) AS c FROM num n WHERE n.value < 800 AND n.value > (SELECT AVG(value) FROM num) GROUP BY n.tag"
    con = _sec_db()
    full = con.execute(sql).fetchall()
    con.execute("CREATE TABLE num_usd AS SELECT * FROM num WHERE value < 800")
    wrong = con.execute(sql.replace("FROM num n", "FROM num_usd n").replace("FROM num)", "FROM num_usd)")).fetchall()
    assert sorted(map(repr, wrong)) != sorted(map(repr, full))


def test_same_table_in_outer_and_subquery_with_different_filters_pushes_their_disjunction() -> None:
    sql = (
        "SELECT n.tag, COUNT(*) AS c FROM num n WHERE n.uom = 'USD' AND n.ddate >= 20230101 "
        "AND n.value > (SELECT AVG(value) FROM num WHERE uom = 'pure' AND ddate >= 20230101) GROUP BY n.tag"
    )
    plan = plan_pushdown(sql, SEC, dialect="duckdb")
    assert _sql(plan, "num") == ['"ddate" >= 20230101', "(\"uom\" = 'USD') OR (\"uom\" = 'pure')"]
    sizes = _check(_sec_db(), sql, SEC)
    assert sizes["num"][1] < sizes["num"][0]


def test_correlated_exists_and_not_exists_push_the_subquerys_own_conjunct_and_never_the_correlation() -> None:
    for neg in ("", "NOT "):
        sql = (
            f"SELECT n.tag, COUNT(*) AS c FROM num n WHERE n.uom = 'USD' AND {neg}EXISTS "
            "(SELECT 1 FROM pre p WHERE p.adsh = n.adsh AND p.tag = n.tag AND p.stmt = 'BS') GROUP BY n.tag"
        )
        plan = plan_pushdown(sql, SEC, dialect="duckdb")
        assert _sql(plan, "pre") == ["\"stmt\" = 'BS'"] and _sql(plan, "num") == ["\"uom\" = 'USD'"]
        sizes = _check(_sec_db(), sql, SEC)
        assert sizes["pre"][1] < sizes["pre"][0]


def test_an_unqualified_outer_column_inside_a_subquery_is_a_correlation_not_a_local_filter() -> None:
    # fy is a column of sub (the outer block), not of pre: it must not be pushed to pre (nor to sub from inside the subquery).
    sql = "SELECT name, COUNT(*) AS c FROM sub WHERE EXISTS (SELECT 1 FROM pre WHERE pre.adsh = sub.adsh AND fy = 2022) GROUP BY name"
    plan = plan_pushdown(sql, SEC, dialect="duckdb")
    assert plan.pushed == {}
    _check(_sec_db(), sql, SEC)


def test_a_derived_table_reading_the_same_table_with_the_same_filters_q2_shape() -> None:
    sql = """
    SELECT s.name, n.tag, n.value
    FROM num n
    JOIN sub s ON n.adsh = s.adsh
    JOIN (SELECT adsh, tag, MAX(value) AS max_value FROM num WHERE uom = 'pure' AND value IS NOT NULL GROUP BY adsh, tag) m
      ON n.adsh = m.adsh AND n.tag = m.tag AND n.value = m.max_value
    WHERE n.uom = 'pure' AND s.fy = 2022 AND n.value IS NOT NULL
    """
    plan = plan_pushdown(sql, SEC, dialect="duckdb")
    assert _sql(plan, "num") == ["\"uom\" = 'pure'", 'NOT "value" IS NULL'] and _sql(plan, "sub") == ['"fy" = 2022']
    _check(_sec_db(), sql, SEC)


def test_a_self_join_with_a_filter_on_each_read_pushes_the_disjunction() -> None:
    sql = "SELECT a.tag, COUNT(*) AS c FROM num a, num b WHERE a.adsh = b.adsh AND a.uom = 'USD' AND b.uom = 'shares' GROUP BY a.tag"
    plan = plan_pushdown(sql, SEC, dialect="duckdb")
    assert _sql(plan, "num") == ["(\"uom\" = 'USD') OR (\"uom\" = 'shares')"]
    _check(_sec_db(), sql, SEC)


@pytest.mark.parametrize(
    "sql",
    [
        "WITH x AS (SELECT * FROM num) SELECT COUNT(*) AS c FROM x WHERE uom = 'USD'",
        "SELECT COUNT(*) AS c FROM num WHERE uom IN (SELECT stmt FROM pre UNION SELECT name FROM sub)",
    ],
)
def test_ctes_and_set_operations_still_refuse_the_whole_query(sql: str) -> None:
    plan = plan_pushdown(sql, SEC, dialect="duckdb")
    assert plan.pushed == {} and plan.refused
