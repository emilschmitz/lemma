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

from research_loop.assemble_verified_program import (
    assemble_verified_join_program,
    assemble_verified_nway_program,
)
from research_loop.harness import resolve_verus_bin, run_verus_compile, run_verus_verify
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.sec_table_assumptions import sec_prove_loop_catalog_assumptions
from research_loop.trusted_ret_bridge import dynamic_ret_type_config, map_new_expr
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

_TAG_SQL = """
SELECT COUNT(*)
FROM pre p
JOIN tag t ON p.tag = t.tag AND p.version = t.version
WHERE p.stmt = 'CI'
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
    assert "pub open spec fn loop_acc2<" in body
    assert "pub proof fn lemma_acc2<" in body
    assert "pub proof fn lemma_pair_pos_origin<" in body
    assert "pub proof fn lemma_pair_pos2_origin<" in body
    assert "pub proof fn lemma_star_pos_origin(" in body
    assert "pub proof fn lemma_loop_at_origin<" in body
    assert "pub proof fn lemma_loop2_at_origin<" in body
    assert "pub proof fn lemma_star_at_origin<" in body
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
    tag = transpile_sql_to_verus(
        _TAG_SQL,
        {"pre": SEC_SCHEMA["pre"], "tag": SEC_SCHEMA["tag"]},
    )
    single = transpile_sql_to_verus(_SINGLE_SQL, {"pre": SEC_SCHEMA["pre"]})
    for out in (adsh, star, tag):
        assert "pub fn equijoin_pairs_str(" in out
        assert "pub fn star_eq_triples_str(" in out
        assert "walk pairs from the end" in out
        assert "pair_acc(pairs@, step, base, k as int)" in out
        assert "triple_acc(triples@, step, base, k as int)" in out
        assert "lemma_<helper>_is_pairs" in out
        assert "lemma_<helper>_is_pairs2" in out
        assert "lemma_<helper>_is_star_pairs" in out
        assert "let mut i = cols.n" not in out
    assert "lemma_join_method_spec_helper_is_loop(" in adsh
    assert "lemma_join_method_spec_helper_is_pairs(" in adsh
    assert "lemma_join_method_spec_helper_is_loop(" not in star
    assert "lemma_join_method_spec_helper_is_pairs(" not in star
    assert "lemma_join_method_spec_helper_is_loop2(" not in adsh
    assert "lemma_join_method_spec_helper_is_loop2(" in tag
    assert "lemma_join_method_spec_helper_is_pairs2(" in tag
    assert "lemma_join_projection_helper_is_star" in star
    assert "lemma_join_projection_helper_is_star_pairs" in star
    assert "pub fn build_eq_index_str(" not in single
    assert "pub fn equijoin_pairs_str(" not in single
    assert "let mut i = cols.n" in single


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
    ("sql", "lemma", "pairs_lemma", "ret", "body", "ensures"),
    [
        (
            """
            SELECT s.fy, SUM(p.line)
            FROM pre p JOIN sub s ON p.adsh = s.adsh
            WHERE p.stmt = 'IS'
            GROUP BY s.fy
            """,
            "lemma_join_method_spec_helper_is_loop",
            "lemma_join_method_spec_helper_is_pairs",
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
            "lemma_multi_agg_helper_is_pairs",
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
            "lemma_join_method_spec_helper_is_pairs",
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
            "lemma_join_projection_helper_is_pairs",
            "Vec<u32>",
            "Vec::new()",
            "res@ == res@",
        ),
    ],
)
def test_pair_fold_lemma_verifies(
    sql: str,
    lemma: str,
    pairs_lemma: str,
    ret: str,
    body: str,
    ensures: str,
    tmp_path: Path,
) -> None:
    """Generated helper==loop_acc and helper==pair_acc proofs verify under big SEC caps."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    projected = _projected(sql)
    catalog = sec_prove_loop_catalog_assumptions()
    spec_rs = transpile_sql_to_verus(sql, projected, catalog_assumptions=catalog)
    assert lemma in spec_rs
    assert pairs_lemma in spec_rs
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
    assert pairs_lemma in program
    rs_path = tmp_path / "fold.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=180)
    assert ok, log[-5000:]
    assert "0 errors" in log


def test_two_column_fold_lemma_verifies(tmp_path: Path) -> None:
    """tag AND version: the helper equals loop_acc2, and that file verifies."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    _, multi = normalize_schema({"pre": SEC_SCHEMA["pre"], "tag": SEC_SCHEMA["tag"]})
    if not isinstance(multi, dict):
        raise TypeError("expected a per-table schema")
    projected = project_multi_schema_for_query(_TAG_SQL, multi)
    if any(not isinstance(cols, dict) for cols in projected.values()):
        raise TypeError("expected a per-table schema")
    projected = cast(dict[str, dict[str, str]], projected)
    catalog = sec_prove_loop_catalog_assumptions()
    spec_rs = transpile_sql_to_verus(_TAG_SQL, projected, catalog_assumptions=catalog)
    assert "lemma_join_method_spec_helper_is_loop2(" in spec_rs
    assert "lemma_join_method_spec_helper_is_pairs2(" in spec_rs
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    assert ret_type == "u64"
    stub = """#[verifier::external_body]
