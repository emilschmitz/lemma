"""Derived EXCEPT and INTERSECT stay in the method spec.

Flattening them used to count the left table. ``EXCEPT`` of a table with
itself is empty in DuckDB and was a proved count of every row.
"""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError
from verus_transpiler.transpiler import transpile_sql_to_verus

_SCHEMA = {"t": {"a": "INTEGER"}}


def _method_spec_body(src: str) -> str:
    start = src.index("pub open spec fn method_spec(")
    rest = src[start:]
    return rest[: rest.index("\n}")]


def test_derived_except_count_is_the_set_difference() -> None:
    sql = "SELECT COUNT(a) FROM (SELECT a FROM t EXCEPT SELECT a FROM t) d"
    body = _method_spec_body(transpile_sql_to_verus(sql, _SCHEMA))
    assert "spec_seq_except(derived_d_left_spec(cols), derived_d_right_spec(cols))" in body
    assert ".len() as u64" in body
    assert "method_spec_helper" not in body


def test_derived_intersect_count_is_the_intersection() -> None:
    sql = "SELECT COUNT(*) FROM (SELECT a FROM t INTERSECT SELECT a FROM t) d"
    body = _method_spec_body(transpile_sql_to_verus(sql, _SCHEMA))
    assert "spec_seq_intersect(derived_d_left_spec(cols), derived_d_right_spec(cols))" in body
    assert ".len() as u64" in body
    assert "method_spec_helper" not in body


def test_derived_except_sum_and_filter_are_not_silently_dropped() -> None:
    with pytest.raises(UnsupportedContractError, match="over derived EXCEPT"):
        transpile_sql_to_verus(
            "SELECT SUM(a) FROM (SELECT a FROM t EXCEPT SELECT a FROM t) d",
            _SCHEMA,
        )
    with pytest.raises(UnsupportedContractError, match="filter over a derived set"):
        transpile_sql_to_verus(
            "SELECT COUNT(*) FROM (SELECT a FROM t EXCEPT SELECT a FROM t) d WHERE a = 1",
            _SCHEMA,
        )


def test_nested_except_is_refused() -> None:
    sql = (
        "SELECT COUNT(*) FROM (SELECT a FROM t EXCEPT SELECT a FROM t "
        "EXCEPT SELECT a FROM t) d"
    )
    with pytest.raises(UnsupportedContractError, match="nested set operations"):
        transpile_sql_to_verus(sql, _SCHEMA)
