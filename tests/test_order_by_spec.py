"""ORDER BY is a spec sort, then LIMIT, inside method_spec."""

from __future__ import annotations

import pytest

from verus_transpiler.parse_sql import UnsupportedContractError
from verus_transpiler.transpiler import transpile_sql_to_verus

_STAR = {
    "pre": {
        "adsh": "string",
        "stmt": "string",
        "tag": "string",
        "version": "string",
        "line": "int",
        "plabel": "string",
    },
    "sub": {"adsh": "string", "form": "string", "name": "string"},
    "tag": {
        "tag": "string",
        "version": "string",
        "tlabel": "string",
        "custom": "int",
    },
}

_STAR_SQL = """
SELECT s.name, p.stmt, t.tlabel, p.line, p.plabel
FROM pre p
JOIN sub s ON p.adsh = s.adsh
JOIN tag t ON p.tag = t.tag AND p.version = t.version
WHERE s.form = '10-Q' AND p.stmt = 'CI' AND t.custom = 0
ORDER BY s.name, p.line
LIMIT 50
"""


def test_star_order_by_sorts_before_limit() -> None:
    out = transpile_sql_to_verus(_STAR_SQL, _STAR)
    assert "spec_seq_take(spec_seq_sort_by(" in out
    assert "|a: (Seq<char>, Seq<char>, Seq<char>, u32, Seq<char>), b:" in out
    assert "spec_join_proj_before(a, b)" in out
    assert "spec_char_seq_lt(a.0, b.0)" in out
    assert "(a.3) < (b.3)" in out
    assert "agent may apply in run_query" not in out
    assert "assume(" not in out
    assert "arbitrary()" not in out


def test_group_by_order_by_is_a_sorted_sequence() -> None:
    sql = """
    SELECT s.form, s.fy, COUNT(*) AS num_lines,
           COUNT(DISTINCT p.tag) AS distinct_tags,
           AVG(p.line) AS avg_line
    FROM pre p JOIN sub s ON p.adsh = s.adsh
    WHERE p.stmt = 'IS'
    GROUP BY s.form, s.fy
    ORDER BY num_lines DESC
    LIMIT 50
    """
    out = transpile_sql_to_verus(
        sql,
        {
            "pre": {"adsh": "string", "stmt": "string", "tag": "string", "line": "int"},
            "sub": {"adsh": "string", "form": "string", "fy": "int"},
        },
    )
    spec = out.split("pub open spec fn method_spec", 1)[1].split("pub proof fn", 1)[0]
    assert "Seq<" in spec.split("{", 1)[0]
    assert "spec_seq_take(spec_seq_sort_by(spec_map_at_keys(" in spec
    assert "pub proof fn lemma_map_at_keys_prefix_complete" in out
    assert "group_keys_helper" in out
    assert "pub proof fn lemma_group_keys_helper_is_pairs" in out
    assert "pub proof fn lemma_group_keys_helper_is_loop" in out
    assert "// lemma_group_topk_map: Map<(Seq<char>, u32), (u64, u64, u64)>" in out
    assert "(b.1.0) < (a.1.0)" in out
    assert "pub exec fn exec_sort_by" in out
    assert "spec_seq_sort_by(vec_str_u32_u64_u64_u64_view(s@)" in out
    assert "agent may apply in run_query" not in out


def test_group_by_without_order_stays_a_map() -> None:
    sql = """
    SELECT s.form, COUNT(*) AS num_lines
    FROM pre p JOIN sub s ON p.adsh = s.adsh
    GROUP BY s.form
    """
    out = transpile_sql_to_verus(
        sql,
        {
            "pre": {"adsh": "string", "stmt": "string"},
            "sub": {"adsh": "string", "form": "string"},
        },
    )
    spec = out.split("pub open spec fn method_spec", 1)[1].split("{", 1)[0]
    assert "Map<" in spec
    assert "group_keys_helper" not in out


