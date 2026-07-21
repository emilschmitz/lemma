"""Basic SQL projection / ORDER BY / arithmetic: verify + DuckDB."""

from __future__ import annotations

import os
import re
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

from verus.research_loop.basic_sql_proj_order_fixtures import (  # noqa: E402
    BASIC_SQL_PROJ_ORDER_FIXTURES,
)
from verus.research_loop.harness import resolve_verus_bin  # noqa: E402

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
from test_adversarial_runquery import (  # noqa: E402
    assemble_verified_program_source,
    compile_and_run_verified_program,
    verify_assembled_run_query,
)
from test_basic_sql_batch1 import (  # noqa: E402
    duckdb_scalar,
    parse_scalar_result,
    write_pipe_tbl,
)

TINY_AB_ROWS: list[tuple[int, int]] = [(1, 10), (2, 20), (3, 30), (4, 40)]
TINY_DISTINCT_ROWS: list[tuple[int]] = [(1,), (2,), (2,), (3,), (5,)]
TINY_ORDER_ROWS: list[tuple[int, int]] = [(3, 10), (1, 5), (2, 20), (1, 7), (4, 100)]
TINY_ARITH_ROWS: list[tuple[int, int]] = [(10, 1), (5, 2), (3, 4)]


def parse_seq_result(stdout: str) -> tuple[int, int]:
    m = re.search(r"RESULT:\s*seq_len=(\d+)\s+checksum=(\d+)", stdout)
    if not m:
        raise ValueError(f"no seq RESULT in output: {stdout!r}")
    return int(m.group(1)), int(m.group(2))


def parse_set_result(stdout: str) -> tuple[int, int]:
    m = re.search(r"RESULT:\s*set_len=(\d+)\s+checksum=(\d+)", stdout)
    if not m:
        raise ValueError(f"no set RESULT in output: {stdout!r}")
    return int(m.group(1)), int(m.group(2))


def duckdb_seq_checksum_a(sql: str, tbl_path: str) -> tuple[int, int]:
    """Checksum first column of multi-column SELECT (spec tracks column a)."""
    con = duckdb.connect()
    con.execute(
        f"CREATE TABLE t AS SELECT * FROM read_csv('{tbl_path}', delim='|', header=true)"
    )
    rows = con.execute(sql).fetchall()
    checksum = sum(int(row[0]) for row in rows) % (1 << 64)
    return len(rows), checksum


def duckdb_distinct_checksum(sql: str, tbl_path: str) -> tuple[int, int]:
    con = duckdb.connect()
    con.execute(
        f"CREATE TABLE t AS SELECT * FROM read_csv('{tbl_path}', delim='|', header=true)"
    )
    rows = con.execute(sql).fetchall()
    checksum = sum(int(row[0]) for row in rows) % (1 << 64)
    return len(rows), checksum


def duckdb_order_limit_checksum(sql: str, tbl_path: str) -> tuple[int, int]:
    con = duckdb.connect()
    con.execute(
        f"CREATE TABLE t AS SELECT * FROM read_csv('{tbl_path}', delim='|', header=true)"
    )
    rows = con.execute(sql).fetchall()
    checksum = 0
    for k, v in rows:
        checksum = (checksum + int(k) + int(v)) % (1 << 64)
    return len(rows), checksum


@unittest.skipUnless(resolve_verus_bin(), "verus binary not found")
class TestBasicSqlProjOrderVerify(unittest.TestCase):
    def test_honest_fixtures_accept(self) -> None:
        for key, fx in BASIC_SQL_PROJ_ORDER_FIXTURES.items():
            with self.subTest(feature=key):
                ok = verify_assembled_run_query(
                    schema=fx.schema,
                    sql=fx.sql,
                    run_query_body=fx.run_query,
                    ret_type=fx.ret_type,
                )
                self.assertTrue(ok, f"honest {key} should verify")

    def test_arith_wrong_term_rejects(self) -> None:
        fx = BASIC_SQL_PROJ_ORDER_FIXTURES["arith_sum"]
        bad = fx.run_query.replace("a > 0", "a < 0")
        ok = verify_assembled_run_query(
            schema=fx.schema,
            sql=fx.sql,
            run_query_body=bad,
            ret_type=fx.ret_type,
        )
        self.assertFalse(ok, "wrong filter on arith_sum should reject")


