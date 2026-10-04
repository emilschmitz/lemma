"""Fixes found by the manual adversary triage: IN (SELECT ...) in a projection, string ordering."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

GUARD = Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"
SCHEMA = {"t": {"a": "bigint", "k": "bigint", "s": "varchar"}, "u": {"b": "bigint", "s": "varchar"}}
CATALOG = CatalogAssumptions(max_rows=16, tables={n: TableAssumptions(max_rows=16) for n in SCHEMA})


def _emit(sql: str) -> str:
    return emit_declarative_spec(sql, SCHEMA, CATALOG)


def _typechecks(spec: str) -> None:
    if not Path("/home/emil/tools/verus/verus").is_file():
        pytest.skip("verus binary not installed")
    program = assemble_declarative_program(spec, "    Vec::new()")
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(program)
    proc = subprocess.run(
        [str(GUARD), handle.name, "--no-verify", "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM t WHERE a IN (SELECT b FROM u)",
        "SELECT a, s FROM t WHERE a NOT IN (SELECT b FROM u WHERE s = 'x') ORDER BY a LIMIT 3",
        "SELECT a FROM t WHERE s IN (SELECT s FROM u) AND k > 1",
    ],
)
def test_in_subquery_in_a_plain_projection_defines_its_membership_function(sql: str) -> None:
    spec = _emit(sql)
    assert "spec fn in_" in spec
    _typechecks(spec)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM t WHERE s < 'b'",
        "SELECT a FROM t WHERE s >= 'b' AND a > 0",
        "SELECT a FROM t WHERE s BETWEEN 'a' AND 'c'",
        "SELECT k, COUNT(*) AS c FROM t WHERE s > 'a' GROUP BY k",
    ],
)
def test_string_ordering_is_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match="string"):
        _emit(sql)


@pytest.mark.parametrize("sql", ["SELECT a FROM t WHERE s = 'b'", "SELECT a FROM t WHERE s <> 'b' OR s = ''"])
def test_string_equality_still_emits(sql: str) -> None:
    _typechecks(_emit(sql))
