"""Declarative emitter coverage: multi-key counts, folded joins, text ORDER BY, real scalars."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

VERUS = Path("/home/emil/tools/verus/verus")

SCHEMA = {
    "a": {"k": "varchar", "j": "varchar", "q": "integer", "r": "integer", "v": "integer"},
    "b": {"k": "varchar", "q": "integer", "w": "integer"},
}
CATALOG = CatalogAssumptions(
    tables={"a": TableAssumptions(max_rows=64), "b": TableAssumptions(max_rows=64)}
)


def _emit(sql: str) -> str:
    return emit_declarative_spec(sql, SCHEMA, CATALOG)


def _typechecks(spec: str) -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    program = assemble_declarative_program(spec, "    assume(false);\n    Vec::new()")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
        f.write(program)
    proc = subprocess.run(
        [str(VERUS), f.name, "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    out = proc.stdout + proc.stderr
    assert re.search(r"verification results:: \d+ verified, 0 errors", out), out[-800:]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT k, j, COUNT(*) AS c FROM a GROUP BY k, j",
        "SELECT q, r, COUNT(*) AS c FROM a GROUP BY q, r",
        "SELECT k, q, COUNT(*) AS c FROM a GROUP BY k, q",
    ],
)
def test_multi_column_count_group_by_emits(sql: str) -> None:
    spec = _emit(sql)
    assert "method_spec" not in spec
    _typechecks(spec)


def test_float_group_key_still_refused() -> None:
    schema = {"a": {"x": "double", "y": "double"}}
    with pytest.raises(Exception, match="float"):
        emit_declarative_spec(
            "SELECT x, y, COUNT(*) AS c FROM a GROUP BY x, y",
            schema,
            CatalogAssumptions(tables={"a": TableAssumptions(max_rows=8)}),
        )


_DERIVED_MAX = """
SELECT b.w, a.v FROM a JOIN b ON a.q = b.q
JOIN (SELECT q, k, MAX(v) AS mx FROM a WHERE v IS NOT NULL GROUP BY q, k) r
  ON a.q = r.q AND a.k = r.k AND a.v = r.mx
WHERE a.v IS NOT NULL ORDER BY a.v DESC LIMIT 5
"""
_DERIVED_MIN = """
SELECT a.q, a.v FROM a
JOIN (SELECT q, MIN(v) AS lo FROM a GROUP BY q) r ON a.q = r.q AND a.v = r.lo
"""


@pytest.mark.parametrize("sql", [_DERIVED_MAX, _DERIVED_MIN])
def test_join_on_derived_group_aggregate_folds_to_correlated_bound(sql: str) -> None:
    _typechecks(_emit(sql))


def test_derived_join_used_in_select_is_not_folded() -> None:
    sql = (
        "SELECT a.q, r.lo FROM a JOIN (SELECT q, MIN(v) AS lo FROM a GROUP BY q) r "
        "ON a.q = r.q AND a.v = r.lo"
    )
    with pytest.raises(Exception, match="derived"):
        _emit(sql)


def test_derived_join_missing_group_key_is_not_folded() -> None:
    sql = (
        "SELECT a.q FROM a JOIN (SELECT q, k, MIN(v) AS lo FROM a GROUP BY q, k) r "
        "ON a.q = r.q AND a.v = r.lo"
    )
    with pytest.raises(Exception, match="derived"):
        _emit(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a.q, COUNT(*) AS c FROM a LEFT JOIN b ON a.q = b.q AND a.k = b.k "
        "WHERE a.v > 1 AND b.q IS NULL GROUP BY a.q",
        "SELECT a.k FROM a LEFT JOIN b ON a.q = b.q WHERE b.q IS NULL",
    ],
)
def test_left_join_anti_pattern_becomes_not_exists(sql: str) -> None:
    spec = _emit(sql)
    assert "exists_1" in spec
    _typechecks(spec)


def test_left_join_is_null_on_column_outside_on_stays_refused() -> None:
    sql = "SELECT a.k FROM a LEFT JOIN b ON a.q = b.q WHERE b.w IS NULL"
    with pytest.raises(Exception, match="outer join"):
        _emit(sql)


def test_left_join_using_the_right_table_stays_refused() -> None:
    sql = "SELECT a.k, b.w FROM a LEFT JOIN b ON a.q = b.q WHERE b.q IS NULL"
    with pytest.raises(Exception, match="outer join"):
        _emit(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT k, COUNT(*) AS c FROM a GROUP BY k ORDER BY k",
        "SELECT k, j, COUNT(*) AS c FROM a GROUP BY k, j ORDER BY k, j DESC LIMIT 3",
        "SELECT k, COUNT(*) AS c FROM a GROUP BY k ORDER BY c DESC, k LIMIT 4",
    ],
)
def test_text_order_by_on_grouped_result_uses_seq_le(sql: str) -> None:
    spec = _emit(sql)
    assert "seq_le(" in spec
    _typechecks(spec)


def test_integer_order_by_does_not_pull_in_seq_le() -> None:
    spec = _emit("SELECT q, COUNT(*) AS c FROM a GROUP BY q ORDER BY c DESC, q")
    assert "seq_le" not in spec


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT k, q FROM a WHERE q > (SELECT AVG(q) FROM a)",
        "SELECT k, q FROM a WHERE (SELECT AVG(r) FROM a) <= q",
        "SELECT q, COUNT(*) AS c FROM a GROUP BY q HAVING COUNT(*) > (SELECT AVG(r) FROM a)",
    ],
)
def test_integer_compared_with_real_scalar_is_promoted(sql: str) -> None:
    spec = _emit(sql)
    assert re.search(r"as int\) as real\)|\) as real\) [<>]", spec), "int side not promoted"
    _typechecks(spec)
