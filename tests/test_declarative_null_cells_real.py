"""The NULL-last ordering clause against DuckDB on real SEC rows with real NULLs (sub.fy is NULL on 4,662 of 86,135 rows)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from declarative_spec.emit import emit_declarative_spec
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions
from tests.spec_eval import VERUS, prove_facts
from tests.test_declarative_null_cells import _order_clause

REAL_DB = Path("/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/duckdb/sec_edgar_dec.duckdb")


@pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")
@pytest.mark.skipif(not REAL_DB.is_file(), reason="real SEC database not present")
def test_the_ordering_clause_matches_duckdb_on_real_sec_sub_rows_with_null_fy() -> None:
    real = duckdb.connect(str(REAL_DB), read_only=True)
    nulls = real.execute("SELECT cik, fy FROM sub WHERE fy IS NULL ORDER BY adsh LIMIT 4").fetchall()
    filled = real.execute("SELECT cik, fy FROM sub WHERE fy IS NOT NULL ORDER BY adsh LIMIT 4").fetchall()
    rows = [{"cik": c, "fy": f} for c, f in filled[:2] + nulls[:2] + filled[2:] + nulls[2:]]
    assert sum(r["fy"] is None for r in rows) == 4
    schema = {"sub": {"cik": "integer", "fy": "integer"}}
    catalog = CatalogAssumptions(
        max_rows=8,
        tables={"sub": TableAssumptions(max_rows=8, columns={"fy": ColumnAssumption(nullable=True)})},
    )
    sql = "SELECT cik, fy FROM sub ORDER BY fy, cik"
    spec = emit_declarative_spec(sql, schema, catalog)
    local = duckdb.connect()
    local.execute("CREATE TABLE sub (cik INTEGER, fy INTEGER)")
    local.executemany("INSERT INTO sub VALUES (?, ?)", [(r["cik"], r["fy"]) for r in rows])
    duck = local.execute(sql).fetchall()
    assert [f for _c, f in duck][-4:] == [None] * 4

    def lit(order: list[tuple]) -> str:
        cells = ", ".join(
            f"OutRow {{ cik: {c}i64, fy: {'None' if f is None else f'Some({f}i64)'} }}" for c, f in order
        )
        return f"    let rs: Seq<OutRow> = seq![{cells}];\n"

    clause = _order_clause(spec)
    ok, out = prove_facts(spec, {"sub": rows}, ["true"], extra=lit(duck) + f"    assert({clause});\n")
    assert ok, out[-1500:]
    nulls_first = [r for r in duck if r[1] is None] + [r for r in duck if r[1] is not None]
    ok, out = prove_facts(spec, {"sub": rows}, ["true"], extra=lit(nulls_first) + f"    assert(!({clause}));\n")
    assert ok, out[-1500:]
