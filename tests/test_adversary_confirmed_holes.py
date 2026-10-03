"""Old SUM attacks do not prove against the hardware Option<u128> spec."""

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
def test_hardware_sum_attack_does_not_prove(name: str) -> None:
    report = judge_candidate(
        load_candidate(_FIXTURES / name),
        config="hardware",
        verify=True,
    )
    assert report["significant"] is False
    assert report["status"] == "impl_does_not_fit_spec"