_NUM = {
    "num": {"adsh": "string", "uom": "string", "value": "double"},
    "sub": {"adsh": "string", "form": "string", "fy": "int", "sic": "int", "cik": "int"},
}


def test_sum_order_by_without_limit_is_the_full_sorted_sequence() -> None:
    sql = """
    SELECT s.form, COUNT(*) AS num_values,
           SUM(n.value) AS total_value, AVG(n.value) AS avg_value
    FROM num n JOIN sub s ON n.adsh = s.adsh
    WHERE n.uom = 'pure' AND s.fy = 2024
    GROUP BY s.form
    ORDER BY total_value DESC
    """
    out = transpile_sql_to_verus(sql, _NUM)
    spec = out.split("pub open spec fn method_spec", 1)[1].split("pub proof fn", 1)[0]
    assert "-> Seq<" in spec.split("{", 1)[0]
    assert "spec_seq_sort_by(spec_map_at_keys(" in spec
    assert "spec_seq_take(" not in spec
    assert "(b.1.1) < (a.1.1)" in out
    assert "not in this Map method_spec" not in out


def test_having_order_by_sorts_after_the_filter() -> None:
    sql = """
    SELECT s.sic, COUNT(DISTINCT s.cik) AS num_companies,
           COUNT(*) AS num_values,
           SUM(n.value) AS total_value,
           AVG(n.value) AS avg_value,
           MIN(n.value) AS min_value,
           MAX(n.value) AS max_value
    FROM num n JOIN sub s ON n.adsh = s.adsh
    WHERE n.uom = 'pure' AND s.fy = 2024 AND n.value > 0
    GROUP BY s.sic
    HAVING COUNT(DISTINCT s.cik) >= 3
    ORDER BY total_value DESC
    LIMIT 1000
    """
    out = transpile_sql_to_verus(sql, _NUM)
    spec = out.split("pub open spec fn method_spec", 1)[1].split("pub proof fn", 1)[0]
    assert "spec_seq_take(spec_seq_sort_by(spec_map_at_keys(" in spec
    assert "(b.1.2) < (a.1.2)" in out
    assert "not in this Map method_spec" not in out


def test_single_column_desc_flips_the_spec_compare() -> None:
    sql = "SELECT name FROM sub ORDER BY name DESC LIMIT 2"
    out = transpile_sql_to_verus(sql, {"sub": {"name": "string", "adsh": "string"}})
    assert "spec_seq_take(spec_seq_sort_by(" in out
    assert "spec_char_seq_lt(b, a)" in out
    assert "agent may apply in run_query" not in out


def test_single_table_group_by_order_is_a_sorted_sequence() -> None:
    sql = """
    SELECT l_returnflag, l_linestatus, SUM(l_quantity) AS sum_qty, COUNT(*) AS count_order
    FROM lineitem
    WHERE l_shipdate <= 19980902
    GROUP BY l_returnflag, l_linestatus
    ORDER BY l_returnflag, l_linestatus
    """
    out = transpile_sql_to_verus(
        sql,
        {
            "lineitem": {
                "l_returnflag": "string",
                "l_linestatus": "string",
                "l_quantity": "int",
                "l_shipdate": "int",
            }
        },
    )
    spec = out.split("pub open spec fn method_spec(", 1)[1].split("pub proof fn", 1)[0]
    assert "-> Seq<" in spec.split("{", 1)[0]
    assert "spec_seq_sort_by(spec_map_at_keys(" in spec
    assert "pub exec fn exec_sort_by" in out
    assert "not in this Map method_spec" not in out
    assert "// lemma_group_topk_map: Map<" in out
    assert "pub const LEMMA_MAX_CELL_U64" not in out
    assert "delta < LEMMA_MAX_CELL_U64" not in out


