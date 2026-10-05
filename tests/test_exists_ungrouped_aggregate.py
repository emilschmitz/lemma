"""EXISTS / NOT EXISTS over an ungrouped aggregate subquery.

SQL: an ungrouped aggregate query returns exactly one row even over no input rows, so ``EXISTS`` is TRUE for every outer
row and ``NOT EXISTS`` is FALSE, whatever the subquery's WHERE selects. The spec used to say "a row of the subquery's
table matches the WHERE" (pinned as strict xfails in test_ratio_division_adversary.py, FINDING 4).
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.pipeline import VERUS_CANDIDATES, verify_assembled
from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

SCHEMA = {
    "li": {"okey": "bigint", "price": "decimal(15,2)", "disc": "decimal(15,2)", "qty": "integer"},
    "part": {"pkey": "bigint", "ptype": "varchar"},
}
CATALOG = CatalogAssumptions(
    max_rows=64,
    tables={
        t: TableAssumptions(
            max_rows=64,
            columns={c: ColumnAssumption(max_value_exclusive=2**20) if ty in ("bigint", "integer") else ColumnAssumption() for c, ty in cols.items()},
        )
        for t, cols in SCHEMA.items()
    },
)
FIXTURES = Path(__file__).parent / "fixtures" / "exists_ungrouped"

EXISTS_SQL = "select count(*) as c from part where exists (select sum(price) as s from li where qty > 100)"
NOT_EXISTS_SQL = "select count(*) as c from part where not exists (select sum(price) as s from li where qty > 100)"
AGG_SUBQUERIES = [
    "select sum(price) as s from li where qty > 100",
    "select sum(price)/sum(disc) as r from li where qty > 100",
    "select count(*)/count(*) as r from li where qty > 100",
    "select max(qty) from li where li.okey = part.pkey",
    "select count(*) from li",
]
# li rows (okey, price, disc, qty): none, only non-matching, matching
LI_STATES = [[], [(1, 3.0, 0.5, 2), (2, 5.0, 0.25, 3)], [(1, 3.0, 0.5, 200), (2, 5.0, 0.25, 3)]]


def _emit(sql: str) -> str:
    return emit_declarative_spec(sql, SCHEMA, CATALOG)


def _flat(spec: str) -> str:
    return " ".join(spec.split())


def _exists_body(spec: str) -> str:
    m = re.search(r"pub open spec fn exists_1\([^)]*\) -> bool \{(.*?)\}", _flat(spec))
    assert m is not None
    return m.group(1).strip()


def _duck(sql: str, li_rows: list[tuple]) -> int:
    con = duckdb.connect()
    con.execute("create table li(okey bigint, price decimal(15,2), disc decimal(15,2), qty integer)")
    con.execute("create table part(pkey bigint, ptype varchar)")
    con.execute("insert into part values (1,'a'),(2,'b'),(3,'c')")
    for r in li_rows:
        con.execute("insert into li values (?,?,?,?)", list(r))
    return con.execute(sql).fetchone()[0]


@pytest.mark.parametrize("sub", AGG_SUBQUERIES)
@pytest.mark.parametrize("li_rows", LI_STATES)
def test_exists_over_an_ungrouped_aggregate_holds_for_every_outer_row_like_duckdb(sub: str, li_rows: list[tuple]) -> None:
    sql = f"select count(*) as c from part where exists ({sub})"
    spec = _emit(sql)
    # the spec's EXISTS only range-checks the outer row: it does not read li at all
    assert _exists_body(spec) == "&&& 0 <= i0 < part.n as int"
    assert "li." not in _exists_body(spec)
    assert _duck(sql, li_rows) == 3  # DuckDB: every part row, whatever li holds


@pytest.mark.parametrize("sub", AGG_SUBQUERIES)
@pytest.mark.parametrize("li_rows", LI_STATES)
def test_not_exists_over_an_ungrouped_aggregate_holds_for_no_outer_row_like_duckdb(sub: str, li_rows: list[tuple]) -> None:
    sql = f"select count(*) as c from part where not exists ({sub})"
    spec = _emit(sql)
    assert _exists_body(spec) == "&&& 0 <= i0 < part.n as int"
    assert "(!exists_1(part, li, i0))" in _flat(spec) or "!exists_1(part, li, i0)" in _flat(spec)
    assert _duck(sql, li_rows) == 0


def test_a_plain_exists_still_depends_on_the_subquery_rows() -> None:
    sql = "select count(*) as c from part where exists (select 1 from li where qty > 100)"
    body = _exists_body(_emit(sql))
    assert "exists|e0: int|" in body and "li.qty" in body
    counts = [_duck(sql, rows) for rows in LI_STATES]
    assert counts == [0, 0, 3]  # data dependent, unlike the aggregate form


@pytest.mark.parametrize(
    "sub",
    [
        "select sum(price) as s from li where qty > 100 having sum(price) > 5",
        "select sum(price) as s from li group by okey",
        "select sum(price) as s from li limit 0",
    ],
)
def test_the_aggregate_exists_forms_that_can_return_zero_rows_are_refused(sub: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        _emit(f"select count(*) as c from part where exists ({sub})")


def test_the_guard_inside_the_emitter_refuses_having_even_if_the_parser_let_it_through(monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec import emit_surface
    from declarative_spec.parse_query import parse_query

    query = parse_query(EXISTS_SQL)
    query.exists[0][1].having_expr = "true"
    with pytest.raises(DeclarativeUnsupported, match="HAVING"):
        emit_surface._exists_fns(query, "", [emit_surface._Slot("part", "part", "part", "Cols_part", "i0")], [], None, [])  # type: ignore[arg-type]


def _verify(body_file: str, sql: str, monkeypatch: pytest.MonkeyPatch, mutate: tuple[str, str] | None = None) -> tuple[bool, str]:
    if not any(c.is_file() for c in VERUS_CANDIDATES):
        pytest.skip("verus binary not installed")
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"))
    text = (FIXTURES / body_file).read_text()
    if mutate is not None:
        assert mutate[0] in text
        text = text.replace(*mutate, 1)
    program = assemble_declarative_program(_emit(sql), extract_agent_edit(text), helpers=extract_agent_helpers(text))
    return verify_assembled(program, timeout_sec=600)


def test_reference_body_for_exists_over_an_aggregate_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, log = _verify("exists_agg_count.rs", EXISTS_SQL, monkeypatch)
    assert ok, log[-3000:]


def test_reference_body_for_not_exists_over_an_aggregate_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, log = _verify("not_exists_agg_count.rs", NOT_EXISTS_SQL, monkeypatch)
    assert ok, log[-3000:]


def test_the_old_data_dependent_answer_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mutation: count only part rows when some li row exists would be the old (wrong) meaning; a body that returns 0
    # for the EXISTS query must fail now that the spec says the count is part.n.
    ok, _log = _verify("not_exists_agg_count.rs", EXISTS_SQL, monkeypatch)
    assert not ok
