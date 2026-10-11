"""[sql] agg_times_constant: off refuses an aggregate times or divided by a constant as before; on states it.

The meaning checks against DuckDB (random tables, NULLs, zeros, empty groups) are in test_declarative_agg_times_constant.py,
which runs with the switch on.
"""

from __future__ import annotations

import pytest

from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from tests.test_declarative_agg_times_constant import CATALOG, SCHEMA, _trusted

SHAPES = {
    "SELECT SUM(d) * 3 AS a FROM t": "SELECT expression",
    "SELECT 0.5 * SUM(d) AS b FROM t": "SELECT expression",
    "SELECT SUM(d) / 7 AS r FROM t": "division operand must be a SUM or COUNT",
    "SELECT 0.2 * AVG(i) AS m FROM t": "SELECT expression",
    "SELECT k, SUM(d) AS s FROM t GROUP BY k HAVING SUM(d) * 100 > 5": "expression operand",
    "SELECT k FROM t GROUP BY k HAVING SUM(d) > (SELECT SUM(d) * 0.05 FROM t)": "SELECT expression needs an alias",
}


@pytest.mark.parametrize("sql", SHAPES)
def test_off_refuses_the_shape_with_the_old_message(sql: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_AGG_TIMES_CONSTANT", raising=False)
    with pytest.raises(DeclarativeUnsupported, match=SHAPES[sql]):
        emit_declarative_spec(sql, SCHEMA, CATALOG)


@pytest.mark.parametrize("sql", SHAPES)
def test_on_emits_the_shape(sql: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_AGG_TIMES_CONSTANT", "1")
    spec = emit_declarative_spec(sql, SCHEMA, CATALOG)
    # No trusted item beyond what the same query without the constant already carries (the float AVG / ratio bridge).
    plain = {"/ 7": "SELECT SUM(d) / SUM(e) AS r FROM t", "0.2 * AVG": "SELECT AVG(i) AS m FROM t"}
    allowed = set().union(*(_trusted(emit_declarative_spec(q, SCHEMA, CATALOG)) for key, q in plain.items() if key in sql))
    assert _trusted(spec) <= allowed
