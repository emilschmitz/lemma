"""zero_copy_round.classify: every query of a round ends supported / refused (exact reason) / no_spec, never silently dropped."""

from __future__ import annotations

from pathlib import Path

import pytest

SEC_DB = Path("/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/duckdb/sec_edgar_dec.duckdb")
pytestmark = pytest.mark.skipif(not SEC_DB.exists(), reason="the SEC database is not on this machine")


def _classify(sql: str) -> dict:
    from research_loop.scripts import zero_copy_round as zr

    return zr.classify_one(sql, "sec")


def test_fixed_width_scans_are_supported():
    r = _classify("SELECT SUM(value) AS total FROM num WHERE value > 5000")
    assert r["state"] == "supported" and r["columns"] == ["value"] and r["table"] == "num"
    r = _classify("SELECT COUNT(*) AS n FROM num WHERE qtrs = 3")
    assert r["state"] == "supported" and r["columns"] == ["qtrs"]


def test_strings_and_joins_are_refused_with_the_exact_reason():
    r = _classify("SELECT COUNT(*) AS n FROM num WHERE uom = 'USD'")
    assert r["state"] == "refused" and "String" in r["reason"] and "uom" in r["reason"]
    r = _classify("SELECT n.qtrs, COUNT(*) AS c FROM num n JOIN sub s ON n.adsh = s.adsh GROUP BY n.qtrs")
    assert r["state"] == "refused" and "one input table" in r["reason"]


def test_a_query_the_emitter_cannot_spec_is_reported_as_no_spec():
    r = _classify("SELECT * FROM num WINDOW")
    assert r["state"] == "no_spec"
