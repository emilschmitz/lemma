"""Extended Basic SQL: INTERSECT/EXCEPT, joins, ILIKE, windows, recursive CTE."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERUS_SRC = ROOT / "verus" / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(VERUS_SRC) not in sys.path:
    sys.path.insert(0, str(VERUS_SRC))

from verus.research_loop.assemble_verified_program import (  # noqa: E402
    _emit_agg_helpers,
    _strip_skeleton,
    generate_load_cols_verus,
)
from verus.research_loop.basic_sql_extended_fixtures import (  # noqa: E402
    BASIC_SQL_EXTENDED_FIXTURES,
)
from verus.research_loop.harness import resolve_verus_bin, run_verus_verify  # noqa: E402
from verus_transpiler import UnsupportedContractError, transpile_sql_to_verus  # noqa: E402
from verus_transpiler.column_projection import project_multi_schema_for_query  # noqa: E402
from verus_transpiler.dialect_flags import TRUSTED_FEATURES  # noqa: E402

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
from test_adversarial_runquery import verify_assembled_run_query  # noqa: E402


def _assemble_nway_program_source(
    *,
    schema: dict[str, dict[str, str]],
    sql: str,
    run_query_body: str,
    table_order: tuple[str, ...],
    ret_type: str,
    default_tbls: dict[str, str],
) -> str:
    projected = project_multi_schema_for_query(sql, schema)
    spec_rs = transpile_sql_to_verus(sql, projected, enable_templates=False)
    core = _strip_skeleton(spec_rs)
    boundary = _emit_agg_helpers(ret_type)
    loaders = "\n".join(
        generate_load_cols_verus(
            cols,
            struct_name=f"Cols_{table}",
            valid_fn=f"valid_cols_{table}",
            load_fn=f"load_cols_{table}",
        ).strip()
        for table, cols in projected.items()
    )
    args = ", ".join(f"{t}: &Cols_{t}" for t in table_order)
    tbl_args = ", ".join(
        f'&load_cols_{t}("{default_tbls[t]}", limit)' for t in table_order
    )
    main_rs = f"""
