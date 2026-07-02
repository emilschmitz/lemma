"""Tests for RunQuery body assembly."""
import pytest

from research_loop.assemble_runquery import (
    assemble_runquery_from_body,
    extract_runquery_body_text,
    validate_runquery_body,
)

SPEC = """
datatype Row = Row(x: bv32)
function MethodSpec(data: seq<Row>): int { 0 }
"""


def test_extract_braced_body():
    assert "var i := 0" in extract_runquery_body_text("{ var i := 0; }")


def test_reject_method_in_body():
    errs = validate_runquery_body("method Evil() {}\n")
    assert errs and any("method" in e for e in errs)


def test_assemble_inserts_trusted_ensures():
    body = "{ res := 0; var i := |data|; while i > 0 { i := i - 1; } }"
    out = assemble_runquery_from_body(SPEC, body)
    assert "ensures res == MethodSpec(data)" in out
    assert "method Evil" not in out


def test_assemble_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        assemble_runquery_from_body(SPEC, "{}")
