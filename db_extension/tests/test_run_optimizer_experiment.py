"""Experiment-mode run_optimizer: fail loud, no mock, holdout workload."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SQL = "SELECT SUM(amount) FROM scan_skew WHERE event_date BETWEEN 19960101 AND 19961231"


@pytest.mark.skipif(
    not (ROOT / "research_loop/holdout/data/scan_skew.tbl").is_file(),
    reason="scan_skew.tbl missing",
)
def test_experiment_holdout_fails_loud_without_api_key(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "LEMMA_EXPERIMENT": "1",
            "LEMMA_WORKLOAD": "holdout",
            "MOCK_AGENT": "0",
            "LEMMA_ALLOW_DUCKDB_FALLBACK": "0",
            "LEMMA_AGENT_BACKEND": "openrouter",
        }
    )
    env.pop("OPENROUTER_API_KEY", None)
    env["OPENROUTER_API_KEY"] = ""  # block config.env setdefault from enabling a real agent
    # Avoid picking up a key from config.env via empty override if loader setdefaults
    proc = subprocess.run(
        [sys.executable, "-m", "db_extension.run_optimizer", SQL],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode != 0
    blob = proc.stdout + proc.stderr
    assert "CUSTOM_PIPELINE_FAILED" in blob or "OPENROUTER_API_KEY" in blob
    assert "lineorder_flat" not in blob or "scan_skew" in blob
    assert "Falling back to DuckDB" not in blob or "Failing loud" in blob
