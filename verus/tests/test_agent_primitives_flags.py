"""Tests for agent primitive flags and context emission."""

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

from verus.research_loop.agent_context import (  # noqa: E402
    hardware_profile,
    table_aggregate_stats,
)
from verus.research_loop.agent_primitives.emit_externs import emit_agent_externs  # noqa: E402
from verus.research_loop.assemble_verified_program import assemble_verified_program  # noqa: E402
from verus.research_loop.harness import run_custom_sql_pipeline  # noqa: E402
from verus_transpiler.transpiler import transpile_sql_to_verus  # noqa: E402


def _write_tbl(path: Path, rows: list[tuple[int, int]]) -> None:
    path.write_text("A|B\n" + "\n".join(f"{a}|{b}" for a, b in rows), encoding="utf-8")


class TestEmitAgentExterns(unittest.TestCase):
    def test_parallel_gated(self) -> None:
        core = emit_agent_externs(enable_parallel=False)
        self.assertIn("build_zone_map_u32", core)
        self.assertNotIn("par_sum_u64", core)
        with_parallel = emit_agent_externs(enable_parallel=True)
        self.assertIn("par_sum_u64", with_parallel)

    def test_assembled_program_includes_core_externs(self) -> None:
        os.environ["LEMMA_ENABLE_PARALLEL"] = "0"
        schema = {"X": "bigint"}
        sql = "SELECT SUM(x) FROM t"
        spec = transpile_sql_to_verus(sql, schema, enable_templates=False)
        body = "pub exec fn run_query(cols: &Cols) -> (res: u64)\n    requires valid_cols(cols),\n    ensures res == method_spec(cols),\n{\n    0u64\n}\n"
        program = assemble_verified_program(
            spec_rs=spec,
            run_query_body=body,
            schema_dict=schema,
            ret_type="u64",
            default_tbl="",
        )
        self.assertIn("build_zone_map_u32", program)
        self.assertNotIn("par_sum_u64", program)


class TestAgentContext(unittest.TestCase):
    def test_table_stats_no_row_samples(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tbl = Path(td) / "t.tbl"
            _write_tbl(tbl, [(1, 2), (3, 4), (5, 6)])
            stats = table_aggregate_stats(str(tbl), ["A", "B"], limit=100)
        self.assertEqual(stats["row_count"], 3)
        self.assertNotIn("rows", stats)
        self.assertNotIn("samples", stats)
        blob = json.dumps(stats)
        self.assertNotIn('"rows"', blob)
        a = stats["columns"]["A"]
        self.assertIn("min", a)
        self.assertIn("zone_map", a)
        self.assertIn("histogram", a)

    def test_hardware_profile(self) -> None:
        prof = hardware_profile()
        self.assertIn("cpu_count", prof)
        self.assertGreaterEqual(prof["cpu_count"], 1)


class TestPendingRunqueryContext(unittest.TestCase):
    def test_context_json_when_awaiting_agent(self) -> None:
        os.environ["LEMMA_AGENT_STATS"] = "1"
        os.environ["LEMMA_AGENT_HARDWARE"] = "1"
        with tempfile.TemporaryDirectory() as td:
            tbl = os.path.join(td, "t.tbl")
            _write_tbl(Path(tbl), [(10, 1), (20, 0)])
            res = run_custom_sql_pipeline(
                "SELECT SUM(a) FROM t WHERE b >= 1",
                {"A": "bigint", "B": "int"},
                tbl=tbl,
                skip_bench=True,
            )
        self.assertEqual(res["status"], "FAILURE")
        self.assertEqual(res.get("stage"), "awaiting_agent")
        manifest = Path(res["agents_failure_path"])
        ctx_path = manifest.parent / "context.json"
        self.assertTrue(ctx_path.is_file())
        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
        self.assertIn("hardware", ctx)
        self.assertIn("table_stats", ctx)
        self.assertNotIn("rows", json.dumps(ctx))


if __name__ == "__main__":
    unittest.main()
