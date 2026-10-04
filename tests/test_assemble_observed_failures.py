"""Assemble regressions for failures that never reached Verus.

A NOT EXISTS anti-join has no SQL JOIN node. The spec still uses one struct
per table. The single-table loader returns ``Cols``, which that spec does not
define. An EXISTS keeps bare ``Cols`` plus a support table. A real JOIN already
used the per-table path. These three must stay distinct.
"""

from __future__ import annotations

import re

import pytest

from research_loop.harness import run_custom_sql_pipeline, spec_requires_per_table_loaders
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema
from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.column_projection import project_multi_schema_for_query
from verus_transpiler.parse_sql import normalize_schema, parse_sql
from verus_transpiler.query_tables import program_table_order

_NOT_EXISTS = """
SELECT n.tag, n.version, COUNT(*) AS cnt, SUM(n.value) AS total
FROM num n
WHERE n.uom = 'shares' AND n.value IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM pre p
          WHERE p.tag = n.tag AND p.version = n.version AND p.adsh = n.adsh
      )
GROUP BY n.tag, n.version
"""

_NOT_EXISTS_STMT = """
SELECT n.tag, COUNT(*) AS cnt
FROM num n
WHERE n.uom = 'USD'
      AND NOT EXISTS (
          SELECT 1 FROM pre p
          WHERE p.adsh = n.adsh AND p.stmt = 'BS'
      )
GROUP BY n.tag
"""

_EXISTS = """
SELECT DISTINCT n.tag, n.version, COUNT(*) AS cnt
FROM num n
WHERE n.uom = 'pure' AND n.value IS NOT NULL
      AND EXISTS (
          SELECT 1 FROM pre p
          WHERE p.tag = n.tag AND p.version = n.version AND p.stmt = 'BS'
      )
GROUP BY n.tag, n.version
"""

_JOIN = """
SELECT s.sic, SUM(n.value) AS total
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.value IS NOT NULL
GROUP BY s.sic
"""

_SINGLE = """
SELECT stmt, COUNT(*) AS cnt
FROM pre
WHERE stmt IS NOT NULL
GROUP BY stmt
"""


def _order_and_spec(sql: str) -> tuple[tuple[str, ...], str]:
    catalog = load_sec_schema()
    _flat, multi = normalize_schema(catalog)
    query = parse_sql(sql, catalog)
    projected = project_multi_schema_for_query(sql, multi)
    spec = transpile_sql_to_verus(sql, projected)
    return program_table_order(query, multi), spec


def _assemble(sql: str, monkeypatch: pytest.MonkeyPatch, tmp_path) -> str:
    monkeypatch.setenv("LEMMA_RUN_DIR", str(tmp_path))
    monkeypatch.delenv("LEMMA_DUCKDB_PATH", raising=False)
    monkeypatch.setenv("ENABLE_VERUS_VERIFY", "0")
    monkeypatch.setenv("REQUIRE_PROOF", "0")
    monkeypatch.setattr(
        "research_loop.harness.run_verus_compile",
        lambda *args, **kwargs: (True, "", str(tmp_path / "fake-bin")),
    )
    catalog = load_sec_schema()
    result = run_custom_sql_pipeline(
        sql,
        catalog,
        run_query_body="pub exec fn run_query() -> (res: u64) ensures res == 0 { 0 }",
        skip_bench=True,
        workload=None,
        duckdb_path="",
    )
    assert result.get("stage") != "assemble", result.get("error")
    return (tmp_path / "workspace" / "custom_query.rs").read_text(encoding="utf-8")


def test_not_exists_spec_has_no_bare_cols() -> None:
    order, spec = _order_and_spec(_NOT_EXISTS)
    assert order == ("num", "pre")
    assert spec_requires_per_table_loaders(spec, order)
    assert "pub struct Cols_num" in spec
    assert "pub struct Cols_pre" in spec


def test_exists_spec_keeps_bare_cols() -> None:
    order, spec = _order_and_spec(_EXISTS)
    assert order == ("num", "pre")
    assert not spec_requires_per_table_loaders(spec, order)
    assert re.search(r"pub struct Cols\b", spec)


def test_not_exists_assemble_loads_each_table(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    program = _assemble(_NOT_EXISTS, monkeypatch, tmp_path)
    assert "pub exec fn load_cols_num" in program
    assert "pub exec fn load_cols_pre" in program
    assert "fn load_cols(" not in program
    assert "-> (cols: Cols)" not in program


def test_not_exists_on_stmt_loaders_match_its_spec(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A two-key NOT EXISTS is not the three-key anti-join. Loaders follow its spec."""
    order, spec = _order_and_spec(_NOT_EXISTS_STMT)
    program = _assemble(_NOT_EXISTS_STMT, monkeypatch, tmp_path)
    if spec_requires_per_table_loaders(spec, order):
        assert "pub exec fn load_cols_num" in program
        assert "pub exec fn load_cols_pre" in program
        assert "fn load_cols(" not in program
    else:
        assert re.search(r"pub struct Cols\b", spec)
        assert "pub exec fn load_cols(" in program
        assert "pub exec fn load_cols_pre" in program
        assert "-> (cols: Cols)" in program


def test_exists_assemble_keeps_primary_cols_loader(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    program = _assemble(_EXISTS, monkeypatch, tmp_path)
    assert "pub exec fn load_cols(" in program
    assert "-> (cols: Cols)" in program
    assert "pub exec fn load_cols_pre" in program
    assert "let pre = load_cols_pre" in program
    assert "run_query(&cols, &pre)" in program


def test_inner_join_assemble_uses_per_table_loaders(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    program = _assemble(_JOIN, monkeypatch, tmp_path)
    assert "pub exec fn load_cols_num" in program
    assert "pub exec fn load_cols_sub" in program
    assert "fn load_cols(" not in program


def test_single_table_assemble_keeps_one_loader(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    program = _assemble(_SINGLE, monkeypatch, tmp_path)
    assert "pub exec fn load_cols(" in program
    assert "fn load_cols_pre(" not in program
    assert "fn load_cols_num(" not in program
