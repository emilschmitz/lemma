"""ORDER BY is a spec sort, then LIMIT, inside method_spec."""

from __future__ import annotations

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
    assert "group_keys_helper" in out
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
