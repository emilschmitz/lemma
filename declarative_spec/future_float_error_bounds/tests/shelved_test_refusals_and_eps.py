"""What the f64 idealization still refuses, and the epsilon defaults (adversary verdict, 2026-10-04)."""

from __future__ import annotations

import pytest

from declarative_spec.bench import float_tolerance, rows_match_error
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.float_eps import default_float_abs_eps
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

SCHEMA = {"t": {"k": "integer", "v": "double", "w": "double", "n": "bigint", "d": "decimal(18,3)"}}


def _catalog(rows: int = 100, n_cap: int | None = 2**10, d_cap: int | None = None) -> CatalogAssumptions:
    cols = {c: ColumnAssumption(max_value_exclusive=2**10) for c in "vw"}
    if n_cap is not None:
        cols["n"] = ColumnAssumption(max_value_exclusive=n_cap)
    if d_cap is not None:
        cols["d"] = ColumnAssumption(max_value_exclusive=d_cap)
    return CatalogAssumptions(max_rows=rows, tables={"t": TableAssumptions(max_rows=rows, columns=cols)})


def _emit(sql: str, catalog: CatalogAssumptions | None = None) -> str:
    return emit_declarative_spec(sql, SCHEMA, catalog or _catalog(), float_abs_eps="0.000001")


# --- colliding float literals ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "both"),
    [
        ("SELECT COUNT(*) AS c FROM t WHERE v > 0.1 AND v < 0.10000000000000001", ("0.1", "0.10000000000000001")),
        ("SELECT COUNT(*) AS c FROM t WHERE v > 9007199254740992.0 AND w < 9007199254740993.0", ("9007199254740992", "9007199254740993")),
    ],
)
def test_two_decimals_that_round_to_one_double_are_refused_naming_both(sql: str, both: tuple[str, str]) -> None:
    with pytest.raises(DeclarativeUnsupported, match="same double") as info:
        _emit(sql)
    assert all(text in str(info.value) for text in both)


def test_a_literal_that_underflows_to_zero_is_refused() -> None:
    tiny = "0." + "0" * 400 + "1"
    with pytest.raises(DeclarativeUnsupported, match="not a finite nonzero double"):
        _emit(f"SELECT COUNT(*) AS c FROM t WHERE v > {tiny}")


def test_distinct_doubles_and_repeated_literals_are_fine() -> None:
    spec = _emit("SELECT COUNT(*) AS c FROM t WHERE v > 0.1 AND v < 0.2 AND w > 0.1")
    assert spec.count("(0.1f64 as real)") == 1


def test_constant_arithmetic_is_folded_exactly_like_duckdb_not_in_f64() -> None:
    spec = _emit("SELECT COUNT(*) AS c FROM t WHERE v >= 0.06 + 0.01")
    assert "(7real / 100real)" in spec
    assert "(0.07f64 as real) == (7real / 100real)" in spec


# --- float equality on computed values ------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS c FROM t WHERE v * w = 0.3",
        "SELECT COUNT(*) AS c FROM t WHERE v - w <> 0.5",
        "SELECT k, SUM(v) AS s FROM t GROUP BY k HAVING SUM(v) = 3",
        "SELECT k, AVG(v) AS s FROM t GROUP BY k HAVING AVG(v) = 3",
    ],
)
def test_float_equality_on_a_computed_value_is_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match="float equality on a computed value"):
        _emit(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS c FROM t WHERE v = 1.5",
        "SELECT COUNT(*) AS c FROM t WHERE v = w",
        "SELECT k, MAX(v) AS m FROM t WHERE v = 2 GROUP BY k",
        "SELECT k, SUM(v) AS s FROM t GROUP BY k HAVING SUM(v) > 3",
    ],
)
def test_equality_on_stored_values_and_ordering_on_computed_values_are_in_scope(sql: str) -> None:
    _emit(sql)


# --- AVG casts: exact only up to 2^53 -------------------------------------------------------------


def test_avg_whose_integer_sum_may_exceed_2_pow_53_is_refused_loudly() -> None:
    with pytest.raises(DeclarativeUnsupported, match="may exceed 2\\^53"):
        _emit("SELECT AVG(n) AS m FROM t", _catalog(rows=2**20, n_cap=2**40))
    with pytest.raises(DeclarativeUnsupported, match="may exceed 2\\^53"):
        _emit("SELECT AVG(n) AS m FROM t", _catalog(n_cap=None))  # the type's 2^63 decides, not a guess
    with pytest.raises(DeclarativeUnsupported, match="may exceed 2\\^53"):
        _emit("SELECT AVG(d) AS m FROM t", _catalog(rows=10**6))  # decimal(18,3): 10^18 per cell


def test_avg_within_2_pow_53_emits_and_states_the_cap() -> None:
    spec = _emit("SELECT AVG(n) AS m FROM t")
    assert "t.n@[i] as int >= -1023 && t.n@[i] as int <= 1023" in spec
    spec = _emit("SELECT AVG(d) AS m FROM t", _catalog(rows=100, d_cap=10**9))
    assert "avg_m_val" in spec


# --- epsilon ------------------------------------------------------------------------------------


def test_default_epsilon_is_relative_1e9_of_the_largest_float_sum() -> None:
    # rows 100, float cap 1024: 1e-9 * 102400 = 0.0001024
    assert default_float_abs_eps(_catalog(), SCHEMA) == "0.0001024"


def test_default_epsilon_has_a_floor_and_ignores_non_float_columns() -> None:
    no_float = CatalogAssumptions(max_rows=10, tables={"t": TableAssumptions(max_rows=10)})
    assert default_float_abs_eps(no_float, SCHEMA) == "0.000000001"
    assert default_float_abs_eps(None, SCHEMA) == "0.000000001"


def test_row_check_is_never_looser_than_relative_1e9_even_for_a_huge_epsilon() -> None:
    assert float_tolerance(1e20, 1000.0) == pytest.approx(1e-6 + 1e-9)
    assert float_tolerance(1e-12, 1000.0) == 1e-12
    assert rows_match_error([["1000.0001"]], [(1000.0,)], ["float"], "1e20") is not None
    assert rows_match_error([["1000.0000000001"]], [(1000.0,)], ["float"], "1e20") is None
