"""The declarative draw runner uses the GenDB SEC shuffle, not a fixed template."""

from __future__ import annotations

from pathlib import Path

from research_loop.scripts.declarative_draws import (
    NUM_GENERATE,
    NUM_SELECT,
    beats_duck,
    gendb_sample_command,
)

ROOT = Path(__file__).resolve().parents[1]


def test_sample_command_is_the_overnight_gendb_shuffle():
    cmd = gendb_sample_command(
        seed=1616,
        db_path=Path("/tmp/sec_edgar_local.duckdb"),
        output=Path("/tmp/queries_1616.sql"),
    )
    assert cmd[1].endswith("holdout/gendb_sec_edgar/generate_queries.py")
    assert cmd[cmd.index("--seed") + 1] == "1616"
    assert cmd[cmd.index("--num-generate") + 1] == str(NUM_GENERATE)
    assert NUM_GENERATE == 600
    assert cmd[cmd.index("--num-select") + 1] == str(NUM_SELECT)
    assert NUM_SELECT == 6
    assert cmd[cmd.index("--db-path") + 1] == "/tmp/sec_edgar_local.duckdb"
    text = (ROOT / "research_loop" / "scripts" / "declarative_draws.py").read_text()
    assert "COUNT(*) AS {alias}" not in text


def test_beats_duck_requires_a_measured_win_and_rejects_a_tie():
    assert beats_duck({"status": "SUCCESS", "latency_us": 100, "duck_us": 250})
    assert not beats_duck({"status": "SUCCESS", "latency_us": 250, "duck_us": 250})
    assert not beats_duck({"status": "SUCCESS", "latency_us": 15, "duck_us": None})
    assert not beats_duck({"status": "FAILED", "latency_us": -1, "duck_us": 250})
