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


# ---- LIKE ------------------------------------------------------------------------------------


def _spec_like(s: str, p: str) -> bool:
    """Python mirror of ``SPEC_LIKE_FN``, line for line."""
    if not p:
        return not s
    if p[0] == "%":
        return _spec_like(s, p[1:]) or (len(s) > 0 and _spec_like(s[1:], p))
    if not s:
        return False
    if p[0] == "_" or p[0] == s[0]:
        return _spec_like(s[1:], p[1:])
    return False


_LIKE_CASES = [
    ("forest green", "%green%"),
    ("greenhouse", "%green%"),
    ("gren", "%green%"),
    ("green", "green"),
    ("Green", "green"),
    ("", "%"),
    ("", "_"),
    ("a", "_"),
    ("ab", "a_"),
    ("abc", "a_"),
    ("a%c", "a%c"),
    ("a\\c", "a\\c"),
    ("a_c", "a_c"),
    ("abc", "%%c"),
    ("abcabc", "a%c%c"),
    ("naïve", "na_ve"),
    ("naïve", "%ï%"),
    ("x", ""),
    ("", ""),
]


@pytest.mark.parametrize(("value", "pattern"), _LIKE_CASES)
def test_spec_like_agrees_with_duckdb_like(value: str, pattern: str) -> None:
    got = duckdb.execute("SELECT ? LIKE ?", [value, pattern]).fetchone()[0]
    assert _spec_like(value, pattern) == got


def test_like_emits_spec_like_over_the_string_view_and_not_like_negates() -> None:
    pos = emit_declarative_spec(
        "SELECT COUNT(*) AS n FROM cust WHERE seg LIKE 'BUILD%'", SCHEMA, CATALOG
    )
    neg = emit_declarative_spec(
        "SELECT COUNT(*) AS n FROM cust WHERE seg NOT LIKE '%ING'", SCHEMA, CATALOG
    )
    assert 'spec_like((cust.seg@[i0]@), "BUILD%"@)' in pos
    assert '!(spec_like((cust.seg@[i0]@), "%ING"@))' in neg
    assert pos.count("spec fn spec_like(") == 1
    if VERUS.is_file():
        for spec in (pos, neg):
            assert "error" not in _typechecks(spec)


def test_spec_like_function_verifies_in_verus() -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    from declarative_spec.emit_like import SPEC_LIKE_FN

    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(f"use vstd::prelude::*;\nverus! {{\n{SPEC_LIKE_FN}\n}}\nfn main() {{}}\n")
    proc = subprocess.run([str(VERUS), handle.name], capture_output=True, text=True, check=False)
    assert "0 errors" in proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "where",
    [
        "seg LIKE 'a' ESCAPE '!'",
        "seg LIKE ckey",
        "seg ILIKE 'a%'",
        "seg LIKE 'a\"b'",
        "seg LIKE 'a\\b'",
    ],
)
def test_like_forms_not_stated_exactly_are_refused(where: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        emit_declarative_spec(f"SELECT COUNT(*) AS n FROM cust WHERE {where}", SCHEMA, CATALOG)


# ---- EXTRACT and derived tables --------------------------------------------------------------


@pytest.mark.parametrize("part", ["year", "month", "day"])
def test_extract_text_matches_duckdb_on_yyyymmdd_integers(part: str) -> None:
    from declarative_spec.parse_exprs import extract_text

    node = sqlglot.parse_one(f"SELECT EXTRACT({part} FROM d)").expressions[0]
    text = extract_text(node, lambda c: "D", [])
    for day in (dt.date(1992, 1, 1), dt.date(1996, 2, 29), dt.date(1998, 12, 31), dt.date(2000, 7, 4)):
        want = duckdb.execute(f"SELECT EXTRACT({part} FROM DATE '{day}')").fetchone()[0]
        got = eval(text.replace("/", "//"), {"D": int(day.strftime("%Y%m%d"))})
        assert got == want


def test_extract_of_an_unsupported_part_is_refused() -> None:
    with pytest.raises(DeclarativeUnsupported, match="EXTRACT"):
        parse_query("SELECT y FROM (SELECT EXTRACT(week FROM ship) AS y FROM li) AS t")


_PROFIT = (
    "SELECT flag, yr, SUM(amt) AS total FROM ("
    " SELECT flag AS flag, EXTRACT(year FROM odate) AS yr, price * (1 - disc) - qty AS amt"
    " FROM li, ord WHERE li.okey = ord.okey AND flag LIKE 'R%'"
    ") AS p GROUP BY flag, yr ORDER BY flag, yr DESC"
)


def test_derived_table_with_date_part_key_and_arithmetic_sum_is_flattened() -> None:
    spec = emit_declarative_spec(_PROFIT, SCHEMA, CATALOG)
    assert "pub struct OutRow {\n    pub flag: String,\n    pub yr: i64,\n    pub total: i128,\n}" in spec
    assert "((ord.odate@[i1] as int) / 10000)" in spec
    assert "(((li.price@[i0] as int) * ((1 - (li.disc@[i0] as int)))) - (li.qty@[i0] as int))" in spec
    assert "pub fn run_query(li: &Cols_li, ord: &Cols_ord)" in spec
    assert "if (res@[i].flag@) == (res@[i + 1].flag@)" in spec
    if VERUS.is_file():
        assert "error" not in _typechecks(spec)


def test_derived_table_renamed_column_key_and_having_on_the_alias() -> None:
    spec = emit_declarative_spec(
        "SELECT f, COUNT(*) AS n FROM (SELECT flag AS f, qty FROM li) AS t GROUP BY f HAVING f = 'R'",
        SCHEMA,
        CATALOG,
    )
    assert "pub f: String" in spec
    assert "li.flag@[i0]@" in spec
    assert '"R"@' in spec
    if VERUS.is_file():
        assert "error" not in _typechecks(spec)


def test_derived_table_aggregate_over_a_plain_output_reads_the_source_column() -> None:
    spec = emit_declarative_spec(
        "SELECT f, SUM(q) AS total FROM (SELECT flag AS f, qty AS q FROM li) AS t GROUP BY f",
        SCHEMA,
        CATALOG,
    )
    assert "(li.qty@[i0] as int)" in spec


@pytest.mark.parametrize(
    "sql",
    [
        # outer WHERE would need a rewrite of the derived table's text
        "SELECT f, COUNT(*) AS n FROM (SELECT flag AS f FROM li) AS t WHERE f = 'R' GROUP BY f",
        # a group key that is arithmetic has no exact integer width to give OutRow
        "SELECT a, COUNT(*) AS n FROM (SELECT price - disc AS a FROM li) AS t GROUP BY a",
        # outer names something the derived table does not output
        "SELECT g, COUNT(*) AS n FROM (SELECT flag AS f FROM li) AS t GROUP BY g",
        # a derived table that itself aggregates
        "SELECT f, COUNT(*) AS n FROM (SELECT flag AS f, COUNT(*) AS c FROM li GROUP BY flag) AS t GROUP BY f",
    ],
)
def test_derived_table_shapes_not_flattened_exactly_are_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        emit_declarative_spec(sql, SCHEMA, CATALOG)
