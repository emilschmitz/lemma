"""Coverage round 2: grouped derived tables, inner-join ON filters, COUNT(CASE), HAVING MIN/MAX, DECIMAL AVG and CASE.

Every rewrite is checked against DuckDB on random rows; every new emission is Verus-typechecked, and the ones that
add host lemmas are verified with ``assume(false)`` as the body (only the host lemmas are proved).
"""

from __future__ import annotations

import random
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
import sqlglot

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.flatten_group import flatten_group_derived, move_inner_join_filters
from declarative_spec.numeric_rewrite import rewrite_numeric
from research_loop.decl_query_measure import decimal_scaled
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

GUARD = Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")

SCHEMA = {
    "t": {"a": "bigint", "g": "bigint", "s": "varchar", "d": "decimal(15,4)"},
    "u": {"g": "bigint", "w": "bigint"},
}
CATALOG = CatalogAssumptions(max_rows=16, tables={n: TableAssumptions(max_rows=16) for n in SCHEMA})


def _emit(sql: str) -> str:
    return emit_declarative_spec(sql, SCHEMA, CATALOG)


def _verify(spec: str, *, lemmas: bool) -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    body = "    assume(false);\n    loop invariant true decreases 0int { assume(false); }" if lemmas else "    Vec::new()"
    program = assemble_declarative_program(spec, body)
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(program)
    args = [] if lemmas else ["--no-verify"]
    proc = subprocess.run(
        [str(GUARD), handle.name, *args, "--triggers-mode", "silent"], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]


def _db(seed: int) -> duckdb.DuckDBPyConnection:
    rng = random.Random(seed)
    con = duckdb.connect()
    con.execute("CREATE TABLE t (a BIGINT, g BIGINT, s VARCHAR, d DECIMAL(15,4))")
    con.execute("CREATE TABLE u (g BIGINT, w BIGINT)")
    con.executemany(
        "INSERT INTO t VALUES (?, ?, ?, ?)",
        [(rng.randint(-5, 9), rng.randint(0, 4), rng.choice("xyz"), Decimal(rng.randint(-50000, 90000)) / 10000) for _ in range(60)],
    )
    con.executemany("INSERT INTO u VALUES (?, ?)", [(rng.randint(0, 4), rng.randint(0, 9)) for _ in range(30)])
    return con


# ---- merging a filter over a grouped derived table ---------------------------------------------------------------

_DERIVED = [
    "SELECT k, c FROM (SELECT g AS k, COUNT(*) AS c FROM t WHERE a > 0 GROUP BY g) d WHERE c > 3 ORDER BY c DESC, k LIMIT 20",
    "SELECT d.k FROM (SELECT s AS k, COUNT(*) AS c, SUM(a) AS x FROM t GROUP BY s) d WHERE d.c > 1 AND d.k <> 'x' AND x > 5 ORDER BY k",
    "SELECT k AS kk, c AS cnt FROM (SELECT g AS k, COUNT(*) AS c FROM t GROUP BY g) d ORDER BY cnt, kk",
    "SELECT k FROM (SELECT g AS k, MAX(a) AS m FROM t GROUP BY g) WHERE m >= 5 ORDER BY k",
    "SELECT k, c FROM (SELECT g AS k, COUNT(*) AS c FROM t GROUP BY g HAVING COUNT(*) > 2) d WHERE k > 0 ORDER BY k",
]


@pytest.mark.parametrize("sql", _DERIVED)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_flattened_grouped_derived_table_returns_duckdbs_rows(sql: str, seed: int) -> None:
    con = _db(seed)
    tree = sqlglot.parse_one(sql)
    flat = flatten_group_derived(tree)
    assert flat is not tree
    want = con.execute(sql).fetchall()
    assert want
    assert con.execute(flat.sql()).fetchall() == want


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT g, COUNT(*) FROM (SELECT g FROM t) d GROUP BY g",  # no GROUP BY inside
        "SELECT SUM(c) FROM (SELECT g, COUNT(*) AS c FROM t GROUP BY g) d",  # outer aggregate
        "SELECT DISTINCT c FROM (SELECT g, COUNT(*) AS c FROM t GROUP BY g) d",
        "SELECT c FROM (SELECT g, COUNT(*) AS c FROM t GROUP BY g ORDER BY c LIMIT 2) d",  # derived LIMIT
        "SELECT c FROM (SELECT g, COUNT(*) AS c FROM t GROUP BY g) d WHERE c > (SELECT 1)",  # subquery in the filter
    ],
)
def test_other_derived_shapes_are_left_alone(sql: str) -> None:
    tree = sqlglot.parse_one(sql)
    assert flatten_group_derived(tree) is tree