pub exec fn run_query(pre: &Cols_pre, tag: &Cols_tag) -> (res: u64)
    requires valid_cols_pre(pre), valid_cols_tag(tag),
    ensures res == method_spec(pre, tag),
{
    0u64
}"""
    program = assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=stub,
        multi_schema=projected,
        table_order=("pre", "tag"),
        ret_type=ret_type,
        default_tbls={"pre": "", "tag": ""},
        catalog_assumptions=catalog,
    )
    assert "lemma_join_method_spec_helper_is_pairs2(" in program
    rs_path = tmp_path / "tag_fold.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=180)
    assert ok, log[-5000:]
    assert "0 errors" in log


def test_previous_failure_joins_fold(tmp_path: Path) -> None:
    """r24 Q16 group-by and r24 Q18 star: the generated fold lemma verifies."""
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    schema = {name: dict(cols) for name, cols in SEC_SCHEMA.items()}
    schema["sub"]["form"] = "string"
    schema["tag"]["custom"] = "int"
    _, multi = normalize_schema(schema)
    if not isinstance(multi, dict):
        raise TypeError("expected a per-table schema")
    catalog = sec_prove_loop_catalog_assumptions()
    cases = [
        (
            """
            SELECT s.form, s.fy, COUNT(*) AS num_lines,
                   COUNT(DISTINCT p.tag) AS distinct_tags,
                   AVG(p.line) AS avg_line
            FROM pre p JOIN sub s ON p.adsh = s.adsh
            WHERE p.stmt = 'EQ'
            GROUP BY s.form, s.fy
            LIMIT 500
            """,
            "lemma_multi_agg_helper_is_loop",
            "lemma_multi_agg_helper_is_pairs",
            ("pre", "sub"),
            False,
        ),
        (
            """
            SELECT s.name, p.stmt, t.tlabel, p.line, p.plabel
            FROM pre p
            JOIN sub s ON p.adsh = s.adsh
            JOIN tag t ON p.tag = t.tag AND p.version = t.version
            WHERE s.form = '10-K/A' AND p.stmt = 'CI' AND t.custom = 0
            LIMIT 200
            """,
            "lemma_join_projection_helper_is_star",
            "lemma_join_projection_helper_is_star_pairs",
            ("pre", "sub", "tag"),
            True,
        ),
    ]
    for sql, lemma, pairs_lemma, order, nway in cases:
        projected = project_multi_schema_for_query(sql, multi)
        if any(not isinstance(cols, dict) for cols in projected.values()):
            raise TypeError("expected a per-table schema")
        projected = cast(dict[str, dict[str, str]], projected)
        spec_rs = transpile_sql_to_verus(sql, projected, catalog_assumptions=catalog)
        assert lemma in spec_rs
        assert pairs_lemma in spec_rs
        ret_type = resolve_ret_type_from_method_spec(spec_rs)
        rust = dynamic_ret_type_config()[ret_type]["rust_ret"]
        params = ", ".join(f"{t}: &Cols_{t}" for t in order)
        reqs = ", ".join(f"valid_cols_{t}({t})" for t in order)
        args = ", ".join(order)
        body = "Vec::new()" if rust.startswith("Vec") else map_new_expr(rust)
        if nway:
            ensures = "res@ == res@"
        elif rust.startswith(("HashMap", "Vec")):
            ensures = f"res@ == method_spec({args})"
        else:
            ensures = f"res == method_spec({args})"
        stub = f"""#[verifier::external_body]
pub exec fn run_query({params}) -> (res: {rust})
    requires {reqs},
    ensures {ensures},
{{
    {body}
}}"""
        if nway:
            program = assemble_verified_nway_program(
                spec_rs=spec_rs,
                run_query_body=stub,
                multi_schema=projected,
                table_order=order,
                ret_type=ret_type,
                default_tbls={t: "" for t in order},
                catalog_assumptions=catalog,
            )
        else:
            program = assemble_verified_join_program(
                spec_rs=spec_rs,
                run_query_body=stub,
                multi_schema=projected,
                table_order=(order[0], order[1]),
                ret_type=ret_type,
                default_tbls={t: "" for t in order},
                catalog_assumptions=catalog,
            )
        rs_path = tmp_path / f"{lemma}.rs"
        rs_path.write_text(program, encoding="utf-8")
        ok, log = run_verus_verify(str(rs_path), timeout=180)
        assert ok, log[-4000:]
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
