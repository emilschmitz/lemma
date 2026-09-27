"""Proved equijoin: Verus, runtime oracle, and join-only splice."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import cast

import pytest
from verus_transpiler.column_projection import project_multi_schema_for_query
from verus_transpiler.eq_join_prelude import proved_eq_join_prelude
from verus_transpiler.parse_sql import normalize_schema

from research_loop.assemble_verified_program import assemble_verified_join_program
from research_loop.harness import resolve_verus_bin, run_verus_compile, run_verus_verify
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.sec_table_assumptions import sec_prove_loop_catalog_assumptions
from tests.test_sec_holdout_parse import SEC_SCHEMA
from verus_transpiler import transpile_sql_to_verus

ROOT = Path(__file__).resolve().parents[1]
EQ_JOIN_RS = ROOT / "research_loop" / "verus_lib" / "eq_join.rs"

_ADSH_SQL = """
SELECT COUNT(*)
FROM pre p
JOIN sub s ON p.adsh = s.adsh
WHERE s.fy = 2024
"""

_STAR_SQL = """
SELECT p.adsh
FROM pre p
JOIN sub s ON p.adsh = s.adsh
JOIN tag t ON p.tag = t.tag AND p.version = t.version
LIMIT 50
"""

_SINGLE_SQL = "SELECT COUNT(*) FROM pre p WHERE p.stmt = 'CI'"


def _projected(sql: str) -> dict[str, dict[str, str]]:
    _, multi = normalize_schema({"pre": SEC_SCHEMA["pre"], "sub": SEC_SCHEMA["sub"]})
    if not isinstance(multi, dict):
        raise TypeError("expected a per-table schema")
    projected = project_multi_schema_for_query(sql, multi)
    if any(not isinstance(cols, dict) for cols in projected.values()):
        raise TypeError("expected a per-table schema")
    return cast(dict[str, dict[str, str]], projected)


def test_proved_slice_is_rocketship_clean() -> None:
    body = proved_eq_join_prelude()
    assert "pub fn equijoin_pairs_str(" in body
    assert "pub fn equijoin_pairs_str2(" in body
    assert "pub fn equijoin_pairs_u64(" in body
    assert "pub fn star_eq_triples_str(" in body
    assert "pub open spec fn loop_acc<" in body
    assert "pub proof fn lemma_acc<" in body
    assert "arbitrary()" not in body
    assert "external_body" not in body
    assert "assume(" not in body


def test_join_transpile_includes_proved_equijoin_and_single_table_does_not() -> None:
    adsh = transpile_sql_to_verus(
        _ADSH_SQL,
        {"pre": SEC_SCHEMA["pre"], "sub": SEC_SCHEMA["sub"]},
    )
    star = transpile_sql_to_verus(
        _STAR_SQL,
        {"pre": SEC_SCHEMA["pre"], "sub": SEC_SCHEMA["sub"], "tag": SEC_SCHEMA["tag"]},
    )
    single = transpile_sql_to_verus(_SINGLE_SQL, {"pre": SEC_SCHEMA["pre"]})
    for out in (adsh, star):
        assert "pub fn equijoin_pairs_str(" in out
        assert "pub fn star_eq_triples_str(" in out
        assert "walk pairs from the end" in out
    assert "lemma_join_method_spec_helper_is_loop" in adsh
    assert "lemma_join_method_spec_helper_is_loop" not in star
    assert "pub fn build_eq_index_str(" not in single
    assert "pub fn equijoin_pairs_str(" not in single


def test_spliced_adsh_join_verifies(tmp_path: Path) -> None:
    """Host file with the proved index verifies. The stub is not an agent proof."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    projected = _projected(_ADSH_SQL)
    spec_rs = transpile_sql_to_verus(_ADSH_SQL, projected)
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
    )
    assert "pub fn equijoin_pairs_str(" in program
    rs_path = tmp_path / "adsh_join.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=180)
    assert ok, log[-5000:]
    assert "0 errors" in log


def _stub(ret: str, body: str, ensures: str) -> str:
    return f"""#[verifier::external_body]
pub exec fn run_query(pre: &Cols_pre, sub: &Cols_sub) -> (res: {ret})
    requires valid_cols_pre(pre), valid_cols_sub(sub),
    ensures {ensures},
{{
    {body}
}}"""


@pytest.mark.parametrize(
    ("sql", "lemma", "ret", "body", "ensures"),
    [
        (
            """
            SELECT s.fy, SUM(p.line)
            FROM pre p JOIN sub s ON p.adsh = s.adsh
            WHERE p.stmt = 'IS'
            GROUP BY s.fy
            """,
            "lemma_join_method_spec_helper_is_loop",
            "HashMap<u32, u64>",
            "HashMap::new()",
            "res@ == method_spec(pre, sub)",
        ),
        (
            """
            SELECT s.fy, COUNT(*), SUM(p.line)
            FROM pre p JOIN sub s ON p.adsh = s.adsh
            WHERE p.stmt = 'IS'
            GROUP BY s.fy
            """,
            "lemma_multi_agg_helper_is_loop",
            "HashMap<u32, (u64, u64)>",
            "HashMap::new()",
            "res@ == method_spec(pre, sub)",
        ),
        (
            """
            SELECT COUNT(*)
            FROM pre p JOIN sub s ON p.line = s.fy
            """,
            "lemma_join_method_spec_helper_is_loop",
            "u64",
            "0u64",
            "res == method_spec(pre, sub)",
        ),
        (
            """
            SELECT p.line
            FROM pre p JOIN sub s ON p.adsh = s.adsh
            """,
            "lemma_join_projection_helper_is_loop",
            "Vec<u32>",
            "Vec::new()",
            "res@ == res@",
        ),
    ],
)
def test_pair_fold_lemma_verifies(
    sql: str, lemma: str, ret: str, body: str, ensures: str, tmp_path: Path,
) -> None:
    """Generated helper==loop_acc proof verifies for sum, multi-agg, and integer keys."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    projected = _projected(sql)
    catalog = sec_prove_loop_catalog_assumptions()
    spec_rs = transpile_sql_to_verus(sql, projected, catalog_assumptions=catalog)
    assert lemma in spec_rs
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    program = assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=_stub(ret, body, ensures),
        multi_schema=projected,
        table_order=("pre", "sub"),
        ret_type=ret_type,
        default_tbls={"pre": "", "sub": ""},
        catalog_assumptions=catalog,
    )
    rs_path = tmp_path / "fold.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=180)
    assert ok, log[-5000:]
    assert "0 errors" in log


def test_eq_join_verus_clean() -> None:
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    ok, log = run_verus_verify(str(EQ_JOIN_RS), timeout=120)
    assert ok, log[-4000:]
    assert "0 errors" in log


def test_eq_join_oracle_matches_nested_loops() -> None:
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    ok, log, binary = run_verus_compile(str(EQ_JOIN_RS), timeout=180)
    assert ok and binary, log[-4000:]
    try:
        subprocess.run([binary], check=True, timeout=60)
    finally:
        if binary and os.path.isfile(binary):
            os.remove(binary)
