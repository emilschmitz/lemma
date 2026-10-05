"""Adversary probes for EXISTS / NOT EXISTS over an ungrouped aggregate subquery (commit 7ace4e0): held properties."""

from __future__ import annotations

import re

import pytest

from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from tests.test_exists_ungrouped_aggregate import CATALOG, LI_STATES, SCHEMA, _duck

HOLDING_SUBQUERIES = [
    "select sum(price) filter (where qty > 100) from li",
    "select count(distinct okey) from li where qty > 100",
    "select count(*) from li join part p2 on li.okey = p2.pkey where qty > 100",
    "select sum(price) from li where li.okey = part.pkey and qty > 100",
    "select sum(price) from li where exists (select 1 from part p2 where p2.pkey = li.okey)",
    "select sum(price) from li where not exists (select 1 from part p2 where p2.pkey = li.okey and p2.pkey > 5)",
    "select sum(s) from (select price as s from li) t",
    "select sum(price) as s, max(qty) as m from li where qty > 100",
    "select avg(price) from li where qty > 100",
    "select max(pkey) from part p2 where p2.pkey > part.pkey",
    "select count(*) from li where false",
]


def _body(spec: str, n: int = 1) -> str:
    m = re.search(rf"pub open spec fn exists_{n}\([^)]*\) -> bool \{{(.*?)\}}", " ".join(spec.split()))
    assert m is not None
    return m.group(1).strip()


@pytest.mark.parametrize("sub", HOLDING_SUBQUERIES)
@pytest.mark.parametrize("li_rows", LI_STATES)
@pytest.mark.parametrize("negated", [False, True])
def test_aggregate_exists_shapes_hold_like_duckdb(sub: str, li_rows: list[tuple], negated: bool) -> None:
    sql = f"select count(*) as c from part where {'not ' if negated else ''}exists ({sub})"
    spec = emit_declarative_spec(sql, SCHEMA, CATALOG)
    assert _body(spec) == "&&& 0 <= i0 < part.n as int"
    assert _duck(sql, li_rows) == (0 if negated else 3)


@pytest.mark.parametrize(
    "sql",
    [
        "select count(*) as c from part where exists (select sum(price) from li where qty > 100 having sum(price) > 1)",
        "select count(*) as c from part where exists (select 1 from li where qty > 100 having count(*) > 0)",
        "select count(*) as c from part where exists (select sum(price) from li where qty > 100 limit 1)",
        "select count(*) as c from part where exists (select sum(price) over () from li)",
        "select count(*) as c from part where pkey not in (select max(qty) from li)",
        "select count(*) as c from part where pkey in (select count(*) from li)",
    ],
)
def test_forms_whose_meaning_differs_stay_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        emit_declarative_spec(sql, SCHEMA, CATALOG)


def test_multi_table_outer_exists_fn_is_well_formed_text() -> None:
    sql = (
        "select count(*) as c from part join li on part.pkey = li.okey "
        "where exists (select sum(price) from li l2 where l2.qty > 100) and not exists (select max(pkey) from part p2)"
    )
    spec = emit_declarative_spec(sql, SCHEMA, CATALOG)
    flat = " ".join(spec.split())
    for n in (1, 2):
        assert f"pub open spec fn exists_{n}(part: &Cols_part, li: &Cols_li, i0: int, i1: int) -> bool" in flat
        assert _body(spec, n) == "&&& 0 <= i0 < part.n as int && 0 <= i1 < li.n as int"
        assert f"exists_{n}(part, li, i0, i1)" in flat
