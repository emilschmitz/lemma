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


# ---- adversary findings (cte_reuse on) ----------------------------------------------------------------------------------

from tests.test_declarative_cte import REVENUE  # noqa: E402


@pytest.mark.parametrize(
    "sql",
    [
        # F1: the WHERE of the scalar subquery would be dropped
        REVENUE + "SELECT COUNT(*) AS n FROM li WHERE price = (SELECT MAX(total) FROM rev WHERE sno > 100)",
        # F2: MAX over zero groups is NULL in SQL, the spec's value is 0: only the folded grouped-WITH shape is exact
        REVENUE + "SELECT COUNT(*) AS n FROM li WHERE price = (SELECT MAX(total) FROM rev)",
        REVENUE + "SELECT COUNT(*) AS n FROM li WHERE price > (SELECT MIN(total) FROM rev)",
    ],
)
def test_max_min_over_with_groups_is_refused_outside_the_exact_shape(sql: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_CTE_REUSE", "1")
    with pytest.raises(DeclarativeUnsupported, match="MAX/MIN over the groups"):
        emit_declarative_spec(sql, SCHEMA, _catalog(True))


def test_the_folded_shape_with_a_filtered_scalar_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_CTE_REUSE", "1")
    sql = REVENUE + "SELECT skey, sname, total FROM sup, rev WHERE skey = sno AND total = (SELECT MAX(total) FROM rev WHERE sno > 100)"
    with pytest.raises(DeclarativeUnsupported, match="MAX/MIN over the groups"):
        emit_declarative_spec(sql, SCHEMA, _catalog(True))


def test_the_fold_states_the_unique_key_in_valid_cols(monkeypatch: pytest.MonkeyPatch) -> None:
    """F4: the loader must check what the fold relies on."""
    monkeypatch.setenv("LEMMA_CTE_REUSE", "1")
    spec = emit_declarative_spec(Q15_SHAPE, SCHEMA, _catalog(True))
    valid_sup = spec.split("pub open spec fn valid_cols_sup(")[1].split("pub open spec fn")[0]
    assert "!(sup.skey@[i] == sup.skey@[j])" in valid_sup or "skey@[i] != " in valid_sup or "skey@[j]" in valid_sup


def test_the_inner_table_of_the_with_body_may_not_share_the_base_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    """F5: `t` joined to a WITH body over `t` would give two parameters of one name."""
    monkeypatch.setenv("LEMMA_CTE_REUSE", "1")
    schema = {"t": {"k": "bigint", "id": "bigint", "x": "bigint"}}
    sql = (
        "WITH c AS (SELECT k AS g, SUM(x) AS s FROM t GROUP BY g) "
        "SELECT t.k, t.id, s FROM t, c WHERE t.k = g AND s > (SELECT MAX(s) FROM c)"
    )
    with pytest.raises(DeclarativeUnsupported):
        emit_declarative_spec(sql, schema, None)
