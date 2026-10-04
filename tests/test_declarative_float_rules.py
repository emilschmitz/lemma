"""Float rules of the declarative emitter.

A stored double may be compared with an integer literal up to 2**53 (exact in DuckDB and in the
spec's reals) and may be added or summed within epsilon. A sum or average of floats is never
compared, a float is never ordered by MIN/MAX, and two floats are never compared with each other.
"""

from __future__ import annotations

import random
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

GUARD = Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")

SCHEMA = {"t": {"k": "varchar", "q": "integer", "v": "double", "w": "double"}}
CATALOG = CatalogAssumptions(
    max_rows=64,
    tables={
        "t": TableAssumptions(
            max_rows=64,
            columns={
                "v": ColumnAssumption(max_value_exclusive=2**40),
                "w": ColumnAssumption(max_value_exclusive=2**40),
            },
        )
    },
)


def _emit(sql: str) -> str:
    return emit_declarative_spec(sql, SCHEMA, CATALOG)


def _typechecks(spec: str) -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    program = assemble_declarative_program(spec, "    Vec::new()")
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(program)
    proc = subprocess.run(
        [str(GUARD), handle.name, "--no-verify", "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]


# ---- a stored double against an integer literal ---------------------------------------------------


@pytest.mark.parametrize(
    "where, literal",
    [
        ("v > 0", "0real"),
        ("0 < v", "0real"),
        ("v BETWEEN 5 AND 10", "10real"),
        ("v = -5", "-5real"),
        ("v IN (1, 2)", "2real"),
        ("v <> 7", "7real"),
    ],
)
def test_float_column_against_integer_literal_is_a_real_comparison(where: str, literal: str) -> None:
    spec = _emit(f"SELECT COUNT(*) FROM t WHERE {where}")
    assert literal in spec
    assert "as real) > 0)" not in spec
    _typechecks(spec)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_duckdb_compares_a_double_with_an_integer_exactly(seed: int) -> None:
    """The spec's real comparison equals DuckDB's on doubles within one ulp of the literal."""
    import math

    rng = random.Random(seed)
    literals = [0, 1, -1, 7, 2**31, 2**53, -(2**53), rng.randrange(1, 2**53)]
    values: list[float] = []
    for k in literals:
        center = float(k)
        values += [center, math.nextafter(center, math.inf), math.nextafter(center, -math.inf)]
    con = duckdb.connect()
    con.execute("CREATE TABLE t (v DOUBLE)")
    con.executemany("INSERT INTO t VALUES (?)", [(v,) for v in values])
    for k in literals:
        for op, test in (
            (">", lambda x, k=k: Fraction(x) > k),
            ("<", lambda x, k=k: Fraction(x) < k),
            ("=", lambda x, k=k: Fraction(x) == k),
            (">=", lambda x, k=k: Fraction(x) >= k),
        ):
            want = sum(1 for v in values if test(v))
            got = con.execute(f"SELECT COUNT(*) FROM t WHERE v {op} {k}").fetchone()[0]
            assert got == want, (op, k)


@pytest.mark.parametrize(
    "where",
    [
        "v > q",  # an integer column is cast to double: not a literal
        "v > w",  # two doubles
        "v > 0.5",  # a decimal literal is not a double
        "v > 9007199254740993",  # beyond 2**53
        "v + 1 > 0",  # arithmetic on a double
    ],
)
def test_other_float_comparisons_are_refused(where: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        _emit(f"SELECT COUNT(*) FROM t WHERE {where}")


# ---- computed floats are never compared or ordered by MIN/MAX -------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT k, SUM(v) AS s FROM t GROUP BY k HAVING SUM(v) > 100",
        "SELECT k, AVG(v) AS a FROM t GROUP BY k HAVING AVG(v) > 1",
        "SELECT k FROM t WHERE v > (SELECT AVG(v) FROM t)",
        "SELECT k FROM t WHERE (SELECT SUM(v) FROM t) > 5",
    ],
)
def test_comparing_a_float_sum_or_average_is_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match="float"):
        _emit(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT MIN(v) FROM t",
        "SELECT k, MAX(v) AS m FROM t GROUP BY k",
        "SELECT k, MIN(v) AS m, MAX(v) AS x FROM t GROUP BY k",
    ],
)
def test_min_max_over_a_float_is_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match="MIN or MAX over a float"):
        _emit(sql)


