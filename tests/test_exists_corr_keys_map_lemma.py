"""Adversarial: correlated EXISTS keys_map lemma type-checks and proves in Verus."""

from __future__ import annotations

from pathlib import Path

import pytest
from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.column_projection import project_multi_schema_for_query

from research_loop.harness import resolve_verus_bin, run_verus_verify

U32_EXISTS_SQL = (
    "SELECT COUNT(*) FROM a "
    "WHERE EXISTS (SELECT 1 FROM b WHERE b.k = a.k AND b.s > 0)"
)
U32_CATALOG = {
    "a": {"id": "int", "k": "int", "v": "double"},
    "b": {"k": "int", "s": "int"},
}
A_SCHEMA = U32_CATALOG["a"]
B_SCHEMA = U32_CATALOG["b"]


def _transpile_u32_exists() -> str:
    projected = project_multi_schema_for_query(U32_EXISTS_SQL, U32_CATALOG)
    return transpile_sql_to_verus(U32_EXISTS_SQL, projected)


def _exists_corr_block(out: str) -> str:
    start = out.find("pub open spec fn exists_corr_")
    assert start != -1, "missing exists_corr helper"
    end = out.find("\npub open spec fn method_spec", start)
    if end == -1:
        end = out.find("\npub open spec fn method_spec_helper", start)
    assert end != -1
    return out[start:end]


def test_exists_corr_emits_keys_map_and_lemma() -> None:
    out = _transpile_u32_exists()
    block = _exists_corr_block(out)
    assert "exists_corr_exists_1_keys_map" in block
    assert "lemma_exists_corr_exists_1_spec_contains" in block
    assert "lemma_exists_corr_exists_1_spec_contains_helper" in block
    assert "HashSetWithView bridge" in block
    assert "b.get_k(k) == outer_key" in block
    assert "outer_key.0" not in block
    assert "Map<u32, bool>" in block


def test_exists_corr_keys_map_lemma_verus(tmp_path: Path) -> None:
    from research_loop.assemble_verified_program import assemble_verified_program

    out = _transpile_u32_exists()
    assert "lemma_exists_corr_exists_1_spec_contains" in out
    projected = project_multi_schema_for_query(U32_EXISTS_SQL, U32_CATALOG)
    run_query = """#[verifier::external_body]
pub exec fn run_query(cols: &Cols, b: &Cols_b) -> (res: u64)
    requires valid_cols(cols), valid_cols_b(b),
    ensures res == method_spec(cols, b),
{
    0u64
}"""
    program = assemble_verified_program(
        spec_rs=out,
        run_query_body=run_query,
        schema_dict=projected["a"],
        ret_type="u64",
        default_tbl=str(tmp_path / "a.tbl"),
        support_tables={"b": projected["b"]},
    )
    rs_path = tmp_path / "exists_corr_keys_map_lemma.rs"
    rs_path.write_text(program, encoding="utf-8")
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    ok, log = run_verus_verify(str(rs_path), timeout=180)
    if not ok:
        pytest.fail(f"verus verify failed:\n{log[-8000:]}")
