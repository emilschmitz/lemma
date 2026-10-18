"""WITH names used more than once: in FROM and inside a scalar subquery (TPC-H Q15 shape), and twice in FROM."""

from __future__ import annotations

import dataclasses
import random

import duckdb
import pytest
import sqlglot

from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.fold_group_join import fold_group_join
from declarative_spec.inline_cte import inline_plain_ctes
from declarative_spec.parse_query import parse_query
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

@pytest.fixture(autouse=True)
def _switch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests are about the shape being on: lemma.toml [sql] cte_reuse."""
    monkeypatch.setenv("LEMMA_CTE_REUSE", "1")


SCHEMA = {
    "li": {"supp": "bigint", "price": "bigint", "disc": "integer", "ship": "date"},
    "sup": {"skey": "bigint", "sname": "varchar"},
}


def _catalog(unique: bool) -> CatalogAssumptions:
    return CatalogAssumptions(
        max_rows=64,
        tables={
            t: TableAssumptions(
                max_rows=64,
                columns={
                    c: ColumnAssumption(max_value_exclusive=2**20) for c, ty in SCHEMA[t].items() if ty in ("bigint", "integer")
                },
                unique_keys=(("skey",),) if unique and t == "sup" else (),
            )
            for t in SCHEMA
        },
    )


REVENUE = (
    "WITH rev AS (SELECT supp AS sno, SUM(price * (100 - disc)) AS total FROM li "
    "WHERE ship >= DATE '1996-01-01' AND ship < DATE '1996-04-01' GROUP BY sno) "
)
Q15_SHAPE = (
    REVENUE + "SELECT skey, sname, total FROM sup, rev WHERE skey = sno AND total = (SELECT MAX(total) FROM rev) ORDER BY skey"
)


def _emit(sql: str, unique: bool = True) -> str:
    """The spec without the comment that quotes the SQL above run_query (two spellings of one query differ only there)."""
    spec = emit_declarative_spec(sql, SCHEMA, _catalog(unique))
    return "\n".join(line for line in spec.splitlines() if not line.startswith(("// SQL (", "//     ")))


# --- parsing ---------------------------------------------------------------------------------------------------------


def test_a_with_name_in_from_and_in_a_scalar_subquery_parses_to_a_grouped_query_over_a_derived_scalar() -> None:
    q = parse_query(Q15_SHAPE)
    assert q.tables == ["sup", "li"] and q.group_columns == ["skey", "sname"]
    assert q.having_expr and "sq_1" in q.having_expr
    (_name, scalar) = q.scalar_subqueries[0]
    assert scalar.aggs[0].kind == "MAX" and scalar.derived[0][0] == "rev"
    assert scalar.derived[0][1].group_columns == ["sno"]
    assert q.unique_needed == [("sup", "skey")]


def test_a_with_name_in_a_scalar_subquery_alone_substitutes_the_definition() -> None:
    q = parse_query(REVENUE + "SELECT COUNT(*) AS n FROM li WHERE price = (SELECT MAX(total) FROM rev)")
    assert q.scalar_subqueries[0][1].derived[0][1].aggs[0].alias == "total"


# --- emission --------------------------------------------------------------------------------------------------------


def test_the_group_join_shape_emits_a_max_over_the_groups_of_the_with_name() -> None:
    from declarative_spec.agent_scan import without_scans

    spec = without_scans(_emit(Q15_SHAPE))  # the authorized agent-scan block is the only trusted item (tests/test_agent_scan.py)
    assert "_ext(" in spec and "Option<int>" in spec
    assert "arbitrary()" not in spec and "assume(" not in spec and "external_body" not in spec


def test_the_group_join_shape_needs_a_declared_unique_key() -> None:
    with pytest.raises(DeclarativeUnsupported, match="declared unique key"):
        _emit(Q15_SHAPE, unique=False)


@pytest.mark.parametrize(
    "sql",
    [
        # a condition mixing the group key and the table's column beyond the key equality
        REVENUE + "SELECT skey, total FROM sup, rev WHERE skey = sno AND total > skey",
        # no equality of the key to a table column
        REVENUE + "SELECT skey, total FROM sup, rev WHERE total = (SELECT MAX(total) FROM rev)",
        # the join column is not kept by the SELECT list
        REVENUE + "SELECT sname, total FROM sup, rev WHERE skey = sno AND total = (SELECT MAX(total) FROM rev)",
    ],
)
def test_unsupported_group_join_shapes_are_refused_loudly(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        _emit(sql)


def test_a_left_join_of_a_grouped_with_name_is_refused() -> None:
    with pytest.raises(DeclarativeUnsupported):
        _emit(REVENUE + "SELECT skey, total FROM sup LEFT JOIN rev ON skey = sno")


@pytest.mark.parametrize(
    "by_alias",
    [
        "SELECT supp AS s, SUM(price) AS t FROM li GROUP BY s",
        "SELECT supp AS s, COUNT(*) AS t FROM li WHERE disc > 0 GROUP BY s",
    ],
)
def test_group_by_a_select_alias_is_the_same_spec_as_group_by_the_column(by_alias: str) -> None:
    assert _emit(by_alias) == _emit(by_alias.replace("GROUP BY s", "GROUP BY supp"))


# --- a plain WITH name used twice in FROM ----------------------------------------------------------------------------

TWICE = (
    "WITH x AS (SELECT supp, price FROM li WHERE disc > 2) "
    "SELECT p.supp, COUNT(*) AS n FROM x p JOIN x q ON p.supp = q.supp WHERE p.price > 5 GROUP BY p.supp"
)
TWICE_DIRECT = (
    "SELECT p.supp, COUNT(*) AS n FROM li p JOIN li q ON p.supp = q.supp "
    "WHERE p.price > 5 AND p.disc > 2 AND q.disc > 2 GROUP BY p.supp"
)


def test_a_plain_with_name_used_twice_in_from_is_the_table_twice_with_its_filter_per_use() -> None:
    q = parse_query(TWICE)
    assert q.tables == ["li", "li"] and set(q.aliases) == {"p", "q"}
    assert q.where_expr.count("disc") == 2


def test_a_plain_with_name_used_twice_emits_the_same_spec_as_the_inlined_query() -> None:
    assert _emit(TWICE) == _emit(TWICE_DIRECT)


def test_a_with_body_that_renames_or_computes_is_not_inlined() -> None:
    inlined = inline_plain_ctes(sqlglot.parse_one("WITH x AS (SELECT supp AS s FROM li) SELECT s FROM x"))
    assert inlined.sql().startswith("WITH x") and "FROM x" in inlined.sql()


# --- differential: the rewrites select the same rows in DuckDB -------------------------------------------------------


def _con(rng: random.Random) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE TABLE li (supp BIGINT, price BIGINT, disc INTEGER, ship DATE)")
    con.execute("CREATE TABLE sup (skey BIGINT, sname VARCHAR)")
    keys = list(range(rng.randint(1, 8)))
    rng.shuffle(keys)
    for k in keys:
        con.execute("INSERT INTO sup VALUES (?, ?)", [k, rng.choice(["a", "b", None])])
    for _ in range(rng.randint(0, 50)):
        con.execute(
            "INSERT INTO li VALUES (?, ?, ?, ?)",
            [
                rng.choice([None, *range(0, 10)]),  # suppliers without a sup row, NULL keys
                rng.choice([None, 0, 0, 1, 5, 5, 7]),  # NULLs, zeros, ties
                rng.choice([None, 0, 1, 3, 3, 100]),
                rng.choice(["1995-12-31", "1996-01-01", "1996-02-10", "1996-03-31", "1996-04-01", None]),
            ],
        )
    return con


def _rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[tuple]:
    return sorted(con.execute(sql).fetchall(), key=repr)


def test_group_join_rewrite_selects_the_same_rows_as_the_join_in_duckdb() -> None:
    folded, needed = fold_group_join(sqlglot.parse_one(Q15_SHAPE))
    assert needed == [("sup", "skey")]
    rewritten = folded.sql(dialect="duckdb")
    assert "GROUP BY" in rewritten and "HAVING" in rewritten
    nonempty = 0
    for seed in range(60):
        con = _con(random.Random(seed))
        want = _rows(con, Q15_SHAPE)
        assert _rows(con, rewritten) == want, (seed, rewritten)
        nonempty += bool(want)
    assert nonempty >= 10  # the comparison is not vacuous


def test_group_join_rewrite_with_a_threshold_and_a_filter_selects_the_same_rows_in_duckdb() -> None:
    sql = REVENUE + "SELECT skey, total FROM sup, rev WHERE skey = sno AND total > 4 AND sname = 'a' ORDER BY skey"
    folded, _ = fold_group_join(sqlglot.parse_one(sql))
    for seed in range(60):
        con = _con(random.Random(100 + seed))
        assert _rows(con, folded.sql(dialect="duckdb")) == _rows(con, sql), seed


def test_inlined_plain_with_name_selects_the_same_rows_in_duckdb() -> None:
    inlined = inline_plain_ctes(sqlglot.parse_one(TWICE)).sql(dialect="duckdb")
    for seed in range(40):
        con = _con(random.Random(200 + seed))
        assert _rows(con, inlined) == _rows(con, TWICE), seed


def test_dataclass_catalog_is_not_mutated_by_the_unique_key_check() -> None:
    cat = _catalog(unique=False)
    with pytest.raises(DeclarativeUnsupported):
        emit_declarative_spec(Q15_SHAPE, SCHEMA, cat)
    assert cat.tables["sup"].unique_keys == ()
    assert dataclasses.is_dataclass(cat)
