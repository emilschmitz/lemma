"""Proved LEFT anti-join miss list: Verus fold under full SEC product caps."""

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
from research_loop.sec_table_assumptions import (
    SEC_PROVE_LOOP_MAX_CELL_U64,
    round_rows_up,
)
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
)
from research_loop.trusted_ret_bridge import dynamic_ret_type_config, map_new_expr
from tests.test_sec_holdout_parse import SEC_SCHEMA
from verus_transpiler import transpile_sql_to_verus

ROOT = Path(__file__).resolve().parents[1]
EQ_JOIN_RS = ROOT / "research_loop" / "verus_lib" / "eq_join.rs"

# Measured SEC counts, rounded up to next power of two (catalog upper bounds).
_SEC_PRODUCT_MAX_ROWS = round_rows_up(39_401_761)

# Holdout Q24 family: LEFT JOIN + IS NULL anti-join (one equijoin key).
_LEFT_ANTI_SQL = """
SELECT p.adsh, COUNT(*) AS cnt
FROM pre p
LEFT JOIN sub s ON p.adsh = s.adsh
WHERE p.stmt = 'CI' AND s.adsh IS NULL
GROUP BY p.adsh
"""

# Holdout Q24: three-key LEFT anti (tag ∧ version ∧ adsh).
_LEFT_ANTI3_SQL = """
SELECT n.tag, n.version, COUNT(*) AS cnt, SUM(n.value) AS total
FROM num n
LEFT JOIN pre p ON n.tag = p.tag AND n.version = p.version AND n.adsh = p.adsh
WHERE n.uom = 'USD' AND n.ddate BETWEEN 20230101 AND 20231231
      AND n.value IS NOT NULL
      AND p.adsh IS NULL
GROUP BY n.tag, n.version
HAVING COUNT(*) > 10
LIMIT 100
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
                max_rows=round_rows_up(9_600_799),
                columns={"line": ColumnAssumption(max_value_exclusive=483)},
            ),
            "sub": TableAssumptions(max_rows=round_rows_up(86_135)),
            "tag": TableAssumptions(max_rows=round_rows_up(1_070_662)),
            "num": TableAssumptions(max_rows=round_rows_up(39_401_761)),
        },
    )


def _assert_full_sec_caps(text: str) -> None:
    assert f"pub const LEMMA_MAX_ROWS: usize = {_SEC_PRODUCT_MAX_ROWS};" in text


def _projected(sql: str) -> dict[str, dict[str, str]]:
    _, multi = normalize_schema({"pre": SEC_SCHEMA["pre"], "sub": SEC_SCHEMA["sub"]})
    if not isinstance(multi, dict):
        raise TypeError("expected a per-table schema")
    projected = project_multi_schema_for_query(sql, multi)
    if any(not isinstance(cols, dict) for cols in projected.values()):
        raise TypeError("expected a per-table schema")
    return cast(dict[str, dict[str, str]], projected)


def test_left_shape_slice_is_rocketship_clean() -> None:
    body = proved_eq_join_prelude()
    assert "// SHAPE_LEFT_BEGIN" in body
    assert "// SHAPE_LEFT_END" in body
    assert "// SHAPE_LEFT3_BEGIN" in body
    assert "// SHAPE_LEFT3_END" in body
    assert "pub fn anti_miss_rows_str(" in body
    assert "pub fn anti_miss_rows_str3(" in body
    assert "pub open spec fn nested_anti_misses<" in body
    assert "pub open spec fn nested_anti_misses3<" in body
    assert "pub open spec fn anti_loop_acc<" in body
    assert "pub open spec fn anti_loop_acc3<" in body
    assert "pub open spec fn miss_acc<" in body
    assert "pub proof fn lemma_anti_at_origin<" in body
    assert "pub proof fn lemma_anti3_at_origin<" in body
    assert "arbitrary()" not in body
    assert "external_body" not in body
    assert "assume(" not in body


def test_left_anti_transpile_emits_is_left_fold() -> None:
    projected = _projected(_LEFT_ANTI_SQL)
    catalog = _large_sec_product_catalog()
    out = transpile_sql_to_verus(
        _LEFT_ANTI_SQL, projected, catalog_assumptions=catalog
    )
    assert "join_right_match_helper" in out
    assert "join_anti_multi_agg_helper" in out
    assert "// shape: left" in out
    assert "lemma_join_anti_multi_agg_helper_is_left(" in out
    assert "lemma_join_anti_multi_agg_helper_is_left_loop(" in out
    assert "lemma_join_anti_multi_agg_helper_method_is_fold(" in out
    assert "anti_miss_rows_str" in out
    assert "nested_anti_misses" in out
    assert "left_join_miss_generic" not in out.split("join_anti_multi_agg_helper")[1].split(
        "pub open spec fn method_spec"
    )[0]
    _assert_full_sec_caps(out)


def test_left_anti_fold_lemma_verifies(tmp_path: Path) -> None:
    """LEFT anti helper == miss_acc verifies under full SEC product caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    projected = _projected(_LEFT_ANTI_SQL)
    catalog = _large_sec_product_catalog()
    spec_rs = transpile_sql_to_verus(
        _LEFT_ANTI_SQL, projected, catalog_assumptions=catalog
    )
    assert "lemma_join_anti_multi_agg_helper_is_left(" in spec_rs
    assert "lemma_join_anti_multi_agg_helper_method_is_fold(" in spec_rs
    _assert_full_sec_caps(spec_rs)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    assert ret_type == "map_str_u64"
    stub = """#[verifier::external_body]
pub exec fn run_query(pre: &Cols_pre, sub: &Cols_sub) -> (res: StringHashMap<u64>)
    requires valid_cols_pre(pre), valid_cols_sub(sub),
    ensures res@ == method_spec(pre, sub),
{
    StringHashMap::new()
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
    assert "lemma_join_anti_multi_agg_helper_is_left(" in program
    assert "lemma_join_anti_multi_agg_helper_method_is_fold(" in program
    assert "pub fn anti_miss_rows_str(" in program
    _assert_full_sec_caps(program)
    rs_path = tmp_path / "left_anti_fold.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=300)
    assert ok, log[-5000:]
    assert "0 errors" in log
    assert "verification results::" in log


def _projected_num_pre(sql: str) -> dict[str, dict[str, str]]:
    _, multi = normalize_schema({"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]})
    if not isinstance(multi, dict):
        raise TypeError("expected a per-table schema")
    projected = project_multi_schema_for_query(sql, multi)
    if any(not isinstance(cols, dict) for cols in projected.values()):
        raise TypeError("expected a per-table schema")
    return cast(dict[str, dict[str, str]], projected)


def test_left_anti3_transpile_emits_is_left_fold() -> None:
    projected = _projected_num_pre(_LEFT_ANTI3_SQL)
    catalog = _large_sec_product_catalog()
    out = transpile_sql_to_verus(
        _LEFT_ANTI3_SQL, projected, catalog_assumptions=catalog
    )
    assert "// shape: left3" in out
    assert "lemma_join_anti_multi_agg_helper_is_left(" in out
    assert "lemma_join_anti_multi_agg_helper_method_is_fold(" in out
    assert "nested_anti_misses3" in out
    assert "anti_loop_acc3" in out
    assert "lemma_anti3_at_origin" in out
    _assert_full_sec_caps(out)


def test_left_anti3_fold_lemma_verifies(tmp_path: Path) -> None:
    """Holdout Q24 three-key LEFT anti equals miss_acc under full SEC caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    projected = _projected_num_pre(_LEFT_ANTI3_SQL)
    catalog = _large_sec_product_catalog()
    spec_rs = transpile_sql_to_verus(
        _LEFT_ANTI3_SQL, projected, catalog_assumptions=catalog
    )
    assert "lemma_join_anti_multi_agg_helper_is_left(" in spec_rs
    assert "nested_anti_misses3" in spec_rs
    _assert_full_sec_caps(spec_rs)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    rust_ret = dynamic_ret_type_config()[ret_type]["rust_ret"]
    body = map_new_expr(rust_ret) if "HashMap" in rust_ret else "Vec::new()"
    stub = f"""#[verifier::external_body]
pub exec fn run_query(num: &Cols_num, pre: &Cols_pre) -> (res: {rust_ret})
    requires valid_cols_num(num), valid_cols_pre(pre),
    ensures res@ == method_spec(num, pre),
{{
    {body}
}}
"""
    program = assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=stub,
        multi_schema=projected,
        table_order=("num", "pre"),
        ret_type=ret_type,
        default_tbls={"num": "", "pre": ""},
        catalog_assumptions=catalog,
    )
    assert "pub fn anti_miss_rows_str3(" in program
    assert "lemma_join_anti_multi_agg_helper_is_left(" in program
    _assert_full_sec_caps(program)
    rs_path = tmp_path / "left_anti3_fold.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=360)
    assert ok, log[-5000:]
    assert "0 errors" in log


def test_eq_join_left_shape_verus_clean() -> None:
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    ok, log = run_verus_verify(str(EQ_JOIN_RS), timeout=180)
    assert ok, log[-4000:]
    assert "0 errors" in log
