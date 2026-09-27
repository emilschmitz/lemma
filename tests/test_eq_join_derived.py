"""Derived-table join fold: Map lookup in the pair step (holdout Q2 shape)."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from verus_transpiler.column_projection import project_multi_schema_for_query
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
from tests.test_sec_holdout_parse import SEC_SCHEMA
from verus_transpiler import transpile_sql_to_verus

# Measured SEC counts, rounded up to next power of two (catalog upper bounds).
_SEC_PRODUCT_MAX_ROWS = round_rows_up(39_401_761)

# Holdout gendb_sec_edgar/queries.sql Q2 (COUNT form of the derived JOIN).
_DERIVED_COUNT_SQL = """
SELECT COUNT(*)
FROM num n
JOIN sub s ON n.adsh = s.adsh
JOIN (
    SELECT adsh, tag, MAX(value) AS max_value
    FROM num
    WHERE uom = 'pure' AND value IS NOT NULL
    GROUP BY adsh, tag
) m ON n.adsh = m.adsh AND n.tag = m.tag AND n.value = m.max_value
WHERE n.uom = 'pure' AND s.fy = 2022 AND n.value IS NOT NULL
"""

# Holdout Q2 projection (LIMIT kept in method_spec via spec_seq_take).
_DERIVED_PROJ_SQL = """
SELECT s.name, n.tag, n.value
FROM num n
JOIN sub s ON n.adsh = s.adsh
JOIN (
    SELECT adsh, tag, MAX(value) AS max_value
    FROM num
    WHERE uom = 'pure' AND value IS NOT NULL
    GROUP BY adsh, tag
) m ON n.adsh = m.adsh AND n.tag = m.tag AND n.value = m.max_value
WHERE n.uom = 'pure' AND s.fy = 2022 AND n.value IS NOT NULL
ORDER BY n.value DESC, s.name, n.tag
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
    _, multi = normalize_schema({"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]})
    if not isinstance(multi, dict):
        raise TypeError("expected a per-table schema")
    projected = project_multi_schema_for_query(sql, multi)
    if any(not isinstance(cols, dict) for cols in projected.values()):
        raise TypeError("expected a per-table schema")
    return cast(dict[str, dict[str, str]], projected)


def test_derived_join_emits_is_pairs_and_method_is_fold() -> None:
    catalog = _large_sec_product_catalog()
    projected = _projected(_DERIVED_COUNT_SQL)
    spec_rs = transpile_sql_to_verus(
        _DERIVED_COUNT_SQL, projected, catalog_assumptions=catalog
    )
    _assert_full_sec_caps(spec_rs)
    assert "// shape: derived." in spec_rs
    assert "lemma_join_method_spec_helper_is_loop(" in spec_rs
    assert "lemma_join_method_spec_helper_is_pairs(" in spec_rs
    assert "lemma_join_method_spec_helper_method_is_fold(" in spec_rs
    assert "derived_m_map" in spec_rs
    assert "contains_key" in spec_rs
    assert "arbitrary()" not in spec_rs
    assert "ensures true" not in spec_rs


def test_derived_count_fold_verifies(tmp_path: Path) -> None:
    """helper == loop_acc / pair_acc with derived Map in the step; full SEC caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    catalog = _large_sec_product_catalog()
    projected = _projected(_DERIVED_COUNT_SQL)
    spec_rs = transpile_sql_to_verus(
        _DERIVED_COUNT_SQL, projected, catalog_assumptions=catalog
    )
    _assert_full_sec_caps(spec_rs)
    assert "lemma_join_method_spec_helper_is_pairs(" in spec_rs
    assert "lemma_join_method_spec_helper_method_is_fold(" in spec_rs
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    assert ret_type == "u64"
    stub = """#[verifier::external_body]
pub exec fn run_query(num: &Cols_num, sub: &Cols_sub) -> (res: u64)
    requires valid_cols_num(num), valid_cols_sub(sub),
    ensures res == method_spec(num, sub),
{
    0u64
}"""
    program = assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=stub,
        multi_schema=projected,
        table_order=("num", "sub"),
        ret_type=ret_type,
        default_tbls={"num": "", "sub": ""},
        catalog_assumptions=catalog,
    )
    _assert_full_sec_caps(program)
    assert "// shape: derived." in program
    assert "lemma_join_method_spec_helper_method_is_fold(" in program
    rs_path = tmp_path / "derived_count.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=180)
    assert ok, log[-5000:]
    assert "0 errors" in log


def test_derived_projection_fold_verifies(tmp_path: Path) -> None:
    """Holdout Q2 projection: same Map-in-step fold under full SEC caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    catalog = _large_sec_product_catalog()
    projected = _projected(_DERIVED_PROJ_SQL)
    spec_rs = transpile_sql_to_verus(
        _DERIVED_PROJ_SQL, projected, catalog_assumptions=catalog
    )
    _assert_full_sec_caps(spec_rs)
    assert "lemma_join_projection_helper_is_pairs(" in spec_rs
    assert "lemma_join_projection_helper_method_is_fold(" in spec_rs
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    stub = """#[verifier::external_body]
pub exec fn run_query(num: &Cols_num, sub: &Cols_sub) -> (res: Vec<(Seq<char>, Seq<char>, u64)>)
    requires valid_cols_num(num), valid_cols_sub(sub),
    ensures res@ == res@,
{
    Vec::new()
}"""
    program = assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=stub,
        multi_schema=projected,
        table_order=("num", "sub"),
        ret_type=ret_type,
        default_tbls={"num": "", "sub": ""},
        catalog_assumptions=catalog,
    )
    _assert_full_sec_caps(program)
    rs_path = tmp_path / "derived_proj.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=180)
    assert ok, log[-5000:]
    assert "0 errors" in log
