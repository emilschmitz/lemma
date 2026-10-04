"""TPC-H shapes in the declarative emitter: arithmetic aggregates, implicit joins,
exact constants (dates, intervals, decimal literals), string ORDER BY keys."""

from __future__ import annotations

import datetime as dt
import subprocess
import tempfile
from pathlib import Path

import duckdb
import pytest
import sqlglot

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.parse_exprs import fold_date, fold_number
from declarative_spec.parse_query import parse_query
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

VERUS = Path("/home/emil/tools/verus/verus")

SCHEMA = {
    "li": {
        "okey": "bigint",
        "qty": "integer",
        "price": "bigint",
        "disc": "integer",
        "tax": "integer",
        "flag": "varchar",
        "ship": "integer",
        "ratio": "double",
    },
    "ord": {"okey": "bigint", "ckey": "bigint", "odate": "integer", "total": "bigint"},
    "cust": {"ckey": "bigint", "seg": "varchar"},
}
CATALOG = CatalogAssumptions(
    max_rows=64,
    tables={t: TableAssumptions(max_rows=64) for t in SCHEMA},
)


def _typechecks(spec: str) -> str:
    program = assemble_declarative_program(spec, "    Vec::new()")
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(program)
    proc = subprocess.run(
        [str(VERUS), handle.name, "--no-verify", "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout + proc.stderr


def _date_int(text: str) -> int:
    return int(dt.date.fromisoformat(text).strftime("%Y%m%d"))


# ---- exact date folding, checked against DuckDB -------------------------------------------

_INTERVALS = [
    ("DATE '1998-12-01' - INTERVAL 90 DAY", "1998-12-01"),
    ("DATE '1994-01-01' + INTERVAL 1 YEAR", "1994-01-01"),
    ("DATE '1995-03-15' + INTERVAL 3 MONTH", "1995-03-15"),
    ("DATE '2000-01-31' + INTERVAL 1 MONTH", "2000-01-31"),
    ("DATE '1996-02-29' + INTERVAL 1 YEAR", "1996-02-29"),
    ("DATE '1996-03-31' - INTERVAL 1 MONTH", "1996-03-31"),
    ("DATE '1999-12-25' + INTERVAL 2 WEEK", "1999-12-25"),
]


@pytest.mark.parametrize(("sql", "_base"), _INTERVALS)
def test_date_interval_fold_matches_duckdb(sql: str, _base: str) -> None:
    got = fold_date(sqlglot.parse_one(f"SELECT {sql}").expressions[0])
    want = duckdb.sql(f"SELECT CAST({sql} AS DATE)").fetchone()[0]
    assert got == want.strftime("%Y%m%d")


def test_interval_unit_not_stated_exactly_is_refused() -> None:
    node = sqlglot.parse_one("SELECT DATE '2000-01-01' + INTERVAL 1 HOUR").expressions[0]
    with pytest.raises(DeclarativeUnsupported, match="unit"):
        fold_date(node)


def test_decimal_constant_folds_as_a_rational_not_a_float() -> None:
    node = sqlglot.parse_one("SELECT 0.06 - 0.01").expressions[0]
    value = fold_number(node)
    assert (value.numerator, value.denominator) == (1, 20)


# ---- decimal literal against an integer column ---------------------------------------------


def test_decimal_literal_compare_is_exact_integer_arithmetic() -> None:
    q = parse_query("SELECT SUM(price) AS s FROM li WHERE disc BETWEEN 0.06 - 0.01 AND 0.06 + 0.01")
    assert "disc" in q.where_expr
    assert "* 20 >= 1" in q.where_expr
    assert "* 100 <= 7" in q.where_expr


def test_decimal_literal_on_either_side_of_a_comparison() -> None:
    left = parse_query("SELECT SUM(price) AS s FROM li WHERE disc > 0.5").where_expr
    right = parse_query("SELECT SUM(price) AS s FROM li WHERE 0.5 < disc").where_expr
    assert left == right
    assert "* 2 > 1" in left


def test_decimal_literal_against_a_float_column_is_refused() -> None:
    sql = "SELECT SUM(price) AS s FROM li WHERE ratio > 0.5"
    with pytest.raises(DeclarativeUnsupported, match="integer column"):
        emit_declarative_spec(sql, SCHEMA, CATALOG)


def test_decimal_compare_spec_typechecks_in_verus() -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    spec = emit_declarative_spec(
        "SELECT SUM(price) AS s FROM li WHERE disc BETWEEN 0.06 - 0.01 AND 0.06 + 0.01"
        " AND ship >= DATE '1994-01-01' AND ship < DATE '1994-01-01' + INTERVAL 1 YEAR",
        SCHEMA,
        CATALOG,
    )
    assert "19950101" in spec
    assert "error" not in _typechecks(spec)


# ---- arithmetic inside aggregates ------------------------------------------------------------


def test_sum_of_product_is_integer_spec_arithmetic() -> None:
    spec = emit_declarative_spec(
        "SELECT flag, SUM(price * (1 - disc) * (1 + tax)) AS charge FROM li GROUP BY flag",
        SCHEMA,
        CATALOG,
    )
    assert "((li.price@[i0] as int) * ((1 - (li.disc@[i0] as int))))" in spec
    assert "pub charge: i128" in spec


def test_min_over_arithmetic_and_avg_over_arithmetic_emit() -> None:
    spec = emit_declarative_spec(
        "SELECT MIN(price - disc) AS lo, AVG(price * qty) AS mean FROM li",
        SCHEMA,
        CATALOG,
        float_abs_eps="1e20",
    )
    assert "min_lo" in spec
    assert "avg_mean" in spec


def test_arithmetic_over_a_float_column_is_refused() -> None:
    with pytest.raises(DeclarativeUnsupported, match="integer column"):
        emit_declarative_spec("SELECT SUM(price * ratio) AS s FROM li", SCHEMA, CATALOG)


@pytest.mark.parametrize("expr", ["price / 2", "price * 1.5", "price % 7"])
def test_arithmetic_whose_duckdb_type_is_not_integer_is_refused(expr: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        parse_query(f"SELECT SUM({expr}) AS s FROM li")


# ---- implicit joins and bare ON columns ------------------------------------------------------


_Q3_COMMA = (
    "SELECT li.okey, SUM(price * (1 - disc)) AS revenue, odate FROM cust, ord, li "
    "WHERE seg = 'BUILDING' AND cust.ckey = ord.ckey AND li.okey = ord.okey "
    "GROUP BY li.okey, odate"
)
_Q3_ON = (
    "SELECT li.okey, SUM(price * (1 - disc)) AS revenue, odate FROM cust "
    "JOIN ord ON cust.ckey = ord.ckey JOIN li ON li.okey = ord.okey "
    "WHERE seg = 'BUILDING' GROUP BY li.okey, odate"
)


def test_comma_join_is_every_row_triple_narrowed_by_where() -> None:
    q = parse_query(_Q3_COMMA)
    assert q.tables == ["cust", "ord", "li"]
    assert [j.on for j in q.joins] == [(), ()]
    assert "cust.ckey == ord.ckey" in q.where_expr


def test_bare_on_columns_are_qualified_from_the_schema() -> None:
    sql = (
        "SELECT SUM(price) AS s FROM li JOIN ord ON qty = total"  # qty/total are unique names
    )
    spec = emit_declarative_spec(sql, SCHEMA, CATALOG)
    assert "li.qty@[i0] == ord.total@[i1]" in spec


def test_ambiguous_bare_on_column_is_refused() -> None:
    with pytest.raises(DeclarativeUnsupported, match="ambiguous"):
        emit_declarative_spec("SELECT SUM(price) AS s FROM li JOIN ord ON okey = ckey", SCHEMA, CATALOG)


def test_comma_and_on_forms_state_the_same_condition_set() -> None:
    comma = emit_declarative_spec(_Q3_COMMA, SCHEMA, CATALOG)
    joined = emit_declarative_spec(_Q3_ON, SCHEMA, CATALOG)
    for equality in ("cust.ckey@[i0] as int) == (ord.ckey@[i1] as int", "li.okey@[i2] as int) == (ord.okey@[i1] as int"):
        assert equality in comma
    assert "cust.ckey@[i0] == ord.ckey@[i1]" in joined
    assert "li.okey@[i2] == ord.okey@[i1]" in joined


def test_comma_join_spec_typechecks_in_verus() -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    assert "error" not in _typechecks(emit_declarative_spec(_Q3_COMMA, SCHEMA, CATALOG))


# ---- ORDER BY over string group keys ---------------------------------------------------------


def test_order_by_string_group_key_uses_seq_le_on_the_view() -> None:
    spec = emit_declarative_spec(
        "SELECT flag, COUNT(*) AS n FROM li GROUP BY flag ORDER BY flag DESC",
        SCHEMA,
        CATALOG,
    )
    assert "seq_le(res@[i + 1].flag@, res@[i].flag@)" in spec
    assert spec.count("spec fn seq_le(") == 1


def test_order_by_string_then_integer_key_breaks_ties_on_the_view() -> None:
    spec = emit_declarative_spec(
        "SELECT flag, qty, COUNT(*) AS n FROM li GROUP BY flag, qty ORDER BY flag, qty",
        SCHEMA,
        CATALOG,
    )
    assert "if (res@[i].flag@) == (res@[i + 1].flag@)" in spec
    if VERUS.is_file():
        assert "error" not in _typechecks(spec)


# ---- HAVING on an aggregate the SELECT list does not show ------------------------------------


def test_having_aggregate_missing_from_select_is_a_hidden_aggregate() -> None:
    spec = emit_declarative_spec(
        "SELECT flag, COUNT(*) AS n FROM li GROUP BY flag HAVING SUM(qty) > 300",
        SCHEMA,
        CATALOG,
    )
    assert "sum_having_sum_0(" in spec
    out_row = spec.split("pub struct OutRow {")[1].split("}")[0]
    assert "having" not in out_row
    assert "pub n:" in out_row
    if VERUS.is_file():
        assert "error" not in _typechecks(spec)


def test_having_picks_the_aggregate_it_names_not_the_first_of_its_kind() -> None:
    q = parse_query(
        "SELECT flag, SUM(price) AS a, SUM(qty) AS b FROM li GROUP BY flag HAVING SUM(qty) > 5"
    )
    assert q.having_expr == "(b > 5)"
    assert [a.hidden for a in q.aggs] == [False, False]


def test_having_aggregate_over_arithmetic_is_hidden_and_exact() -> None:
    q = parse_query(
        "SELECT flag, SUM(price) AS a FROM li GROUP BY flag HAVING SUM(price * qty) > 10"
    )
    assert q.aggs[1].hidden
    assert q.aggs[1].arith == "(price * qty)"


# ---- IN (SELECT ...) -------------------------------------------------------------------------

_IN_GROUPED = (
    "SELECT ord.okey, SUM(qty) AS q FROM ord, li "
    "WHERE ord.okey IN (SELECT okey FROM li GROUP BY okey HAVING SUM(qty) > 300) "
    "AND li.okey = ord.okey GROUP BY ord.okey"
)


def test_in_subquery_group_having_is_exists_a_hit_row_of_a_passing_group() -> None:
    spec = emit_declarative_spec(_IN_GROUPED, SCHEMA, CATALOG)
    assert "spec fn in_1_in(li: &Cols_li, x: int) -> bool" in spec
    assert "in_1_key_at(li, i0) == x" in spec
    assert "in_1_sum_having_sum_0(li, 0, in_1_key_at(li, i0)) > 300" in spec
    assert "in_1_in(li, (ord.okey@[i0] as int))" in spec


def test_in_subquery_grouped_spec_typechecks_in_verus() -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    assert "error" not in _typechecks(emit_declarative_spec(_IN_GROUPED, SCHEMA, CATALOG))


def test_in_subquery_over_a_table_the_outer_query_lacks_adds_it_as_a_parameter() -> None:
    spec = emit_declarative_spec(
        "SELECT seg, COUNT(*) AS n FROM cust WHERE ckey IN (SELECT ckey FROM ord WHERE total > 5) GROUP BY seg",
        SCHEMA,
        CATALOG,
    )
    assert "pub fn run_query(cust: &Cols_cust, ord: &Cols_ord)" in spec
    assert "in_1_in(ord, (cust.ckey@[i0] as int))" in spec
    if VERUS.is_file():
        assert "error" not in _typechecks(spec)


def test_in_subquery_returning_an_aggregate_or_two_columns_is_refused() -> None:
    for sub in (
        "SELECT SUM(qty) FROM li",
        "SELECT okey, qty FROM li",
        "SELECT okey, COUNT(*) FROM li GROUP BY okey",
    ):
        sql = f"SELECT SUM(price) AS s FROM ord WHERE okey IN ({sub})"
        with pytest.raises(DeclarativeUnsupported):
            emit_declarative_spec(sql, SCHEMA, CATALOG)
