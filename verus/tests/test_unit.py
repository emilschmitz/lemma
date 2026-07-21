"""Unit tests for verus-transpiler."""

from __future__ import annotations

import unittest

from verus_transpiler import (
    UnsupportedContractError,
    project_schema_for_query,
    transpile_sql_to_verus,
)


class TestVerusTranspiler(unittest.TestCase):
    def setUp(self) -> None:
        self.ssb_subset = {
            "LO_ORDERDATE": "int",
            "LO_EXTENDEDPRICE": "bigint",
            "LO_DISCOUNT": "int",
        }
        self.ssb_q11_sql = """
            SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) AS revenue
            FROM lineorder
            WHERE LO_ORDERDATE >= 19930101 AND LO_ORDERDATE <= 19931231
        """

    def test_ssb_scalar_sum_parity(self) -> None:
        result = transpile_sql_to_verus(self.ssb_q11_sql, self.ssb_subset)
        self.assertIn("pub open spec fn method_spec", result)
        self.assertIn("pub open spec fn valid_cols", result)
        self.assertIn("run_query", result)
        self.assertIn("lo_orderdate", result)
        self.assertIn("mul_u64_u32", result)
        self.assertIn("LEMMA_MAX_ROWS", result)
        self.assertIn("cols.n <= LEMMA_MAX_ROWS", result)
        self.assertNotIn("let _ = cols", result)

    def test_enable_templates_changes_output(self) -> None:
        skeleton = transpile_sql_to_verus(self.ssb_q11_sql, self.ssb_subset, enable_templates=False)
        templated = transpile_sql_to_verus(self.ssb_q11_sql, self.ssb_subset, enable_templates=True)
        self.assertIn("// === RunQuery skeleton", skeleton)
        self.assertNotIn("// === RunQuery skeleton", templated)
        self.assertIn("pub exec fn run_query", templated)
        self.assertIn("while i > 0", templated)
        self.assertNotEqual(skeleton, templated)

    def test_inner_join_emits_helper(self) -> None:
        schema = {
            "orders": {"id": "int", "amount": "int"},
            "customers": {"id": "int", "region": "string"},
        }
        sql = """
            SELECT SUM(orders.amount)
            FROM orders
            INNER JOIN customers ON orders.id = customers.id
        """
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("join_method_spec_helper", result)
        self.assertIn("Cols_orders", result)
        self.assertIn("Cols_customers", result)
        self.assertIn("pub open spec fn method_spec", result)

    def test_scalar_subquery_emits_nested_helper(self) -> None:
        schema = {"value": "int", "category": "string"}
        sql = """
            SELECT SUM(value)
            FROM my_table
            WHERE value > (SELECT SUM(value) FROM my_table WHERE category = 'A')
        """
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("subquery_sq", result)
        self.assertIn("_spec(cols)", result)
        self.assertIn("pub open spec fn method_spec", result)

    def test_unsupported_raises(self) -> None:
        schema = {"value": "int"}
        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_verus("SELECT DISTINCT SUM(value) FROM t", schema)
        from verus_transpiler.dialect_flags import TRUSTED_FEATURES

        old_window = TRUSTED_FEATURES["window"]
        old_recursive = TRUSTED_FEATURES["recursive_cte"]
        TRUSTED_FEATURES["window"] = False
        TRUSTED_FEATURES["recursive_cte"] = False
        try:
            with self.assertRaises(UnsupportedContractError):
                transpile_sql_to_verus(
                    "SELECT SUM(value) OVER () FROM t", schema
                )
            with self.assertRaises(UnsupportedContractError):
                transpile_sql_to_verus(
                    "WITH RECURSIVE cte AS (SELECT 1) SELECT SUM(value) FROM t",
                    schema,
                )
        finally:
            TRUSTED_FEATURES["window"] = old_window
            TRUSTED_FEATURES["recursive_cte"] = old_recursive

    def test_full_join_transpiles_when_enabled(self) -> None:
        schema = {
            "t": {"id": "int", "value": "int"},
            "other": {"id": "int", "value": "int"},
        }
        result = transpile_sql_to_verus(
            "SELECT SUM(t.value) FROM t FULL OUTER JOIN other ON t.id = other.id",
            schema,
        )
        self.assertIn("full_join_method_spec_helper", result)

    def test_intersect_transpile(self) -> None:
        schema = {"a": "int", "b": "int"}
        result = transpile_sql_to_verus(
            "SELECT SUM(a) FROM t WHERE b > 0 INTERSECT SELECT SUM(b) FROM t WHERE a > 0",
            schema,
        )
        self.assertIn("intersect_distinct_compose", result)

    def test_min_max_transpile(self) -> None:
        schema = {"value": "int", "metric": "bigint"}
        for agg in ("MIN", "MAX"):
            sql = f"SELECT {agg}(value) FROM t WHERE metric > 0"
            result = transpile_sql_to_verus(sql, schema)
            self.assertIn("pub open spec fn method_spec", result)
            self.assertIn("method_spec_helper", result)

    def test_where_or_not_in_like(self) -> None:
        schema = {"value": "int", "name": "string", "region": "string"}
        sql = """
            SELECT SUM(value) FROM t
            WHERE (value > 10 OR value < 5)
              AND NOT (region = 'X')
              AND value IN (1, 2, 3)
              AND name LIKE '%foo%'
        """
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("||", result)
        self.assertIn("!", result)
        self.assertIn("str_like_contains", result)
        self.assertIn('"foo"@', result)

    def test_having_transpile(self) -> None:
        schema = {"k": "int", "v": "bigint"}
        sql = """
            SELECT k, SUM(v) FROM t GROUP BY k HAVING SUM(v) > 100
        """
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("apply_having_filter", result)
        self.assertIn("pub open spec fn method_spec", result)

    def test_distinct_projection(self) -> None:
        schema = {"a": "int"}
        result = transpile_sql_to_verus(
            "SELECT DISTINCT a FROM t WHERE a > 0", schema
        )
        self.assertIn("projection_distinct_helper", result)
        self.assertIn("Set<", result)

    def test_order_by_limit(self) -> None:
        schema = {"k": "int", "v": "bigint"}
        sql = """
            SELECT k, SUM(v) FROM t GROUP BY k ORDER BY k LIMIT 10 OFFSET 2
        """
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("method_spec_result", result)
        self.assertIn("ORDER BY", result)

    def test_left_join_transpile(self) -> None:
        schema = {
            "orders": {"id": "int", "amount": "int"},
            "customers": {"id": "int", "region": "string"},
        }
        sql = """
            SELECT SUM(orders.amount)
            FROM orders
            LEFT JOIN customers ON orders.id = customers.id
        """
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("left_join_method_spec_helper", result)
        self.assertIn("LEFT JOIN", result)

    def test_union_all_transpile(self) -> None:
        schema = {"a": "int", "b": "int"}
        sql = """
            SELECT SUM(a) FROM t WHERE b > 0
            UNION ALL
            SELECT SUM(b) FROM t WHERE a > 0
        """
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("union_all_compose", result)
        self.assertIn("union_left_branch", result)

    def test_with_cte_transpile(self) -> None:
        schema = {"a": "int", "b": "int"}
        sql = """
            WITH cte AS (SELECT a FROM t WHERE b > 0)
            SELECT SUM(a) FROM cte
        """
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("CTE cte", result)
        self.assertIn("pub open spec fn method_spec", result)

    def test_exists_transpile(self) -> None:
        schema = {"value": "int", "cat": "string"}
        sql = """
            SELECT SUM(value) FROM t
            WHERE EXISTS (SELECT 1 FROM t WHERE cat = 'A')
        """
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("exists_", result)
        self.assertIn("_spec(cols)", result)

    def test_in_subquery_transpile(self) -> None:
        schema = {"value": "int", "cat": "string"}
        sql = """
            SELECT SUM(value) FROM t
            WHERE cat IN (SELECT cat FROM t WHERE value > 0)
        """
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("in_", result)
        self.assertIn("_contains", result)

    def test_scalar_order_by_ignored_comment(self) -> None:
        schema = {"value": "int"}
        result = transpile_sql_to_verus(
            "SELECT SUM(value) FROM t ORDER BY value LIMIT 5", schema
        )
        self.assertIn("ORDER BY / LIMIT ignored", result)

    def test_column_projection(self) -> None:
        projected = project_schema_for_query(self.ssb_q11_sql, self.ssb_subset)
        self.assertIn("LO_ORDERDATE", projected)
        self.assertIn("LO_EXTENDEDPRICE", projected)
        self.assertIn("LO_DISCOUNT", projected)
        self.assertEqual(len(projected), 3)

    def test_groupby_emits_map_spec(self) -> None:
        schema = {
            "D_YEAR": "int",
            "S_NATION": "string",
            "LO_REVENUE": "bigint",
        }
        sql = """
            SELECT D_YEAR, S_NATION, SUM(LO_REVENUE)
            FROM lineorder
            GROUP BY D_YEAR, S_NATION
        """
        result = transpile_sql_to_verus(sql, schema, enable_templates=True)
        self.assertIn("method_spec_helper", result)
        self.assertIn("Map<(u32, Seq<char>)", result)
        self.assertIn("HashMap", result)
        self.assertIn("// === RunQuery skeleton", result)
        self.assertTrue(
            "agg_push" in result.lower() or "AggPush" in result,
            "expected schema-driven agg_push helper in group-by emit",
        )

    def test_scalar_avg_emits_sum_count_helpers(self) -> None:
        schema = {"value": "int", "category": "string"}
        sql = "SELECT AVG(value) FROM my_table WHERE category = 'A'"
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("sum_helper", result)
        self.assertIn("count_helper", result)
        self.assertIn("sum / count", result)

    def test_avg_template_emits_dual_loop(self) -> None:
        schema = {"value": "int"}
        result = transpile_sql_to_verus(
            "SELECT AVG(value) FROM t WHERE value > 0",
            schema,
            enable_templates=True,
        )
        self.assertIn("sum_helper", result)
        self.assertIn("count_helper", result)
        self.assertIn("pub exec fn run_query", result)
        self.assertNotIn("// === RunQuery skeleton", result)

    def test_count_template_emits_scalar_loop(self) -> None:
        schema = {"value": "int"}
        result = transpile_sql_to_verus(
            "SELECT COUNT(*) FROM t WHERE value > 0",
            schema,
            enable_templates=True,
        )
        self.assertIn("pub exec fn run_query", result)
        self.assertIn("add_u64(res, 1)", result)

    def test_derived_scalar_from_composes_specs(self) -> None:
        schema = {"a": "int", "b": "int"}
        sql = """
            SELECT SUM(x)
            FROM (SELECT SUM(a) AS x FROM t WHERE b > 0) s
        """
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("derived_s_spec", result)
        self.assertIn("derived_s_helper", result)
        self.assertIn("pub open spec fn method_spec", result)

    def test_derived_project_flattens_to_base_scan(self) -> None:
        schema = {"a": "int", "b": "int"}
        sql = """
            SELECT SUM(x)
            FROM (SELECT a AS x FROM t WHERE b > 0) s
        """
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("method_spec_helper", result)
        self.assertIn("cols.get_b", result)

    def test_select_list_scalar_subquery(self) -> None:
        schema = {"value": "int", "category": "string"}
        sql = """
            SELECT (SELECT SUM(value) FROM my_table WHERE category = 'A')
            FROM my_table
        """
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("subquery_sel_sq", result)
        self.assertIn("pub open spec fn method_spec", result)

    def test_join_groupby_emits_helper(self) -> None:
        schema = {
            "orders": {"id": "int", "amt": "int", "region": "int"},
            "customers": {"id": "int", "tier": "int"},
        }
        sql = """
            SELECT orders.region, SUM(orders.amt)
            FROM orders
            INNER JOIN customers ON orders.id = customers.id
            GROUP BY orders.region
        """
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("join_method_spec_helper", result)
        self.assertIn("left.region", result)

    def test_str_str_groupby_template(self) -> None:
        schema = {"c1": "string", "c2": "string", "v": "bigint"}
        sql = "SELECT c1, c2, SUM(v) FROM t GROUP BY c1, c2"
        result = transpile_sql_to_verus(sql, schema, enable_templates=True)
        self.assertIn("agg_push_str", result)
        self.assertIn("// === RunQuery skeleton", result)
        self.assertNotIn("unimplemented!()", result)

    def test_string_column_exec_ensures(self) -> None:
        schema = {"name": "string", "value": "int"}
        result = transpile_sql_to_verus(
            "SELECT SUM(value) FROM t WHERE name = 'foo'", schema
        )
        self.assertIn(
            "ensures res@ == self.get_name(i as int),",
            result,
        )
        self.assertIn(
            "ensures res == (self.get_name(i as int) == lit@),",
            result,
        )

    def test_unsupported_derived_groupby_raises_when_disabled(self) -> None:
        from verus_transpiler.dialect_flags import TRUSTED_FEATURES

        schema = {"a": "int", "b": "int"}
        old = TRUSTED_FEATURES["grouped_derived"]
        TRUSTED_FEATURES["grouped_derived"] = False
        try:
            with self.assertRaises(UnsupportedContractError):
                transpile_sql_to_verus(
                    "SELECT SUM(x) FROM (SELECT a, SUM(b) AS x FROM t GROUP BY a) s",
                    schema,
                )
        finally:
            TRUSTED_FEATURES["grouped_derived"] = old


if __name__ == "__main__":
    unittest.main()
