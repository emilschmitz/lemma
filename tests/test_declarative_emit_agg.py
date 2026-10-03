"""Tests for declarative aggregate condition emission."""

from __future__ import annotations

from declarative_spec.emit_agg import agg_ensures, agg_helpers
from declarative_spec.surface import Agg, Query


def test_count_star_group_by_single_column() -> None:
    query = Query(
        tables=["items"],
        group_columns=["region"],
        aggs=[Agg(kind="COUNT", column=None, alias="cnt")],
    )
    helpers = agg_helpers(query)
    ensures = agg_ensures(query)
    combined = helpers + "\n" + ensures
    assert "group_count" in helpers
    assert "row_ok(cols, i)" in helpers
    assert "decreases" in helpers
    assert "group_count" in ensures
    assert "row_ok" in combined
    assert "res.cnt as int == group_count(cols, 0, res.region)" in ensures
    assert "inserts into a map" not in combined.lower()
    assert "method_spec" not in combined
    assert "assume(" not in combined
    assert "external_body" not in combined


def test_sum_and_count_distinct_two_columns() -> None:
    query = Query(
        tables=["facts"],
        group_columns=["bucket"],
        aggs=[
            Agg(kind="SUM", column="amount", alias="total"),
            Agg(kind="COUNT_DISTINCT", column="sku", alias="distinct_sku"),
        ],
    )
    helpers = agg_helpers(query)
    ensures = agg_ensures(query)
    combined = helpers + "\n" + ensures
    assert "pub open spec fn sum_total" in helpers
    assert "pub open spec fn count_distinct_distinct_sku" in helpers
    assert "row_ok(cols, i)" in helpers
    assert "exists|j: int|" in helpers
    assert "res.total as int == sum_total(cols, 0, res.bucket)" in ensures
    assert "res.distinct_sku as int == count_distinct_distinct_sku(cols, 0, res.bucket)" in ensures
    assert "inserts into a map" not in combined.lower()
    assert ".insert(" not in combined


def test_min_is_a_bound_not_a_zero_seed() -> None:
    query = Query(
        tables=["readings"],
        group_columns=["k"],
        aggs=[Agg(kind="MIN", column="v", alias="lo")],
    )
    helpers = agg_helpers(query)
    ensures = agg_ensures(query)
    assert "forall|j: int|" in helpers
    assert "exists|j: int|" in helpers
    assert "row_ok(cols, j)" in helpers
    assert "let acc" not in helpers
    assert "min_lo(cols, 0, res.k, res.lo)" in ensures
