"""Rows-level soundness of alias binding: Verus evaluates the emitted spec on rows where a wrong binding differs.

The expected values come from DuckDB running the same SQL on the same rows (see ``tests/spec_eval.py``).
Each case has a control: the value a mis-bound alias would give fails to prove, so the harness can tell.
"""

from __future__ import annotations

import duckdb
import pytest

from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions
from tests.spec_eval import VERUS, prove_facts

pytestmark = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")

SCHEMA = {"t": {"a": "bigint", "g": "bigint"}}
CATALOG = CatalogAssumptions(max_rows=4, tables={"t": TableAssumptions(max_rows=4)})
ROWS = [{"a": 1, "g": 0}, {"a": 2, "g": 0}, {"a": 3, "g": 1}, {"a": 2, "g": 1}]
TABLES = {"t": ROWS}


def _duck() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (rid INTEGER, a BIGINT, g BIGINT)")
    con.executemany("INSERT INTO t VALUES (?, ?, ?)", [(i, r["a"], r["g"]) for i, r in enumerate(ROWS)])
    return con


def _spec(sql: str) -> str:
    return emit_declarative_spec(sql, SCHEMA, CATALOG, float_abs_eps="1e20")


def _group_facts(sql: str, fn: str, params: str, key_col: str = "g") -> tuple[list[str], dict[int, int]]:
    """``fn(params, 0, key) == value`` for each group DuckDB returns."""
    want = {int(k): int(v) for k, v in _duck().execute(sql).fetchall()}
    return [f"{fn}({params}, 0, {k}) == {v}int" for k, v in want.items()], want


@pytest.mark.parametrize(
    ("alias", "other"),
    [("a", "b"), ("b", "a")],
)
def test_self_join_group_key_binds_to_the_alias_it_names(alias: str, other: str) -> None:
    sql = f"SELECT {alias}.g AS g, COUNT(*) AS c FROM t a, t b WHERE a.a < b.a GROUP BY {alias}.g"
    facts, want = _group_facts(sql, "count_c", "a, b")
    spec = _spec(sql)
    ok, out = prove_facts(spec, TABLES, facts, funs=["count_c", "count_c_d1"])
    assert ok, out[-1500:]
    # Control: the counts of the other alias's key differ on these rows, and do not prove.
    other_sql = sql.replace(f"{alias}.g", f"{other}.g")
    other_facts, other_want = _group_facts(other_sql, "count_c", "a, b")
    assert other_want != want
    bad, _ = prove_facts(spec, TABLES, other_facts, funs=["count_c", "count_c_d1"])
    assert not bad


@pytest.mark.parametrize("summed", ["a", "b"])
def test_self_join_sum_reads_the_alias_it_names(summed: str) -> None:
    sql = f"SELECT a.g AS g, SUM({summed}.a) AS s FROM t a, t b WHERE a.a < b.a GROUP BY a.g"
    facts, want = _group_facts(sql, "sum_s", "a, b")
    ok, out = prove_facts(_spec(sql), TABLES, facts, funs=["sum_s", "sum_s_d1"])
    assert ok, out[-1500:]
    other = "b" if summed == "a" else "a"
    other_facts, other_want = _group_facts(sql.replace(f"SUM({summed}.a)", f"SUM({other}.a)"), "sum_s", "a, b")
    assert other_want != want
    bad, _ = prove_facts(_spec(sql), TABLES, other_facts, funs=["sum_s", "sum_s_d1"])
    assert not bad


@pytest.mark.parametrize("negated", ["", "NOT "])
def test_correlated_exists_over_the_same_table_selects_the_rows_duckdb_selects(negated: str) -> None:
    sql = (
        f"SELECT COUNT(*) AS c FROM t a WHERE {negated}EXISTS "
        "(SELECT 1 FROM t b WHERE b.g = a.g AND b.a > a.a)"
    )
    want = _duck().execute(sql).fetchone()[0]
    spec = _spec(sql)
    ok, out = prove_facts(spec, TABLES, [f"count_c(a, 0) == {want}int"], funs=["count_c"])
    assert ok, out[-1500:]
    bad, _ = prove_facts(spec, TABLES, [f"count_c(a, 0) == {want + 1}int"], funs=["count_c"])
    assert not bad


def test_correlated_exists_binds_inner_and_outer_rows_apart_per_row() -> None:
    """Row by row: ``row_hit(a, i)`` is DuckDB's verdict for row i (an inner row never stands in for the outer)."""
    sql = "SELECT COUNT(*) AS c FROM t a WHERE EXISTS (SELECT 1 FROM t b WHERE b.g = a.g AND b.a > a.a)"
    member = {
        i: bool(
            _duck()
            .execute("SELECT COUNT(*) FROM t a WHERE a.rid = ? AND EXISTS (SELECT 1 FROM t b WHERE b.g = a.g AND b.a > a.a)", [i])
            .fetchone()[0]
        )
        for i in range(len(ROWS))
    }
    assert any(member.values()) and not all(member.values())
    facts = [f"row_hit(a, {i}) == {str(v).lower()}" for i, v in member.items()]
    ok, out = prove_facts(_spec(sql), TABLES, facts, funs=[])
    assert ok, out[-1500:]


def test_correlated_max_scalar_selects_the_rows_duckdb_selects() -> None:
    sql = "SELECT a FROM t t1 WHERE a = (SELECT MAX(a) FROM t t2 WHERE t2.g = t1.g)"
    chosen = {r[0] for r in _duck().execute(
        "SELECT rid FROM t t1 WHERE a = (SELECT MAX(a) FROM t t2 WHERE t2.g = t1.g)").fetchall()}
    assert chosen and len(chosen) < len(ROWS)
    facts = [f"row_hit(t1, {i}) == {str(i in chosen).lower()}" for i in range(len(ROWS))]
    ok, out = prove_facts(_spec(sql), TABLES, facts, funs=[])
    assert ok, out[-1500:]


@pytest.mark.parametrize("agg", ["AVG(w.a)", "SUM(w.a)", "COUNT(*)", "COUNT(w.a)"])
def test_correlated_non_extremum_scalars_are_refused_not_mis_bound(agg: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        _spec(f"SELECT a FROM t t1 WHERE a > (SELECT {agg} FROM t w WHERE w.g = t1.g)")
    with pytest.raises(DeclarativeUnsupported):
        _spec(f"SELECT COUNT(*) AS c FROM t t1 WHERE a > (SELECT {agg} FROM t w WHERE w.g = t1.g)")


def test_grouped_derived_table_merges_to_the_groups_duckdb_returns() -> None:
    sql = "SELECT k, c FROM (SELECT g AS k, COUNT(*) AS c FROM t WHERE a > 1 GROUP BY g) d WHERE c > 1"
    base = "SELECT g, COUNT(*) FROM t WHERE a > 1 GROUP BY g HAVING COUNT(*) > 1"
    want = {int(k): int(v) for k, v in _duck().execute(base).fetchall()}
    assert {int(k): int(v) for k, v in _duck().execute(sql).fetchall()} == want
    facts = [f"count_c(t, 0, {k}) == {v}int" for k, v in want.items()]
    ok, out = prove_facts(_spec(sql), TABLES, facts, funs=["count_c"])
    assert ok, out[-1500:]
