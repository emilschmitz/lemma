"""Proved FULL OUTER JOIN fold: matched + unmatched left + unmatched right."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from verus_transpiler.column_projection import project_multi_schema_for_query
from verus_transpiler.eq_join_prelude import proved_eq_join_prelude
from verus_transpiler.parse_sql import UnsupportedContractError, normalize_schema

from research_loop.assemble_verified_program import assemble_verified_join_program
from research_loop.harness import resolve_verus_bin, run_verus_verify
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.sec_table_assumptions import (
    SEC_PROVE_LOOP_MAX_CELL_U64,
    round_rows_up,
)
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
# Power-of-two product cap used for new multi-agg Verus proofs.
_SEC_PRODUCT_MAX_ROWS_POW2 = round_rows_up(39_401_761)

# Two-table FULL OUTER on the join key (adsh): matched + left miss + right miss.
_FULL_GB_SQL = """
SELECT p.adsh, COUNT(*) AS cnt
FROM pre p
FULL OUTER JOIN sub s ON p.adsh = s.adsh
GROUP BY p.adsh
"""

_FULL_MULTI_AGG_SQL = """
SELECT p.adsh, COUNT(*) AS c, SUM(p.line) AS s
FROM pre p
FULL OUTER JOIN sub s ON p.adsh = s.adsh
GROUP BY p.adsh
"""

_FULL_SUM_SQL = """
SELECT SUM(p.line)
FROM pre p
FULL OUTER JOIN sub s ON p.adsh = s.adsh
"""

_FULL_PROJ_SQL = """
SELECT p.adsh
FROM pre p
FULL OUTER JOIN sub s ON p.adsh = s.adsh
"""

# Multi-column FULL OUTER projection: join key + left non-key (Option on right miss).
_FULL_PROJ_MULTI_SQL = """
SELECT p.adsh, p.stmt
FROM pre p
FULL OUTER JOIN sub s ON p.adsh = s.adsh
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


def test_full_shape_slice_is_rocketship_clean() -> None:
    body = proved_eq_join_prelude()
    assert "// SHAPE_FULL_BEGIN" in body
    assert "// SHAPE_FULL_END" in body
    assert "pub open spec fn full_acc<" in body
    assert "pub fn full_outer_parts_str(" in body
    assert "pub proof fn lemma_full_at_origin<" in body
    assert "arbitrary()" not in body
    assert "external_body" not in body
    assert "assume(" not in body


def test_full_outer_transpile_emits_is_full_fold() -> None:
    projected = _projected(_FULL_GB_SQL)
    catalog = _large_sec_product_catalog()
    out = transpile_sql_to_verus(
        _FULL_GB_SQL, projected, catalog_assumptions=catalog
    )
    assert "// shape: full" in out
    assert "full_join_matched_helper" in out
    assert "full_join_left_unmatched_helper" in out
    assert "full_join_right_unmatched_helper" in out
    assert "full_join_groupby_helper" in out
    assert "lemma_full_join_matched_helper_is_full(" in out
    assert "lemma_full_join_matched_helper_method_is_fold(" in out
    assert "full_acc(" in out
    assert "join_left_match_helper" in out
    _assert_full_sec_caps(out)


def test_full_outer_scalar_and_projection_transpile() -> None:
    catalog = _large_sec_product_catalog()
    for sql in (_FULL_SUM_SQL, _FULL_PROJ_SQL):
        projected = _projected(sql)
        out = transpile_sql_to_verus(sql, projected, catalog_assumptions=catalog)
        assert "full_join_right_unmatched_helper" in out
        assert "lemma_full_join_matched_helper_is_full(" in out
        assert "// shape: full" in out
        _assert_full_sec_caps(out)