def test_single_agg_join_group_by_order_is_a_sorted_sequence() -> None:
    sql = """
    SELECT lineitem.l_orderkey,
           SUM(lineitem.l_extendedprice * (1 - lineitem.l_discount)) AS revenue,
           orders.o_orderdate, orders.o_shippriority
    FROM customer
    JOIN orders ON customer.c_custkey = orders.o_custkey
    JOIN lineitem ON lineitem.l_orderkey = orders.o_orderkey
    WHERE customer.c_mktsegment = 'BUILDING'
      AND orders.o_orderdate < 19950315
      AND lineitem.l_shipdate > 19950315
    GROUP BY lineitem.l_orderkey, orders.o_orderdate, orders.o_shippriority
    ORDER BY revenue DESC, orders.o_orderdate
    LIMIT 10
    """
    out = transpile_sql_to_verus(
        sql,
        {
            "customer": {"c_custkey": "int", "c_mktsegment": "string"},
            "orders": {
                "o_orderkey": "int",
                "o_custkey": "int",
                "o_orderdate": "int",
                "o_shippriority": "int",
            },
            "lineitem": {
                "l_orderkey": "int",
                "l_extendedprice": "int",
                "l_discount": "int",
                "l_shipdate": "int",
            },
        },
    )
    spec = out.split("pub open spec fn method_spec(", 1)[1].split("pub proof fn", 1)[0]
    assert "-> Seq<" in spec.split("{", 1)[0]
    assert "spec_seq_take(spec_seq_sort_by(spec_map_at_keys(" in spec
    assert "not in this Map method_spec" not in out
    assert "(b.1) < (a.1)" in out


def test_single_table_one_sum_group_by_order_is_a_sorted_sequence() -> None:
    sql = """
    SELECT l_returnflag, l_linestatus, SUM(l_quantity) AS sum_qty
    FROM lineitem
    WHERE l_shipdate <= 19980902
    GROUP BY l_returnflag, l_linestatus
    ORDER BY sum_qty DESC
    """
    out = transpile_sql_to_verus(
        sql,
        {
            "lineitem": {
                "l_returnflag": "string",
                "l_linestatus": "string",
                "l_quantity": "int",
                "l_shipdate": "int",
            }
        },
    )
    spec = out.split("pub open spec fn method_spec(", 1)[1].split("pub proof fn", 1)[0]
    assert "-> Seq<" in spec.split("{", 1)[0]
    assert "spec_seq_sort_by(spec_map_at_keys(" in spec
    assert "not in this Map method_spec" not in out
    assert "(b.1) < (a.1)" in out
    assert "pub const LEMMA_MAX_CELL_U64" not in out


_TPCH = {
    "lineitem": {
        "l_orderkey": "int",
        "l_quantity": "int",
        "l_extendedprice": "int",
        "l_discount": "int",
        "l_tax": "int",
        "l_returnflag": "string",
        "l_linestatus": "string",
        "l_shipdate": "int",
    },
    "orders": {
        "o_orderkey": "int",
        "o_custkey": "int",
        "o_orderdate": "int",
        "o_shippriority": "int",
        "o_totalprice": "int",
    },
    "customer": {"c_custkey": "int", "c_name": "string", "c_mktsegment": "string"},
}


def test_paper_tpch_q1_date_literal_is_an_integer_in_the_sorted_spec() -> None:
    sql = """
    SELECT l_returnflag, l_linestatus,
           SUM(l_quantity) AS sum_qty,
           SUM(l_extendedprice) AS sum_base_price,
           SUM(l_extendedprice * (1 - l_discount)) AS sum_disc_price,
           SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge,
           AVG(l_quantity) AS avg_qty,
           AVG(l_extendedprice) AS avg_price,
           AVG(l_discount) AS avg_disc,
           COUNT(*) AS count_order
    FROM lineitem
    WHERE l_shipdate <= DATE '1998-09-02'
    GROUP BY l_returnflag, l_linestatus
    ORDER BY l_returnflag, l_linestatus
    """
    out = transpile_sql_to_verus(sql, _TPCH)
    spec = out.split("pub open spec fn method_spec(", 1)[1].split("{", 1)[0]
    assert "-> Seq<" in spec
    assert "19980902" in out
    assert "DATE" not in out
    assert "spec_seq_sort_by" in out
    assert "not in this Map method_spec" not in out