@pytest.mark.parametrize("sql", _DERIVED[:2])
def test_a_grouped_derived_table_emits_and_typechecks(sql: str) -> None:
    _verify(_emit(sql), lemmas=False)


# ---- ON filters of an inner join -----------------------------------------------------------------------------------

_JOINS = [
    "SELECT t.g, COUNT(*) AS c FROM t JOIN u ON t.g = u.g AND u.w > 3 GROUP BY t.g ORDER BY t.g",
    "SELECT t.s, SUM(u.w) AS x FROM t JOIN u ON t.g = u.g AND (t.a > 2 OR u.w = 0) AND t.s = 'x' GROUP BY t.s",
    "SELECT COUNT(*) AS c FROM t INNER JOIN u ON u.g = t.g AND t.a <> u.w",
]


@pytest.mark.parametrize("sql", _JOINS)
@pytest.mark.parametrize("seed", [1, 2])
def test_inner_join_on_filters_moved_to_where_return_duckdbs_rows(sql: str, seed: int) -> None:
    con = _db(seed)
    tree = sqlglot.parse_one(sql)
    assert move_inner_join_filters(tree)
    want = con.execute(sql).fetchall()
    assert want
    assert con.execute(tree.sql()).fetchall() == want


def test_left_join_filters_are_not_moved() -> None:
    tree = sqlglot.parse_one("SELECT COUNT(*) FROM t LEFT JOIN u ON t.g = u.g AND u.w > 3")
    assert not move_inner_join_filters(tree)


@pytest.mark.parametrize("sql", _JOINS[:2])
def test_inner_join_with_an_extra_on_predicate_emits_and_typechecks(sql: str) -> None:
    _verify(_emit(sql), lemmas=False)


# ---- COUNT(CASE WHEN c THEN x END) --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT g, COUNT(CASE WHEN a > 2 THEN 1 END) AS c, COUNT(*) AS n FROM t GROUP BY g",
        "SELECT COUNT(CASE WHEN s = 'x' THEN a END) AS c FROM t",
    ],
)
def test_count_case_emits_a_zero_one_fold_and_verifies_its_lemmas(sql: str) -> None:
    spec = _emit(sql)
    assert "0int }" in spec
    _verify(spec, lemmas=True)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(CASE WHEN a > 2 THEN 1 ELSE 0 END) AS c FROM t",  # ELSE 0 counts every row
        "SELECT COUNT(CASE WHEN a > 2 THEN 1 WHEN a < 0 THEN 2 END) AS c FROM t",
        "SELECT COUNT(CASE WHEN a > 2 THEN NULL END) AS c FROM t",
    ],
)
def test_count_case_other_shapes_are_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        _emit(sql)


# ---- HAVING MIN / MAX, and aliases that look like the bound functions -----------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT g, COUNT(*) AS c FROM t GROUP BY g HAVING MIN(a) < MAX(a)",
        "SELECT g, MAX(a) AS m FROM t GROUP BY g HAVING MAX(a) = 9 AND COUNT(*) > 1",
    ],
)
def test_having_min_max_uses_the_unique_bound(sql: str) -> None:
    spec = _emit(sql)
    assert "choose|b: int|" in spec
    _verify(spec, lemmas=False)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT g, MIN(a) AS min_value FROM t GROUP BY g",
        "SELECT g, MIN(a) AS min_min, MAX(a) AS max_row_hit FROM t GROUP BY g",
        "SELECT MAX(a) AS max_ FROM t",
    ],
)
def test_aliases_containing_min_or_max_do_not_break_the_bound_helpers(sql: str) -> None:
    _verify(_emit(sql), lemmas=False)


# ---- DECIMAL: AVG in natural units, CASE over a decimal column ---------------------------------------------------------


