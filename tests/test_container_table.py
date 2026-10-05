"""The container run table: tie/loss/win rule and missing results."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_loop.scripts.container_table import row, verdict


@pytest.mark.parametrize(("x", "v"), [(None, "no timing"), (0.5, "LOSS"), (0.79, "LOSS"), (0.8, "TIE"), (1.0, "TIE"), (1.25, "TIE"), (1.26, "WIN"), (5.0, "WIN")])
def test_tie_band_is_25_percent(x: float | None, v: str) -> None:
    assert verdict(x) == v


def _log(tmp_path: Path, rec: dict | None) -> Path:
    p = tmp_path / "x.log"
    p.write_text("noise\n" + ("" if rec is None else "RESULT " + json.dumps(rec) + "\n"))
    return p


def test_a_result_line_becomes_a_row_with_the_x_factor(tmp_path: Path) -> None:
    r = row(_log(tmp_path, {"sql": "q", "model": "m", "status": "SUCCESS", "threads_used": True, "latency_us": 1000, "duck_us": 4000, "egress_hosts": ["api.anthropic.com"]}))
    assert r["x_factor"] == 4.0 and r["verdict"] == "WIN" and r["threads_used"] is True


def test_a_failed_or_missing_run_has_no_timing(tmp_path: Path) -> None:
    failed = row(_log(tmp_path, {"status": "FAILED", "latency_us": -1, "duck_us": 500, "error": "below the speed bar"}))
    assert failed["x_factor"] is None and failed["verdict"] == "no timing"
    assert "NO RESULT LINE" in row(_log(tmp_path, None))["status"]
