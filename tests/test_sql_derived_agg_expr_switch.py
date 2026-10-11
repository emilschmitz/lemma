"""[sql] derived_agg_expr: off refuses a CASE aggregate over a derived table as before; on inlines it.

The meaning checks (DuckDB on random tables with zeros, negatives, unmatched join keys) are in
test_declarative_derived_case.py, which runs with the switch on.
"""

from __future__ import annotations

import pytest

from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from tests.test_declarative_derived_case import CATALOG, REUSED, SCHEMA
from tests.test_declarative_derived_case import RATIO as RATIO_SQL


@pytest.mark.parametrize("sql", [RATIO_SQL, REUSED])
def test_off_refuses_a_case_aggregate_over_a_derived_table(sql: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_DERIVED_AGG_EXPR", raising=False)
    with pytest.raises(DeclarativeUnsupported, match="aggregate expression over a derived table"):
        emit_declarative_spec(sql, SCHEMA, CATALOG)


@pytest.mark.parametrize("sql", [RATIO_SQL, REUSED])
def test_on_emits_it(sql: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_DERIVED_AGG_EXPR", "1")
    assert "spec fn" in emit_declarative_spec(sql, SCHEMA, CATALOG)


def test_a_plain_column_aggregate_over_a_derived_table_needs_no_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_DERIVED_AGG_EXPR", raising=False)
    sql = "SELECT g, SUM(q) AS sq FROM (SELECT tag AS g, v AS q FROM fact WHERE w <> 0) AS t GROUP BY g"
    assert "spec fn" in emit_declarative_spec(sql, SCHEMA, CATALOG)


def test_an_ambiguous_derived_output_is_refused_with_the_switch_off_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_DERIVED_AGG_EXPR", raising=False)
    sql = "SELECT SUM(q) AS s FROM (SELECT v AS q, w AS q FROM fact) AS t"
    with pytest.raises(DeclarativeUnsupported, match="ambiguous"):
        emit_declarative_spec(sql, SCHEMA, CATALOG)
