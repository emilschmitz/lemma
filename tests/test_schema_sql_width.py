"""The declared SQL integer width survives schema resolution on the declarative path (db_extension/verus_bridge.py).

The legacy normalization collapsed BIGINT / SMALLINT / TINYINT / HUGEINT to ``int``; with ``assumptions = false`` the declarative
spec loads ``int`` at its SQL width (i32), so a BIGINT column became an i32 cell (the loader then refused any value past 2^31).
The declarative path now keeps the type word and ``classify_sql_type`` decides; the legacy path still gets int/string.
"""

from __future__ import annotations

import re

import pytest

from db_extension import optimizer
from db_extension.verus_bridge import resolve_schema_for_sql
from declarative_spec.emit import emit_declarative_spec

SQL = "SELECT SUM(b) AS sb, SUM(i) AS si, SUM(s) AS ss FROM t WHERE b > 0"
RAW = {"t": {"b": "BIGINT", "i": "INTEGER", "s": "SMALLINT", "x": "VARCHAR"}}


@pytest.fixture
def no_assumptions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_ASSUMPTIONS", raising=False)
    monkeypatch.delenv("LEMMA_ASSUMPTION_PACKAGE", raising=False)
    monkeypatch.delenv("LEMMA_NARROW_CELLS", raising=False)


def _cell(spec: str, col: str) -> str:
    m = re.search(rf"pub {col}: Vec<([^>]+)>,", spec)
    assert m is not None, f"no field {col} in the spec"
    return m.group(1)


def test_declarative_resolution_keeps_the_type_word_and_legacy_still_collapses_it() -> None:
    assert resolve_schema_for_sql(SQL, RAW, sql_types=True) == {"t": {"b": "bigint", "i": "integer", "s": "smallint", "x": "varchar"}}
    assert resolve_schema_for_sql(SQL, RAW) == {"t": {"b": "int", "i": "int", "s": "int", "x": "string"}}
    assert resolve_schema_for_sql(SQL, {"b": "HUGEINT", "y": "TINYINT"}, sql_types=True) == {"b": "hugeint", "y": "tinyint"}


def test_bigint_is_i64_integer_i32_smallint_i16_in_the_spec_without_assumptions(no_assumptions: None) -> None:
    spec = emit_declarative_spec(SQL, resolve_schema_for_sql(SQL, RAW, sql_types=True), None)
    assert (_cell(spec, "b"), _cell(spec, "i"), _cell(spec, "s")) == ("i64", "i32", "i16")


def test_the_legacy_int_word_was_the_bug_bigint_became_i32(no_assumptions: None) -> None:
    spec = emit_declarative_spec(SQL, resolve_schema_for_sql(SQL, RAW), None)
    assert _cell(spec, "b") == "i32"  # what the declarative path used to get; kept here to show what the flag changes


@pytest.mark.parametrize("style,expected", [("declarative", "bigint"), ("imperative", "int")])
def test_run_optimization_loop_resolves_the_schema_for_its_spec_style(style: str, expected: str, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_resolve(sql, schema=None, *, catalog=None, sql_types=False):
        from db_extension.verus_bridge import resolve_schema_for_sql as real

        seen["schema"] = real(sql, schema, catalog=catalog, sql_types=sql_types)
        raise ValueError("stop after resolution")  # run_optimization_loop returns FAILED here; nothing else runs

    monkeypatch.setattr(optimizer, "_read_lemma_spec_style", lambda: style)
    monkeypatch.setattr(optimizer, "resolve_schema_for_sql", fake_resolve)
    out = optimizer.run_optimization_loop(SQL, schema=RAW)
    assert out["status"] == "FAILED" and seen["schema"]["t"]["b"] == expected


def test_run_optimization_loop_hands_the_projected_type_words_to_the_declarative_loop(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Through resolve_schema_for_sql and the projection (project_schema_for_query / project_multi_schema_for_query)."""
    seen: dict = {}

    def fake_loop(**kw):
        seen.update(kw)
        return {"status": "STOPPED"}

    import declarative_spec.drive as drive

    monkeypatch.setattr(optimizer, "_read_lemma_spec_style", lambda: "declarative")
    monkeypatch.setattr(drive, "run_declarative_optimization_loop", fake_loop)
    monkeypatch.setattr(optimizer, "lemma_research_log", lambda: False)
    # A query the legacy parser behind the projection accepts (it drops the unused column x).
    optimizer.run_optimization_loop("SELECT SUM(b) AS sb FROM t WHERE i > 0 AND s < 5", schema=RAW, use_mock=True)
    resolved = seen["resolved_schema"]
    flat = resolved.get("t", resolved)
    assert flat["b"] == "bigint" and flat["i"] == "integer" and flat["s"] == "smallint" and "x" not in flat