def test_paper_tpch_q3_unqualified_names_are_a_sorted_sequence() -> None:
    sql = """
    SELECT l_orderkey,
           SUM(l_extendedprice * (1 - l_discount)) AS revenue,
           o_orderdate, o_shippriority
    FROM customer
    JOIN orders ON c_custkey = o_custkey
    JOIN lineitem ON l_orderkey = o_orderkey
    WHERE c_mktsegment = 'BUILDING'
      AND o_orderdate < DATE '1995-03-15'
      AND l_shipdate > DATE '1995-03-15'
    GROUP BY l_orderkey, o_orderdate, o_shippriority
    ORDER BY revenue DESC, o_orderdate
    LIMIT 10
    """
    out = transpile_sql_to_verus(sql, _TPCH)
    spec = out.split("pub open spec fn method_spec(", 1)[1].split("{", 1)[0]
    assert "-> Seq<" in spec
    assert "19950315" in out
    assert "spec_seq_take(spec_seq_sort_by(spec_map_at_keys(" in out
    assert "not in this Map method_spec" not in out


def test_official_tpch_q1_interval_is_the_integer_date() -> None:
    sql = """
    SELECT l_returnflag, l_linestatus, SUM(l_quantity) AS sum_qty
    FROM lineitem
    WHERE l_shipdate <= DATE '1998-12-01' - INTERVAL 90 DAY
    GROUP BY l_returnflag, l_linestatus
    ORDER BY l_returnflag, l_linestatus
    """
    out = transpile_sql_to_verus(sql, _TPCH)
    assert "19980902" in out
    assert "INTERVAL" not in out
    assert "spec_seq_sort_by" in out


def test_official_tpch_q3_comma_join_is_an_inner_sorted_sequence() -> None:
    sql = """
    SELECT l_orderkey,
           SUM(l_extendedprice * (1 - l_discount)) AS revenue,
           o_orderdate, o_shippriority
    FROM customer, orders, lineitem
    WHERE c_mktsegment = 'BUILDING'
      AND c_custkey = o_custkey
      AND l_orderkey = o_orderkey
      AND o_orderdate < DATE '1995-03-15'
      AND l_shipdate > DATE '1995-03-15'
    GROUP BY l_orderkey, o_orderdate, o_shippriority
    ORDER BY revenue DESC, o_orderdate
    LIMIT 10
    """
    out = transpile_sql_to_verus(sql, _TPCH)
    spec = out.split("pub open spec fn method_spec(", 1)[1].split("{", 1)[0]
    assert "-> Seq<" in spec
    assert "19950315" in out
    assert "BUILDING" in out
    assert "spec_seq_take(spec_seq_sort_by(spec_map_at_keys(" in out


def test_official_tpch_q18_in_group_having_is_a_sorted_sequence() -> None:
    sql = """
    SELECT c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice, SUM(l_quantity)
    FROM customer, orders, lineitem
    WHERE o_orderkey IN (
        SELECT l_orderkey FROM lineitem
        GROUP BY l_orderkey
        HAVING SUM(l_quantity) > 300
    )
      AND c_custkey = o_custkey
      AND o_orderkey = l_orderkey
    GROUP BY c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice
    ORDER BY o_totalprice DESC, o_orderdate
    LIMIT 100
    """
    out = transpile_sql_to_verus(sql, _TPCH)
    spec = out.split("pub open spec fn method_spec(", 1)[1].split("{", 1)[0]
    assert "-> Seq<" in spec
    assert "300" in out
    assert "spec_seq_take(spec_seq_sort_by(spec_map_at_keys(" in out
    assert "not in this Map method_spec" not in out


