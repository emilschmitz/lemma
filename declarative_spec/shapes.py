"""Shape classes of the declarative emitter and what is known about proving them.

Everything the emitter emits should be provable. A shape class is one SQL feature the surface parser
records on a ``Query`` (``query_features``); a query's classes are its features. Each class has a status:

* ``witnessed``   a verified reference body exists (``witness`` names the fixture under ``tests/fixtures``);
* ``unwitnessed`` the emitter emits it and no verified body is known yet (unknown, not impossible);
* ``impossible``  no body can satisfy the emitted spec (Verus-confirmed ``reason``): the emitter refuses it.

``check_shapes`` raises ``DeclarativeUnsupported`` for an impossible class. A class without an entry is a
bug the shapes test reports (every class the coverage samples emit must be registered).
"""

from __future__ import annotations

from dataclasses import dataclass

from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.surface import Query

WITNESSED = "witnessed"
UNWITNESSED = "unwitnessed"
IMPOSSIBLE = "impossible"

_PROOFS = "tests/fixtures/declarative_proofs/"
_ADV = "tests/fixtures/adversary_declarative/"


@dataclass(frozen=True)
class Shape:
    status: str
    witness: str = ""  # fixture path relative to the repo root (witnessed)
    reason: str = ""  # Verus-confirmed error (impossible)


REGISTRY: dict[str, Shape] = {
    # row sources
    "scan": Shape(WITNESSED, _PROOFS + "group_count_where.rs"),
    "join_inner": Shape(WITNESSED, _PROOFS + "join_group_sum.rs"),
    "join_self": Shape(WITNESSED, _PROOFS + "self_join_count.rs"),
    "join_or_on": Shape(UNWITNESSED),
    "join_outer": Shape(UNWITNESSED),
    "derived": Shape(UNWITNESSED),
    "cte": Shape(UNWITNESSED),
    # filters
    "where": Shape(WITNESSED, _PROOFS + "group_count_where.rs"),
    "like": Shape(WITNESSED, _PROOFS + "tpch_q14_promo_ratio.rs"),
    "exists": Shape(UNWITNESSED),
    "not_exists": Shape(UNWITNESSED),
    "in_subquery": Shape(UNWITNESSED),
    "scalar_subquery": Shape(WITNESSED, _PROOFS + "hard/dict_having_scalar_subquery.rs"),
    # grouping
    "group_by": Shape(WITNESSED, _PROOFS + "int_group_count.rs"),
    "group_by_multi": Shape(WITNESSED, _PROOFS + "hard/two_key.rs"),
    "group_by_string": Shape(WITNESSED, _PROOFS + "string_group_count.rs"),
    "group_by_alias": Shape(UNWITNESSED),
    "having": Shape(WITNESSED, _PROOFS + "hard/dict_having_scalar_subquery.rs"),
    "having_min_max": Shape(UNWITNESSED),
    # aggregates
    "global_agg": Shape(WITNESSED, _PROOFS + "ungrouped_sum_where.rs"),
    "count_star": Shape(WITNESSED, _PROOFS + "int_group_count.rs"),
    "count_column": Shape(UNWITNESSED),
    "count_distinct": Shape(WITNESSED, _PROOFS + "hard/count_distinct.rs"),
    "count_case": Shape(WITNESSED, _PROOFS + "count_case_global.rs"),
    "sum": Shape(WITNESSED, _PROOFS + "group_sum_where.rs"),
    "sum_expr": Shape(WITNESSED, _PROOFS + "hard/usum_nonlinear.rs"),
    "sum_case": Shape(WITNESSED, _PROOFS + "tpch_q14_promo_ratio.rs"),
    "ratio": Shape(WITNESSED, _PROOFS + "tpch_q14_promo_ratio.rs"),
    "avg": Shape(WITNESSED, _PROOFS + "hard/dict_group_two_keys_count_distinct_avg.rs"),
    "avg_decimal": Shape(UNWITNESSED),
    "min": Shape(UNWITNESSED),
    "max": Shape(UNWITNESSED),
    # output
    "projection": Shape(WITNESSED, _ADV + "limit_zero.json"),
    "distinct": Shape(UNWITNESSED),
    "order_by": Shape(WITNESSED, _PROOFS + "tpch_q3_join_group_topk.rs"),
    "limit": Shape(WITNESSED, _ADV + "limit_zero.json"),
    "offset": Shape(UNWITNESSED),
    "set_op": Shape(UNWITNESSED),
}


def query_features(q: Query) -> set[str]:
    """The shape classes of a parsed query (and of every query nested in it)."""
    f: set[str] = set()
    if q.set_op:
        f.add("set_op")
    if q.set_query is not None:
        f |= query_features(q.set_query)
    f.add("group_by" if q.group_columns else ("global_agg" if q.aggs else "projection"))
    if len(q.group_columns) > 1:
        f.add("group_by_multi")
    if any(o.name.casefold() != o.text.rpartition(".")[2].casefold() and o.name in q.group_exprs for o in q.outputs):
        f.add("group_by_alias")
    if len(q.tables) + len(q.joins) > 1 or q.joins:
        tables = [t.casefold() for t in q.tables] + [j.table.casefold() for j in q.joins]
        f.add("join_self" if len(set(tables)) < len(tables) else "join_inner")
        if any(j.kind != "inner" for j in q.joins):
            f.add("join_outer")
        if any(j.on_combiner == "or" for j in q.joins):
            f.add("join_or_on")
    else:
        f.add("scan")
    if q.where_expr.strip():
        f.add("where")
        if "spec_like(" in q.where_expr:
            f.add("like")
    if any("spec_like(" in a.expr for a in q.aggs):
        f.add("like")
    for kind in q.aggs:
        k = kind.kind.upper()
        if k == "RATIO":
            f.add("ratio")
        elif k == "COUNT":
            f.add("count_case" if kind.expr else ("count_star" if kind.column == "*" else "count_column"))
        elif k == "COUNT_DISTINCT":
            f.add("count_distinct")
        elif k == "SUM":
            f.add("sum_case" if kind.expr else ("sum_expr" if kind.arith else "sum"))
        elif k == "AVG":
            f.add("avg_decimal" if kind.avg_scale else "avg")
        elif k in ("MIN", "MAX"):
            f.add(k.lower())
    if q.having_expr.strip():
        f.add("having")
        if any(a.kind.upper() in ("MIN", "MAX") for a in q.aggs):
            f.add("having_min_max")
    if q.distinct:
        f.add("distinct")
    if q.order_by:
        f.add("order_by")
    if q.limit is not None:
        f.add("limit")
    if q.offset is not None:
        f.add("offset")
    for _name, sub, negated in q.exists:
        f.add("not_exists" if negated else "exists")
        f |= query_features(sub)
    if q.in_subqueries:
        f.add("in_subquery")
    if q.scalar_subqueries:
        f.add("scalar_subquery")
    for _n, _c, sub in q.in_subqueries:
        f |= query_features(sub)
    for _n, sub in q.scalar_subqueries:
        f |= query_features(sub)
    if q.derived:
        f.add("derived")
        for _n, sub in q.derived:
            f |= query_features(sub)
    if q.ctes:
        f.add("cte")
    return f


def check_shapes(q: Query) -> set[str]:
    """Refuse a query with an impossible class; return its classes."""
    features = query_features(q)
    for name in sorted(features):
        shape = REGISTRY.get(name)
        if shape is not None and shape.status == IMPOSSIBLE:
            raise DeclarativeUnsupported(f"{name}: no body can satisfy the spec ({shape.reason})")
    return features
