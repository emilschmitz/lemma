"""Every GenDB SEC template (T1–T30) must transpile to a real MethodSpec fold."""

from __future__ import annotations

import importlib.util
import random
from pathlib import Path

import pytest

from research_loop.scripts.sqlsmith_trusted_coverage import classify_query, load_sec_schema
from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.column_projection import project_multi_schema_for_query

ROOT = Path(__file__).resolve().parents[1]
_GEN = ROOT / "holdout" / "gendb_sec_edgar" / "generate_queries.py"


def _generate_templates():
    spec = importlib.util.spec_from_file_location("gendb_generate_queries", _GEN)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.generate_templates()


TEMPLATES = _generate_templates()
assert len(TEMPLATES) == 30, f"expected 30 GenDB templates, got {len(TEMPLATES)}"


@pytest.mark.parametrize("tid", range(1, 31), ids=[f"T{i:02d}" for i in range(1, 31)])
def test_gendb_template_transpiles_real_fold(tid: int) -> None:
    random.seed(tid)
    sql = TEMPLATES[tid - 1][0]().strip()
    schema = load_sec_schema()
    shell = classify_query(sql, f"T{tid}", schema)
    assert shell.status == "ok_shell", f"T{tid} {shell.status}: {shell.reason}"
    projected = project_multi_schema_for_query(sql, schema)
    out = transpile_sql_to_verus(sql, projected)
    assert "pub open spec fn method_spec" in out
    assert "arbitrary()" not in out
    assert "unimplemented!" not in out
    assert "decreases" in out