_TPCH_Q9 = {
    "part": {"p_partkey": "int", "p_name": "string"},
    "supplier": {"s_suppkey": "int", "s_nationkey": "int"},
    "lineitem": {
        "l_suppkey": "int",
        "l_partkey": "int",
        "l_orderkey": "int",
        "l_extendedprice": "int",
        "l_discount": "int",
        "l_quantity": "int",
    },
    "partsupp": {"ps_suppkey": "int", "ps_partkey": "int", "ps_supplycost": "int"},
    "orders": {"o_orderkey": "int", "o_orderdate": "int"},
    "nation": {"n_nationkey": "int", "n_name": "string"},
}


def test_official_tpch_q9_derived_extract_year_is_a_sorted_sequence() -> None:
    sql = """
    SELECT nation, o_year, SUM(amount) AS sum_profit
    FROM (
        SELECT n_name AS nation, EXTRACT(year FROM o_orderdate) AS o_year,
            l_extendedprice * (1 - l_discount) - ps_supplycost * l_quantity AS amount
        FROM part, supplier, lineitem, partsupp, orders, nation
        WHERE s_suppkey = l_suppkey AND ps_suppkey = l_suppkey AND ps_partkey = l_partkey
          AND p_partkey = l_partkey AND o_orderkey = l_orderkey AND s_nationkey = n_nationkey
          AND p_name LIKE '%green%'
    ) AS profit
    GROUP BY nation, o_year
    ORDER BY nation, o_year DESC
    """
    out = transpile_sql_to_verus(sql, _TPCH_Q9)
    spec = out.split("pub open spec fn method_spec", 1)[1].split("pub proof fn", 1)[0]
    assert "-> Seq<" in spec.split("{", 1)[0]
    assert "spec_seq_sort_by" in out
    assert "/ 10000" in out
    assert "green" in out
    assert "not in this Map method_spec" not in out


def test_anti_join_group_by_order_is_a_sorted_sequence() -> None:
    sql = """
    SELECT n.tag, n.version, COUNT(*) AS cnt, SUM(n.value) AS total
    FROM num n
    WHERE n.uom = 'USD' AND n.ddate BETWEEN 20240101 AND 20241231
      AND n.value IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM pre p
          WHERE p.tag = n.tag AND p.version = n.version AND p.adsh = n.adsh
      )
    GROUP BY n.tag, n.version
    HAVING COUNT(*) > 10
    ORDER BY cnt DESC
    LIMIT 200
    """
    out = transpile_sql_to_verus(
        sql,
        {
            "num": {
                "adsh": "string",
                "tag": "string",
                "version": "string",
                "ddate": "int",
                "uom": "string",
                "value": "double",
            },
            "pre": {"adsh": "string", "tag": "string", "version": "string"},
        },
    )
    spec = out.split("pub open spec fn method_spec(", 1)[1].split("pub proof fn", 1)[0]
    assert "-> Seq<" in spec.split("{", 1)[0]
    assert "spec_seq_take(spec_seq_sort_by(spec_map_at_keys(" in spec
    assert "group_keys_helper(num, pre, 0)" in spec
    assert "not in this Map method_spec" not in out


def test_paper_tpch_q6_decimal_bound_stays_unsupported() -> None:
    sql = """
    SELECT SUM(l_extendedprice * l_discount) AS revenue
    FROM lineitem
    WHERE l_shipdate >= DATE '1994-01-01'
      AND l_shipdate < DATE '1995-01-01'
      AND l_discount BETWEEN 0.06 - 0.01 AND 0.06 + 0.01
      AND l_quantity < 24
    """
    with pytest.raises(UnsupportedContractError, match="Non-integer numeric literal"):
        transpile_sql_to_verus(sql, _TPCH)
