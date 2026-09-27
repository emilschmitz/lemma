"""Proved plain LEFT OUTER JOIN: matched pairs + null-extended misses under full SEC caps."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from verus_transpiler.column_projection import project_multi_schema_for_query
from verus_transpiler.eq_join_prelude import proved_eq_join_prelude
from verus_transpiler.parse_sql import normalize_schema

from research_loop.assemble_verified_program import assemble_verified_join_program
from research_loop.harness import resolve_verus_bin, run_verus_verify
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.sec_table_assumptions import SEC_PROVE_LOOP_MAX_CELL_U64
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
)
from tests.test_sec_holdout_parse import SEC_SCHEMA
from verus_transpiler import transpile_sql_to_verus

ROOT = Path(__file__).resolve().parents[1]
EQ_JOIN_RS = ROOT / "research_loop" / "verus_lib" / "eq_join.rs"

# Full SEC product caps (num global max). Not the 65536 prove_loop profile.
_SEC_PRODUCT_MAX_ROWS = 39_401_761

# Plain LEFT JOIN (no IS NULL): matched pairs + unmatched left (null-extended right).
_LOJ_SQL = """
SELECT p.adsh, s.fy FROM pre p LEFT JOIN sub s ON p.adsh = s.adsh
"""


def _large_sec_product_catalog() -> CatalogAssumptions:
    """Full-table SEC product catalog for join fold proofs under real row caps."""
    return CatalogAssumptions(
        max_rows=_SEC_PRODUCT_MAX_ROWS,
        max_rows_cube=_SEC_PRODUCT_MAX_ROWS,
        max_rows_4=_SEC_PRODUCT_MAX_ROWS,
        max_cell_u64=SEC_PROVE_LOOP_MAX_CELL_U64,
        max_native_u32=2**31,
        max_string_len=128,
        tables={
            "pre": TableAssumptions(
                max_rows=9_600_799,
                columns={"line": ColumnAssumption(max_value_exclusive=483)},
            ),
            "sub": TableAssumptions(max_rows=86_135),
            "tag": TableAssumptions(max_rows=1_070_662),
            "num": TableAssumptions(max_rows=39_401_761),
        },
    )


def _assert_full_sec_caps(text: str) -> None:
    assert "pub const LEMMA_MAX_ROWS: usize = 39401761;" in text


def _projected(sql: str) -> dict[str, dict[str, str]]:
    _, multi = normalize_schema({"pre": SEC_SCHEMA["pre"], "sub": SEC_SCHEMA["sub"]})
    if not isinstance(multi, dict):
        raise TypeError("expected a per-table schema")
    projected = project_multi_schema_for_query(sql, multi)
    if any(not isinstance(cols, dict) for cols in projected.values()):
        raise TypeError("expected a per-table schema")
    return cast(dict[str, dict[str, str]], projected)


def test_loj_shape_slice_is_rocketship_clean() -> None:
    body = proved_eq_join_prelude()
    assert "// SHAPE_LOJ_BEGIN" in body
    assert "// SHAPE_LOJ_END" in body
    assert "pub fn left_outer_pairs_str(" in body
    assert "pub fn left_outer_pairs_u64(" in body
    assert "pub open spec fn nested_loj_pairs<" in body
    assert "pub open spec fn loj_loop_acc<" in body
    assert "pub open spec fn loj_acc<" in body
    assert "pub proof fn lemma_loj_at_origin<" in body
    assert "arbitrary()" not in body
    assert "external_body" not in body
    assert "assume(" not in body


def test_loj_transpile_emits_is_loj_fold() -> None:
    projected = _projected(_LOJ_SQL)
    catalog = _large_sec_product_catalog()
    out = transpile_sql_to_verus(
        _LOJ_SQL, projected, catalog_assumptions=catalog
    )
    assert "join_loj_projection_helper" in out
    assert "// shape: loj" in out
    assert "lemma_join_loj_projection_helper_is_loj(" in out
    assert "lemma_join_loj_projection_helper_is_loj_loop(" in out
    assert "lemma_join_loj_projection_helper_method_is_fold(" in out
    assert "nested_loj_pairs" in out
    assert "left_outer_pairs_str" in out
    assert "Option<u32>" in out
    assert "join_projection_helper" not in out
    _assert_full_sec_caps(out)


def test_loj_fold_lemma_verifies(tmp_path: Path) -> None:
    """Plain LEFT OUTER helper == loj_acc verifies under full SEC product caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    projected = _projected(_LOJ_SQL)
    catalog = _large_sec_product_catalog()
    spec_rs = transpile_sql_to_verus(
        _LOJ_SQL, projected, catalog_assumptions=catalog
    )
    assert "lemma_join_loj_projection_helper_is_loj(" in spec_rs
    assert "lemma_join_loj_projection_helper_method_is_fold(" in spec_rs
    _assert_full_sec_caps(spec_rs)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    stub = """#[verifier::external_body]
pub exec fn run_query(pre: &Cols_pre, sub: &Cols_sub) -> (res: Vec<(String, Option<u32>)>)
    requires valid_cols_pre(pre), valid_cols_sub(sub),
    ensures res@ == res@,
{
    Vec::new()
}"""
    program = assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=stub,
        multi_schema=projected,
        table_order=("pre", "sub"),
        ret_type=ret_type,
        default_tbls={"pre": "", "sub": ""},
        catalog_assumptions=catalog,
    )
    assert "lemma_join_loj_projection_helper_is_loj(" in program
    assert "lemma_join_loj_projection_helper_method_is_fold(" in program
    assert "pub fn left_outer_pairs_str(" in program
    _assert_full_sec_caps(program)
    rs_path = tmp_path / "loj_fold.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=300)
    assert ok, log[-5000:]
    assert "0 errors" in log
    assert "verification results::" in log


def test_eq_join_loj_shape_verus_clean() -> None:
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    ok, log = run_verus_verify(str(EQ_JOIN_RS), timeout=120)
    assert ok, log[-4000:]
    assert "0 errors" in log