def test_full_outer_multi_projection_transpile() -> None:
    projected = _projected(_FULL_PROJ_MULTI_SQL)
    catalog = _large_sec_product_catalog()
    out = transpile_sql_to_verus(
        _FULL_PROJ_MULTI_SQL, projected, catalog_assumptions=catalog
    )
    assert "full_join_projection_helper" in out
    assert "full_join_right_unmatched_helper" in out
    assert "lemma_full_join_matched_helper_is_full(" in out
    assert "lemma_full_join_matched_helper_method_is_fold(" in out
    assert "Option<Seq<char>>" in out
    assert "full_acc(" in out or "pair_acc(" in out
    assert "nested_eq_pairs" in out
    assert "nested_anti_misses" in out
    assert "// shape: full" in out
    _assert_full_sec_caps(out)


def test_full_outer_multi_projection_fold_verifies(tmp_path: Path) -> None:
    """FULL OUTER multi-col projection == three-phase fold under full SEC caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    projected = _projected(_FULL_PROJ_MULTI_SQL)
    catalog = _large_sec_product_catalog()
    spec_rs = transpile_sql_to_verus(
        _FULL_PROJ_MULTI_SQL, projected, catalog_assumptions=catalog
    )
    assert "lemma_full_join_matched_helper_is_full(" in spec_rs
    assert "lemma_full_join_matched_helper_method_is_fold(" in spec_rs
    _assert_full_sec_caps(spec_rs)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    stub = """#[verifier::external_body]
pub exec fn run_query(pre: &Cols_pre, sub: &Cols_sub) -> (res: Vec<(String, Option<String>)>)
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
    assert "lemma_full_join_matched_helper_is_full(" in program
    assert "pub fn full_outer_parts_str(" in program
    assert "full_join_projection_helper" in program
    _assert_full_sec_caps(program)
    rs_path = tmp_path / "full_outer_multi_proj.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=360)
    assert ok, log[-5000:]
    assert "0 errors" in log
    assert "verification results::" in log


def test_full_outer_left_only_groupby_still_loud() -> None:
    sql = """
    SELECT p.stmt, COUNT(*) AS cnt
    FROM pre p
    FULL OUTER JOIN sub s ON p.adsh = s.adsh
    GROUP BY p.stmt
    """
    projected = _projected(sql)
    with pytest.raises(UnsupportedContractError, match="NULL keys|left-only"):
        transpile_sql_to_verus(
            sql, projected, catalog_assumptions=_large_sec_product_catalog()
        )


def _large_sec_product_catalog_pow2() -> CatalogAssumptions:
    """Rounded SEC product catalog (LEMMA_MAX_ROWS = 67108864)."""
    return CatalogAssumptions(
        max_rows=_SEC_PRODUCT_MAX_ROWS_POW2,
        max_rows_cube=_SEC_PRODUCT_MAX_ROWS_POW2,
        max_rows_4=_SEC_PRODUCT_MAX_ROWS_POW2,
        max_cell_u64=SEC_PROVE_LOOP_MAX_CELL_U64,
        max_native_u32=2**31,
        max_string_len=128,
        tables={
            "pre": TableAssumptions(
                max_rows=round_rows_up(9_600_799),
                columns={"line": ColumnAssumption(max_value_exclusive=483)},
            ),
            "sub": TableAssumptions(max_rows=round_rows_up(86_135)),
            "tag": TableAssumptions(max_rows=round_rows_up(1_070_662)),
            "num": TableAssumptions(max_rows=round_rows_up(39_401_761)),
        },
    )


def test_full_outer_multi_agg_transpile_emits_fold() -> None:
    projected = _projected(_FULL_MULTI_AGG_SQL)
    catalog = _large_sec_product_catalog_pow2()
    out = transpile_sql_to_verus(
        _FULL_MULTI_AGG_SQL, projected, catalog_assumptions=catalog
    )
    assert "// shape: full" in out
    assert "full_join_groupby_helper" in out
    assert "full_acc(" in out
    assert "Map<Seq<char>, (u64, u64)>" in out
    assert "lemma_full_join_matched_helper_is_full(" in out
    assert "lemma_full_join_matched_helper_method_is_fold(" in out
    assert f"pub const LEMMA_MAX_ROWS: usize = {_SEC_PRODUCT_MAX_ROWS_POW2};" in out


