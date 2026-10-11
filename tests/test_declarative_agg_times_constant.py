"""An aggregate times or divided by a constant (``0.5 * SUM(x)``, ``SUM(x) / 7.0``, ``0.2 * AVG(x)``).

Meaning, all against DuckDB on small random tables (<= 50 rows, zeros, an all-filtered empty answer):

* ``SUM(x) * K`` is DuckDB's exact DECIMAL product (scales add): the rewrite states it as the integer
  ``SUM(x * K)``; its integer SQL returns DuckDB's rows.
* ``SUM(x) / c`` is a DOUBLE quotient: the spec says ``v == (N / 10**sN) / (c / 10**sc)`` over the exact integer
  sum N (no zero branch, so no trusted division lemma); the formula agrees with DuckDB within 1e-9.
* ``c * AVG(x)`` is ``c * (sum / (count * 10**s))`` in reals; the same formula check.
No fixture here adds a trusted item: the emitted text carries no ``external_body`` and no ``assume``.
"""

from __future__ import annotations

import random
import re
from decimal import Decimal
from fractions import Fraction

import duckdb
import pytest

from declarative_spec.emit import emit_declarative_spec
from declarative_spec.numeric_rewrite import rewrite_numeric
from declarative_spec.parse import DeclarativeUnsupported
from research_loop.decl_query_measure import _canon, decimal_scaled
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

