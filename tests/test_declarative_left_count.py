"""LEFT JOIN ON predicate + COUNT over the right side + a count of counts (TPC-H Q13 shape).

The reading (``surface.CorrCount``): the rows of L are grouped by the number of right rows matching the ON equality AND the
other ON conjuncts. It equals the left join's per-key count when the key is unique in L. The meaning is checked against
DuckDB on small random tables (NULLs, zeros, empty groups, ties); the emission is Verus-typechecked with ``--no-verify``.
"""

from __future__ import annotations

import random
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.numeric_rewrite import rewrite_numeric
from declarative_spec.parse_query import parse_query
from research_loop.decl_query_measure import decimal_scaled
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

GUARD = Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")

@pytest.fixture(autouse=True)
def _switch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests are about the shape being on: lemma.toml [sql] left_join_count."""
    monkeypatch.setenv("LEMMA_LEFT_JOIN_COUNT", "1")


SCHEMA = {
    "l": {"k": "bigint", "g": "bigint"},
    "r": {"fk": "bigint", "c": "bigint", "w": "bigint", "s": "varchar", "d": "decimal(15,2)"},
}


def _catalog(*, unique: bool = True) -> CatalogAssumptions:
    return CatalogAssumptions(
        max_rows=64,
        tables={
            "l": TableAssumptions(max_rows=64, unique_keys=(("k",),) if unique else ()),
            "r": TableAssumptions(max_rows=64),
        },
    )


def _emit(sql: str, *, unique: bool = True) -> str:
    return emit_declarative_spec(sql, SCHEMA, _catalog(unique=unique))


def _derived(inner_on: str, count: str = "c", group: str = "k") -> str:
    return (
        f"SELECT n, COUNT(*) AS dist FROM (SELECT {group}, COUNT({count}) FROM l LEFT OUTER JOIN r ON k = fk {inner_on} "
        f"GROUP BY {group}) AS d (k, n) GROUP BY n ORDER BY dist DESC, n DESC"
    )


Q13_LIKE = _derived("AND s NOT LIKE '%a%b%'")
Q13_CMP = _derived("AND w > 2")


# ---- emission ----------------------------------------------------------------------------------------------------


def test_the_count_of_counts_groups_left_rows_by_the_keyed_count_fold_of_the_filtered_right_table() -> None:
    spec = _emit(Q13_CMP)
    assert "cc0_count_corr_n(r_t, 0, (l.k@[i0] as int))" in spec  # the group key of left row i0
    assert "((r_t.w@[i0] as int) > 2)" in spec.split("cc0_row_hit")[1].split("}")[0]  # the ON conjunct filters the right rows (and nothing else does)
    assert "count_dist(l, r_t, i0, k)" in spec  # the outer COUNT(*) counts left rows per key


def test_the_unique_key_the_reading_needs_is_required_of_the_data() -> None:
    spec = _emit(Q13_CMP)
    valid_l = spec.split("pub open spec fn valid_cols_l(")[1].split("pub open spec fn")[0]
    assert "!(l.k@[i] == l.k@[j])" in valid_l  # the loader asserts it before run_query
    assert "forall|i: int, j: int|" in valid_l


def test_a_catalog_without_the_unique_key_is_refused() -> None:
    with pytest.raises(DeclarativeUnsupported, match=r"l\.k is unique"):
        _emit(Q13_CMP, unique=False)
    with pytest.raises(DeclarativeUnsupported, match=r"l\.k is unique"):
        emit_declarative_spec(Q13_CMP, SCHEMA, None)


def test_a_not_like_conjunct_is_the_existing_spec_like() -> None:
    spec = _emit(Q13_LIKE)
    assert "!(spec_like(" in spec and "pub open spec fn spec_like(" in spec


def test_an_equality_only_left_join_count_is_the_same_shape() -> None:
    spec = _emit(_derived(""))
    assert "(true)" in spec.split("cc0_row_hit")[1].split("}")[0]  # no right row is filtered out


def test_the_derived_column_names_may_come_from_the_items_instead_of_the_alias_list() -> None:
    sql = (
        "SELECT n, COUNT(*) AS dist FROM (SELECT k AS key, COUNT(c) AS n FROM l LEFT JOIN r ON k = fk AND w > 2 GROUP BY k) d "
        "GROUP BY n ORDER BY n"
    )
    assert "cc0_count_corr_n(r_t, 0" in _emit(sql)


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        # COUNT(*) counts the NULL-extended row of an unmatched left row
        ("SELECT n, COUNT(*) AS dist FROM (SELECT k, COUNT(*) AS n FROM l LEFT JOIN r ON k = fk AND w > 2 GROUP BY k) d GROUP BY n", None),
        # the counted column belongs to the left table (it would count unmatched rows too)
        ("SELECT n, COUNT(*) AS dist FROM (SELECT k, COUNT(g) AS n FROM l LEFT JOIN r ON k = fk AND w > 2 GROUP BY k) d GROUP BY n", "right table"),
        # the inner GROUP BY is not the join key: groups are not rows of L
        ("SELECT n, COUNT(*) AS dist FROM (SELECT g, COUNT(c) AS n FROM l LEFT JOIN r ON k = fk AND w > 2 GROUP BY g) d GROUP BY n", "left key"),
        # a conjunct that reads the left table is a correlated filter, not a right-table filter
        ("SELECT n, COUNT(*) AS dist FROM (SELECT k, COUNT(c) AS n FROM l LEFT JOIN r ON k = fk AND w > g GROUP BY k) d GROUP BY n", "not a column of r"),
        ("SELECT n, COUNT(*) AS dist FROM (SELECT k, COUNT(c) AS n FROM l LEFT JOIN r ON k = fk AND l.g > 1 GROUP BY k) d GROUP BY n", "outside the right table"),
        # two equalities, or an OR
        ("SELECT n, COUNT(*) AS dist FROM (SELECT k, COUNT(c) AS n FROM l LEFT JOIN r ON k = fk AND g = w GROUP BY k) d GROUP BY n", "exactly one"),
        ("SELECT n, COUNT(*) AS dist FROM (SELECT k, COUNT(c) AS n FROM l LEFT JOIN r ON k = fk AND (w > 2 OR w < 0) GROUP BY k) d GROUP BY n", "OR"),
        # the outer query reads the key, or selects something else
        ("SELECT k, COUNT(*) AS dist FROM (SELECT k, COUNT(c) AS n FROM l LEFT JOIN r ON k = fk GROUP BY k) d GROUP BY n", None),
        ("SELECT n, SUM(n) AS dist FROM (SELECT k, COUNT(c) AS n FROM l LEFT JOIN r ON k = fk GROUP BY k) d GROUP BY n", "other than"),
        # a RIGHT/INNER join or a plain left join keeps its old refusal
        ("SELECT n, COUNT(*) AS dist FROM (SELECT k, COUNT(c) AS n FROM l JOIN r ON k = fk AND w > 2 GROUP BY k) d GROUP BY n", None),
    ],
)
def test_other_shapes_are_refused(sql: str, message: str | None) -> None:
    with pytest.raises(DeclarativeUnsupported, match=message) if message else pytest.raises(DeclarativeUnsupported):
        _emit(sql)


def test_a_left_join_on_predicate_outside_this_shape_is_still_refused() -> None:
    with pytest.raises(DeclarativeUnsupported, match="JOIN ON predicate"):
        parse_query("SELECT k, COUNT(c) AS n FROM l LEFT JOIN r ON k = fk AND w > 2 GROUP BY k")


# ---- the ON predicate gets the numeric rewrite (a DECIMAL literal in an ON conjunct was never scaled) --------------


def test_an_on_conjunct_with_a_decimal_literal_is_scaled_like_a_where_conjunct() -> None:
    sql, _ = rewrite_numeric(_derived("AND d > 1.5"), SCHEMA)
    assert "d > 150" in sql
    sql, _ = rewrite_numeric("SELECT COUNT(*) FROM l LEFT JOIN r ON k = fk AND d >= 0.25", SCHEMA)
    assert "d >= 25" in sql


# ---- the reading against DuckDB on small random tables -------------------------------------------------------------


def _db(seed: int, *, empty_right: bool = False) -> duckdb.DuckDBPyConnection:
    rng = random.Random(seed)
    con = duckdb.connect()
    con.execute("CREATE TABLE l (k BIGINT, g BIGINT)")
    con.execute("CREATE TABLE r (fk BIGINT, c BIGINT, w BIGINT, s VARCHAR, d DECIMAL(15,2))")
    keys = rng.sample(range(0, 30), rng.randint(1, 20))  # unique; some have no right row, some fall to zero by the filter
    con.executemany("INSERT INTO l VALUES (?, ?)", [(k, rng.randint(0, 3)) for k in keys])
    rows = [
        (
            rng.choice(keys + [40, 41]),  # fk values missing from L are dropped by the join
            rng.randint(0, 9),
            rng.choice([None, -1, 0, 1, 2, 3, 4]),  # NULLs and zeros: a NULL predicate drops the right row
            rng.choice([None, "ab", "axb", "ba", "", "a b"]),
            rng.choice([None, Decimal("0.00"), Decimal("1.50"), Decimal("1.51"), Decimal("-2.25"), Decimal("9.99")]),
        )
        for _ in range(0 if empty_right else rng.randint(1, 50))
    ]
    if rows:
        con.executemany("INSERT INTO r VALUES (?, ?, ?, ?, ?)", rows)
    return con


def _reading(sql: str) -> str:
    """The SQL the emitted spec states: group the rows of L by the count of right rows matching the key and the conjuncts."""
    cc = parse_query(sql).corr_counts[0]
    conds = [f"{cc.right_alias or cc.right}.fk = l.k"] + ([f"({cc.pred_sql})"] if cc.pred_sql else [])
    return (
        f"SELECT n, COUNT(*) AS dist FROM (SELECT (SELECT COUNT(*) FROM {cc.right} {cc.right_alias or ''} "
        f"WHERE {' AND '.join(conds)}) AS n FROM l) AS d GROUP BY n ORDER BY dist DESC, n DESC"
    )


_SQLS = [
    Q13_CMP,
    Q13_LIKE,
    _derived(""),
    _derived("AND w = 0"),
    _derived("AND w <> 1 AND s <> ''"),
    _derived("AND d > 1.5"),
    _derived("AND NOT (w > 2)"),
]


@pytest.mark.parametrize("sql", _SQLS)
@pytest.mark.parametrize("seed", range(12))
def test_the_reading_returns_duckdbs_rows(sql: str, seed: int) -> None:
    con = _db(seed)
    assert con.execute(_reading(sql)).fetchall() == con.execute(sql).fetchall()


@pytest.mark.parametrize("sql", _SQLS[:3])
def test_empty_right_table_gives_every_left_row_count_zero(sql: str) -> None:
    con = _db(3, empty_right=True)
    want = con.execute(sql).fetchall()
    n_left = con.execute("SELECT COUNT(*) FROM l").fetchone()[0]
    assert want == [(0, n_left)]
    assert con.execute(_reading(sql)).fetchall() == want


def test_the_reading_needs_the_unique_key() -> None:
    """With a repeated left key the left join multiplies counts, so the catalog's unique key is what makes the reading exact."""
    con = duckdb.connect()
    con.execute("CREATE TABLE l (k BIGINT, g BIGINT)")
    con.execute("CREATE TABLE r (fk BIGINT, c BIGINT, w BIGINT, s VARCHAR, d DECIMAL(15,2))")
    con.execute("INSERT INTO l VALUES (1, 0), (1, 0)")
    con.execute("INSERT INTO r VALUES (1, 1, 3, 'x', 1.00)")
    assert con.execute(Q13_CMP).fetchall() != con.execute(_reading(Q13_CMP)).fetchall()


