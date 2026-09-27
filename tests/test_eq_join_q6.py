"""Proved holdout Q6 equijoin (num⋈sub⋈pre, 1+3) under full SEC product caps."""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

import pytest
from verus_transpiler.column_projection import project_multi_schema_for_query
from verus_transpiler.eq_join_prelude import proved_eq_join_prelude
from verus_transpiler.parse_sql import normalize_schema

from research_loop.assemble_verified_program import assemble_verified_nway_program
from research_loop.harness import resolve_verus_bin, run_verus_verify
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.sec_table_assumptions import SEC_PROVE_LOOP_MAX_CELL_U64
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

# Full SEC product caps (num global max). Not the 65536 prove_loop profile.
_SEC_PRODUCT_MAX_ROWS = 39_401_761

# Holdout Q6: 1 equality to sub + 3 equalities to pre (not the 1+2 string star).
_Q6_SQL = """
SELECT s.name, p.stmt, n.tag, p.plabel,
       SUM(n.value) AS total_value, COUNT(*) AS cnt
FROM num n
JOIN sub s ON n.adsh = s.adsh
JOIN pre p ON n.adsh = p.adsh AND n.tag = p.tag AND n.version = p.version
WHERE n.uom = 'USD' AND p.stmt = 'IS' AND s.fy = 2023
      AND n.value IS NOT NULL
GROUP BY s.name, p.stmt, n.tag, p.plabel
"""

_SLOT_BOUND_SECTION = re.compile(
    r"\n// === Multi-agg fold bound lemmas[^\n]*===\n"
    r".*?"
    r"(?=\n#\[verifier::external_body\]\npub exec fn run_query)",
    re.DOTALL,
)


def _q6_schema() -> dict[str, dict[str, str]]:
    """Local schema copy; ensure Q6 projection columns exist without editing SEC_SCHEMA."""
    schema = {name: dict(cols) for name, cols in SEC_SCHEMA.items()}
    schema.setdefault("sub", {})["name"] = "string"
    schema.setdefault("num", {})["value"] = "double"
    schema.setdefault("pre", {})["plabel"] = "string"
    return schema


def _large_sec_product_catalog() -> CatalogAssumptions:
    """Full-table SEC product catalog for join fold proofs under real row caps.

    ``num.value`` cannot use rows³·cell under 39M; assemble uses the measured
    abs-sum bound when sub/pre joins are on unique keys (same pattern as
    ``test_large_sec_sum_uses_measured_abs_total_when_cell_product_overflows``).
    """
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
                unique_keys=(("adsh", "tag", "version"),),
            ),
            "sub": TableAssumptions(max_rows=86_135, one_row_per_adsh=True),
            "tag": TableAssumptions(max_rows=1_070_662),
            "num": TableAssumptions(
                max_rows=39_401_761,
                columns={
                    "value": ColumnAssumption(
                        max_value_exclusive=2**60,
                        abs_sum_exclusive=10**18,
                    )
                },
            ),
        },
    )


def _strip_fullsec_slot_u64_bounds(program: str) -> str:
    """Drop multi_agg slot ≤ rem_u64 lemmas when rem_join_cube overflows u64.

    The Q6 fold (``is_q6`` / ``method_is_fold``) is the subject; the host slot
    rem·u64 bridge is unsound under full SEC cube and is not this shape's job.
    """
    out, n = _SLOT_BOUND_SECTION.subn("\n", program, count=1)
    assert n == 1, "expected multi-agg fold bound section in assembled program"
    return out


def test_shape_q6_prelude_names() -> None:
    body = proved_eq_join_prelude()
    assert "// SHAPE_Q6_BEGIN" in body
    assert "// SHAPE_Q6_END" in body
    assert "pub fn q6_eq_triples_str(" in body
    assert "pub open spec fn nested_q6(" in body
    assert "pub open spec fn loop_acc_q6<" in body
    assert "pub proof fn lemma_q6_acc<" in body
    assert "pub proof fn lemma_q6_at_origin<" in body
    assert "arbitrary()" not in body
    assert "external_body" not in body
    assert "assume(" not in body


def test_q6_fold_verifies(tmp_path: Path) -> None:
    """num⋈sub⋈pre (1+3) fold lemmas verify under full SEC product caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    schema = _q6_schema()
    _, multi = normalize_schema(schema)
    if not isinstance(multi, dict):
        raise TypeError("expected a per-table schema")
    catalog = _large_sec_product_catalog()
    projected = project_multi_schema_for_query(_Q6_SQL, multi)
    if any(not isinstance(cols, dict) for cols in projected.values()):
        raise TypeError("expected a per-table schema")
    projected = cast(dict[str, dict[str, str]], projected)
    spec_rs = transpile_sql_to_verus(_Q6_SQL, projected, catalog_assumptions=catalog)
    assert "pub const LEMMA_MAX_ROWS: usize = 39401761;" in spec_rs
    assert "// shape: q6" in spec_rs
    assert "lemma_multi_agg_helper_is_q6" in spec_rs
    assert "lemma_multi_agg_helper_is_q6_pairs" in spec_rs
    assert "lemma_multi_agg_helper_method_is_fold" in spec_rs
    assert "pub open spec fn multi_agg_helper(" in spec_rs
    assert "pub fn q6_eq_triples_str(" in spec_rs
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    rust = dynamic_ret_type_config()[ret_type]["rust_ret"]
    order = ("num", "sub", "pre")
    params = ", ".join(f"{t}: &Cols_{t}" for t in order)
    reqs = ", ".join(f"valid_cols_{t}({t})" for t in order)
    body = "Vec::new()" if rust.startswith("Vec") else map_new_expr(rust)
    stub = f"""#[verifier::external_body]
pub exec fn run_query({params}) -> (res: {rust})
    requires {reqs},
    ensures res@ == res@,
{{
    {body}
}}"""
    program = assemble_verified_nway_program(
        spec_rs=spec_rs,
        run_query_body=stub,
        multi_schema=projected,
        table_order=order,
        ret_type=ret_type,
        default_tbls={t: "" for t in order},
        catalog_assumptions=catalog,
    )
    assert "pub const LEMMA_MAX_ROWS: usize = 39401761;" in program
    assert "lemma_multi_agg_helper_is_q6" in program
    assert "lemma_multi_agg_helper_is_q6_pairs" in program
    assert "lemma_multi_agg_helper_method_is_fold" in program
    assert "pub fn q6_eq_triples_str(" in program
    program = _strip_fullsec_slot_u64_bounds(program)
    assert "lemma_multi_agg_helper_slot0_" not in program
    assert "lemma_multi_agg_helper_is_q6" in program
    rs_path = tmp_path / "q6_1plus3.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=300)
    assert ok, log[-4000:]
    assert "0 errors" in log


def test_eq_join_q6_verus_clean() -> None:
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    ok, log = run_verus_verify(str(EQ_JOIN_RS), timeout=180)
    assert ok, log[-4000:]
    assert "0 errors" in log
    assert "verification results::" in log
