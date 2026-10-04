"""The declarative judge decodes NULL and DECIMAL output cells (false-positive `hole` and crash found by the round-5 adversary)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from research_loop.adversary.judge_declarative import _decode, _out_scales, _parse_rows

SPEC = """
// OUT_SCALES: 4,0
pub struct OutRow {
    pub lo: Option<i128>,
    pub c: u64,
}
"""
SPEC_NO_SCALE = "pub struct OutRow {\n    pub lo: Option<i64>,\n    pub c: u64,\n}\n"


def _line(*cells: str) -> str:
    return "ROW\x1f" + "\x1f".join(cells)


def test_a_scaled_decimal_cell_becomes_the_decimal_duckdb_returns() -> None:
    rows, why = _parse_rows(_line("5001", "2") + "\n", SPEC)
    assert why is None and rows == [(Decimal("0.5001"), 2)]
    rows, _ = _parse_rows(_line("-12", "1") + "\n", SPEC)
    assert rows == [(Decimal("-0.0012"), 1)]


def test_null_option_cell_decodes_to_none_not_a_crash() -> None:
    rows, why = _parse_rows(_line("NULL", "0") + "\n", SPEC)
    assert why is None and rows == [(None, 0)]
    rows, _ = _parse_rows(_line("NULL", "0") + "\n", SPEC_NO_SCALE)
    assert rows == [(None, 0)]


def test_unscaled_spec_keeps_plain_integers_and_scales_length_is_checked() -> None:
    assert _parse_rows(_line("7", "3") + "\n", SPEC_NO_SCALE)[0] == [(7, 3)]
    assert _out_scales(SPEC_NO_SCALE, 2) == [0, 0]
    with pytest.raises(ValueError, match="OUT_SCALES has 2 entries, OutRow has 3"):
        _out_scales(SPEC, 3)


def test_decode_option_string_and_f64() -> None:
    assert _decode("NULL", "Option<String>") is None
    assert _decode("6162", "Option<String>") == "ab"
    assert _decode("1.5", "f64") == 1.5


def test_report_with_a_decimal_serializes() -> None:
    assert json.loads(json.dumps({"duck_rows": [[Decimal("0.5001")]]}, default=str)) == {"duck_rows": [["0.5001"]]}


def test_candidate_helpers_key_is_optional_and_checked(tmp_path) -> None:
    from research_loop.adversary.candidate import load_candidate

    base = {"sql": "SELECT 1", "schema": {}, "rows": {}, "run_query_body": "    Vec::new()"}
    f = tmp_path / "c.json"
    f.write_text(json.dumps(base))
    assert load_candidate(f).helpers == ""
    f.write_text(json.dumps({**base, "helpers": "proof fn p() { }"}))
    assert load_candidate(f).helpers == "proof fn p() { }"
    f.write_text(json.dumps({**base, "helpers": "#[verifier::external_body] proof fn p() { }"}))
    with pytest.raises(ValueError, match="forbidden token"):
        load_candidate(f)
    f.write_text(json.dumps({**base, "helpers": 3}))
    with pytest.raises(TypeError, match="helpers must be a string"):
        load_candidate(f)
