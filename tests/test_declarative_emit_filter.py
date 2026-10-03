"""Tests for declarative WHERE/HAVING filter helper emission."""

from __future__ import annotations

from declarative_spec.emit_filter import filter_helpers
from declarative_spec.surface import Agg, Query


def test_where_only_emits_row_ok() -> None:
    q = Query(where_expr="(cols.qty == 7)")
    out = filter_helpers(q)
    assert "pub open spec fn row_ok(cols, i: int) -> bool" in out
    assert "cols.qty@[i] == 7" in out
    assert "group_ok" not in out


def test_where_and_having_emit_both_helpers() -> None:
    q = Query(
        where_expr="(cols.active != 0 && cols.note@ != \"\"@)",
        group_columns=["region"],
        aggs=[Agg(kind="COUNT", column=None, alias="cnt")],
        having_expr="(cnt > 2)",
    )
    out = filter_helpers(q)
    assert "pub open spec fn row_ok(cols, i: int) -> bool" in out
    assert "pub open spec fn group_ok(key: int, cnt: int) -> bool" in out
    assert "cols.active@[i] != 0" in out
    assert "cols.note@[i]@ != \"\"@" in out
    assert "cnt > 2" in out
    assert "agg_value" not in out
    assert out.index("row_ok") < out.index("group_ok")


def test_having_keeps_two_aggregate_aliases_apart() -> None:
    q = Query(
        group_columns=["tag"],
        aggs=[
            Agg(kind="SUM", column="value", alias="total"),
            Agg(kind="COUNT", column=None, alias="cnt"),
        ],
        having_expr="(total > cnt)",
    )
    out = filter_helpers(q)
    assert "group_ok(key: int, total: int, cnt: int)" in out
    assert "total > cnt" in out
