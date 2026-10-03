"""Hardware refuses signed arithmetic and does not treat empty string as NULL."""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError
from verus_transpiler.transpiler import transpile_sql_to_verus

from research_loop.adversary.candidate import Candidate
from research_loop.adversary.judge import judge_candidate

_SCHEMA = {"t": {"a": "BIGINT", "b": "BIGINT", "s": "VARCHAR"}}


def test_product_string_null_is_empty_and_hardware_null_is_false(monkeypatch) -> None:
    sql = "SELECT COUNT(*) FROM t WHERE s IS NULL"
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = transpile_sql_to_verus(sql, _SCHEMA)
    assert '== ""@' in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    hardware = transpile_sql_to_verus(sql, _SCHEMA)
    assert '== ""@' not in hardware
    assert "if false" in hardware


def test_hardware_string_not_null_is_true(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    src = transpile_sql_to_verus("SELECT COUNT(*) FROM t WHERE s IS NOT NULL", _SCHEMA)
    assert "if true" in src
    assert '!= ""@' not in src


def test_hardware_refuses_negation_and_subtraction(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="subtraction or negation"):
        transpile_sql_to_verus("SELECT SUM(-a) FROM t", _SCHEMA)
    with pytest.raises(UnsupportedContractError, match="subtraction or negation"):
        transpile_sql_to_verus("SELECT SUM(a - b) FROM t", _SCHEMA)


def test_product_still_emits_negation_and_hardware_keeps_addition(monkeypatch) -> None:
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = transpile_sql_to_verus("SELECT SUM(-a) FROM t", _SCHEMA)
    assert "-(cols.get_a" in product or "-(" in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    added = transpile_sql_to_verus("SELECT SUM(a + b) FROM t", _SCHEMA)
    assert "Option<u128>" in added


def test_sql_null_cell_is_outside_the_column_model() -> None:
    candidate = Candidate(
        sql="SELECT COUNT(*) FROM t",
        schema=_SCHEMA,
        rows={"t": [{"a": 1, "b": 1, "s": None}]},
        run_query_body="let mut res: u64 = 0; res",
    )
    report = judge_candidate(candidate, config="hardware", verify=False)
    assert report["significant"] is False
    assert report["status"] == "rows_outside_model"


def test_empty_string_cell_is_still_scored() -> None:
    candidate = Candidate(
        sql="SELECT COUNT(*) FROM t WHERE s IS NULL",
        schema={"s": "VARCHAR"},
        rows={"t": [{"s": ""}]},
        run_query_body="let mut res: u64 = 0; res",
    )
    report = judge_candidate(candidate, config="hardware", verify=False)
    assert report["status"] == "unchecked_exec"
    assert report["duck_rows"] == [(0,)]
