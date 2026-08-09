"""Host codegen smoke: SEC Q1-like loader + multi-agg MethodSpec must typecheck in Verus."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from db_extension.verus_bridge import resolve_ret_type_for_spec
from research_loop.assemble_verified_program import (
    assemble_verified_program,
    generate_load_cols_duckdb_like_verus,
    generate_load_cols_verus,
)
from research_loop.harness import resolve_verus_bin, run_verus_verify
from research_loop.trusted_ret_bridge import get_bridge
from verus_transpiler import transpile_sql_to_verus

PRE_SCHEMA = {
    "stmt": "string",
    "rfile": "string",
    "adsh": "string",
    "line": "int",
}

Q1_LIKE_SQL = """SELECT stmt, rfile, COUNT(*) AS cnt,
       COUNT(DISTINCT adsh) AS num_filings,
       AVG(line) AS avg_line_num
FROM pre
WHERE stmt IS NOT NULL
GROUP BY stmt, rfile"""

_HOST_RUSTC_ERRORS = (
    "error[E0282]",
    "error[E0308]",
    "type annotations needed",
    "expected `char`, found",
)


def _assert_loader_no_line_shadow(load_rs: str) -> None:
    assert "for line in rdr.lines" not in load_rs
    assert "for raw_line in rdr.lines" in load_rs
    assert "line.push(" in load_rs or "let mut line: Vec" in load_rs


def test_generate_load_cols_verus_line_column_no_shadow() -> None:
    load_rs = generate_load_cols_verus(PRE_SCHEMA)
    _assert_loader_no_line_shadow(load_rs)


def test_generate_load_cols_duckdb_like_verus_line_column_no_shadow() -> None:
    load_rs = generate_load_cols_duckdb_like_verus(PRE_SCHEMA)
    _assert_loader_no_line_shadow(load_rs)


def test_q1_like_method_spec_map_values_typed_closure() -> None:
    out = transpile_sql_to_verus(Q1_LIKE_SQL, {"pre": PRE_SCHEMA})
    assert re.search(r"map_values\(\|v:\s*\(", out), "expected typed map_values(|v: (...)|"
    closure = re.search(r"map_values\(\|[^|]+\|\s*.+?\)\)", out, re.DOTALL)
    assert closure is not None
    inner = closure.group(0)
    for name in (f"s{i}" for i in range(8)):
        assert not re.search(rf"(?<![.\w]){name}(?![.\w])", inner.split("|", 2)[-1]), (
            f"free aggregate state {name!r} in map_values closure"
        )


def _external_body_run_query_stub(ret_type: str) -> str:
    bridge = get_bridge(ret_type)
    assert bridge is not None, f"missing bridge for {ret_type}"
    return f"""#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: {bridge.rust_ret})
    requires valid_cols(cols),
    ensures {bridge.ensures}
{{
    HashMap::new()
}}"""


def test_sec_q1_assemble_verus_smoke(tmp_path: Path) -> None:
    spec_rs = transpile_sql_to_verus(Q1_LIKE_SQL, {"pre": PRE_SCHEMA})
    ret_type = resolve_ret_type_for_spec(spec_rs)
    assert ret_type == "map_str_str__u64_u64_u64"

    program = assemble_verified_program(
        spec_rs=spec_rs,
        run_query_body=_external_body_run_query_stub(ret_type),
        schema_dict=PRE_SCHEMA,
        ret_type=ret_type,
        default_tbl=str(tmp_path / "pre.tbl"),
    )

    rs_path = tmp_path / "sec_q1_smoke.rs"
    rs_path.write_text(program, encoding="utf-8")

    if resolve_verus_bin() is None:
        pytest.skip("verus not found")

    ok, log = run_verus_verify(str(rs_path), timeout=120)
    for err in _HOST_RUSTC_ERRORS:
        assert err not in log, f"host codegen bug still present ({err!r}):\n{log[-4000:]}"

    if not ok:
        pytest.fail(f"verus verify failed (non-host errors):\n{log[-4000:]}")
