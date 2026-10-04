"""Ungrouped SUM, MIN, MAX and AVG are NULL when no row passes the filter."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.bench import rows_match_error
from declarative_spec.emit import emit_declarative_spec
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

VERUS = Path("/home/emil/tools/verus/verus")
SCHEMA = {"t": {"a": "integer", "g": "integer"}}
CATALOG = CatalogAssumptions(tables={"t": TableAssumptions(max_rows=8)})

# No row can pass: the filter is contradictory, so the result must be NULL.
_NEVER = "WHERE a > 100 AND a < 50"


def _emit(sql: str) -> str:
    return emit_declarative_spec(sql, SCHEMA, CATALOG, float_abs_eps="1e20")


def _verus(spec: str, body: str) -> str:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    program = assemble_declarative_program(spec, body)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
        f.write(program)
    proc = subprocess.run(
        [str(VERUS), f.name, "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    return proc.stdout + proc.stderr


@pytest.mark.parametrize("agg", ["SUM", "MIN", "MAX", "AVG"])
def test_ungrouped_aggregate_has_option_field_and_null_clause(agg: str) -> None:
    spec = _emit(f"SELECT {agg}(a) AS r FROM t")
    assert re.search(r"pub r: Option<", spec)
    assert "res@[r].r is None" in spec
    assert "res@[r].r is Some" in spec
    assert "res@.len() == 1" in spec


def test_count_stays_non_null_on_empty_input() -> None:
    spec = _emit("SELECT COUNT(*) AS c FROM t")
    assert "pub c: u64" in spec
    assert "Option<" not in spec


def test_grouped_aggregate_is_not_nullable() -> None:
    spec = _emit("SELECT g, SUM(a) AS s FROM t GROUP BY g")
    assert "Option<" not in spec


def test_mixed_count_and_sum_only_sum_is_nullable() -> None:
    spec = _emit(f"SELECT COUNT(*) AS c, SUM(a) AS s FROM t {_NEVER}")
    assert "pub c: u64" in spec
    assert re.search(r"pub s: Option<", spec)


def test_empty_result_body_returning_null_verifies() -> None:
    spec = _emit(f"SELECT SUM(a) AS s FROM t {_NEVER}")
    out = _verus(
        spec,
        "    let mut v: Vec<OutRow> = Vec::new();\n"
        "    v.push(OutRow { s: None });\n"
        "    proof {\n"
        "        assert(forall|i0: int| !row_hit(t, i0));\n"
        "    }\n"
        "    v\n",
    )
    assert re.search(r"verification results:: \d+ verified, 0 errors", out), out[-1500:]


def test_empty_result_body_returning_zero_is_rejected() -> None:
    spec = _emit(f"SELECT SUM(a) AS s FROM t {_NEVER}")
    out = _verus(
        spec,
        "    let mut v: Vec<OutRow> = Vec::new();\n    v.push(OutRow { s: Some(0) });\n    v\n",
    )
    assert re.search(r"verification results:: \d+ verified, [1-9]\d* errors?", out), out[-1500:]


def test_empty_min_spec_is_satisfiable_by_null() -> None:
    spec = _emit(f"SELECT MIN(a) AS r FROM t {_NEVER}")
    out = _verus(
        spec,
        "    let mut v: Vec<OutRow> = Vec::new();\n"
        "    v.push(OutRow { r: None });\n"
        "    proof {\n"
        "        assert(forall|i0: int| !row_hit(t, i0));\n"
        "    }\n"
        "    v\n",
    )
    assert re.search(r"verification results:: \d+ verified, 0 errors", out), out[-1500:]


def test_null_cell_matches_expected_null() -> None:
    assert rows_match_error([["NULL"]], [[None]], ["int"]) is None
    assert rows_match_error([["NULL"]], [[None]], ["float"]) is None


def test_null_cell_does_not_match_a_zero() -> None:
    assert rows_match_error([["NULL"]], [[0]], ["int"]) is not None
    assert rows_match_error([["0"]], [[None]], ["int"]) is not None


def test_row_printer_prints_null_for_option_fields() -> None:
    from declarative_spec.assemble import _row_printer

    _hex, body = _row_printer("run_query(&cols)", [("s", "Option<i128>"), ("f", "Option<f64>")])
    assert '"NULL".to_string()' in body
    assert "format!(\"{:.17}\"" in body


def _emit_typed(sql: str, col_type: str, exclusive: int) -> str:
    from research_loop.table_assumptions import ColumnAssumption

    catalog = CatalogAssumptions(
        tables={
            "t": TableAssumptions(
                max_rows=8, columns={"a": ColumnAssumption(max_value_exclusive=exclusive)}
            )
        }
    )
    return emit_declarative_spec(sql, {"t": {"a": col_type, "g": "integer"}}, catalog)


_EMPTY_BODY = (
    "    let mut v: Vec<OutRow> = Vec::new();\n"
    "    v.push(OutRow { s: None });\n"
    "    proof {\n"
    "        assert(forall|i0: int| !row_hit(t, i0));\n"
    "    }\n"
    "    v\n"
)


@pytest.mark.parametrize(
    ("col_type", "exclusive"),
    [("ubigint", 2**64), ("bigint", 2**62)],
)
def test_integer_sum_is_i128_for_unsigned_and_signed_columns(col_type: str, exclusive: int) -> None:
    spec = _emit_typed(f"SELECT SUM(a) AS s FROM t {_NEVER}", col_type, exclusive)
    assert "pub s: Option<i128>," in spec
    assert "(res@[r].s->Some_0 as int) == sum_s(t, 0)" in spec
    assert "0x8000_0000_0000_0000int" not in spec  # the catalog row cap already states it
    out = _verus(spec, _EMPTY_BODY)
    assert re.search(r"verification results:: \d+ verified, 0 errors", out), out[-1500:]


def test_grouped_integer_sum_is_i128_even_for_ubigint() -> None:
    spec = _emit_typed("SELECT g, SUM(a) AS s FROM t GROUP BY g", "ubigint", 2**64)
    assert "pub s: i128," in spec
    assert "(row.s as int) ==" in spec


def test_integer_sum_without_row_cap_states_row_count_below_two_pow_63() -> None:
    spec = emit_declarative_spec(
        "SELECT g, SUM(a) AS s FROM t GROUP BY g", {"t": {"a": "ubigint", "g": "integer"}}, None
    )
    assert "t.n as int < 0x8000_0000_0000_0000int" in spec
