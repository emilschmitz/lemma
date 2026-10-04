"""IS TRUE on an integer is non-zero, not the IS NOT NULL constant."""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError
from verus_transpiler.transpiler import transpile_sql_to_verus

_INT = {"t": {"a": "BIGINT"}}
_BOOL = {"t": {"a": "BOOLEAN"}}
_STR = {"t": {"s": "VARCHAR"}}


def test_integer_is_true_is_nonzero_and_is_false_is_zero() -> None:
    true_sql = transpile_sql_to_verus("SELECT COUNT(*) FROM t WHERE a IS TRUE", _INT)
    assert "cols.get_a(k) != 0" in true_sql
    assert "if true" not in true_sql
    false_sql = transpile_sql_to_verus("SELECT COUNT(*) FROM t WHERE a IS FALSE", _INT)
    assert "cols.get_a(k) == 0" in false_sql


def test_bool_is_true_and_not_is_true_and_string_is_refused() -> None:
    flag = transpile_sql_to_verus("SELECT COUNT(*) FROM t WHERE a IS TRUE", _BOOL)
    assert "cols.get_a(k) == true" in flag
    negated = transpile_sql_to_verus("SELECT COUNT(*) FROM t WHERE a IS NOT TRUE", _INT)
    assert "!(cols.get_a(k) != 0)" in negated
    with pytest.raises(UnsupportedContractError, match="string"):
        transpile_sql_to_verus("SELECT COUNT(*) FROM t WHERE s IS TRUE", _STR)


def test_comparison_is_true_is_the_predicate() -> None:
    src = transpile_sql_to_verus(
        "SELECT COUNT(*) FROM t WHERE (a > 0) IS TRUE",
        _INT,
    )
    assert "cols.get_a(k) > 0" in src
    false_src = transpile_sql_to_verus(
        "SELECT COUNT(*) FROM t WHERE (a > 0) IS FALSE",
        _INT,
    )
    assert "!(cols.get_a(k) > 0)" in false_src or "!((" in false_src
