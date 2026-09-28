"""Proved OR-of-two-equalities join fold under full SEC product caps."""

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
# Not the 65536 prove_loop profile.
_SEC_PRODUCT_MAX_ROWS = round_rows_up(39_401_761)

_OR_SQL = """
SELECT COUNT(*)
FROM pre p
JOIN sub s ON p.adsh = s.adsh OR p.tag = s.adsh
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


def test_or_shape_slice_is_rocketship_clean() -> None:
    body = proved_eq_join_prelude()
    assert "// SHAPE_OR_BEGIN" in body
    assert "// SHAPE_OR_END" in body
    # Markers sit before EQ_JOIN_PROVED_END (line markers, not the module doc mention).
    text = EQ_JOIN_RS.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines()]
    assert lines.index("// SHAPE_OR_BEGIN") < lines.index("// EQ_JOIN_PROVED_END")
    assert lines.index("// SHAPE_OR_END") < lines.index("// EQ_JOIN_PROVED_END")
    assert "pub fn orjoin_pairs_str(" in body
    assert "pub open spec fn nested_or_eq_pairs<" in body
    assert "pub open spec fn or_loop_acc<" in body
    assert "pub open spec fn or_match_ids<" in body
    assert "pub proof fn lemma_or_at_origin<" in body
    assert "arbitrary()" not in body
    assert "external_body" not in body
    assert "assume(" not in body


def test_or_join_transpile_emits_is_or_and_method_is_fold() -> None:
    projected = _projected(_OR_SQL)
    catalog = _large_sec_product_catalog()
    out = transpile_sql_to_verus(_OR_SQL, projected, catalog_assumptions=catalog)
    assert "||" in out.split("pub open spec fn join_method_spec_helper")[1].split(
        "pub open spec fn method_spec"
    )[0]
    assert "// shape: orjoin" in out
    assert "lemma_join_method_spec_helper_is_or(" in out
    assert "lemma_join_method_spec_helper_is_or_loop(" in out
    assert "lemma_join_method_spec_helper_method_is_fold(" in out
    assert "nested_or_eq_pairs" in out
    assert "or_loop_acc" in out
    assert "lemma_or_at_origin" in out
    _assert_full_sec_caps(out)


def test_or_join_fold_lemma_verifies(tmp_path: Path) -> None:
    """OR-join helper == pair_acc(nested_or_eq_pairs) under full SEC caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    projected = _projected(_OR_SQL)
    catalog = _large_sec_product_catalog()
    spec_rs = transpile_sql_to_verus(
        _OR_SQL, projected, catalog_assumptions=catalog
    )
    assert "lemma_join_method_spec_helper_is_or(" in spec_rs
    assert "lemma_join_method_spec_helper_method_is_fold(" in spec_rs
    _assert_full_sec_caps(spec_rs)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    assert ret_type == "u64"
    stub = """#[verifier::external_body]
pub exec fn run_query(pre: &Cols_pre, sub: &Cols_sub) -> (res: u64)
    requires valid_cols_pre(pre), valid_cols_sub(sub),
    ensures res == method_spec(pre, sub),
{
    0u64
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
    assert "lemma_join_method_spec_helper_is_or(" in program
    assert "lemma_join_method_spec_helper_method_is_fold(" in program
    assert "pub fn orjoin_pairs_str(" in program
    assert "// shape: orjoin" in program
    _assert_full_sec_caps(program)
    rs_path = tmp_path / "or_join_fold.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=300)
    assert ok, log[-5000:]
    assert "0 errors" in log
    assert "verification results::" in log
