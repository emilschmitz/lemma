"""Proved two-table three-equality equijoin (pair3) under full SEC caps."""

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
from tests.test_sec_holdout_parse import SEC_SCHEMA
from verus_transpiler import transpile_sql_to_verus

ROOT = Path(__file__).resolve().parents[1]
EQ_JOIN_RS = ROOT / "research_loop" / "verus_lib" / "eq_join.rs"

# Measured SEC counts, rounded up to next power of two (catalog upper bounds).
_SEC_PRODUCT_MAX_ROWS = round_rows_up(39_401_761)

_PAIR3_SQL = """
SELECT COUNT(*)
FROM num n
JOIN pre p ON n.adsh = p.adsh AND n.tag = p.tag AND n.version = p.version
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
    assert "pub const LEMMA_MAX_pre_line: u32 = 483;" in text
    # Catalog carries full SEC table sizes (pre/sub/tag/num); global row const is num max.
    catalog = _large_sec_product_catalog()
    assert catalog.max_rows == round_rows_up(39_401_761)
    assert catalog.tables["pre"].max_rows == round_rows_up(9_600_799)
    assert catalog.tables["pre"].columns["line"].max_value_exclusive == 483
    assert catalog.tables["sub"].max_rows == round_rows_up(86_135)
    assert catalog.tables["tag"].max_rows == round_rows_up(1_070_662)
    assert catalog.tables["num"].max_rows == round_rows_up(39_401_761)


def test_pair3_markers_and_prelude() -> None:
    body = EQ_JOIN_RS.read_text(encoding="utf-8")
    assert "// SHAPE_PAIR3_BEGIN" in body
    assert "// SHAPE_PAIR3_END" in body
    begin = body.index("// SHAPE_PAIR3_BEGIN")
    end = body.index("// SHAPE_PAIR3_END")
    proved_end = body.rindex("// EQ_JOIN_PROVED_END")
    assert begin < end < proved_end
    assert "pub fn equijoin_pairs_str3(" in body
    assert "pub open spec fn nested_eq_pairs3<" in body
    assert "pub open spec fn loop_acc_pair3<" in body
    prelude = proved_eq_join_prelude()
    assert "nested_eq_pairs3" in prelude
    assert "equijoin_pairs_str3" in prelude
    assert "loop_acc_pair3" in prelude
    for bad in ("arbitrary()", "ensures true", "unimplemented!"):
        assert bad not in prelude


def test_pair3_transpile_emits_fold_lemmas() -> None:
    _, multi = normalize_schema({"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]})
    if not isinstance(multi, dict):
        raise TypeError("expected a per-table schema")
    projected = project_multi_schema_for_query(_PAIR3_SQL, multi)
    projected = cast(dict[str, dict[str, str]], projected)
    catalog = _large_sec_product_catalog()
    spec_rs = transpile_sql_to_verus(_PAIR3_SQL, projected, catalog_assumptions=catalog)
    assert "// shape: pair3" in spec_rs
    assert "lemma_join_method_spec_helper_is_loop3(" in spec_rs
    assert "lemma_join_method_spec_helper_is_pairs3(" in spec_rs
    assert "lemma_join_method_spec_helper_method_is_fold(" in spec_rs
    assert "nested_eq_pairs3(" in spec_rs
    assert "loop_acc_pair3(" in spec_rs
    _assert_full_sec_caps(spec_rs)
    assert f"pub const LEMMA_MAX_ROWS: usize = {_SEC_PRODUCT_MAX_ROWS};" in spec_rs


def test_pair3_fold_lemma_verifies(tmp_path: Path) -> None:
    """num⋈pre on adsh∧tag∧version: helper==loop_acc_pair3 under full SEC caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    _, multi = normalize_schema({"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]})
    if not isinstance(multi, dict):
        raise TypeError("expected a per-table schema")
    projected = project_multi_schema_for_query(_PAIR3_SQL, multi)
    if any(not isinstance(cols, dict) for cols in projected.values()):
        raise TypeError("expected a per-table schema")
    projected = cast(dict[str, dict[str, str]], projected)
    catalog = _large_sec_product_catalog()
    spec_rs = transpile_sql_to_verus(_PAIR3_SQL, projected, catalog_assumptions=catalog)
    assert "lemma_join_method_spec_helper_is_pairs3(" in spec_rs
    assert "lemma_join_method_spec_helper_method_is_fold(" in spec_rs
    _assert_full_sec_caps(spec_rs)
    assert f"pub const LEMMA_MAX_ROWS: usize = {_SEC_PRODUCT_MAX_ROWS};" in spec_rs
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    assert ret_type == "u64"
    stub = """#[verifier::external_body]
pub exec fn run_query(num: &Cols_num, pre: &Cols_pre) -> (res: u64)
    requires valid_cols_num(num), valid_cols_pre(pre),
    ensures res == method_spec(num, pre),
{
    0u64
}"""
    program = assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=stub,
        multi_schema=projected,
        table_order=("num", "pre"),
        ret_type=ret_type,
        default_tbls={"num": "", "pre": ""},
        catalog_assumptions=catalog,
    )
    assert "lemma_join_method_spec_helper_is_pairs3(" in program
    assert "lemma_join_method_spec_helper_method_is_fold(" in program
    assert "// shape: pair3" in program
    _assert_full_sec_caps(program)
    assert f"pub const LEMMA_MAX_ROWS: usize = {_SEC_PRODUCT_MAX_ROWS};" in program
    rs_path = tmp_path / "pair3_fold.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=300)
    assert ok, log[-5000:]
    assert "0 errors" in log
    assert "verification results::" in log.lower() or "verified" in log.lower()
