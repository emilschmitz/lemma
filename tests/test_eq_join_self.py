"""Proved self-join (same table twice): two slots, pair fold under full SEC caps."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from verus_transpiler.column_projection import project_multi_schema_for_query
from verus_transpiler.parse_sql import normalize_schema

from research_loop.assemble_verified_program import assemble_verified_join_program
from research_loop.harness import resolve_verus_bin, run_verus_verify
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

_SELF_SQL = """
SELECT a.adsh
FROM pre a
JOIN pre b ON a.adsh = b.adsh
WHERE a.line < b.line
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
    assert "LEMMA_MAX_pre_line" in text
    assert "483" in text


def _projected(sql: str) -> dict[str, dict[str, str]]:
    _, multi = normalize_schema({"pre": SEC_SCHEMA["pre"]})
    if not isinstance(multi, dict):
        raise TypeError("expected a per-table schema")
    projected = project_multi_schema_for_query(sql, multi)
    if any(not isinstance(cols, dict) for cols in projected.values()):
        raise TypeError("expected a per-table schema")
    return cast(dict[str, dict[str, str]], projected)


def test_selfjoin_transpile_two_slots_and_is_pairs() -> None:
    """Same physical table twice → two alias slots + existing pair fold (no new exec)."""
    projected = _projected(_SELF_SQL)
    catalog = _large_sec_product_catalog()
    out = transpile_sql_to_verus(
        _SELF_SQL, projected, catalog_assumptions=catalog
    )
    assert "pub open spec fn join_projection_helper(a: &Cols_pre, b: &Cols_pre," in out
    assert "pub open spec fn method_spec(a: &Cols_pre, b: &Cols_pre)" in out
    assert "a.adsh[i0 as int]@ == b.adsh[i1 as int]@" in out
    assert "a.line[i0 as int] < b.line[i1 as int]" in out
    assert "// shape: selfjoin" in out
    assert "lemma_join_projection_helper_is_loop(" in out
    assert "lemma_join_projection_helper_is_pairs(" in out
    assert "lemma_join_projection_helper_method_is_fold(" in out
    assert "pair_acc(" in out
    assert "nested_eq_pairs(key_views(a.adsh@), key_views(b.adsh@)," in out
    assert "equijoin_pairs_str(" in out
    # No collapsed duplicate-param signature.
    assert "method_spec(pre: &Cols_pre, pre: &Cols_pre)" not in out
    _assert_full_sec_caps(out)


def test_selfjoin_pair_fold_verifies(tmp_path: Path) -> None:
    """helper == pair_acc / method_is_fold verifies under full SEC product caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    projected = _projected(_SELF_SQL)
    catalog = _large_sec_product_catalog()
    spec_rs = transpile_sql_to_verus(
        _SELF_SQL, projected, catalog_assumptions=catalog
    )
    assert "lemma_join_projection_helper_is_pairs(" in spec_rs
    assert "lemma_join_projection_helper_method_is_fold(" in spec_rs
    assert "pair_acc(" in spec_rs
    _assert_full_sec_caps(spec_rs)
    # Seq<Seq<char>> has no product ret bridge; stub is external_body-only (not an agent proof).
    # Assemble uses set_u32 solely for main/format wiring; ensures is vacuous.
    stub = """#[verifier::external_body]
pub exec fn run_query(a: &Cols_pre, b: &Cols_pre) -> (res: Vec<u32>)
    requires valid_cols_pre(a), valid_cols_pre(b),
    ensures res@ == res@,
{
    Vec::new()
}"""
    program = assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=stub,
        multi_schema=projected,
        table_order=("pre", "pre"),
        ret_type="set_u32",
        default_tbls={"pre": ""},
        catalog_assumptions=catalog,
    )
    assert "// shape: selfjoin" in program
    assert "lemma_join_projection_helper_is_pairs(" in program
    _assert_full_sec_caps(program)
    rs_path = tmp_path / "selfjoin_fold.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=180)
    assert ok, log[-5000:]
    assert "0 errors" in log
    assert "verified" in log.lower()
    # Keep the count line in the failure output / pytest log for the parent report.
    for line in log.splitlines():
        if "verification results" in line.lower() or "verified" in line.lower():
            print(line)