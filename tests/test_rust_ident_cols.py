"""Rust keyword column names must emit raw identifiers in host codegen."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from research_loop.assemble_verified_program import (
    assemble_verified_program,
    generate_load_cols_duckdb_like_verus,
    generate_load_cols_verus,
)
from research_loop.exec_cols import generate_cols_exec_rs
from research_loop.harness import resolve_verus_bin, run_verus_verify
from verus_transpiler import generate_cols_rs, rust_ident, transpile_sql_to_verus

ABSTRACT_SCHEMA = {
    "abstract": "int",
    "x": "int",
}

TRIVIAL_SQL = "SELECT COUNT(*) FROM t WHERE abstract > 0"


def test_rust_ident_keyword_abstract() -> None:
    assert rust_ident("abstract") == "r#abstract"
    assert rust_ident("ABSTRACT") == "r#abstract"
    assert rust_ident("x") == "x"
    assert rust_ident("match") == "r#match"


def test_generate_cols_rs_keyword_field() -> None:
    out = generate_cols_rs(ABSTRACT_SCHEMA)
    assert "pub r#abstract: Vec<u32>" in out
    assert re.search(r"pub abstract:", out) is None
    assert "cols.r#abstract[" in transpile_sql_to_verus(
        "SELECT abstract FROM t", {"t": ABSTRACT_SCHEMA}
    )


def test_generate_load_cols_verus_keyword_field() -> None:
    load_rs = generate_load_cols_verus(ABSTRACT_SCHEMA)
    assert "let mut r#abstract: Vec<u32>" in load_rs
    assert "r#abstract.push(" in load_rs
    assert "let abstract_i =" in load_rs
    assert "pub abstract:" not in load_rs


def test_generate_load_cols_duckdb_like_verus_keyword_field() -> None:
    load_rs = generate_load_cols_duckdb_like_verus(ABSTRACT_SCHEMA)
    assert "let mut r#abstract: Vec<u32>" in load_rs
    assert "abstract_zones:" in load_rs
    assert "let abstract_i =" in load_rs


def test_generate_cols_exec_rs_keyword_field() -> None:
    cols_rs = generate_cols_exec_rs(ABSTRACT_SCHEMA)
    assert "pub r#abstract: Vec<u32>" in cols_rs
    assert "let mut r#abstract: Vec<u32>" in cols_rs


def _external_body_run_query_stub() -> str:
    return """#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    0u64
}"""


def test_abstract_schema_assemble_verus_smoke(tmp_path: Path) -> None:
    spec_rs = transpile_sql_to_verus(TRIVIAL_SQL, {"t": ABSTRACT_SCHEMA})
    program = assemble_verified_program(
        spec_rs=spec_rs,
        run_query_body=_external_body_run_query_stub(),
        schema_dict=ABSTRACT_SCHEMA,
        ret_type="u64",
        default_tbl=str(tmp_path / "t.tbl"),
    )

    rs_path = tmp_path / "abstract_smoke.rs"
    rs_path.write_text(program, encoding="utf-8")

    if resolve_verus_bin() is None:
        pytest.skip("verus not found")

    ok, log = run_verus_verify(str(rs_path), timeout=120)
    assert "expected identifier, found keyword `abstract`" not in log
    if not ok:
        pytest.fail(f"verus verify failed:\n{log[-4000:]}")
