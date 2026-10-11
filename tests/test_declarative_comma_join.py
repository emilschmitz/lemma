"""Comma joins (``FROM a, b WHERE a.x = b.y``) are rewritten to inner equi-joins; cross products stay refused."""

from __future__ import annotations

import random

import duckdb
import pytest

from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.parse_query import rewrite_comma_joins

SCHEMA = {
    "fact": {"f_a": "integer", "f_b": "integer", "f_c": "integer", "f_v": "integer", "f_d": "integer"},
    "da": {"a_key": "integer", "a_attr": "integer"},
    "db": {"b_key": "integer", "b_attr": "varchar"},
    "dc": {"c_key": "integer", "c_attr": "integer"},
    "dd": {"d_key": "integer", "d_attr": "integer"},
}


def test_two_table_flight1_shape_becomes_inner_join():
    out = rewrite_comma_joins(
        "select sum(f_v * f_d) as r from fact, da where f_a = a_key and a_attr = 3 and f_d between 1 and 3", SCHEMA
    )
    assert "JOIN da ON f_a = a_key" in out
    assert "WHERE a_attr = 3 AND f_d BETWEEN 1 AND 3" in out
    assert "," not in out.split("FROM")[1].split("JOIN")[0]


def test_five_table_star_any_from_order():
    sql = (
        "select a_attr, sum(f_v) as s from da, db, dc, dd, fact "
        "where f_a = a_key and f_b = b_key and f_c = c_key and f_d = d_key and b_attr = 'x' group by a_attr"
    )
    out = rewrite_comma_joins(sql, SCHEMA)
    assert out.count(" JOIN ") == 4
    assert "FROM da JOIN fact ON" in out  # da is the root; fact is the only table it connects to
    assert "b_attr = 'x'" in out.split("WHERE")[1]
    assert "f_b = b_key" in out.split("JOIN db")[1].split("JOIN")[0]


def test_cross_product_is_refused():
    with pytest.raises(DeclarativeUnsupported, match="cross product"):
        rewrite_comma_joins("select count(*) as n from fact, da where f_v > 1", SCHEMA)
    with pytest.raises(DeclarativeUnsupported, match="'dc'"):
        rewrite_comma_joins("select count(*) as n from fact, da, dc where f_a = a_key", SCHEMA)


def test_explicit_join_untouched():
    sql = "select count(*) as n from fact join da on f_a = a_key"
    assert rewrite_comma_joins(sql, SCHEMA) == sql


def test_emit_comma_equals_explicit():
    comma = "select sum(f_v) as s from fact, da where f_a = a_key and a_attr = 3"
    explicit = "select sum(f_v) as s from fact join da on f_a = a_key where a_attr = 3"
    assert emit_declarative_spec(comma, SCHEMA) == emit_declarative_spec(explicit, SCHEMA)


def _random_db(seed: int) -> duckdb.DuckDBPyConnection:
    rnd = random.Random(seed)
    con = duckdb.connect()

    def maybe(v):
        return None if rnd.random() < 0.15 else v

    for name, cols in SCHEMA.items():
        ddl = ", ".join(f"{c} {'VARCHAR' if t == 'varchar' else 'INTEGER'}" for c, t in cols.items())
        con.execute(f"create table {name} ({ddl})")
        for _ in range(25):
            row = []
            for c, t in cols.items():
                row.append(maybe(rnd.choice(["x", "y"]) if t == "varchar" else rnd.randint(0, 5)))
            con.execute(f"insert into {name} values ({', '.join('?' for _ in row)})", row)  # duplicate keys on purpose
    return con


@pytest.mark.parametrize("seed", range(5))
def test_differential_against_duckdb(seed):
    con = _random_db(seed)
    queries = [
        "select sum(f_v * f_d) as r, count(*) as n from fact, da where f_a = a_key and a_attr < 4 and f_d between 1 and 3",
        "select a_attr, b_attr, sum(f_v) as s, count(*) as n from da, db, dc, fact "
        "where f_c = c_key and f_b = b_key and f_a = a_key and c_attr >= 2 group by a_attr, b_attr",
        "select d_attr, sum(f_v) as s from dd, fact, da, db, dc "
        "where f_d = d_key and a_key = f_a and b_key = f_b and c_key = f_c and f_v > 1 group by d_attr",
    ]
    for sql in queries:
        rewritten = rewrite_comma_joins(sql, SCHEMA)
        assert rewritten != sql and " JOIN " in rewritten
        want = sorted(map(repr, con.execute(sql).fetchall()))
        got = sorted(map(repr, con.execute(rewritten).fetchall()))
        assert got == want, sql
