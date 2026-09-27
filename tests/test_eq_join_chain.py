"""Proved 3-table chain equijoin (A.k=B.k AND B.m=C.m) under full SEC product caps.

Holdout/harvest has no true chain (num has no cik; Q4/Q6 are star-shaped).
Invented smallest SEC-shaped chain: pre.adsh=num.adsh AND num.tag=tag.tag.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from verus_transpiler.column_projection import project_multi_schema_for_query
from verus_transpiler.eq_join_prelude import proved_eq_join_prelude
from verus_transpiler.parse_sql import normalize_schema

from research_loop.assemble_verified_program import (
    RET_TYPE_CONFIG,
    assemble_verified_nway_program,
)
from research_loop.harness import resolve_verus_bin, run_verus_verify
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.sec_table_assumptions import SEC_PROVE_LOOP_MAX_CELL_U64
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
)
from research_loop.trusted_ret_bridge import map_new_expr
from tests.test_sec_holdout_parse import SEC_SCHEMA
from verus_transpiler import transpile_sql_to_verus

ROOT = Path(__file__).resolve().parents[1]
EQ_JOIN_RS = ROOT / "research_loop" / "verus_lib" / "eq_join.rs"

# Full SEC product caps (num global max). Not the 65536 prove_loop profile.
_SEC_PRODUCT_MAX_ROWS = 39_401_761

# Invented: holdout has no A.k=B.k AND B.m=C.m chain (num lacks cik).
_CHAIN_SQL = """
SELECT COUNT(*)
FROM pre p
JOIN num n ON p.adsh = n.adsh
JOIN tag t ON n.tag = t.tag
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


def test_shape_chain_prelude_names() -> None:
    body = proved_eq_join_prelude()
    assert "// SHAPE_CHAIN_BEGIN" in body
    assert "// SHAPE_CHAIN_END" in body
    assert "pub fn chain_eq_triples_str(" in body
    assert "pub open spec fn loop_acc_chain<" in body
    assert "pub open spec fn nested_chain<" in body
    assert "pub proof fn lemma_chain_acc<" in body
    assert "pub proof fn lemma_chain_at_origin<" in body
    assert "arbitrary()" not in body
    assert "external_body" not in body
    assert "assume(" not in body


def test_chain_transpile_emits_is_chain_fold() -> None:
    schema = {
        "pre": dict(SEC_SCHEMA["pre"]),
        "num": dict(SEC_SCHEMA["num"]),
        "tag": dict(SEC_SCHEMA["tag"]),
    }
    _, multi = normalize_schema(schema)
    if not isinstance(multi, dict):
        raise TypeError("expected a per-table schema")
    catalog = _large_sec_product_catalog()
    projected = project_multi_schema_for_query(_CHAIN_SQL, multi)
    if any(not isinstance(cols, dict) for cols in projected.values()):
        raise TypeError("expected a per-table schema")
    projected = cast(dict[str, dict[str, str]], projected)
    out = transpile_sql_to_verus(_CHAIN_SQL, projected, catalog_assumptions=catalog)
    assert "pub const LEMMA_MAX_ROWS: usize = 39401761;" in out
    assert "// shape: chain" in out
    assert "lemma_join_method_spec_helper_is_chain(" in out
    assert "lemma_join_method_spec_helper_is_chain_pairs(" in out
    assert "lemma_join_method_spec_helper_method_is_fold(" in out
    assert "loop_acc_chain(" in out
    assert "nested_chain(" in out
    assert "lemma_join_method_spec_helper_is_star(" not in out


def test_three_table_chain_fold_verifies(tmp_path: Path) -> None:
    """pre⋈num⋈tag chain fold lemmas verify under full SEC product caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    schema = {
        "pre": dict(SEC_SCHEMA["pre"]),
        "num": dict(SEC_SCHEMA["num"]),
        "tag": dict(SEC_SCHEMA["tag"]),
    }
    _, multi = normalize_schema(schema)
    if not isinstance(multi, dict):
        raise TypeError("expected a per-table schema")
    catalog = _large_sec_product_catalog()
    projected = project_multi_schema_for_query(_CHAIN_SQL, multi)
    if any(not isinstance(cols, dict) for cols in projected.values()):
        raise TypeError("expected a per-table schema")
    projected = cast(dict[str, dict[str, str]], projected)
    spec_rs = transpile_sql_to_verus(
        _CHAIN_SQL, projected, catalog_assumptions=catalog
    )
    assert "pub const LEMMA_MAX_ROWS: usize = 39401761;" in spec_rs
    assert "lemma_join_method_spec_helper_is_chain" in spec_rs
    assert "lemma_join_method_spec_helper_is_chain_pairs" in spec_rs
    assert "lemma_join_method_spec_helper_method_is_fold" in spec_rs
    assert "pub fn chain_eq_triples_str(" in spec_rs
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    rust = RET_TYPE_CONFIG[ret_type]["rust_ret"]
    order = ("pre", "num", "tag")
    params = ", ".join(f"{t}: &Cols_{t}" for t in order)
    reqs = ", ".join(f"valid_cols_{t}({t})" for t in order)
    body = "Vec::new()" if rust.startswith("Vec") else map_new_expr(rust)
    if rust == "u64":
        body = "0u64"
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
    assert "lemma_join_method_spec_helper_is_chain" in program
    assert "lemma_join_method_spec_helper_method_is_fold" in program
    assert "pub fn chain_eq_triples_str(" in program
    rs_path = tmp_path / "three_table_chain.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=300)
    assert ok, log[-4000:]
    assert "0 errors" in log


def test_eq_join_chain_verus_clean() -> None:
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    ok, log = run_verus_verify(str(EQ_JOIN_RS), timeout=300)
    assert ok, log[-4000:]
    assert "0 errors" in log
    assert "verification results::" in log
