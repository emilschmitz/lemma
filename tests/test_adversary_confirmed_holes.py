"""Confirmed holes: a body Verus accepts, executed, disagrees with DuckDB.

Skips when Verus is not on the machine. The fixtures are the candidate JSON
the host judge accepts; the test does not trust a handwritten result.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_loop.adversary.candidate import load_candidate
from research_loop.adversary.judge import judge_candidate
from research_loop.harness import resolve_verus_bin

_FIXTURES = Path(__file__).resolve().parent / "fixtures"

pytestmark = pytest.mark.skipif(resolve_verus_bin() is None, reason="verus not found")


@pytest.mark.parametrize(
    "name",
    ["adversary_empty_sum.json", "adversary_u64_wrap_sum.json"],
)
def test_fixture_is_a_significant_hole(name: str) -> None:
    report = judge_candidate(
        load_candidate(_FIXTURES / name),
        config="hardware",
        verify=True,
    )
    assert report["status"] == "hole"
    assert report["significant"] is True
    assert report["proof_verified"] is True
