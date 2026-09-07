"""Catalog table discovery for parsed SQL queries."""

from __future__ import annotations

from verus_transpiler.parse_sql import parse_sql
from verus_transpiler.query_tables import (
    catalog_tables_in_query,
    program_table_order,
    uses_multi_table_program,
)

from tests.test_sec_holdout_parse import SEC_SCHEMA

_EXISTS_NUM_PRE_SQL = """SELECT DISTINCT n.tag, n.version, COUNT(*) AS cnt
FROM num n
WHERE n.uom = 'shares' AND n.value IS NOT NULL
      AND EXISTS (SELECT 1 FROM pre p WHERE p.tag = n.tag AND p.version = n.version AND p.stmt = 'IS')
GROUP BY n.tag, n.version"""

_SINGLE_PRE_SQL = "SELECT COUNT(*) FROM pre WHERE line > 0"

_IN_NUM_PRE_SQL = """SELECT COUNT(*) FROM num n
WHERE n.tag IN (SELECT p.tag FROM pre p WHERE p.stmt = 'IS')"""

_FOUR_TABLE_JOIN_SQL = """SELECT s.name, s.sic, t.tlabel, p.stmt, p.plabel,
       SUM(n.value) AS total_value, COUNT(*) AS cnt
FROM num n
JOIN sub s ON n.adsh = s.adsh
JOIN tag t ON n.tag = t.tag AND n.version = t.version
JOIN pre p ON n.adsh = p.adsh AND n.tag = p.tag AND n.version = p.version
WHERE n.uom = 'USD' AND n.value IS NOT NULL AND t.abstract = 0
GROUP BY s.name, s.sic, t.tlabel, p.stmt, p.plabel"""


def test_exists_catalog_tables_outer_then_inner() -> None:
    query = parse_sql(_EXISTS_NUM_PRE_SQL, SEC_SCHEMA)
    assert catalog_tables_in_query(query) == ("num", "pre")


def test_exists_uses_multi_table_program() -> None:
    query = parse_sql(_EXISTS_NUM_PRE_SQL, SEC_SCHEMA)
    catalog = {t: SEC_SCHEMA[t] for t in ("num", "pre")}
    assert uses_multi_table_program(query, catalog) is True


def test_single_table_count_not_multi() -> None:
    query = parse_sql(_SINGLE_PRE_SQL, SEC_SCHEMA)
    assert catalog_tables_in_query(query) == ("pre",)
    assert uses_multi_table_program(query, SEC_SCHEMA) is False
    assert program_table_order(query, None) == ("pre",)


def test_four_table_join_lists_all_catalog_tables() -> None:
    query = parse_sql(_FOUR_TABLE_JOIN_SQL, SEC_SCHEMA)
    tables = catalog_tables_in_query(query)
    assert set(tables) == {"num", "sub", "tag", "pre"}
    assert len(tables) == 4
    catalog = {t: SEC_SCHEMA[t] for t in ("num", "sub", "tag", "pre")}
    assert uses_multi_table_program(query, catalog) is True


_IN_NUM_PRE_SQL = """SELECT COUNT(*) FROM num n
WHERE n.tag IN (SELECT p.tag FROM pre p WHERE p.stmt = 'IS')"""


def test_in_subquery_uses_multi_table_program() -> None:
    query = parse_sql(_IN_NUM_PRE_SQL, SEC_SCHEMA)
    catalog = {t: SEC_SCHEMA[t] for t in ("num", "pre")}
    assert catalog_tables_in_query(query) == ("num", "pre")
    assert uses_multi_table_program(query, catalog) is True


def test_program_table_order_respects_explicit_permutation() -> None:
    query = parse_sql(_FOUR_TABLE_JOIN_SQL, SEC_SCHEMA)
    catalog = {t: SEC_SCHEMA[t] for t in ("num", "sub", "tag", "pre")}
    default_order = program_table_order(query, catalog)
    permuted = program_table_order(
        query,
        catalog,
        table_order=("pre", "tag", "sub", "num"),
    )
    assert set(default_order) == set(permuted) == {"num", "sub", "tag", "pre"}
    assert permuted == ("pre", "tag", "sub", "num")
