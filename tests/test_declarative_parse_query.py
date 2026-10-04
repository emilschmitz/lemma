"""Tests for declarative_spec.parse_query."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

# Avoid declarative_spec/__init__.py (may import emit under development).
if "declarative_spec" not in sys.modules:
    _pkg = types.ModuleType("declarative_spec")
    _pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "declarative_spec")]
    sys.modules["declarative_spec"] = _pkg

from declarative_spec.literals import string_token
from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.parse_query import parse_query
from declarative_spec.surface import Query


def test_multi_agg_group_having_order_limit() -> None:
    sql = """
    SELECT region, tier, COUNT(*) AS cnt, SUM(qty) AS total
    FROM orders
    WHERE region > 5 AND status = 'active'
    GROUP BY region, tier
    HAVING cnt > 10
    ORDER BY region DESC, cnt
    LIMIT 100
    """
    q = parse_query(sql)
    assert q.tables == ["orders"]
    assert q.group_columns == ["region", "tier"]
    assert len(q.aggs) == 2
    kinds = {a.kind for a in q.aggs}
    assert kinds == {"COUNT", "SUM"}
    aliases = {a.alias for a in q.aggs}
    assert "cnt" in aliases and "total" in aliases
    assert "region" in q.where_expr
    assert "5" in q.where_expr
    assert "&&" in q.where_expr
    assert string_token("active") in q.where_expr
    assert q.having_expr
    assert "cnt" in q.having_expr
    assert q.limit == 100
    assert len(q.order_by) == 2
    assert q.order_by[0].column == "region"
    assert q.order_by[0].descending is True
    assert q.order_by[1].column == "cnt"


def test_join_with_exists_subquery() -> None:
    sql = """
    SELECT t.a, COUNT(*) AS c
    FROM t
    JOIN u ON t.k = u.k
    WHERE EXISTS (SELECT 1 FROM v WHERE v.x = t.a)
    GROUP BY t.a
    """
    q = parse_query(sql)
    assert q.tables == ["t", "u"]
    assert len(q.joins) == 1
    join = q.joins[0]
    assert join.kind == "inner"
    assert join.table == "u"
    assert join.on == (("t.k", "u.k"),)
    assert len(q.exists) == 1
    name, nested, negated = q.exists[0]
    assert negated is False
    assert name in q.where_expr
    assert isinstance(nested, Query)
    assert nested.tables == ["v"]
    assert "v.x" in nested.where_expr or "t.a" in nested.where_expr


def test_union_sets_set_op() -> None:
    sql = "SELECT a FROM t1 UNION SELECT a FROM t2"
    q = parse_query(sql)
    assert q.set_op == "union"
    assert q.set_query is not None
    assert q.tables == ["t1"]
    assert q.set_query.tables == ["t2"]
    assert q.projection == ["a"] or "a" in q.projection


def test_having_sum_compared_to_scalar_subquery() -> None:
    sql = """
    SELECT name, SUM(value) AS total
    FROM facts
    GROUP BY name
    HAVING SUM(value) > (SELECT AVG(value) FROM facts)
    """
    q = parse_query(sql)
    assert q.scalar_subqueries
    assert "total" in q.having_expr
    assert q.scalar_subqueries[0][0] in q.having_expr


def test_case_sum_and_count_distinct_having() -> None:
    sql = """
    SELECT tag, SUM(CASE WHEN value > 0 THEN 1 ELSE 0 END) AS positive_count,
           COUNT(DISTINCT adsh) AS num_filings
    FROM facts
    GROUP BY tag
    HAVING COUNT(DISTINCT adsh) >= 2
    """
    q = parse_query(sql)
    summed = next(a for a in q.aggs if a.alias == "positive_count")
    assert "if " in summed.expr
    assert "cols.value@[i]" in summed.expr
    assert "num_filings" in q.having_expr


def test_similar_to_raises_specific_clause() -> None:
    with pytest.raises(DeclarativeUnsupported, match="SIMILAR TO"):
        parse_query("SELECT x FROM t WHERE x SIMILAR TO 'a%'")
