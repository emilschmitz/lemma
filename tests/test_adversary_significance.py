from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_loop.admit_runquery import admit_runquery_body
from research_loop.adversary.candidate import load_candidate
from research_loop.adversary.judge import _parse_printed_result
from research_loop.adversary.significance import (
    classify_difference,
    sql_demands_order,
)


def test_order_swap_without_order_by_not_significant() -> None:
    sql = "SELECT a, b FROM t"
    v = classify_difference(sql, [(1, 2), (3, 4)], [(3, 4), (1, 2)])
    assert not v.significant
    assert v.reason == "same_multiset"


def test_order_swap_with_order_by_significant() -> None:
    sql = "SELECT a, b FROM t ORDER BY a"
    v = classify_difference(sql, [(1, 2), (3, 4)], [(3, 4), (1, 2)])
    assert v.significant
    assert v.reason == "order"


def test_order_by_inside_string_not_demanded() -> None:
    sql = "SELECT a FROM t WHERE b = 'ORDER BY x'"
    assert not sql_demands_order(sql)


_FULL = [(1,), (2,), (3,)]


def test_limit_without_order_any_subset_of_right_size_is_fine() -> None:
    v = classify_difference("SELECT a FROM t LIMIT 2", [(3,), (1,)], [(1,), (2,)], unlimited=_FULL)
    assert not v.significant
    assert v.reason == "limit_without_order"


def test_limit_without_order_wrong_row_count_is_significant() -> None:
    v = classify_difference("SELECT a FROM t LIMIT 2", [(1,)], [(1,), (2,)], unlimited=_FULL)
    assert v.significant
    assert v.reason == "limit_row_count"


def test_limit_without_order_row_outside_result_is_significant() -> None:
    v = classify_difference("SELECT a FROM t LIMIT 2", [(1,), (9,)], [(1,), (2,)], unlimited=_FULL)
    assert v.significant
    assert v.reason == "limit_rows_not_in_result"


def test_limit_without_order_duplicate_beyond_multiplicity_is_significant() -> None:
    v = classify_difference("SELECT a FROM t LIMIT 2", [(1,), (1,)], [(1,), (2,)], unlimited=_FULL)
    assert v.significant


def test_limit_larger_than_table_expects_every_row() -> None:
    sql = "SELECT a FROM t LIMIT 10"
    assert not classify_difference(sql, [(2,), (1,), (3,)], _FULL, unlimited=_FULL).significant
    assert classify_difference(sql, [(1,), (2,)], _FULL, unlimited=_FULL).significant


def test_limit_offset_without_order_expects_n_minus_offset() -> None:
    sql = "SELECT a FROM t LIMIT 5 OFFSET 2"
    assert not classify_difference(sql, [(3,)], [(3,)], unlimited=_FULL).significant
    assert classify_difference(sql, [(3,), (2,)], [(3,)], unlimited=_FULL).significant


def test_unlimited_sql_drops_limit_and_offset() -> None:
    from research_loop.adversary.significance import unlimited_sql

    assert "LIMIT" not in unlimited_sql("SELECT a FROM t WHERE a > 1 LIMIT 3 OFFSET 1").upper()


def test_empty_sum_zero_vs_null_significant() -> None:
    sql = "SELECT SUM(a) FROM t"
    v = classify_difference(sql, [(0,)], [(None,)])
    assert v.significant
    assert v.reason == "multiset"


def test_u64_wrap_significant() -> None:
    sql = "SELECT SUM(a) FROM t"
    v = classify_difference(sql, [(0,)], [(2**64,)])
    assert v.significant
    assert v.reason == "multiset"


def test_identical_multiset_different_order_not_significant() -> None:
    sql = "SELECT x FROM t"
    v = classify_difference(sql, [(1,), (2,)], [(2,), (1,)])
    assert not v.significant


def test_error_vs_value_significant() -> None:
    v = classify_difference("SELECT 1", None, [(1,)], impl_error="boom")
    assert v.significant
    assert v.reason == "error_vs_value"


def test_printed_none_matches_sql_null() -> None:
    row, err = _parse_printed_result("RESULT: none\n")
    assert err is None
    assert row == (None,)
    verdict = classify_difference("SELECT SUM(a) FROM t", [row], [(None,)])
    assert not verdict.significant


def test_printed_some_matches_wide_integer() -> None:
    row, err = _parse_printed_result("RESULT: some 18446744073709551616\n")
    assert err is None
    assert row == (2**64,)
    verdict = classify_difference("SELECT SUM(a) FROM t", [row], [(2**64,)])
    assert not verdict.significant
    wrapped = classify_difference("SELECT SUM(a) FROM t", [(0,)], [(2**64,)])
    assert wrapped.significant


def test_both_errors_not_significant() -> None:
    v = classify_difference(
        "SELECT 1", None, None, impl_error="a", duck_error="b"
    )
    assert not v.significant
    assert v.reason == "both_error"


def test_candidate_rejects_extra_key(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps(
            {
                "sql": "SELECT 1",
                "schema": {"a": "INTEGER"},
                "rows": {"t": []},
                "run_query_body": "0u64",
                "extra": True,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unexpected JSON keys"):
        load_candidate(p)


@pytest.mark.parametrize(
    "body",
    [
        "#[verifier::external_body]\n0u64",
        "assume(false);\n0u64",
        "arbitrary()\n",
        "unimplemented!()",
    ],
)
def test_candidate_rejects_forbidden_body(tmp_path: Path, body: str) -> None:
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps(
            {
                "sql": "SELECT 1",
                "schema": {"a": "INTEGER"},
                "rows": {"t": []},
                "run_query_body": body,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_candidate(p)


def test_admit_also_rejects_external_body() -> None:
    res = admit_runquery_body("#[verifier::external_body]\n0u64")
    assert not res.ok


def test_shell_wraps_interior_as_run_query() -> None:
    from research_loop.adversary.judge import shell_run_query

    text = shell_run_query("let mut res: u64 = 0;\nres\n", "u64", None)
    assert "pub exec fn run_query" in text
    assert "ensures res ==" in text
    assert "let mut res: u64 = 0;" in text
    assert "fn helper" not in text
