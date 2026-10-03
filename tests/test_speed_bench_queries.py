from __future__ import annotations

from collections import Counter

import duckdb

from research_loop.adversary.significance import classify_difference, sql_demands_order
from research_loop.speed_bench.oracle import oracle_query
from research_loop.speed_bench.queries import QUERIES


def test_ten_unique_query_ids() -> None:
    ids = [q.id for q in QUERIES]
    assert len(ids) == 10
    assert len(set(ids)) == 10


def test_each_sql_references_t() -> None:
    for q in QUERIES:
        assert q.sql.strip()
        assert " t" in q.sql or q.sql.startswith("SELECT") and "FROM t" in q.sql or "JOIN" in q.sql


def test_q10_has_order_and_limit() -> None:
    q10 = next(q for q in QUERIES if q.id == "q10_top")
    assert "ORDER BY" in q10.sql.upper()
    assert "LIMIT" in q10.sql.upper()


def test_q01_no_order_by() -> None:
    q01 = next(q for q in QUERIES if q.id == "q01_filter_sum")
    assert not sql_demands_order(q01.sql)


def _duckdb_oracle(n: int, sql: str) -> list[tuple]:
    con = duckdb.connect()
    try:
        con.execute(
            f"""
            CREATE TABLE t AS
            SELECT
                (i % 32)::INTEGER AS k,
                (i % 8)::INTEGER AS k2,
                (i % 10000)::INTEGER AS d,
                CASE WHEN i % 7 = 0 THEN 1 ELSE 0 END AS flag,
                ((i * 17) % 1000)::BIGINT AS amount,
                (i % 1000)::INTEGER AS dim_id
            FROM range(0, {n}) AS r(i)
            """
        )
        con.execute(
            """
            CREATE TABLE dim AS
            SELECT j::INTEGER AS id, (j * 3)::BIGINT AS w
            FROM range(0, 1000) AS r(j)
            """
        )
        return [tuple(r) for r in con.execute(sql).fetchall()]
    finally:
        con.close()


def test_oracle_matches_duckdb_n50() -> None:
    n = 50
    for q in QUERIES:
        duck = _duckdb_oracle(n, q.sql)
        py = oracle_query(q.id, n)
        if q.id == "q10_top":
            assert py == duck
        else:
            v = classify_difference(q.sql, py, duck)
            assert not v.significant, (q.id, v.reason, Counter(py), Counter(duck))
