"""Basic SQL joins: verify INNER ACCEPT, adversarial REJECT, DuckDB, LEFT smoke."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
VERUS_SRC = ROOT / "verus" / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(VERUS_SRC) not in sys.path:
    sys.path.insert(0, str(VERUS_SRC))

from verus.research_loop.assemble_verified_program import (  # noqa: E402
    assemble_verified_join_program,
)
from verus.research_loop.basic_sql_join_fixtures import (  # noqa: E402
    BASIC_SQL_JOIN_FIXTURES,
)
from verus.research_loop.harness import (  # noqa: E402
    resolve_verus_bin,
    run_verus_compile,
    run_verus_verify,
)
from verus.research_loop._transpiler import (  # noqa: E402
    project_multi_schema_for_query,
    transpile_sql_to_verus,
)

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

TINY_ORDERS: list[tuple[int, int]] = [
    (1, 100),
    (2, 200),
    (3, 50),
]

TINY_CUSTOMERS: list[tuple[int, int]] = [
    (1, 1),
    (2, 2),
    (3, 1),
]

_WRONG_JOIN_KEY_BODY = """\
pub exec fn run_query(left: &Cols_orders, right: &Cols_customers) -> (res: u64)
    requires
        valid_cols_orders(left),
        valid_cols_customers(right),
    ensures res == method_spec(left, right),
{
    let mut acc: u64 = 0;
    let mut li: usize = left.n;
    while li > 0
        invariant
            li <= left.n,
            valid_cols_orders(left),
            valid_cols_customers(right),
            acc == join_method_spec_helper(left, right, li as int, 0),
        decreases li,
    {
        li = li - 1;
        let mut ri: usize = right.n;
        while ri > 0
            invariant
                li < left.n,
                ri <= right.n,
                valid_cols_orders(left),
                valid_cols_customers(right),
                acc == join_method_spec_helper(left, right, li as int, ri as int),
            decreases ri,
        {
            ri = ri - 1;
            let l_key = left.get_custkey_exec(li);
            let r_key = right.get_custkey_exec(ri);
            if l_key != r_key {
                let region = right.get_region_exec(ri);
                if region == 1 {
                    let amt = left.get_amount_exec(li);
                    acc = add_u64(acc, amt);
                }
            }
            assert(acc == join_method_spec_helper(left, right, li as int, ri as int));
        }
    }
    acc
}"""

_WRONG_JOIN_KEY_EXTERNAL_BODY = """\
// TRUSTED: wrong join key still verifies (residual external_body gap).
#[verifier::external_body]
pub exec fn run_query(left: &Cols_orders, right: &Cols_customers) -> (res: u64)
    requires
        valid_cols_orders(left),
        valid_cols_customers(right),
    ensures res == method_spec(left, right),
{
    let mut acc: u64 = 0;
    let mut li: usize = 0;
    while li < left.n {
        let mut ri: usize = 0;
        while ri < right.n {
            let l_key = left.get_custkey_exec(li);
            let r_key = right.get_custkey_exec(ri);
            if l_key != r_key {
                let region = right.get_region_exec(ri);
                if region == 1 {
                    let amt = left.get_amount_exec(li);
                    acc = add_u64(acc, amt);
                }
            }
            ri = ri + 1;
        }
        li = li + 1;
    }
    acc
}"""


def write_pipe_tbl(
    path: str,
    columns: list[str],
    rows: list[tuple[object, ...]],
) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("|".join(columns) + "\n")
        for row in rows:
            cells = [str(val) for val in row]
            f.write("|".join(cells) + "\n")


def parse_scalar_result(stdout: str) -> int:
    m = re.search(r"RESULT:\s*(\d+)", stdout)
    if not m:
        raise ValueError(f"no scalar RESULT in output: {stdout!r}")
    return int(m.group(1))


def duckdb_join_scalar(
    sql: str,
    left_tbl: str,
    right_tbl: str,
    *,
    left_table: str = "orders",
    right_table: str = "customers",
) -> int:
    con = duckdb.connect()
    con.execute(
        f"CREATE TABLE {left_table} AS "
        f"SELECT * FROM read_csv('{left_tbl}', delim='|', header=true)"
    )
    con.execute(
        f"CREATE TABLE {right_table} AS "
        f"SELECT * FROM read_csv('{right_tbl}', delim='|', header=true)"
    )
    row = con.execute(sql).fetchone()
    assert row is not None
    return int(row[0])


def assemble_verified_join_program_source(
    *,
    schema: dict[str, dict[str, str]],
    sql: str,
    run_query_body: str,
    table_order: tuple[str, str],
    ret_type: str,
    default_tbls: dict[str, str],
    hot_path_rs: str = "",
) -> str:
    projected = project_multi_schema_for_query(sql, schema)
    spec_rs = transpile_sql_to_verus(sql, projected, enable_templates=False)
    return assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=run_query_body,
        multi_schema=projected,
        table_order=table_order,
        ret_type=ret_type,
        default_tbls=default_tbls,
        hot_path_rs=hot_path_rs,
    )


def verify_assembled_join_run_query(
    *,
    schema: dict[str, dict[str, str]],
    sql: str,
    run_query_body: str,
    table_order: tuple[str, str],
    ret_type: str,
    timeout: int = 120,
    hot_path_rs: str = "",
) -> bool:
    program = assemble_verified_join_program_source(
        schema=schema,
        sql=sql,
        run_query_body=run_query_body,
        table_order=table_order,
        ret_type=ret_type,
        default_tbls={t: "/dev/null" for t in table_order},
        hot_path_rs=hot_path_rs,
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".rs", delete=False, encoding="utf-8"
    ) as f:
        f.write(program)
        rs_path = f.name
    try:
        ok, _msg = run_verus_verify(rs_path, timeout)
        return ok
    finally:
        os.unlink(rs_path)


def compile_and_run_join_program(
    program: str,
    left_tbl: str,
    right_tbl: str,
    *,
    limit: int = 1000,
    compile_timeout: int = 180,
) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        rs_path = os.path.join(tmp, "join_query.rs")
        with open(rs_path, "w", encoding="utf-8") as f:
            f.write(program)
        ok, msg, binary = run_verus_compile(rs_path, compile_timeout)
        if not ok or not binary:
            return False, msg
        res = subprocess.run(
            [binary, left_tbl, right_tbl, str(limit)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (res.stdout + "\n" + res.stderr).strip()
        if res.returncode != 0:
            return False, out
        return True, out


@unittest.skipUnless(resolve_verus_bin(), "verus binary not found")
class TestBasicSqlJoinsVerify(unittest.TestCase):
    def test_inner_join_honest_accepts(self) -> None:
        fx = BASIC_SQL_JOIN_FIXTURES["inner_join_sum"]
        ok = verify_assembled_join_run_query(
            schema=fx.schema,
            sql=fx.sql,
            run_query_body=fx.run_query,
            table_order=fx.table_order,
            ret_type=fx.ret_type,
            hot_path_rs=fx.hot_path,
        )
        self.assertTrue(ok, "honest inner_join_sum should verify")

    def test_inner_join_wrong_key_rejects(self) -> None:
        fx = BASIC_SQL_JOIN_FIXTURES["inner_join_sum"]
        ok = verify_assembled_join_run_query(
            schema=fx.schema,
            sql=fx.sql,
            run_query_body=_WRONG_JOIN_KEY_BODY,
            table_order=fx.table_order,
            ret_type=fx.ret_type,
        )
        self.assertFalse(ok, "proved wrong join key should be rejected")

    def test_inner_join_wrong_key_external_body_still_accepts(self) -> None:
        """TRUSTED run_query can verify while lying; DuckDB tests catch exec bugs."""
        fx = BASIC_SQL_JOIN_FIXTURES["inner_join_sum"]
        ok = verify_assembled_join_run_query(
            schema=fx.schema,
            sql=fx.sql,
            run_query_body=_WRONG_JOIN_KEY_EXTERNAL_BODY,
            table_order=fx.table_order,
            ret_type=fx.ret_type,
        )
        self.assertTrue(ok, "external_body wrong join key still verifies (known gap)")

    def test_left_join_smoke_accepts(self) -> None:
        fx = BASIC_SQL_JOIN_FIXTURES["left_join_sum"]
        ok = verify_assembled_join_run_query(
            schema=fx.schema,
            sql=fx.sql,
            run_query_body=fx.run_query,
            table_order=fx.table_order,
            ret_type=fx.ret_type,
            hot_path_rs=fx.hot_path,
        )
        self.assertTrue(ok, "LEFT JOIN smoke (TRUSTED) should verify")

    def test_tpch_join_honest_accepts(self) -> None:
        fx = BASIC_SQL_JOIN_FIXTURES["tpch_join_sum"]
        ok = verify_assembled_join_run_query(
            schema=fx.schema,
            sql=fx.sql,
            run_query_body=fx.run_query,
            table_order=fx.table_order,
            ret_type=fx.ret_type,
            timeout=180,
            hot_path_rs=fx.hot_path,
        )
        self.assertTrue(ok, "honest tpch_join_sum should verify")


@unittest.skipUnless(resolve_verus_bin(), "verus binary not found")
class TestBasicSqlJoinsDuckDB(unittest.TestCase):
    def test_inner_join_matches_duckdb(self) -> None:
        fx = BASIC_SQL_JOIN_FIXTURES["inner_join_sum"]
        with tempfile.TemporaryDirectory() as tmp:
            left = os.path.join(tmp, "orders.tbl")
            right = os.path.join(tmp, "customers.tbl")
            write_pipe_tbl(left, ["CUSTKEY", "AMOUNT"], TINY_ORDERS)
            write_pipe_tbl(right, ["CUSTKEY", "REGION"], TINY_CUSTOMERS)
            expected = duckdb_join_scalar(fx.sql, left, right)
            program = assemble_verified_join_program_source(
                schema=fx.schema,
                sql=fx.sql,
                run_query_body=fx.run_query,
                table_order=fx.table_order,
                ret_type=fx.ret_type,
                default_tbls=fx.default_tbls,
                hot_path_rs=fx.hot_path,
            )
            ok, out = compile_and_run_join_program(program, left, right)
            self.assertTrue(ok, out)
            self.assertEqual(parse_scalar_result(out), expected)

    def test_left_join_matches_duckdb(self) -> None:
        fx = BASIC_SQL_JOIN_FIXTURES["left_join_sum"]
        with tempfile.TemporaryDirectory() as tmp:
            left = os.path.join(tmp, "orders.tbl")
            right = os.path.join(tmp, "customers.tbl")
            write_pipe_tbl(left, ["CUSTKEY", "AMOUNT"], TINY_ORDERS + [(5, 40)])
            write_pipe_tbl(right, ["CUSTKEY", "REGION"], TINY_CUSTOMERS)
            expected = duckdb_join_scalar(fx.sql, left, right)
            program = assemble_verified_join_program_source(
                schema=fx.schema,
                sql=fx.sql,
                run_query_body=fx.run_query,
                table_order=fx.table_order,
                ret_type=fx.ret_type,
                default_tbls=fx.default_tbls,
                hot_path_rs=fx.hot_path,
            )
            ok, out = compile_and_run_join_program(program, left, right)
            self.assertTrue(ok, out)
            self.assertEqual(parse_scalar_result(out), expected)


if __name__ == "__main__":
    unittest.main()
