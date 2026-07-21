"""Basic SQL set-ops / subqueries / CTEs: verify, DuckDB, adversarial."""

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

from verus.research_loop.basic_sql_set_cte_fixtures import (  # noqa: E402
    BASIC_SQL_SET_CTE_FIXTURES,
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

TINY_UNION_ROWS: list[tuple[int, int]] = [(10, 1), (5, 0), (3, 2), (20, 3)]
TINY_SUBQ_ROWS: list[tuple[int, int]] = [(10, 1), (20, 2), (5, 1), (15, 3)]
TINY_CTE_ROWS: list[tuple[int, int]] = [(10, 1), (5, 0), (3, 2), (20, 3)]


def parse_seq_result(stdout: str) -> tuple[int, int]:
    m = re.search(r"RESULT:\s*seq_len=(\d+)\s+checksum=(\d+)", stdout)
    if not m:
        raise ValueError(f"no seq RESULT in output: {stdout!r}")
    return int(m.group(1)), int(m.group(2))


def duckdb_union_checksum(sql: str, tbl_path: str) -> tuple[int, int]:
    con = duckdb.connect()
    con.execute(
        f"CREATE TABLE t AS SELECT * FROM read_csv('{tbl_path}', delim='|', header=true)"
    )
    rows = con.execute(sql).fetchall()
    checksum = 0
    for row in rows:
        checksum = (checksum + int(row[0])) % (1 << 64)
    return len(rows), checksum


@unittest.skipUnless(resolve_verus_bin(), "verus binary not found")
class TestBasicSqlSetCteVerify(unittest.TestCase):
    def test_honest_fixtures_accept(self) -> None:
        for key, fx in BASIC_SQL_SET_CTE_FIXTURES.items():
            with self.subTest(feature=key):
                ok = verify_assembled_run_query(
                    schema=fx.schema,
                    sql=fx.sql,
                    run_query_body=fx.run_query,
                    ret_type=fx.ret_type,
                )
                self.assertTrue(ok, f"honest {key} should verify")

    def test_scalar_subquery_wrong_filter_rejects(self) -> None:
        fx = BASIC_SQL_SET_CTE_FIXTURES["scalar_subquery"]
        bad_body = fx.run_query.replace("cat == 1", "cat == 2")
        ok = verify_assembled_run_query(
            schema=fx.schema,
            sql=fx.sql,
            run_query_body=bad_body,
            ret_type=fx.ret_type,
        )
        self.assertFalse(ok, "wrong subquery filter should be rejected")


@unittest.skipUnless(resolve_verus_bin(), "verus binary not found")
class TestBasicSqlSetCteDuckDB(unittest.TestCase):
    def test_union_all_matches_duckdb(self) -> None:
        fx = BASIC_SQL_SET_CTE_FIXTURES["union_all"]
        with tempfile.TemporaryDirectory() as tmp:
            tbl = os.path.join(tmp, "union.tbl")
            write_pipe_tbl(tbl, ["A", "B"], TINY_UNION_ROWS)
            expected_len, expected_cs = duckdb_union_checksum(fx.sql, tbl)
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

    def test_scalar_features_match_duckdb(self) -> None:
        cases = [
            ("exists_uncorrelated", TINY_SUBQ_ROWS),
            ("in_subquery", TINY_SUBQ_ROWS),
            ("scalar_subquery", TINY_SUBQ_ROWS),
            ("with_cte", TINY_CTE_ROWS),
        ]
        for key, rows in cases:
            fx = BASIC_SQL_SET_CTE_FIXTURES[key]
            with self.subTest(feature=key):
                with tempfile.TemporaryDirectory() as tmp:
                    tbl = os.path.join(tmp, f"{key}.tbl")
                    cols = (
                        ["VALUE", "CAT"]
                        if key != "with_cte"
                        else ["A", "B"]
                    )
                    write_pipe_tbl(tbl, cols, rows)
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
