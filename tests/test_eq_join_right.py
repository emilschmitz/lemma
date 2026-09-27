"""Proved RIGHT OUTER projection: Verus fold under full SEC product caps."""

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
from research_loop.trusted_ret_bridge import dynamic_ret_type_config
from tests.test_sec_holdout_parse import SEC_SCHEMA
from verus_transpiler import transpile_sql_to_verus

ROOT = Path(__file__).resolve().parents[1]
EQ_JOIN_RS = ROOT / "research_loop" / "verus_lib" / "eq_join.rs"

# Full SEC product caps (num global max). Not the 65536 prove_loop profile.
_SEC_PRODUCT_MAX_ROWS = 39_401_761

_RIGHT_SQL = """
SELECT s.adsh, p.stmt FROM pre p RIGHT JOIN sub s ON p.adsh = s.adsh
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


def test_right_shape_slice_is_rocketship_clean() -> None:
    body = proved_eq_join_prelude()
    assert "// SHAPE_RIGHT_BEGIN" in body
    assert "// SHAPE_RIGHT_END" in body
    begin = body.index("// SHAPE_RIGHT_BEGIN")
    end = body.index("// SHAPE_RIGHT_END")
    assert begin < end
    # Markers sit before EQ_JOIN_PROVED_END (exact line; ignore doc-comment mentions).
    src = EQ_JOIN_RS.read_text(encoding="utf-8")
    lines = src.splitlines()
    right_begin = next(i for i, ln in enumerate(lines) if ln.strip() == "// SHAPE_RIGHT_BEGIN")
    right_end = next(i for i, ln in enumerate(lines) if ln.strip() == "// SHAPE_RIGHT_END")
    proved_end = next(i for i, ln in enumerate(lines) if ln.strip() == "// EQ_JOIN_PROVED_END")
    assert right_begin < right_end < proved_end
    slice_body = body[begin:end]
    assert "pub fn right_outer_pairs_str(" in slice_body
    assert "pub open spec fn nested_right_pairs<" in slice_body
    assert "pub open spec fn right_loop_acc<" in slice_body
    assert "pub open spec fn right_acc<" in slice_body
    assert "pub proof fn lemma_right_at_origin<" in slice_body
    assert "arbitrary()" not in slice_body
    assert "external_body" not in slice_body
    assert "assume(" not in slice_body
    assert "admit()" not in slice_body


def test_right_outer_transpile_emits_is_right_fold() -> None:
    projected = _projected(_RIGHT_SQL)
    catalog = _large_sec_product_catalog()
    out = transpile_sql_to_verus(
        _RIGHT_SQL, projected, catalog_assumptions=catalog
    )
    assert "join_right_projection_helper" in out
    assert "// shape: right" in out
    assert "lemma_join_right_projection_helper_is_right(" in out
    assert "lemma_join_right_projection_helper_is_right_loop(" in out
    assert "lemma_join_right_projection_helper_method_is_fold(" in out
    assert "nested_right_pairs" in out
    assert "right_acc(" in out
    assert "right_outer_pairs_str" in out or "nested_right_pairs" in out
    assert "arbitrary()" not in out
    assert "ensures true" not in out
    _assert_full_sec_caps(out)


def test_right_outer_fold_lemma_verifies(tmp_path: Path) -> None:
    """RIGHT OUTER helper == right_acc verifies under full SEC product caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    projected = _projected(_RIGHT_SQL)
    catalog = _large_sec_product_catalog()
    spec_rs = transpile_sql_to_verus(
        _RIGHT_SQL, projected, catalog_assumptions=catalog
    )
    assert "lemma_join_right_projection_helper_is_right(" in spec_rs
    assert "lemma_join_right_projection_helper_method_is_fold(" in spec_rs
    _assert_full_sec_caps(spec_rs)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    cfg = dynamic_ret_type_config()[ret_type]
    rust_ret = cfg["rust_ret"]
    view_spec = cfg.get("view_spec")
    # table_order after swap: preserved side first (sub), nullable (pre)
    if view_spec:
        ensures = f"{view_spec}(res@) == method_spec(sub, pre)"
    else:
        ensures = "res@ == method_spec(sub, pre)"
    stub = f"""#[verifier::external_body]
pub exec fn run_query(sub: &Cols_sub, pre: &Cols_pre) -> (res: {rust_ret})
    requires valid_cols_sub(sub), valid_cols_pre(pre),
    ensures {ensures},
{{
    Vec::new()
}}
"""
    program = assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=stub,
        multi_schema=projected,
        table_order=("sub", "pre"),
        ret_type=ret_type,
        default_tbls={"pre": "", "sub": ""},
        catalog_assumptions=catalog,
    )
    assert "lemma_join_right_projection_helper_is_right(" in program
    assert "lemma_join_right_projection_helper_method_is_fold(" in program
    assert "pub fn right_outer_pairs_str(" in program
    _assert_full_sec_caps(program)
    rs_path = tmp_path / "right_outer_fold.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=300)
    assert ok, log[-5000:]
    assert "0 errors" in log
    assert "verification results::" in log


def test_eq_join_right_shape_verus_clean() -> None:
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    ok, log = run_verus_verify(str(EQ_JOIN_RS), timeout=180)
    assert ok, log[-4000:]
    assert "0 errors" in log
