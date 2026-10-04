"""The hard-shape worked examples inlined in the prompt are real proofs (Verus, memory-guarded)."""

from __future__ import annotations

from pathlib import Path

import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.pipeline import VERUS_CANDIDATES, verify_assembled
from declarative_spec.prompt import _FIXTURES
from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
from research_loop.assumption_packages import assumption_package
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema

HARD = _FIXTURES / "hard"

CASES = {
    "string_tuple_count_distinct_sorted.rs": (
        "SELECT stmt, rfile, COUNT(*) AS cnt, COUNT(DISTINCT adsh) AS num_filings FROM pre "
        "WHERE stmt IS NOT NULL GROUP BY stmt, rfile ORDER BY cnt DESC"
    ),
}
# Fixtures that live next to the other worked examples (not under hard/), on the SEC DECIMAL variant.
TOP = {
    "ungrouped_minmax_string_filter.rs": (
        "SELECT MIN(ddate) AS lo, MAX(ddate) AS hi FROM num WHERE uom = 'pure' AND qtrs = 3"
    ),
}


def _verify(name: str, monkeypatch: pytest.MonkeyPatch, mutate: tuple[str, str] | None = None) -> tuple[bool, str]:
    if not any(c.is_file() for c in VERUS_CANDIDATES):
        pytest.skip("verus binary not installed")
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"))
    text = ((HARD if name in CASES else _FIXTURES) / name).read_text()
    if mutate is not None:
        assert mutate[0] in text
        text = text.replace(*mutate, 1)
    sql = {**CASES, **TOP}[name]
    spec = emit_declarative_spec(sql, load_sec_schema(), assumption_package("sec_margin"), float_abs_eps="1e20")
    program = assemble_declarative_program(spec, extract_agent_edit(text), helpers=extract_agent_helpers(text))
    return verify_assembled(program, timeout_sec=600)


@pytest.mark.parametrize("name", sorted({**CASES, **TOP}))
def test_hard_fixture_verifies(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = _verify(name, monkeypatch)
    assert ok and "0 errors" in out, out[-2000:]


def test_a_broken_sorted_insert_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = _verify("string_tuple_count_distinct_sorted.rs", monkeypatch, ("out.insert(p, row);", "out.insert(0, row);"))
    assert not ok and "error" in out


def test_a_wrong_string_comparison_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = _verify("ungrouped_minmax_string_filter.rs", monkeypatch, ("let hit = q == 3 && num.uom[i] == pure;", "let hit = q == 3 && num.uom[i] != pure;"))
    assert not ok and "error" in out