@pytest.fixture(autouse=True)
def _switch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests are about the shape being on: lemma.toml [sql] agg_times_constant."""
    monkeypatch.setenv("LEMMA_AGG_TIMES_CONSTANT", "1")


SCHEMA = {"t": {"d": "decimal(15,2)", "e": "decimal(10,3)", "i": "integer", "k": "integer"}}
CATALOG = CatalogAssumptions(
    max_rows=64,
    tables={
        "t": TableAssumptions(
            max_rows=64,
            columns={c: ColumnAssumption(max_value_exclusive=2**20) for c in "dei"},
        )
    },
)


def _trusted(spec: str) -> set[str]:
    """Names of the trusted (external_body) functions and assumptions a spec carries."""
    names = set(re.findall(r"external_body\][^{;]*?fn (\w+)", spec, flags=re.S))
    return names | {"assume"} if "assume(" in spec else names


def _rows(seed: int) -> list[tuple]:
    rng = random.Random(seed)
    return [
        (
            Decimal(rng.choice([0, 0, rng.randint(-9999, 9999)])) / 100,
            Decimal(rng.randint(-999, 999)) / 1000,
            rng.choice([0, rng.randint(-5, 5)]),
            rng.randint(0, 3),
        )
        for _ in range(rng.randint(0, 50))
    ]


def _dbs(rows: list[tuple]) -> tuple[duckdb.DuckDBPyConnection, duckdb.DuckDBPyConnection]:
    typed, ints = duckdb.connect(), duckdb.connect()
    typed.execute("CREATE TABLE t (d DECIMAL(15,2), e DECIMAL(10,3), i INTEGER, k INTEGER)")
    ints.execute("CREATE TABLE t (d HUGEINT, e HUGEINT, i INTEGER, k INTEGER)")
    typed.executemany("INSERT INTO t VALUES (?, ?, ?, ?)", rows)
    ints.executemany(
        "INSERT INTO t VALUES (?, ?, ?, ?)",
        [(decimal_scaled(r[0], 2), decimal_scaled(r[1], 3), r[2], r[3]) for r in rows],
    )
    return typed, ints


def _canon_row(row: tuple, scales: list[int]) -> tuple:
    return tuple(_canon("i128", v, s) if isinstance(v, Decimal) else v for v, s in zip(row, scales, strict=True))


_SUM_TIMES = [
    "SELECT SUM(d) * 3 AS a, 0.5 * SUM(d) AS b, SUM(e) * -0.25 AS c, SUM(i) * 7 AS g FROM t",
    "SELECT k, SUM(d * e) * 0.0001 AS a, 2 * SUM(i) AS b FROM t GROUP BY k",
    "SELECT k, SUM(d) AS s FROM t GROUP BY k HAVING SUM(d) * 100 > 5",
    "SELECT k, SUM(d) AS s FROM t GROUP BY k HAVING SUM(d) > (SELECT SUM(d) * 0.05 FROM t)",
    "SELECT SUM(d) * 0 AS z FROM t WHERE d > 99999",  # all rows filtered: both sides NULL
]


@pytest.mark.parametrize("sql", _SUM_TIMES)
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_sum_times_constant_is_the_exact_integer_sum(sql: str, seed: int) -> None:
    typed, ints = _dbs(_rows(seed))
    int_sql, scales = rewrite_numeric(sql, SCHEMA)
    want = sorted(_canon_row(r, scales) for r in typed.execute(sql).fetchall())
    got = sorted(tuple(r) for r in ints.execute(int_sql).fetchall())
    assert got == want


def test_the_constant_moves_into_the_sum_and_the_scale_adds() -> None:
    sql, scales = rewrite_numeric("SELECT 0.5 * SUM(d) AS b, SUM(d) * 0.0001 AS c FROM t", SCHEMA)
    assert "SUM((d) * 5)" in sql and "SUM((d) * 1)" in sql
    assert scales == [3, 6]


def test_a_sum_of_a_case_keeps_its_old_shape() -> None:
    sql, _ = rewrite_numeric("SELECT SUM(CASE WHEN k = 1 THEN d ELSE 0 END) * 2 AS a FROM t", SCHEMA)
    assert "SUM(CASE" in sql and "SUM((CASE" not in sql


def test_a_comparison_against_a_scaled_sum_subquery_emits_without_a_trusted_item() -> None:
    sql = (
        "SELECT k, SUM(d * e) AS v FROM t GROUP BY k "
        "HAVING SUM(d * e) > (SELECT SUM(d * e) * 0.0001000000 FROM t)"
    )
    spec = emit_declarative_spec(sql, SCHEMA, CATALOG)
    assert "external_body" not in spec and "assume(" not in spec
    assert "* (1000000)" in spec or "1000000" in spec


def test_a_scaled_sum_as_a_select_item_emits() -> None:
    spec = emit_declarative_spec("SELECT 0.5 * SUM(d) AS half FROM t", SCHEMA, CATALOG)
    assert "external_body" not in spec and "5" in spec


# ---- division by a constant -------------------------------------------------------------------------


@pytest.mark.parametrize(("divisor", "den", "sd"), [("7.0", 70, 1), ("4", 4, 0), ("0.125", 125, 3)])
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_division_by_a_constant_is_the_quotient_of_the_exact_natural_values(
    divisor: str, den: int, sd: int, seed: int
) -> None:
    rows = _rows(seed)
    typed, _ = _dbs(rows)
    got = typed.execute(f"SELECT SUM(d) / {divisor} FROM t").fetchone()[0]
    if not rows:
        assert got is None  # the spec marks the ratio nullable: SUM of no rows is NULL
        return
    n_int = sum(int(r[0] * 100) for r in rows)  # the exact integer sum N at scale 2
    want = (Fraction(n_int, 10**2)) / (Fraction(den, 10**sd))
    assert abs(float(want) - got) <= 1e-9 * max(1.0, abs(got))


def test_division_by_a_constant_is_stated_without_a_zero_branch() -> None:
    spec = emit_declarative_spec("SELECT SUM(d) / 7.0 AS avg_y FROM t", SCHEMA, CATALOG)
    assert "7" in spec and "70real" in spec
    assert "is_infinite_spec" not in spec and "is_nan_spec" not in spec  # no division by an aggregate that may be 0
    assert "host_f64_div_by_zero" not in spec
    # the trusted set is the one an AVG spec already has (the f64 idealization), nothing new
    assert _trusted(spec) <= _trusted(emit_declarative_spec("SELECT AVG(d) AS a FROM t", SCHEMA, CATALOG))


def test_division_by_a_constant_over_a_group_key_emits() -> None:
    spec = emit_declarative_spec("SELECT k, SUM(d) / 4 AS q, COUNT(*) AS c FROM t GROUP BY k", SCHEMA, CATALOG)
    assert "4real" in spec


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(d) / 0 AS a FROM t",
        "SELECT SUM(d) / 0.00 AS a FROM t",
        "SELECT 7.0 / SUM(d) AS a FROM t",
        "SELECT SUM(d) / (1 + 1) AS a FROM t",
        "SELECT MAX(d) / 7.0 AS a FROM t",
    ],
)
def test_other_divisions_stay_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        emit_declarative_spec(sql, SCHEMA, CATALOG)


# ---- a constant times AVG ----------------------------------------------------------------------------


@pytest.mark.parametrize("const", ["0.2", "3", "-0.5"])
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_constant_times_avg_is_the_product_of_the_exact_reals(const: str, seed: int) -> None:
    rows = _rows(seed)
    typed, _ = _dbs(rows)
    got = typed.execute(f"SELECT {const} * AVG(d), AVG(e) * {const} FROM t").fetchone()
    if not rows:
        assert got == (None, None)
        return
    for col, scale, value in ((0, 2, got[0]), (1, 3, got[1])):
        total = sum(int(r[col] * 10**scale) for r in rows)
        want = Fraction(const) * Fraction(total, len(rows) * 10**scale)
        assert abs(float(want) - value) <= 1e-9 * max(1.0, abs(value))


def test_constant_times_avg_states_the_exact_rational_factor() -> None:
    spec = emit_declarative_spec("SELECT 0.2 * AVG(d) AS a, AVG(d) * 3 AS b FROM t", SCHEMA, CATALOG)
    assert "* (1real) / ((c as real) * 500real)" in spec  # 0.2 = 1/5 over scale 2
    assert "* (3real) / ((c as real) * 100real)" in spec
    assert _trusted(spec) <= _trusted(emit_declarative_spec("SELECT AVG(d) AS a FROM t", SCHEMA, CATALOG))


def test_avg_without_a_constant_is_unchanged() -> None:
    spec = emit_declarative_spec("SELECT AVG(d) AS a FROM t", SCHEMA, CATALOG)
    assert "(c as real) * 100real" in spec and "* (1real)" not in spec
