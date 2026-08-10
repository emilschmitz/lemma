"""Tests for shared column expression / WHERE spec helpers."""

from __future__ import annotations

from verus_transpiler.col_exprs import spec_where_cond


def test_spec_where_cond_table_scoped_getter_lit_at() -> None:
    schema = {"uom": "string", "tag": "string"}
    cond = 'num.get_uom(k) == "USD" && num.get_tag(k) != "X"'
    out = spec_where_cond(cond, "k", schema)
    assert out == 'num.get_uom(k) == "USD"@ && num.get_tag(k) != "X"@'
