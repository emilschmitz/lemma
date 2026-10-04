"""Known soundness holes of the declarative spec emitter, pinned as regression tests.

Each fixture under ``fixtures/adversary_declarative/hole_*.json`` is a hand-proved
body: Verus accepts it against the emitted spec, and its rows differ from DuckDB's.
The tests assert ``status == "hole"`` TODAY. When an emitter fix lands, the test for
that hole fails: flip it to expect a refusal (``refused``) or ``no_difference``.

All fixtures use a catalog row cap of 1 so the body can be proved without a loop.
The holes themselves do not depend on the cap.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from research_loop.adversary.candidate import load_candidate
from research_loop.adversary.judge_declarative import judge_declarative_candidate
from research_loop.decl_query_measure import _export_table, _pack
from research_loop.harness import resolve_verus_bin
from research_loop.table_assumptions import CatalogAssumptions

_DIR = Path(__file__).resolve().parent / "fixtures" / "adversary_declarative"

HOLES = sorted(p.stem for p in _DIR.glob("hole_*.json"))

# Holes that were fixed: the emitter now refuses (or the judge finds no difference).
# Anything not listed still reports "hole" today.
FIXED: dict[str, str] = {
    "hole_offset_dropped": "refused",
    "hole_limit_expression_dropped": "refused",
    "hole_limit_percent_read_as_rows": "refused",
    "hole_using_sample_ignored": "refused",
    "hole_group_by_all_dropped": "refused",
    "hole_group_by_grouping_sets_dropped": "refused",
    "hole_group_by_rollup_dropped": "refused",
    "hole_exists_subquery_limit_ignored": "refused",
    "hole_min_two_arg_is_list": "refused",
    # The hand-proved body encodes the old wrong semantics; Verus now rejects it.
    "hole_is_null_empty_string": "impl_does_not_fit_spec",
    "hole_is_not_null_empty_string": "impl_does_not_fit_spec",
    "hole_is_true_read_as_not_null": "impl_does_not_fit_spec",
    "hole_is_false_read_as_not_null": "impl_does_not_fit_spec",
    "hole_literal_rewritten_to_column": "impl_does_not_fit_spec",
    "hole_string_literal_backslash_escape": "impl_does_not_fit_spec",
}


def test_hole_fixtures_exist() -> None:
    assert len(HOLES) >= 14


@pytest.mark.skipif(resolve_verus_bin() is None, reason="verus not found")
@pytest.mark.parametrize("name", HOLES)
def test_declarative_hole_is_reported_today(name: str) -> None:
    cand = load_candidate(_DIR / f"{name}.json")
    report = judge_declarative_candidate(
        cand, verify=True, catalog=CatalogAssumptions(tables={}, max_rows=1)
    )
    expected = FIXED.get(name, "hole")
    assert report["status"] == expected, report
    if expected == "hole":
        assert report["proof_verified"] is True


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM t ORDER BY a LIMIT 1 OFFSET 1",
        "SELECT a FROM t OFFSET 2",
        "SELECT a FROM t LIMIT 1 - 1",
        "SELECT a FROM t LIMIT NULL",
        "SELECT a FROM t LIMIT (SELECT 1)",
        "SELECT a FROM t LIMIT 50%",
        "SELECT a FROM t USING SAMPLE 10 ROWS",
        "SELECT a FROM t TABLESAMPLE (10 PERCENT)",
        "SELECT b, SUM(a) FROM t GROUP BY ALL",
        "SELECT b, SUM(a) FROM t GROUP BY ROLLUP (b)",
        "SELECT b, SUM(a) FROM t GROUP BY CUBE (b)",
        "SELECT b, SUM(a) FROM t GROUP BY GROUPING SETS ((b), ())",
        "SELECT a FROM t WHERE EXISTS (SELECT 1 FROM u WHERE u.k = t.k LIMIT 0)",
        "SELECT a FROM t WHERE EXISTS (SELECT DISTINCT 1 FROM u WHERE u.k = t.k)",
        "SELECT a FROM t WHERE EXISTS (SELECT k FROM u GROUP BY k HAVING COUNT(*) > 1)",
        "SELECT b, MIN(a, 1) FROM t GROUP BY b",
        "SELECT b, MAX(a, 1) FROM t GROUP BY b",
    ],
)
def test_dropped_clauses_are_refused_at_parse(sql: str) -> None:
    from declarative_spec.parse import DeclarativeUnsupported
    from declarative_spec.parse_query import parse_query

    with pytest.raises(DeclarativeUnsupported):
        parse_query(sql)


def test_plain_limit_and_group_by_still_parse() -> None:
    from declarative_spec.parse_query import parse_query

    assert parse_query("SELECT a FROM t ORDER BY a LIMIT 5").limit == 5
    assert parse_query("SELECT b, SUM(a) FROM t GROUP BY b").group_columns == ["b"]


def test_loader_turns_sql_null_into_a_value_today() -> None:
    """The column export packs NULL as 0, "" or false, so a NULL cell is indistinguishable
    from a real value. The judge refuses NULL rows; production export does not."""
    assert _pack("i64", None) == _pack("i64", 0)
    assert _pack("u64", None) == _pack("u64", 0)
    assert _pack("f64", None) == _pack("f64", 0.0)
    assert _pack("i128", None) == _pack("i128", 0)
    assert _pack("String", None) == _pack("String", "")
    assert _pack("bool", None) == _pack("bool", False)


def test_exported_column_blob_is_identical_for_null_and_zero() -> None:
    from declarative_spec.schema_types import SchemaModel

    model = SchemaModel.from_caller({"t": {"a": "BIGINT"}}, "t")
    blobs = []
    for cell in ("NULL", "0"):
        con = duckdb.connect()
        con.execute('CREATE TABLE "t" ("a" BIGINT)')
        con.execute(f'INSERT INTO "t" VALUES ({cell})')
        blobs.append(_export_table(con, model, "t", [("a", "i64")]))
        con.close()
    assert blobs[0] == blobs[1]


def _spec(sql: str, schema: dict) -> str:
    from declarative_spec.emit_surface import emit_from_surface

    return emit_from_surface(sql, schema, CatalogAssumptions(tables={}, max_rows=1))


@pytest.mark.parametrize("col, ty", [("s", "VARCHAR"), ("a", "BIGINT")])
def test_is_null_is_false_and_is_not_null_true_for_every_type(col: str, ty: str) -> None:
    schema = {"t": {"a": "BIGINT", "s": "VARCHAR"}}
    assert ty
    null_spec = _spec(f"SELECT a FROM t WHERE {col} IS NULL", schema)
    not_null_spec = _spec(f"SELECT a FROM t WHERE {col} IS NOT NULL", schema)
    assert '""@' not in null_spec and '""@' not in not_null_spec


def test_string_literal_is_not_rewritten_to_a_column() -> None:
    spec = _spec("SELECT a FROM t WHERE s = 'a'", {"t": {"a": "BIGINT", "s": "VARCHAR"}})
    assert '"a"@' in spec


@pytest.mark.parametrize(
    "literal, rust",
    [("x\\\\y", '"x\\\\\\\\y"@'), ('say "hi"', '"say \\"hi\\""@')],
)
def test_string_literal_is_escaped_into_rust(literal: str, rust: str) -> None:
    spec = _spec(f"SELECT a FROM t WHERE s = '{literal}'", {"t": {"a": "BIGINT", "s": "VARCHAR"}})
    assert rust in spec


@pytest.mark.parametrize(
    "predicate, expected",
    [("c IS TRUE", "(c == true)"), ("c IS FALSE", "(c == false)"), ("c IS NOT TRUE", "!(c == true)")],
)
def test_is_true_false_compile_to_the_boolean_comparison(predicate: str, expected: str) -> None:
    from declarative_spec.parse_query import parse_query

    assert parse_query(f"SELECT a FROM t WHERE {predicate}").where_expr == expected


@pytest.mark.parametrize("predicate", ["a IS 5", "(a > 1) IS TRUE"])
def test_is_with_other_right_sides_is_refused(predicate: str) -> None:
    from declarative_spec.parse import DeclarativeUnsupported
    from declarative_spec.parse_query import parse_query

    with pytest.raises(DeclarativeUnsupported):
        parse_query(f"SELECT a FROM t WHERE {predicate}")