def test_full_outer_multi_agg_fold_verifies(tmp_path: Path) -> None:
    """FULL OUTER COUNT+SUM group-by == three-phase fold under pow2 SEC caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    from research_loop.assemble_verified_program import RET_TYPE_CONFIG
    from research_loop.trusted_ret_bridge import map_new_expr

    projected = _projected(_FULL_MULTI_AGG_SQL)
    catalog = _large_sec_product_catalog_pow2()
    spec_rs = transpile_sql_to_verus(
        _FULL_MULTI_AGG_SQL, projected, catalog_assumptions=catalog
    )
    assert "lemma_full_join_matched_helper_is_full(" in spec_rs
    assert "lemma_full_join_matched_helper_method_is_fold(" in spec_rs
    assert f"pub const LEMMA_MAX_ROWS: usize = {_SEC_PRODUCT_MAX_ROWS_POW2};" in spec_rs
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    cfg = RET_TYPE_CONFIG.get(ret_type) or dynamic_ret_type_config().get(ret_type)
    if cfg is None:
        raise AssertionError(f"unknown ret_type {ret_type!r}")
    rust_ret = cfg["rust_ret"]
    view_spec = cfg.get("view_spec")
    if view_spec:
        ensures = f"{view_spec}(res@) == method_spec(pre, sub)"
    else:
        ensures = "res@ == method_spec(pre, sub)"
    stub = f"""#[verifier::external_body]
pub exec fn run_query(pre: &Cols_pre, sub: &Cols_sub) -> (res: {rust_ret})
    requires valid_cols_pre(pre), valid_cols_sub(sub),
    ensures {ensures},
{{
    {map_new_expr(rust_ret)}
}}
"""
    program = assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=stub,
        multi_schema=projected,
        table_order=("pre", "sub"),
        ret_type=ret_type,
        default_tbls={"pre": "", "sub": ""},
        catalog_assumptions=catalog,
    )
    assert "lemma_full_join_matched_helper_is_full(" in program
    assert "pub fn full_outer_parts_str(" in program
    assert f"pub const LEMMA_MAX_ROWS: usize = {_SEC_PRODUCT_MAX_ROWS_POW2};" in program
    rs_path = tmp_path / "full_outer_multi_agg_fold.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=360)
    assert ok, log[-5000:]
    assert "0 errors" in log
    assert "verification results::" in log


def test_full_outer_fold_lemma_verifies(tmp_path: Path) -> None:
    """FULL OUTER group-by helper == three-phase fold under full SEC caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    projected = _projected(_FULL_GB_SQL)
    catalog = _large_sec_product_catalog()
    spec_rs = transpile_sql_to_verus(
        _FULL_GB_SQL, projected, catalog_assumptions=catalog
    )
    assert "lemma_full_join_matched_helper_is_full(" in spec_rs
    assert "lemma_full_join_matched_helper_method_is_fold(" in spec_rs
    _assert_full_sec_caps(spec_rs)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    assert ret_type == "map_str_u64"
    stub = """#[verifier::external_body]
pub exec fn run_query(pre: &Cols_pre, sub: &Cols_sub) -> (res: StringHashMap<u64>)
    requires valid_cols_pre(pre), valid_cols_sub(sub),
    ensures res@ == method_spec(pre, sub),
{
    StringHashMap::new()
}
"""
    program = assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=stub,
        multi_schema=projected,
        table_order=("pre", "sub"),
        ret_type=ret_type,
        default_tbls={"pre": "", "sub": ""},
        catalog_assumptions=catalog,
    )
    assert "lemma_full_join_matched_helper_is_full(" in program
    assert "pub fn full_outer_parts_str(" in program
    _assert_full_sec_caps(program)
    rs_path = tmp_path / "full_outer_fold.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=360)
    assert ok, log[-5000:]
    assert "0 errors" in log
    assert "verification results::" in log


def test_eq_join_full_shape_verus_clean() -> None:
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    ok, log = run_verus_verify(str(EQ_JOIN_RS), timeout=180)
    assert ok, log[-4000:]
    assert "0 errors" in log