@unittest.skipUnless(resolve_verus_bin(), "verus binary not found")
class TestBasicSqlProjOrderDuckDB(unittest.TestCase):
    def test_distinct_proj_matches_duckdb(self) -> None:
        fx = BASIC_SQL_PROJ_ORDER_FIXTURES["distinct_proj"]
        with tempfile.TemporaryDirectory() as tmp:
            tbl = os.path.join(tmp, "distinct.tbl")
            write_pipe_tbl(tbl, ["A"], TINY_DISTINCT_ROWS)
            expected_len, expected_cs = duckdb_distinct_checksum(fx.sql, tbl)
            program = assemble_verified_program_source(
                schema=fx.schema,
                sql=fx.sql,
                run_query_body=fx.run_query,
                ret_type=fx.ret_type,
                default_tbl=tbl,
            )
            ok, out = compile_and_run_verified_program(program, tbl)
            self.assertTrue(ok, out)
            actual_len, actual_cs = parse_set_result(out)
            self.assertEqual(actual_len, expected_len)
            self.assertEqual(actual_cs, expected_cs)

    def test_projection_matches_duckdb_column_a(self) -> None:
        fx = BASIC_SQL_PROJ_ORDER_FIXTURES["projection"]
        with tempfile.TemporaryDirectory() as tmp:
            tbl = os.path.join(tmp, "proj.tbl")
            write_pipe_tbl(tbl, ["A", "B"], TINY_AB_ROWS)
            expected_len, expected_cs = duckdb_seq_checksum_a(fx.sql, tbl)
            program = assemble_verified_program_source(
                schema=fx.schema,
                sql=fx.sql,
                run_query_body=fx.run_query,
                ret_type=fx.ret_type,
                default_tbl=tbl,
            )
            ok, out = compile_and_run_verified_program(program, tbl)
            self.assertTrue(ok, out)
            actual_len, actual_cs = parse_seq_result(out)
            self.assertEqual(actual_len, expected_len)
            self.assertEqual(actual_cs, expected_cs)

    def test_order_limit_matches_duckdb(self) -> None:
        fx = BASIC_SQL_PROJ_ORDER_FIXTURES["order_limit"]
        with tempfile.TemporaryDirectory() as tmp:
            tbl = os.path.join(tmp, "order.tbl")
            write_pipe_tbl(tbl, ["K", "V"], TINY_ORDER_ROWS)
            expected_len, expected_cs = duckdb_order_limit_checksum(fx.sql, tbl)
            program = assemble_verified_program_source(
                schema=fx.schema,
                sql=fx.sql,
                run_query_body=fx.run_query,
                ret_type=fx.ret_type,
                default_tbl=tbl,
            )
            ok, out = compile_and_run_verified_program(program, tbl)
            self.assertTrue(ok, out)
            actual_len, actual_cs = parse_seq_result(out)
            self.assertEqual(actual_len, expected_len)
            self.assertEqual(actual_cs, expected_cs)

    def test_arith_sum_matches_duckdb(self) -> None:
        fx = BASIC_SQL_PROJ_ORDER_FIXTURES["arith_sum"]
        with tempfile.TemporaryDirectory() as tmp:
            tbl = os.path.join(tmp, "arith.tbl")
            write_pipe_tbl(tbl, ["A", "B"], TINY_ARITH_ROWS)
            expected = duckdb_scalar(fx.sql, tbl)
            program = assemble_verified_program_source(
                schema=fx.schema,
                sql=fx.sql,
                run_query_body=fx.run_query,
                ret_type=fx.ret_type,
                default_tbl=tbl,
            )
            ok, out = compile_and_run_verified_program(program, tbl)
            self.assertTrue(ok, out)
            self.assertEqual(parse_scalar_result(out), expected)


if __name__ == "__main__":
    unittest.main()