def test_an_integer_average_still_compares_with_an_integer() -> None:
    # AVG of integers is an exact real quotient (sums below 2**53), so this stays supported.
    _typechecks(_emit("SELECT k FROM t WHERE q > (SELECT AVG(q) FROM t)"))


# ---- SUM / AVG over a CASE that returns a float ---------------------------------------------------


@pytest.mark.parametrize(
    "agg",
    [
        "SUM(CASE WHEN v > 0 THEN v ELSE 0 END)",
        "SUM(CASE WHEN v < 0 THEN v ELSE 0 END)",
        "AVG(CASE WHEN v > 0 THEN v ELSE 0 END)",
        "SUM(CASE WHEN v > 1000 THEN 1 ELSE 0 END)",
        "SUM(CASE WHEN q > 3 THEN v ELSE 0 END)",
    ],
)
def test_case_sum_over_a_float_emits_real_arms_and_typechecks(agg: str) -> None:
    spec = _emit(f"SELECT k, {agg} AS s FROM t GROUP BY k")
    _typechecks(spec)


def test_case_float_arm_is_a_real_zero() -> None:
    spec = _emit("SELECT SUM(CASE WHEN v > 0 THEN v ELSE 0 END) FROM t")
    assert "else { 0real }" in spec
    assert "else { 0int }" not in spec


def test_case_that_mixes_a_float_and_an_integer_column_is_refused() -> None:
    with pytest.raises(DeclarativeUnsupported, match="CASE"):
        _emit("SELECT SUM(CASE WHEN v > 0 THEN v ELSE q END) FROM t")


def test_float_case_without_a_catalog_magnitude_is_refused() -> None:
    from declarative_spec.lemmas import FitRefusal

    bare = CatalogAssumptions(max_rows=64, tables={"t": TableAssumptions(max_rows=64)})
    with pytest.raises(FitRefusal, match="magnitude"):
        emit_declarative_spec(
            "SELECT SUM(CASE WHEN v > 0 THEN v ELSE 0 END) FROM t", SCHEMA, bare
        )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT MIN(k) FROM t",
        "SELECT q, MAX(k) AS m FROM t GROUP BY q",
    ],
)
def test_min_max_over_a_string_is_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match="MIN or MAX over a str"):
        _emit(sql)


def test_min_max_over_an_integer_still_typechecks() -> None:
    _typechecks(_emit("SELECT k, MIN(q) AS lo, MAX(q) AS hi FROM t GROUP BY k"))


# ---- cases of the f64 idealization adversary (SQL only; the float lemma text is not ours) ---------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS c FROM t WHERE v > 0.1 AND v < 0.10000000000000001",  # colliding float literals
        "SELECT COUNT(*) AS c FROM t WHERE v * w = 0.3",  # float product compared
        "SELECT COUNT(*) AS c FROM t WHERE v > q",  # a double against a non-literal
        "SELECT k, SUM(v) AS s FROM t GROUP BY k HAVING SUM(v) > 0.6",  # HAVING on a float sum
        "SELECT COUNT(*) AS c FROM t WHERE v BETWEEN 0.06 - 0.01 AND 0.06 + 0.01",  # float against decimal constants
        "SELECT MIN(v) AS lo, MAX(v) AS hi FROM t",  # float MIN/MAX
        "SELECT SUM(v * q) AS s FROM t",  # double times an integer column
    ],
)
def test_adversary_float_queries_are_refused_by_the_emitter(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        _emit(sql)