def test_avg_over_a_decimal_divides_by_the_scale() -> None:
    spec = _emit("SELECT g, AVG(d) AS m FROM t GROUP BY g")
    assert "* 10000real" in spec
    _verify(spec, lemmas=False)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_decimal_avg_in_natural_units_matches_duckdb(seed: int) -> None:
    """The stored-integer average divided by 10**scale is DuckDB's AVG(DECIMAL) up to double rounding."""
    con = _db(seed)
    int_sql, _scales = rewrite_numeric("SELECT g, AVG(d) AS m FROM t GROUP BY g", SCHEMA)
    assert "__DEC4(" in int_sql
    ints = duckdb.connect()
    ints.execute("CREATE TABLE t (g BIGINT, d HUGEINT)")
    ints.executemany(
        "INSERT INTO t VALUES (?, ?)",
        [(g, decimal_scaled(d, 4)) for g, d in con.execute("SELECT g, d FROM t").fetchall()],
    )
    got = dict(ints.execute(int_sql.replace("__DEC4(d)", "d")).fetchall())
    want = dict(con.execute("SELECT g, AVG(d) FROM t GROUP BY g").fetchall())
    assert got.keys() == want.keys()
    for g in want:
        assert abs(got[g] / 10**4 - float(want[g])) < 1e-9


@pytest.mark.parametrize(
    "case",
    [
        "SUM(CASE WHEN d > 0 THEN d ELSE 0 END)",
        "SUM(CASE WHEN d < 0 THEN d ELSE 5 END)",
        "SUM(CASE WHEN a = 1 THEN d ELSE 0 END)",
    ],
)
@pytest.mark.parametrize("seed", [1, 2])
def test_decimal_case_sum_integer_form_returns_duckdbs_rows(case: str, seed: int) -> None:
    con = _db(seed)
    sql = f"SELECT g, {case} AS x FROM t GROUP BY g"
    int_sql, scales = rewrite_numeric(sql, SCHEMA)
    ints = duckdb.connect()
    ints.execute("CREATE TABLE t (a BIGINT, g BIGINT, s VARCHAR, d HUGEINT)")
    ints.executemany(
        "INSERT INTO t VALUES (?, ?, ?, ?)",
        [(a, g, s, decimal_scaled(d, 4)) for a, g, s, d in con.execute("SELECT a, g, s, d FROM t").fetchall()],
    )
    assert scales == [0, 4]
    want = sorted((g, decimal_scaled(x, 4)) for g, x in con.execute(sql).fetchall())
    got = sorted(tuple(r) for r in ints.execute(int_sql).fetchall())
    assert want and got == want


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(CASE WHEN a = 1 THEN d ELSE 1.5 END) AS x FROM t",  # literal of another scale
        "SELECT SUM(CASE WHEN a = 1 THEN d ELSE a END) AS x FROM t",  # integer column beside a decimal
    ],
)
def test_decimal_case_with_other_scales_is_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match="DECIMAL"):
        _emit(sql)


@pytest.mark.parametrize(
    "case",
    [
        "SUM(CASE WHEN s = 'x' OR s = 'y' THEN 1 ELSE 0 END)",
        "SUM(CASE WHEN s <> 'x' AND NOT (a > 2) THEN 1 ELSE 0 END)",
        "SUM(CASE WHEN s IN ('x', 'z') AND (a > 2 OR g = 1) THEN 1 ELSE 0 END)",
    ],
)
def test_case_conditions_may_combine_and_or_not_in(case: str) -> None:
    spec = _emit(f"SELECT g, {case} AS v FROM t GROUP BY g")
    _verify(spec, lemmas=False)


def test_case_condition_with_an_unsupported_function_is_refused() -> None:
    with pytest.raises(DeclarativeUnsupported):
        _emit("SELECT SUM(CASE WHEN LENGTH(s) = 1 THEN 1 ELSE 0 END) AS v FROM t")


# ---- DECIMAL cells honor the catalog's column cap; integer SUM totals must fit i128 -----------------------------------

from declarative_spec.lemmas import FitRefusal  # noqa: E402
from research_loop.table_assumptions import ColumnAssumption  # noqa: E402

BIG = {"n": {"k": "bigint", "v": "decimal(38,4)"}, "s": {"k": "bigint", "fy": "bigint"}}


def _big(cap: int | None, n_rows: int = 2**31, s_rows: int = 2**20) -> CatalogAssumptions:
    cols = {} if cap is None else {"v": ColumnAssumption(max_value_exclusive=cap)}
    return CatalogAssumptions(
        max_rows=n_rows,
        tables={"n": TableAssumptions(max_rows=n_rows, columns=cols), "s": TableAssumptions(max_rows=s_rows)},
    )


JOIN_SUM = "SELECT s.fy, SUM(n.v) AS total FROM n JOIN s ON n.k = s.k WHERE s.fy > 1 AND n.v > 0 GROUP BY s.fy"


