"""Predicate pushdown (lemma.toml [run] pushdown, declarative_spec/pushdown.py): the rule, its refusals, the export path, flag off.

SQL here are fixtures (TPC-H / SSB shapes), not engine code. The Verus differential runs are in test_pushdown_differential.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from declarative_spec.pushdown import plan_pushdown
from research_loop.decl_query_measure import write_query_measure
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

TPCH = {
    "lineitem": {
        "l_orderkey": "bigint", "l_partkey": "bigint", "l_quantity": "decimal(15,2)", "l_extendedprice": "decimal(15,2)",
        "l_discount": "decimal(15,2)", "l_shipdate": "date", "l_shipmode": "varchar", "l_shipinstruct": "varchar",
    },
    "part": {"p_partkey": "bigint", "p_type": "varchar", "p_brand": "varchar", "p_container": "varchar", "p_size": "integer"},
    "orders": {"o_orderkey": "bigint", "o_custkey": "bigint", "o_orderdate": "date"},
    "customer": {"c_custkey": "bigint", "c_mktsegment": "varchar"},
}
SSB = {
    "lineorder": {"lo_orderdate": "integer", "lo_discount": "integer", "lo_quantity": "integer", "lo_extendedprice": "integer", "lo_custkey": "integer"},
    "date": {"d_datekey": "integer", "d_year": "integer", "d_yearmonthnum": "integer"},
    "customer": {"c_custkey": "integer", "c_region": "varchar"},
}
Q6 = (
    "select sum(l_extendedprice * l_discount) as revenue from lineitem where l_shipdate >= date '1994-01-01' "
    "and l_shipdate < date '1994-01-01' + interval '1' year and l_discount between 0.05 and 0.07 and l_quantity < 24"
)
Q14 = (
    "select 100.00 * sum(case when p_type like 'PROMO%' then l_extendedprice * (1 - l_discount) else 0 end) "
    "/ sum(l_extendedprice * (1 - l_discount)) as promo_revenue from lineitem, part "
    "where l_partkey = p_partkey and l_shipdate >= date '1995-09-01' and l_shipdate < date '1995-09-01' + interval '1' month"
)
SSB_Q11 = (
    "select sum(lo_extendedprice * lo_discount) as revenue from lineorder, date where lo_orderdate = d_datekey "
    "and d_year = 1993 and lo_discount between 1 and 3 and lo_quantity < 25"
)
SSB_Q12 = (
    "select sum(lo_extendedprice * lo_discount) as revenue from lineorder, date where lo_orderdate = d_datekey "
    "and d_yearmonthnum = 199401 and lo_discount between 4 and 6 and lo_quantity between 26 and 35"
)


def _sql(plan, table: str) -> list[str]:
    return [f.sql for f in plan.pushed.get(table, [])]


# ---- the rule pushes single-table conjuncts ----------------------------------------------------------------------------------


def test_q6_pushes_every_conjunct_into_the_one_table() -> None:
    plan = plan_pushdown(Q6, TPCH, dialect="duckdb")
    assert plan.refused is None and plan.kept == []
    assert _sql(plan, "lineitem") == [
        "\"l_shipdate\" >= CAST('1994-01-01' AS DATE)",
        "\"l_shipdate\" < CAST('1994-01-01' AS DATE) + INTERVAL '1' YEAR",
        '"l_discount" BETWEEN 0.05 AND 0.07',
        '"l_quantity" < 24',
    ]


def test_q14_pushes_the_date_range_and_keeps_the_join_equality() -> None:
    plan = plan_pushdown(Q14, TPCH, dialect="duckdb")
    assert len(_sql(plan, "lineitem")) == 2 and _sql(plan, "part") == []
    assert any("l_partkey = p_partkey" in k for k in plan.kept)


def test_ssb_q1_1_and_q1_2_push_to_both_the_fact_and_the_date_table() -> None:
    p11 = plan_pushdown(SSB_Q11, SSB, dialect="duckdb")
    assert _sql(p11, "date") == ['"d_year" = 1993']
    assert _sql(p11, "lineorder") == ['"lo_discount" BETWEEN 1 AND 3', '"lo_quantity" < 25']
    p12 = plan_pushdown(SSB_Q12, SSB, dialect="duckdb")
    assert _sql(p12, "date") == ['"d_yearmonthnum" = 199401']
    assert len(_sql(p12, "lineorder")) == 2


def test_aliases_and_qualified_columns_resolve_to_their_table() -> None:
    sql = "select count(*) as c from lineitem l join part p on l.l_partkey = p.p_partkey where p.p_size > 3 and l.l_quantity <= 5"
    plan = plan_pushdown(sql, TPCH, dialect="duckdb")
    assert _sql(plan, "part") == ['"p_size" > 3'] and _sql(plan, "lineitem") == ['"l_quantity" <= 5']


def test_an_or_spanning_two_tables_pushes_the_implied_per_table_disjunction_q19_shape() -> None:
    sql = (
        "select sum(l_extendedprice) as s from lineitem, part where (p_partkey = l_partkey and p_brand = 'A' and l_quantity < 5) "
        "or (p_partkey = l_partkey and p_brand = 'B' and l_quantity > 9)"
    )
    plan = plan_pushdown(sql, TPCH, dialect="duckdb")
    assert _sql(plan, "part") == ["(\"p_brand\" = 'A') OR (\"p_brand\" = 'B')"]
    assert _sql(plan, "lineitem") == ['("l_quantity" < 5) OR ("l_quantity" > 9)']


# ---- the rule refuses ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "select count(*) as c from lineitem where l_quantity > 1 and not exists (select 1 from part where p_partkey = l_partkey)",
        "select count(*) as c from lineitem where l_quantity > 1 and l_partkey not in (select p_partkey from part)",
    ],
)
def test_not_exists_and_anti_joins_push_only_the_outer_tables_own_conjuncts(sql: str) -> None:
    # The subquery's table has no conjunct of its own (only the correlation / nothing): it is exported in full.
    plan = plan_pushdown(sql, TPCH)
    assert plan.refused is None and plan.pushed.keys() == {"lineitem"} and _sql(plan, "lineitem") == ['"l_quantity" > 1']


def test_a_left_join_pushes_the_preserved_side_only() -> None:
    plan = plan_pushdown("select count(p_partkey) as c from lineitem left join part on l_partkey = p_partkey where l_quantity > 3", TPCH)
    assert plan.refused is None and plan.pushed.keys() == {"lineitem"} and _sql(plan, "lineitem") == ['"l_quantity" > 3']


@pytest.mark.parametrize(
    "sql",
    [
        "select count(*) as c from part right join lineitem on l_partkey = p_partkey where l_quantity > 3 and p_size > 1",
        "select count(*) as c from lineitem full join part on l_partkey = p_partkey where p_size > 1",
    ],
)
def test_right_and_full_joins_push_nothing_on_either_side(sql: str) -> None:
    plan = plan_pushdown(sql, TPCH)
    assert plan.pushed == {} and any("JOIN in its block" in k for k in plan.kept)


@pytest.mark.parametrize(
    "sql",
    [
        "select l_shipmode, count(*) as c from lineitem group by l_shipmode having l_shipmode = 'AIR'",
        "select l_shipmode, count(*) as c from lineitem group by l_shipmode having count(*) > 3",
    ],
)
def test_having_only_filters_are_never_pushed(sql: str) -> None:
    plan = plan_pushdown(sql, TPCH)
    assert plan.pushed == {} and plan.refused is None


@pytest.mark.parametrize(
    "sql",
    [
        "select count(*) as c from lineitem, part where l_partkey = p_partkey and (l_quantity > 3 or p_size > 1)",
        "select count(*) as c from lineitem, part where l_partkey = p_partkey and ((l_quantity > 3 and p_size > 1) or p_size < 0)",
    ],
)
def test_an_or_across_tables_without_a_part_in_every_disjunct_is_not_pushed(sql: str) -> None:
    plan = plan_pushdown(sql, TPCH)
    assert "lineitem" not in plan.pushed
    assert plan.pushed.get("part") in (None, []) or sql.endswith("p_size < 0)")
    if sql.endswith("p_size < 0)"):  # part has a conjunct in both disjuncts: (p_size > 1) OR (p_size < 0) is implied
        assert _sql(plan, "part") == ['("p_size" > 1) OR ("p_size" < 0)']


@pytest.mark.parametrize(
    "sql",
    [
        "select count(*) as c from lineitem where l_quantity > (select avg(l_quantity) from lineitem)",  # scalar subquery
        "with x as (select * from lineitem) select count(*) as c from x where l_quantity > 1",
        "select count(*) as c from lineitem where l_quantity > 1 union all select count(*) from part",
        "select l_quantity, row_number() over (order by l_quantity) as r from lineitem where l_quantity > 1",
    ],
)
def test_subqueries_ctes_set_operations_and_windows_push_nothing(sql: str) -> None:
    assert plan_pushdown(sql, TPCH).pushed == {}


def test_a_self_join_pushes_nothing_for_that_table_but_still_for_the_others() -> None:
    sql = "select count(*) as c from lineitem a, lineitem b, part where a.l_orderkey = b.l_orderkey and a.l_partkey = p_partkey and a.l_quantity > 1 and p_size > 2"
    plan = plan_pushdown(sql, TPCH)
    assert "lineitem" not in plan.pushed and _sql(plan, "part") == ['"p_size" > 2']


@pytest.mark.parametrize(
    "conj",
    ["random() < 0.5", "abs(l_quantity) > 1", "l_quantity / 2 > 1", "case when l_quantity > 1 then true else false end", "l_shipmode like 'A!%' escape '!'"],
)
def test_conjuncts_outside_the_allow_list_stay_in_the_spec_only(conj: str) -> None:
    plan = plan_pushdown(f"select count(*) as c from lineitem where l_quantity > 0 and {conj}", TPCH)
    assert _sql(plan, "lineitem") == ['"l_quantity" > 0']


def test_named_parameters_are_reported_and_anonymous_ones_refused() -> None:
    plan = plan_pushdown("select count(*) as c from lineitem where l_quantity > :lo and l_discount < ?", TPCH)
    assert [(f.sql, f.params) for f in plan.pushed["lineitem"]] == [('"l_quantity" > :lo', ("lo",))]
    assert plan.params("lineitem") == ("lo",)


def test_pushed_fragments_are_valid_duckdb_that_selects_the_same_rows_as_the_where() -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE lineitem AS SELECT i AS l_orderkey, i % 7 AS l_partkey, (i % 50)::DECIMAL(15,2) AS l_quantity, "
                "(i * 3.5)::DECIMAL(15,2) AS l_extendedprice, ((i % 11) / 100.0)::DECIMAL(15,2) AS l_discount, "
                "DATE '1993-06-01' + (i % 900)::INTEGER AS l_shipdate, 'AIR' AS l_shipmode, 'X' AS l_shipinstruct FROM range(5000) t(i)")
    plan = plan_pushdown(Q6, TPCH, dialect="duckdb")
    where = plan.where("lineitem")
    pushed = con.execute(f"SELECT count(*) FROM lineitem WHERE {where}").fetchone()[0]
    direct = con.execute(f"SELECT count(*) FROM lineitem WHERE {Q6.split(' where ', 1)[1]}").fetchone()[0]
    assert pushed == direct and 0 < pushed < 5000


# ---- the export path ----------------------------------------------------------------------------------------------------------

_SCHEMA = {"t": {"g": "BIGINT", "a": "BIGINT", "s": "VARCHAR"}}
_SQL = "SELECT g, COUNT(*) AS c FROM t WHERE a > 3 AND s = 'x' GROUP BY g"


def _db(path: Path) -> Path:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t AS SELECT i % 3 AS g, i AS a, CASE WHEN i % 2 = 0 THEN 'x' ELSE 'y' END AS s FROM range(10) r(i)")
    con.close()
    return path


def _cat() -> CatalogAssumptions:
    return CatalogAssumptions(max_rows=16, tables={"t": TableAssumptions(max_rows=16)})


def test_pushdown_on_exports_only_the_rows_the_where_keeps_and_writes_the_scan_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_PUSHDOWN", "1")
    db = _db(tmp_path / "t.duckdb")
    got = write_query_measure(sql=_SQL, schema=_SCHEMA, catalog=_cat(), db_path=db, dest=tmp_path / "on")
    assert got["table_rows"] == {"t": 3}  # a in {4, 6, 8}
    plan = json.loads((tmp_path / "on" / "scan_plan.json").read_text())
    entry = plan["tables"]["t"]
    assert entry["rows_full"] == 10 and entry["rows_delivered"] == 3
    assert [p["sql"] for p in entry["predicates"]] == ['"a" > 3', "\"s\" = 'x'"]
    assert set(entry["columns"]) >= {"g", "a", "s"} or set(entry["columns"]) >= {"g"}
    assert json.loads((tmp_path / "on" / "expect.json").read_text())["scan_plan"] == plan
    assert sorted(got["rows"]) == [[0, 1], [1, 1], [2, 1]]  # DuckDB on the full original SQL


def test_pushdown_off_is_the_full_export_byte_for_byte(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path / "t.duckdb")
    monkeypatch.setenv("LEMMA_PUSHDOWN", "0")
    off = write_query_measure(sql=_SQL, schema=_SCHEMA, catalog=_cat(), db_path=db, dest=tmp_path / "off")
    assert off["table_rows"] == {"t": 10} and "scan_plan" not in off
    assert not (tmp_path / "off" / "scan_plan.json").exists()
    assert "scan_plan" not in json.loads((tmp_path / "off" / "expect.json").read_text())
    # A query with no WHERE pushes nothing: with the flag on its column file equals the flag-off file.
    no_where = "SELECT g, COUNT(*) AS c FROM t GROUP BY g"
    monkeypatch.setenv("LEMMA_PUSHDOWN", "0")
    a = write_query_measure(sql=no_where, schema=_SCHEMA, catalog=_cat(), db_path=db, dest=tmp_path / "a")
    monkeypatch.setenv("LEMMA_PUSHDOWN", "1")
    b = write_query_measure(sql=no_where, schema=_SCHEMA, catalog=_cat(), db_path=db, dest=tmp_path / "b")
    assert Path(a["bins"]["t"]).read_bytes() == Path(b["bins"]["t"]).read_bytes()


def test_the_spec_text_does_not_depend_on_the_pushdown_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.emit import emit_declarative_spec

    monkeypatch.setenv("LEMMA_PUSHDOWN", "0")
    off = emit_declarative_spec(_SQL, _SCHEMA, _cat())
    monkeypatch.setenv("LEMMA_PUSHDOWN", "1")
    assert emit_declarative_spec(_SQL, _SCHEMA, _cat()) == off


def test_a_dictionary_column_of_a_pushed_export_numbers_only_the_delivered_strings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    monkeypatch.setenv("LEMMA_PUSHDOWN", "1")
    db = _db(tmp_path / "t.duckdb")
    got = write_query_measure(sql="SELECT s, COUNT(*) AS c FROM t WHERE a < 2 GROUP BY s", schema=_SCHEMA, catalog=_cat(), db_path=db, dest=tmp_path / "d")
    assert got["table_rows"] == {"t": 2}
    assert got["dict_sizes"] == {"t.s": 2}
    assert sorted(got["rows"]) == [["x", 1], ["y", 1]]
