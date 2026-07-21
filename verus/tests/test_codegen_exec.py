"""Custom SQL codegen_exec: scalar / group-by / join pipeline (no fixture dicts)."""

from __future__ import annotations

import os
import re
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

from verus.research_loop.harness import (  # noqa: E402
    resolve_verus_bin,
    run_custom_sql_pipeline,
)
from verus.research_loop.ssb_queries import load_schema  # noqa: E402
from verus_transpiler.codegen_exec import generate_exec_bundle  # noqa: E402
from verus_transpiler.parse_sql import parse_sql  # noqa: E402

_SCALAR_SCHEMA = {"X": "bigint", "Y": "int"}
_GROUPBY_SCHEMA = {"K": "int", "S": "string", "V": "bigint"}
_JOIN_SCHEMA = {
    "orders": {"CUSTKEY": "int", "AMOUNT": "bigint"},
    "customers": {"CUSTKEY": "int", "REGION": "int"},
}

TINY_SCALAR = [(10, 2), (20, 0), (30, 5), (7, 1)]
TINY_GROUPBY = [(1, "a", 8), (1, "a", 5), (2, "b", 12), (1, "b", 3)]
TINY_ORDERS = [(1, 100), (2, 200), (3, 50)]
TINY_CUSTOMERS = [(1, 1), (2, 2), (3, 1)]


def write_pipe_tbl(path: str, columns: list[str], rows: list[tuple[object, ...]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("|".join(columns) + "\n")
        for row in rows:
            f.write("|".join(str(v) for v in row) + "\n")


def parse_scalar(stdout: str) -> int:
    m = re.search(r"RESULT:\s*(\d+)", stdout)
    if not m:
        raise ValueError(stdout)
    return int(m.group(1))


@unittest.skipUnless(resolve_verus_bin(), "verus not on PATH")
class TestCodegenExecPipeline(unittest.TestCase):
    def test_scalar_sum_where_generates_and_verifies(self) -> None:
        sql = "SELECT SUM(x) FROM t WHERE y >= 1"
        bundle = generate_exec_bundle(parse_sql(sql, _SCALAR_SCHEMA), _SCALAR_SCHEMA)
        self.assertTrue(bundle.proved)
        self.assertIn("method_spec_helper", bundle.run_query_rs)

        with tempfile.TemporaryDirectory() as td:
            tbl = os.path.join(td, "t.tbl")
            write_pipe_tbl(tbl, ["X", "Y"], TINY_SCALAR)
            res = run_custom_sql_pipeline(
                sql, _SCALAR_SCHEMA, tbl=tbl, limit=10_000, skip_bench=True
            )
        self.assertEqual(res["status"], "SUCCESS")
        self.assertTrue(res["proof_verified"])

    def test_groupby_two_key_generates_and_verifies(self) -> None:
        sql = "SELECT k, s, SUM(v) FROM t GROUP BY k, s"
        bundle = generate_exec_bundle(parse_sql(sql, _GROUPBY_SCHEMA), _GROUPBY_SCHEMA)
        self.assertFalse(bundle.proved)
        self.assertIn("external_body", bundle.run_query_rs)
        self.assertIn("custom_groupby_hot", bundle.hot_path_rs)

        with tempfile.TemporaryDirectory() as td:
            tbl = os.path.join(td, "t.tbl")
            write_pipe_tbl(tbl, ["K", "S", "V"], TINY_GROUPBY)
            res = run_custom_sql_pipeline(
                sql, _GROUPBY_SCHEMA, tbl=tbl, limit=10_000, skip_bench=True
            )
        self.assertEqual(res["status"], "SUCCESS")
        self.assertTrue(res["proof_verified"])

    def test_inner_join_scalar_generates_and_verifies(self) -> None:
        sql = (
            "SELECT SUM(o.amount) FROM orders o "
            "INNER JOIN customers c ON o.custkey = c.custkey "
            "WHERE c.region = 1"
        )
        bundle = generate_exec_bundle(parse_sql(sql, _JOIN_SCHEMA), _JOIN_SCHEMA)
        self.assertFalse(bundle.proved)
        self.assertIn("custom_join_sum_hot", bundle.hot_path_rs)

        with tempfile.TemporaryDirectory() as td:
            left = os.path.join(td, "orders.tbl")
            right = os.path.join(td, "customers.tbl")
            write_pipe_tbl(left, ["CUSTKEY", "AMOUNT"], TINY_ORDERS)
            write_pipe_tbl(right, ["CUSTKEY", "REGION"], TINY_CUSTOMERS)
            res = run_custom_sql_pipeline(
                sql,
                _JOIN_SCHEMA,
                tbls={"orders": left, "customers": right},
                limit=10_000,
                skip_bench=True,
            )
        self.assertEqual(res["status"], "SUCCESS")
        self.assertTrue(res["proof_verified"])

    def test_custom_ssb_variant_not_in_fixtures(self) -> None:
        """Slightly different filter from SSB Q1 — proves generality without fixture dict."""
        schema = load_schema()
        sql = (
            "SELECT SUM(lo_extendedprice * lo_discount) AS revenue "
            "FROM lineorder "
            "WHERE lo_orderdate >= 19930101 AND lo_orderdate <= 19931231 "
            "AND lo_discount BETWEEN 2 AND 4 AND lo_quantity < 30"
        )
        bundle = generate_exec_bundle(parse_sql(sql, schema), schema)
        self.assertTrue(bundle.proved)

        ssb_tbl = ROOT / "ssb-dbgen" / "lineorder_flat.tbl"
        if not ssb_tbl.is_file():
            self.skipTest("SSB tbl missing")

        res = run_custom_sql_pipeline(
            sql,
            schema,
            tbl=str(ssb_tbl),
            limit=5_000,
            skip_bench=True,
        )
        self.assertEqual(res["status"], "SUCCESS")
        self.assertTrue(res["proof_verified"])


if __name__ == "__main__":
    unittest.main()
