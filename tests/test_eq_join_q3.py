"""Holdout Q3: join + HAVING (AVG of a second join+GROUP BY).

Q3 decomposes into existing pair-fold lemmas (equijoin_pairs_str):
  - outer num⋈sub SUM GROUP BY → is_loop / is_pairs / method_is_fold
  - HAVING subquery join+SUM GROUP BY → is_loop / is_pairs (shape: having_join)
No new SHAPE_Q3 geometry; do not duplicate pair lemmas.
"""

from __future__ import annotations

import re
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

# Holdout gendb_sec_edgar/queries.sql Q3.
_Q3_SQL = """
SELECT s.name, s.cik, SUM(n.value) AS total_value
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD' AND s.fy = 2022 AND n.value IS NOT NULL
GROUP BY s.name, s.cik
HAVING SUM(n.value) > (
    SELECT AVG(sub_total) FROM (
        SELECT SUM(n2.value) AS sub_total
        FROM num n2
        JOIN sub s2 ON n2.adsh = s2.adsh
        WHERE n2.uom = 'USD' AND s2.fy = 2022 AND n2.value IS NOT NULL
        GROUP BY s2.cik
    ) avg_sub
)
ORDER BY total_value DESC
LIMIT 100
"""

_SLOT_BOUND_SECTION = re.compile(
    r"\n// === Scalar map fold bound lemmas[^\n]*===\n"
    r".*?"
    r"(?=\n#\[verifier::external_body\]\npub exec fn run_query)",
    re.DOTALL,
)


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
            "sub": TableAssumptions(
                max_rows=round_rows_up(86_135),
                one_row_per_adsh=True,
            ),
            "num": TableAssumptions(
                max_rows=round_rows_up(39_401_761),
                columns={
                    "value": ColumnAssumption(
                        max_value_exclusive=2**60,
                        abs_sum_exclusive=10**18,
                    )
                },
            ),
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


def _strip_fullsec_sum_cell_bounds(program: str) -> str:
    """Drop sum_cell rem·CELL lemmas when ROWS²·CELL overflows u64.

    The Q3 fold (pair / method_is_fold / having_join) is the subject; the host
    slot rem·cell bridge is unsound under full SEC product and is not this
    shape's job (same policy as test_eq_join_q6).
    """
    out, n = _SLOT_BOUND_SECTION.subn("\n", program, count=1)
    assert n == 1, "expected scalar map fold bound section in assembled program"
    return out


def test_q3_emits_pair_fold_and_method_is_fold() -> None:
    catalog = _large_sec_product_catalog()
    projected = _projected(_Q3_SQL)
    spec_rs = transpile_sql_to_verus(
        _Q3_SQL, projected, catalog_assumptions=catalog
    )
    _assert_full_sec_caps(spec_rs)
    assert "lemma_join_method_spec_helper_is_loop(" in spec_rs
    assert "lemma_join_method_spec_helper_is_pairs(" in spec_rs
    assert "lemma_join_method_spec_helper_method_is_fold(" in spec_rs
    assert "lemma_subquery_having_sq1_derived_avg_sub_helper_is_loop(" in spec_rs
    assert "lemma_subquery_having_sq1_derived_avg_sub_helper_is_pairs(" in spec_rs
    assert "// shape: having_join" in spec_rs
    assert "subquery_having_sq1_spec" in spec_rs
    assert "apply_having_filter" in spec_rs
    assert "arbitrary()" not in spec_rs
    assert "ensures true" not in spec_rs
    # No duplicate Q3 geometry — reuses pair / equijoin_pairs_str.
    assert "lemma_join_method_spec_helper_is_q3" not in spec_rs
    assert "pub fn equijoin_pairs_str(" in spec_rs


def test_q3_fold_verifies(tmp_path: Path) -> None:
    """Outer + HAVING-join pair folds verify under full SEC product caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    catalog = _large_sec_product_catalog()
    projected = _projected(_Q3_SQL)
    spec_rs = transpile_sql_to_verus(
        _Q3_SQL, projected, catalog_assumptions=catalog
    )
    _assert_full_sec_caps(spec_rs)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    assert ret_type == "map_str_u32_u64"
    stub = """#[verifier::external_body]
pub exec fn run_query(num: &Cols_num, sub: &Cols_sub) -> (res: HashMapWithView<(String, u32), u64>)
    requires valid_cols_num(num), valid_cols_sub(sub),
    ensures res@ == method_spec(num, sub),
{
    HashMapWithView::new()
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
    assert "lemma_join_method_spec_helper_method_is_fold(" in program
    assert "lemma_subquery_having_sq1_derived_avg_sub_helper_is_pairs(" in program
    assert "// shape: having_join" in program
    assert "pub fn equijoin_pairs_str(" in program
    program = _strip_fullsec_sum_cell_bounds(program)
    assert "lemma_join_method_spec_helper_sum_cell_u64_leq_" not in program
    assert "lemma_join_method_spec_helper_method_is_fold(" in program
    rs_path = tmp_path / "q3_having_join.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=300)
    assert ok, log[-5000:]
    assert "0 errors" in log
    assert "verification results::" in log
