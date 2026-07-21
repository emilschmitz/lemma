"""Custom SQL agent path: transpile → run_query_body → verify (no codegen_exec)."""

from __future__ import annotations

import json
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

from verus.research_loop.harness import (  # noqa: E402
    FAILED_TRANSPILE_DIR,
    PENDING_RUNQUERY_DIR,
    resolve_verus_bin,
    run_custom_sql_pipeline,
)

_SCALAR_SCHEMA = {"X": "bigint", "Y": "int"}

_SCALAR_SUM_RUNQUERY = """\
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut res: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            res == method_spec_helper(cols, i as int),
        decreases i,
    {
        i = i - 1;
        let y = cols.get_y_exec(i);
        if y >= 1 {
            let x = cols.get_x_exec(i);
            res = add_u64(res, x);
        }
        assert(res == method_spec_helper(cols, i as int));
    }
    res
}"""

TINY_SCALAR = [(10, 2), (20, 0), (30, 5), (7, 1)]


def write_pipe_tbl(path: str, columns: list[str], rows: list[tuple[object, ...]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("|".join(columns) + "\n")
        for row in rows:
            f.write("|".join(str(v) for v in row) + "\n")


class TestCustomSqlAgentPathNoDuckDB(unittest.TestCase):
    def test_harness_custom_path_has_no_duckdb_import(self) -> None:
        harness_src = (ROOT / "verus" / "research_loop" / "harness.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("import duckdb", harness_src)
        self.assertNotIn("duckdb.", harness_src)
        self.assertNotIn("generate_exec_bundle", harness_src)


class TestCustomSqlAgentPathFailures(unittest.TestCase):
    def test_missing_runquery_body_fails_to_pending(self) -> None:
        sql = "SELECT SUM(x) FROM t WHERE y >= 1"
        res = run_custom_sql_pipeline(sql, _SCALAR_SCHEMA, skip_bench=True)
        self.assertEqual(res["status"], "FAILURE")
        self.assertEqual(res.get("stage"), "awaiting_agent")
        agents_path = res.get("agents_failure_path")
        self.assertIsNotNone(agents_path)
        assert agents_path is not None
        self.assertTrue(agents_path.startswith(PENDING_RUNQUERY_DIR))
        manifest = Path(agents_path)
        self.assertTrue(manifest.is_file())
        spec_rs = manifest.parent / "spec.rs"
        self.assertTrue(spec_rs.is_file())
        self.assertIn("method_spec", spec_rs.read_text(encoding="utf-8"))
        with open(manifest, encoding="utf-8") as f:
            payload = json.load(f)
        self.assertEqual(payload["stage"], "awaiting_agent")
        self.assertEqual(payload["sql"], sql)
        self.assertNotIn("binary", res)

    def test_unsupported_sql_fails_transpile_artifact(self) -> None:
        sql = "SELECT DISTINCT SUM(y) FROM t"
        schema = {"Y": "bigint"}
        res = run_custom_sql_pipeline(sql, schema, skip_bench=True)
        self.assertEqual(res["status"], "FAILURE")
        self.assertIn(res.get("stage"), ("parse", "transpile"))
        agents_path = res.get("agents_failure_path")
        self.assertIsNotNone(agents_path)
        assert agents_path is not None
        self.assertTrue(agents_path.startswith(FAILED_TRANSPILE_DIR))
        self.assertNotIn("binary", res)


@unittest.skipUnless(resolve_verus_bin(), "verus not on PATH")
class TestCustomSqlAgentPathSuccess(unittest.TestCase):
    def test_scalar_sum_with_agent_body_verifies(self) -> None:
        sql = "SELECT SUM(x) FROM t WHERE y >= 1"
        with tempfile.TemporaryDirectory() as td:
            tbl = os.path.join(td, "t.tbl")
            write_pipe_tbl(tbl, ["X", "Y"], TINY_SCALAR)
            res = run_custom_sql_pipeline(
                sql,
                _SCALAR_SCHEMA,
                run_query_body=_SCALAR_SUM_RUNQUERY,
                tbl=tbl,
                limit=10_000,
                skip_bench=True,
            )
        self.assertEqual(res["status"], "SUCCESS")
        self.assertTrue(res["proof_verified"])
        self.assertEqual(res.get("ret_type"), "u64")


if __name__ == "__main__":
    unittest.main()
