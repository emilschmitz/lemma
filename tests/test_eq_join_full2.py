"""Proved two-equality FULL OUTER multi-agg fold under full SEC product caps."""

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
from tests.test_sec_holdout_parse import SEC_SCHEMA
from verus_transpiler import transpile_sql_to_verus

ROOT = Path(__file__).resolve().parents[1]
EQ_JOIN_RS = ROOT / "research_loop" / "verus_lib" / "eq_join.rs"

# Measured SEC counts, rounded up to next power of two (catalog upper bounds).
_SEC_PRODUCT_MAX_ROWS = round_rows_up(39_401_761)

# Two string equalities (adsh + tag); GROUP BY one join key (n.adsh).
_FULL2_MULTI_SQL = """
SELECT n.adsh, COUNT(*) AS c, SUM(n.value) AS s
FROM pre p
FULL OUTER JOIN num n ON n.adsh = p.adsh AND n.tag = p.tag
GROUP BY n.adsh
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
            "num": TableAssumptions(
                max_rows=round_rows_up(39_401_761),
                columns={"value": ColumnAssumption(max_value_exclusive=10_000)},
            ),
        },
    )


def _assert_full_sec_caps(text: str) -> None:
    assert f"pub const LEMMA_MAX_ROWS: usize = {_SEC_PRODUCT_MAX_ROWS};" in text


def _projected(sql: str) -> dict[str, dict[str, str]]:
    _, multi = normalize_schema({"pre": SEC_SCHEMA["pre"], "num": SEC_SCHEMA["num"]})
    if not isinstance(multi, dict):
        raise TypeError("expected a per-table schema")
    projected = project_multi_schema_for_query(sql, multi)
    if any(not isinstance(cols, dict) for cols in projected.values()):
        raise TypeError("expected a per-table schema")
    return cast(dict[str, dict[str, str]], projected)


def test_full2_shape_slice_is_rocketship_clean() -> None:
    body = proved_eq_join_prelude()
    assert "// SHAPE_FULL2_BEGIN" in body
    assert "// SHAPE_FULL2_END" in body
    assert "pub fn full_outer_parts_str2(" in body
    # Markers sit before EQ_JOIN_PROVED_END (exact line; ignore doc-comment mentions).
    lines = EQ_JOIN_RS.read_text(encoding="utf-8").splitlines()
    begin = next(i for i, ln in enumerate(lines) if ln.strip() == "// SHAPE_FULL2_BEGIN")
    end = next(i for i, ln in enumerate(lines) if ln.strip() == "// SHAPE_FULL2_END")
    proved_end = next(
        i for i, ln in enumerate(lines) if ln.strip() == "// EQ_JOIN_PROVED_END"
    )
    assert begin < end < proved_end
    # Do not interleave LOJ2 / RIGHT2 markers inside FULL2.
    for i in range(begin, end + 1):
        assert "SHAPE_LOJ2" not in lines[i]
        assert "SHAPE_RIGHT2" not in lines[i]
    slice_body = "\n".join(lines[begin : end + 1])
    assert "arbitrary()" not in slice_body
    assert "external_body" not in slice_body
    assert "assume(" not in slice_body


def test_full2_multi_transpile_emits_is_full2_fold() -> None:
    projected = _projected(_FULL2_MULTI_SQL)
    catalog = _large_sec_product_catalog()
    out = transpile_sql_to_verus(
        _FULL2_MULTI_SQL, projected, catalog_assumptions=catalog
    )
    assert "full_join_groupby_helper" in out
    assert "// shape: full2" in out
    assert "lemma_full_join_matched_helper_is_full(" in out
    assert "lemma_full_join_matched_helper_method_is_fold(" in out
    assert "nested_eq_pairs2" in out
    assert "nested_anti_misses2" in out
    assert "full_acc(" in out
    assert "lemma_full_at_origin(" in out
    assert "lemma_anti2_at_origin(" in out
    assert "lemma_loop2_at_origin(" in out
    _assert_full_sec_caps(out)
    assert _SEC_PRODUCT_MAX_ROWS == 67_108_864
    assert "lemma_rem_cap_native_add_fits(" not in out or (
        "lemma_rem_cap_native_add_fits_rows(" in out
    )


def test_full2_projection_still_loud() -> None:
    sql = """
    SELECT n.adsh, n.tag
    FROM pre p
    FULL OUTER JOIN num n ON n.adsh = p.adsh AND n.tag = p.tag
    """
    projected = _projected(sql)
    with pytest.raises(UnsupportedContractError, match="NULL padding|projection"):
        transpile_sql_to_verus(
            sql, projected, catalog_assumptions=_large_sec_product_catalog()
        )


def test_full2_multi_fold_lemma_verifies(tmp_path: Path) -> None:
    """Two-eq FULL OUTER multi-agg helper == full_acc verifies under full SEC caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    projected = _projected(_FULL2_MULTI_SQL)
    catalog = _large_sec_product_catalog()
    spec_rs = transpile_sql_to_verus(
        _FULL2_MULTI_SQL, projected, catalog_assumptions=catalog
    )
    assert "lemma_full_join_matched_helper_is_full(" in spec_rs
    assert "lemma_full_join_matched_helper_method_is_fold(" in spec_rs
    _assert_full_sec_caps(spec_rs)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    stub = """#[verifier::external_body]
pub exec fn run_query(pre: &Cols_pre, num: &Cols_num) -> (res: StringHashMap<(u64, u64)>)
    requires valid_cols_pre(pre), valid_cols_num(num),
    ensures res@ == method_spec(pre, num),
{
    StringHashMap::new()
}"""
    program = assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=stub,
        multi_schema=projected,
        table_order=("pre", "num"),
        ret_type=ret_type,
        default_tbls={"pre": "", "num": ""},
        catalog_assumptions=catalog,
    )
    assert "lemma_full_join_matched_helper_is_full(" in program
    assert "lemma_full_join_matched_helper_method_is_fold(" in program
    assert "pub fn full_outer_parts_str2(" in program
    _assert_full_sec_caps(program)
    assert "lemma_join_roj_multi_agg_helper_slot0_count_leq_" not in program
    assert "// === Multi-agg fold bound lemmas" not in program
    rs_path = tmp_path / "full2_multi_fold.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=360)
    assert ok, log[-5000:]
    assert "0 errors" in log
    assert "verification results::" in log


def test_eq_join_full2_shape_verus_clean() -> None:
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    ok, log = run_verus_verify(str(EQ_JOIN_RS), timeout=180)
    assert ok, log[-4000:]
    assert "0 errors" in log