@pytest.mark.parametrize("seed", range(6))
def test_the_integer_sql_of_a_decimal_on_conjunct_returns_duckdbs_rows(seed: int) -> None:
    sql = _derived("AND d > 1.5 AND d <= 9.99")
    integer_sql, _scales = rewrite_numeric(sql, SCHEMA)
    con = _db(seed)
    scaled = duckdb.connect()
    scaled.execute("CREATE TABLE l (k BIGINT, g BIGINT)")
    scaled.execute("CREATE TABLE r (fk BIGINT, c BIGINT, w BIGINT, s VARCHAR, d BIGINT)")
    scaled.executemany("INSERT INTO l VALUES (?, ?)", con.execute("SELECT * FROM l").fetchall())
    scaled.executemany(
        "INSERT INTO r VALUES (?, ?, ?, ?, ?)",
        [(*row[:4], None if row[4] is None else decimal_scaled(row[4], 2)) for row in con.execute("SELECT * FROM r").fetchall()],
    )
    assert scaled.execute(integer_sql).fetchall() == con.execute(sql).fetchall()


# ---- the emitted spec typechecks -----------------------------------------------------------------------------------


@pytest.mark.parametrize("sql", [Q13_CMP, Q13_LIKE])
def test_the_emission_typechecks(sql: str) -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    program = assemble_declarative_program(_emit(sql), "    Vec::new()")
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(program)
    proc = subprocess.run(
        [str(GUARD), handle.name, "--no-verify", "--triggers-mode", "silent"], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]


@pytest.mark.parametrize("nullable", [("r", "w"), ("r", "c"), ("r", "fk"), ("l", "k")])
def test_a_nullable_column_of_the_shape_is_refused_not_misread(nullable: tuple[str, str]) -> None:
    """The NULL pass refuses a nullable column in a JOIN condition and a nullable COUNT argument: no NULL semantics are guessed."""
    from research_loop.table_assumptions import ColumnAssumption

    table, col = nullable
    tables = {
        "l": TableAssumptions(max_rows=64, unique_keys=(("k",),)),
        "r": TableAssumptions(max_rows=64),
    }
    tables[table] = TableAssumptions(
        max_rows=64, unique_keys=tables[table].unique_keys, columns={col: ColumnAssumption(nullable=True)}
    )
    with pytest.raises(DeclarativeUnsupported, match="nullable"):
        emit_declarative_spec(Q13_CMP, SCHEMA, CatalogAssumptions(max_rows=64, tables=tables))