fn main() {{
    let limit: usize = 1000;
    let res = run_query({tbl_args});
    println!("{{}}", res);
}}
"""
    return (
        f"{core}\n"
        f"{boundary}\n"
        f"{run_query_body.rstrip()}\n\n"
        f"{loaders}\n"
        f"}} // verus!\n"
        f"{main_rs}"
    )


class TestBasicSqlExtendedEmit(unittest.TestCase):
    def test_intersect_emits_compose(self) -> None:
        schema = {"a": "bigint", "b": "int"}
        sql = "SELECT SUM(a) FROM t WHERE b > 0 INTERSECT SELECT SUM(b) FROM t WHERE a > 0"
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("intersect_distinct_compose", result)
        self.assertIn("intersect_left_branch", result)

    def test_except_emits_compose(self) -> None:
        schema = {"a": "bigint", "b": "int"}
        sql = "SELECT SUM(a) FROM t WHERE b > 0 EXCEPT SELECT SUM(b) FROM t WHERE a > 0"
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("except_distinct_compose", result)

    def test_cross_join_emits_trusted_helper(self) -> None:
        schema = {"a": {"v": "bigint"}, "b": {"k": "int"}}
        sql = "SELECT SUM(a.v) FROM a CROSS JOIN b"
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("cross_join_method_spec_helper", result)

    def test_full_join_emits_helper(self) -> None:
        schema = {"a": {"id": "int", "v": "bigint"}, "b": {"id": "int", "k": "int"}}
        result = transpile_sql_to_verus(
            "SELECT SUM(a.v) FROM a FULL OUTER JOIN b ON a.id = b.id", schema
        )
        self.assertIn("full_join_method_spec_helper", result)

    def test_nway_join_emits_helper(self) -> None:
        schema = {
            "a": {"id": "int", "v": "bigint"},
            "b": {"id": "int", "k": "int"},
            "c": {"id": "int", "w": "bigint"},
        }
        sql = "SELECT SUM(a.v) FROM a JOIN b ON a.id = b.id JOIN c ON b.id = c.id"
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("nway_join_method_spec_helper", result)

    def test_window_sum_emits_helper(self) -> None:
        schema = {"value": "bigint", "cat": "int"}
        sql = (
            "SELECT SUM(x) FROM "
            "(SELECT SUM(value) OVER (PARTITION BY cat) AS x FROM t) s"
        )
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("window_sum_x_spec", result)

    def test_row_number_emits_helper(self) -> None:
        schema = {"value": "bigint", "cat": "int"}
        sql = (
            "SELECT SUM(rn) FROM "
            "(SELECT ROW_NUMBER() OVER (ORDER BY value) AS rn FROM t) s"
        )
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("window_row_number_rn_spec", result)

    def test_recursive_cte_emits_helper(self) -> None:
        schema = {"cat": "int", "value": "bigint"}
        sql = (
            "WITH RECURSIVE cnt(n) AS ("
            "  SELECT cat AS n FROM t WHERE cat = 1 "
            "  UNION ALL SELECT n AS n FROM cnt WHERE n < 3"
            ") SELECT SUM(n) FROM cnt"
        )
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("recursive_cnt_spec", result)

    def test_ilike_emits_helper(self) -> None:
        schema = {"name": "string", "value": "bigint"}
        result = transpile_sql_to_verus(
            "SELECT SUM(value) FROM t WHERE name ILIKE 'foo%'", schema
        )
        self.assertIn("str_ilike_match", result)

    def test_like_underscore_emits_helper(self) -> None:
        schema = {"name": "string", "value": "bigint"}
        result = transpile_sql_to_verus(
            "SELECT SUM(value) FROM t WHERE name LIKE 'f_o'", schema
        )
        self.assertIn("str_like_underscore_match", result)

    def test_grouped_derived_emits_trusted_map(self) -> None:
        schema = {"a": "bigint", "b": "int"}
        sql = (
            "SELECT SUM(x) FROM "
            "(SELECT a, SUM(b) AS x FROM t GROUP BY a) s"
        )
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("derived_s_spec", result)

    def test_correlated_exists_emits_corr_helper(self) -> None:
        schema = {"value": "bigint", "cat": "int"}
        sql = (
            "SELECT SUM(value) FROM t AS t_outer "
            "WHERE EXISTS (SELECT 1 FROM t AS t_inner WHERE t_inner.cat = t_outer.cat)"
        )
        result = transpile_sql_to_verus(sql, schema)
        self.assertIn("exists_corr_", result)

    def test_abs_emits_helper(self) -> None:
        schema = {"delta": "int", "value": "bigint", "active": "bool"}
        result = transpile_sql_to_verus("SELECT SUM(abs(delta)) FROM t", schema)
        self.assertIn("abs_u64", result)

    def test_flag_off_rejects_intersect(self) -> None:
        schema = {"a": "bigint", "b": "int"}
        sql = "SELECT SUM(a) FROM t INTERSECT SELECT SUM(b) FROM t"
        old = TRUSTED_FEATURES["intersect_except"]
        TRUSTED_FEATURES["intersect_except"] = False
        try:
            with self.assertRaises(UnsupportedContractError) as ctx:
                transpile_sql_to_verus(sql, schema)
            self.assertIn("intersect_except disabled", str(ctx.exception))
        finally:
            TRUSTED_FEATURES["intersect_except"] = old

    def test_flag_off_rejects_ilike(self) -> None:
        schema = {"name": "string", "value": "int"}
        old = TRUSTED_FEATURES["ilike"]
        TRUSTED_FEATURES["ilike"] = False
        try:
            with self.assertRaises(UnsupportedContractError):
                transpile_sql_to_verus(
                    "SELECT SUM(value) FROM t WHERE name ILIKE 'x%'", schema
                )
        finally:
            TRUSTED_FEATURES["ilike"] = old

    def test_flag_off_rejects_like_underscore(self) -> None:
        schema = {"name": "string", "value": "int"}
        old = TRUSTED_FEATURES["like_underscore"]
        TRUSTED_FEATURES["like_underscore"] = False
        try:
            with self.assertRaises(UnsupportedContractError):
                transpile_sql_to_verus(
                    "SELECT SUM(value) FROM t WHERE name LIKE 'f_o'", schema
                )
        finally:
            TRUSTED_FEATURES["like_underscore"] = old


@unittest.skipUnless(resolve_verus_bin(), "verus binary not found")
class TestBasicSqlExtendedVerify(unittest.TestCase):
    def test_honest_fixtures_accept(self) -> None:
        for key, fx in BASIC_SQL_EXTENDED_FIXTURES.items():
            with self.subTest(feature=key):
                if fx.is_nway_join:
                    assert fx.table_order is not None
                    assert fx.default_tbls is not None
                    src = _assemble_nway_program_source(
                        schema=fx.schema,
                        sql=fx.sql,
                        run_query_body=fx.run_query,
                        table_order=fx.table_order,
                        ret_type=fx.ret_type,
                        default_tbls=fx.default_tbls,
                    )
                    with tempfile.NamedTemporaryFile(
                        mode="w", suffix=".rs", delete=False, encoding="utf-8"
                    ) as f:
                        f.write(src)
                        path = f.name
                    try:
                        ok, _ = run_verus_verify(path, 120)
                    finally:
                        os.unlink(path)
                elif fx.is_join:
                    from test_basic_sql_joins import assemble_verified_join_program_source

                    assert fx.table_order is not None and len(fx.table_order) == 2
                    assert fx.default_tbls is not None
                    src = assemble_verified_join_program_source(
                        schema=fx.schema,
                        sql=fx.sql,
                        run_query_body=fx.run_query,
                        ret_type=fx.ret_type,
                        table_order=(fx.table_order[0], fx.table_order[1]),
                        default_tbls=fx.default_tbls,
                    )
                    with tempfile.NamedTemporaryFile(
                        mode="w", suffix=".rs", delete=False, encoding="utf-8"
                    ) as f:
                        f.write(src)
                        path = f.name
                    try:
                        ok, _ = run_verus_verify(path, 120)
                    finally:
                        os.unlink(path)
                else:
                    ok = verify_assembled_run_query(
                        schema=fx.schema,
                        sql=fx.sql,
                        run_query_body=fx.run_query,
                        ret_type=fx.ret_type,
                    )
                self.assertTrue(ok, f"honest {key} should verify")


if __name__ == "__main__":
    unittest.main()
