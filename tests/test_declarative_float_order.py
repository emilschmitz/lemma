"""The emitter refuses float ordering, equality, MIN and MAX (no proved bridge from f64 to real)."""

from __future__ import annotations

import pytest

from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

SCHEMA = {"t": {"k": "integer", "v": "double"}, "u": {"k": "integer", "w": "integer"}}
CATALOG = CatalogAssumptions(
    max_rows=100, tables={"t": TableAssumptions(max_rows=100, columns={"v": ColumnAssumption(max_value_exclusive=2**20)}), "u": TableAssumptions(max_rows=100)}
)
REASON = "float comparison has no proved bridge to reals"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT k, COUNT(*) AS c FROM t WHERE v > 0 GROUP BY k",
        "SELECT k, SUM(v) AS s FROM t GROUP BY k HAVING SUM(v) > 10",
        "SELECT k, MAX(v) AS m FROM t GROUP BY k",
        "SELECT k, MIN(t.v) AS m FROM t GROUP BY k",
        "SELECT k, SUM(v) AS s FROM t GROUP BY k ORDER BY s DESC LIMIT 5",
        "SELECT k, SUM(CASE WHEN v < 1.5 THEN 1 ELSE 0 END) AS c FROM t GROUP BY k",
        "SELECT x.k, COUNT(*) AS c FROM t x JOIN u ON x.k = u.k WHERE x.v BETWEEN 1 AND 2 GROUP BY x.k",
    ],
)
def test_float_ordering_forms_are_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match=REASON):
        emit_declarative_spec(sql, SCHEMA, CATALOG, float_abs_eps="1e-6")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT k, SUM(v) AS s FROM t WHERE v IS NOT NULL GROUP BY k",
        "SELECT k, COUNT(*) AS c FROM t WHERE k > 1 GROUP BY k ORDER BY c DESC LIMIT 3",
        "SELECT k, COUNT(v) AS c FROM t GROUP BY k HAVING COUNT(v) > 1",
        "SELECT u.k, COUNT(*) AS c FROM t JOIN u ON t.k = u.k WHERE u.w > 2 GROUP BY u.k",
    ],
)
def test_sum_count_and_integer_ordering_are_not_refused(sql: str) -> None:
    emit_declarative_spec(sql, SCHEMA, CATALOG, float_abs_eps="1e-6")