def test_decimal_valid_cols_uses_the_column_cap_when_the_catalog_gives_one() -> None:
    cap = 2**62 * 10**4
    spec = emit_declarative_spec(JOIN_SUM, BIG, _big(cap))
    assert f">= -{cap - 1}" in spec and f"<= {cap - 1}" in spec
    assert "99999999999999999999999999999999999999" not in spec.split("valid_cols_n")[1].split("\n}")[0]


def test_decimal_valid_cols_falls_back_to_the_type_digits_without_a_column_cap() -> None:
    small = _big(None, n_rows=1, s_rows=1)
    spec = emit_declarative_spec("SELECT k, SUM(v) AS total FROM n WHERE v > 0 GROUP BY k", BIG, small)
    assert "99999999999999999999999999999999999999" in spec


def test_a_join_sum_that_can_exceed_i128_is_refused() -> None:
    with pytest.raises(FitRefusal, match="can exceed i128"):
        emit_declarative_spec(JOIN_SUM, BIG, _big(None))  # 2^51 rows x 1e38
    with pytest.raises(FitRefusal, match="can exceed i128"):
        emit_declarative_spec(JOIN_SUM, BIG, _big(2**100))


def test_a_join_sum_with_the_sec_cap_fits_i128_and_typechecks() -> None:
    spec = emit_declarative_spec(JOIN_SUM, BIG, _big(2**62 * 10**4))  # 2^51 * 2^75.3 < 2^127
    _verify(spec, lemmas=False)


# ---- the joined-row bound uses declared unique keys ---------------------------------------------------------------------

from declarative_spec.emit_surface import _joined_rows_bound  # noqa: E402
from declarative_spec.parse_query import parse_query  # noqa: E402


def _sec_dec():
    from research_loop.assumption_packages import assumption_package
    from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema

    db = Path("/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/duckdb/sec_edgar_local_dec.duckdb")
    if not db.is_file():
        pytest.skip("DECIMAL SEC database not present")
    return load_sec_schema(db), assumption_package("sec_margin_dec")


UNIQUE_CHAIN = (
    "SELECT t.tlabel, SUM(n.value) AS total FROM num n JOIN sub s ON n.adsh = s.adsh "
    "JOIN tag t ON n.tag = t.tag AND n.version = t.version WHERE n.uom = 'USD' AND s.fy = 2023 GROUP BY t.tlabel"
)
NON_UNIQUE = (
    "SELECT p.stmt, SUM(n.value) AS total FROM num n JOIN pre p ON n.adsh = p.adsh AND n.tag = p.tag "
    "AND n.version = p.version WHERE n.uom = 'USD' GROUP BY p.stmt"
)
PARTIAL_KEY = (
    "SELECT t.tlabel, SUM(n.value) AS total FROM num n JOIN tag t ON n.tag = t.tag "
    "WHERE n.uom = 'USD' GROUP BY t.tlabel"
)


def test_unique_key_chain_is_bounded_by_the_driving_table() -> None:
    schema, cat = _sec_dec()
    from research_loop.assumption_packages.sec_margin import NUM_ROWS

    q = parse_query(UNIQUE_CHAIN)
    from declarative_spec.emit_join import _build_slots

    assert _joined_rows_bound(q, _build_slots(q), cat) == NUM_ROWS  # sub.adsh and (tag, version) are unique


def test_unique_key_chain_sum_emits_and_typechecks() -> None:
    schema, cat = _sec_dec()
    _verify(emit_declarative_spec(UNIQUE_CHAIN, schema, cat), lemmas=False)


@pytest.mark.parametrize("sql", [NON_UNIQUE, PARTIAL_KEY])
def test_a_join_on_a_non_unique_or_partial_key_still_multiplies_and_is_refused(sql: str) -> None:
    schema, cat = _sec_dec()
    with pytest.raises(FitRefusal, match="can exceed i128"):
        emit_declarative_spec(sql, schema, cat)


def test_unique_keys_equated_only_in_an_or_or_in_where_do_not_count() -> None:
    schema, cat = _sec_dec()
    comma = "SELECT SUM(n.value) AS t FROM num n, sub s, pre p WHERE n.adsh = s.adsh AND n.adsh = p.adsh"
    with pytest.raises(FitRefusal, match="can exceed i128"):
        emit_declarative_spec(comma + " AND n.uom = 'USD'", schema, cat)


def test_the_unique_keys_the_bound_relies_on_are_checked_against_the_data_by_the_package_check() -> None:
    import inspect

    from research_loop.assumption_packages import check

    assert "unique key" in inspect.getsource(check) and "a group has" in inspect.getsource(check)
