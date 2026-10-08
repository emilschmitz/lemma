"""[sql] cte_reuse: off refuses a reused WITH name, MAX/MIN over derived groups and GROUP BY a select alias as before; on states them.

The meaning checks (DuckDB on random tables) are in test_declarative_cte.py, which runs with the switch on.
"""

from __future__ import annotations

import pytest

from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from tests.test_declarative_cte import _catalog, Q15_SHAPE, SCHEMA, TWICE

GROUP_BY_ALIAS = "SELECT supp AS s, SUM(price) AS t FROM li GROUP BY s"
SHAPES = {
    "q15": (Q15_SHAPE, "a WITH name used inside a subquery"),
    "twice": (TWICE, "derived table shape"),
    "group_by_alias": (GROUP_BY_ALIAS, "unknown column"),
}


@pytest.mark.parametrize("name", SHAPES)
def test_off_refuses_the_shape(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_CTE_REUSE", raising=False)
    sql, message = SHAPES[name]
    with pytest.raises(Exception) as err:
        emit_declarative_spec(sql, SCHEMA, _catalog(True))
    assert not isinstance(err.value, AssertionError)
    if message:
        assert isinstance(err.value, DeclarativeUnsupported) and message in str(err.value)


@pytest.mark.parametrize("name", SHAPES)
def test_on_emits_the_shape(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_CTE_REUSE", "1")
    spec = emit_declarative_spec(SHAPES[name][0], SCHEMA, _catalog(True))
    assert "arbitrary()" not in spec and "assume(" not in spec and "external_body" not in spec


def test_a_query_without_a_with_name_is_the_same_with_the_switch_on_or_off(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = "SELECT supp, SUM(price) AS t FROM li WHERE disc > 0 GROUP BY supp"
    monkeypatch.delenv("LEMMA_CTE_REUSE", raising=False)
    off = emit_declarative_spec(sql, SCHEMA, _catalog(True))
    monkeypatch.setenv("LEMMA_CTE_REUSE", "1")
    assert emit_declarative_spec(sql, SCHEMA, _catalog(True)) == off
