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


def test_hole_fixtures_exist() -> None:
    assert len(HOLES) >= 14


@pytest.mark.skipif(resolve_verus_bin() is None, reason="verus not found")
@pytest.mark.parametrize("name", HOLES)
def test_declarative_hole_is_reported_today(name: str) -> None:
    cand = load_candidate(_DIR / f"{name}.json")
    report = judge_declarative_candidate(
        cand, verify=True, catalog=CatalogAssumptions(tables={}, max_rows=1)
    )
    assert report["status"] == "hole", report
    assert report["proof_verified"] is True


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
