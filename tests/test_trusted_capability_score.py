"""Unit tests for host-side Trusted capability scorer."""

from __future__ import annotations

from pathlib import Path

from research_loop.scripts.trusted_capability_score import (
    fold_has_arbitrary,
    guess_capability,
    score_query,
    summarize,
)
from tests.test_sec_holdout_parse import SEC_SCHEMA

ROOT = Path(__file__).resolve().parents[1]

_SIMPLE = """SELECT stmt, COUNT(*) AS cnt
FROM pre
WHERE stmt IS NOT NULL
GROUP BY stmt;"""

Q1_LIKE = """SELECT stmt, rfile, COUNT(*) AS cnt,
       COUNT(DISTINCT adsh) AS num_filings,
       AVG(line) AS avg_line_num
FROM pre
WHERE stmt IS NOT NULL
GROUP BY stmt, rfile"""


def test_guess_capability_ready_for_simple_map() -> None:
    assert (
        guess_capability(
            shell_ok=True,
            shell_status="ok_shell",
            fold_arbitrary=False,
            has_agg_step=False,
            sql_has_count_distinct=False,
            sql_is_multi_agg=False,
            sql_is_scalar=False,
            sql_is_simple_map=True,
        )
        == "ready"
    )


def test_guess_capability_needs_trusted_for_multi_agg_without_step() -> None:
    assert (
        guess_capability(
            shell_ok=True,
            shell_status="ok_shell",
            fold_arbitrary=False,
            has_agg_step=False,
            sql_has_count_distinct=True,
            sql_is_multi_agg=True,
            sql_is_scalar=False,
            sql_is_simple_map=False,
        )
        == "needs_trusted"
    )


def test_score_simple_sec_query() -> None:
    result = score_query(
        source="fixture",
        qid="t_simple",
        sql=_SIMPLE,
        schema=SEC_SCHEMA,
    )
    assert result.shell_ok
    assert result.capability_guess == "ready"
    assert not result.fold_arbitrary


def test_score_q1_like_has_agg_step() -> None:
    result = score_query(
        source="fixture",
        qid="t_q1",
        sql=Q1_LIKE,
        schema=SEC_SCHEMA,
    )
    assert result.shell_ok
    assert result.has_agg_step
    assert result.has_distinct_set
    assert not result.fold_arbitrary
    assert result.capability_guess == "ready"


def test_summarize_counts() -> None:
    r1 = score_query(source="f", qid="a", sql=_SIMPLE, schema=SEC_SCHEMA)
    summary = summarize([r1])
    assert summary["total"] == 1
    assert summary["capability_guess"]["ready"] == 1


def test_fold_has_arbitrary_detects_fake_fold() -> None:
    fake = """
pub open spec fn method_spec_helper(cols: &Cols, i: int) -> Map<Seq<char>, u64>
    decreases i,
{
    arbitrary()
}
"""
    assert fold_has_arbitrary(fake)
