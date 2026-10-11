"""A DECIMAL column compared with a float aggregate or subquery is refused (default on, no switch).

The emitter widens the stored integer of a DECIMAL (value times 10**scale) to a real, while the float side (an average) is in
natural units: the comparison was off by 10**scale. A refusal only removes a wrong answer, so it is not behind a setting.
"""

from __future__ import annotations

import pytest

from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

SCHEMA = {"t": {"d": "decimal(15,2)", "e": "decimal(10,3)", "i": "integer", "k": "integer"}}
CATALOG = CatalogAssumptions(
    max_rows=64,
    tables={"t": TableAssumptions(max_rows=64, columns={c: ColumnAssumption(max_value_exclusive=2**20) for c in "dei"})},
)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS c FROM t WHERE d > (SELECT AVG(d) FROM t)",
        "SELECT COUNT(*) AS c FROM t WHERE e < (SELECT AVG(i) FROM t)",
    ],
)
def test_a_decimal_beside_a_float_aggregate_is_refused_not_misscaled(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match="scales are not aligned"):
        emit_declarative_spec(sql, SCHEMA, CATALOG)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS c FROM t WHERE i > (SELECT AVG(i) FROM t)",
        "SELECT COUNT(*) AS c FROM t WHERE d > (SELECT SUM(d) FROM t)",
        "SELECT COUNT(*) AS c FROM t WHERE d > 1.5",
    ],
)
def test_integers_and_exact_decimal_comparisons_still_emit(sql: str) -> None:
    assert "spec fn" in emit_declarative_spec(sql, SCHEMA, CATALOG)
