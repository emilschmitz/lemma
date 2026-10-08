"""[sql] left_join_count: off refuses a LEFT JOIN count of counts as before; on states it.

The meaning checks (DuckDB on random tables with NULLs, zeros, empty groups, ties) are in test_declarative_left_count.py,
which runs with the switch on.
"""

from __future__ import annotations

import pytest

from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from tests.test_declarative_left_count import _catalog, _derived, Q13_CMP, Q13_LIKE, SCHEMA

SHAPES = {"cmp": (Q13_CMP, "JOIN ON predicate"), "like": (Q13_LIKE, "JOIN ON predicate"), "eq": (_derived(""), "derived table body")}


@pytest.mark.parametrize("name", SHAPES)
def test_off_refuses_the_shape_with_the_old_message(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_LEFT_JOIN_COUNT", raising=False)
    sql, message = SHAPES[name]
    with pytest.raises(DeclarativeUnsupported, match=message):
        emit_declarative_spec(sql, SCHEMA, _catalog())


@pytest.mark.parametrize("name", SHAPES)
def test_on_emits_the_shape_and_requires_the_unique_key(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_LEFT_JOIN_COUNT", "1")
    sql = SHAPES[name][0]
    spec = emit_declarative_spec(sql, SCHEMA, _catalog())
    assert "arbitrary()" not in spec and "assume(" not in spec and "external_body" not in spec
    assert "!(l.k@[i] == l.k@[j])" in spec  # the uniqueness the reading needs is required of the data
    with pytest.raises(DeclarativeUnsupported, match="is unique"):
        emit_declarative_spec(sql, SCHEMA, _catalog(unique=False))


def test_a_plain_left_join_is_the_same_with_the_switch_on_or_off(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = "SELECT g, COUNT(*) AS n FROM l LEFT JOIN r ON k = fk GROUP BY g"
    monkeypatch.delenv("LEMMA_LEFT_JOIN_COUNT", raising=False)
    try:
        off = emit_declarative_spec(sql, SCHEMA, _catalog())
    except DeclarativeUnsupported as exc:
        off = str(exc)
    monkeypatch.setenv("LEMMA_LEFT_JOIN_COUNT", "1")
    try:
        on = emit_declarative_spec(sql, SCHEMA, _catalog())
    except DeclarativeUnsupported as exc:
        on = str(exc)
    assert on == off
