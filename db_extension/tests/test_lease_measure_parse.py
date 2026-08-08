"""Parse lease H1 stdout without running the binary."""
from __future__ import annotations

import pytest

from db_extension.agent.lease_measure import parse_h1_stdout

SAMPLE_STDOUT = """
OPEN_US: 1200
PREP_US: 340
COLD_QUERY_US: 45000
SESSION_HOT_US: 12345
QUERY_US: 12345
E2E_CACHED_RERUN_US: 46200
MATCHED_ROWS: 500000
SUM: 1260130811
EXPECT: 1260130811
SCAN_MODE: zone_map
"""


def test_parse_h1_stdout_extracts_metrics() -> None:
    meta = parse_h1_stdout(SAMPLE_STDOUT)
    assert meta["SESSION_HOT_US"] == 12345
    assert meta["PREP_US"] == 340
    assert meta["OPEN_US"] == 1200
    assert meta["COLD_QUERY_US"] == 45000
    assert meta["SUM"] == 1_260_130_811
    assert meta["SCAN_MODE"] == "zone_map"
    assert meta["PRIMARY_US"] == 12345


def test_parse_h1_stdout_requires_primary_metric() -> None:
    with pytest.raises(ValueError, match="SESSION_HOT_US"):
        parse_h1_stdout("OPEN_US: 1\n")


def test_parse_h1_stdout_query_us_fallback() -> None:
    meta = parse_h1_stdout("QUERY_US: 999\n")
    assert meta["PRIMARY_US"] == 999
