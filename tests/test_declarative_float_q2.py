"""The SEC shape of the manual prover (round 2, Q2): strings, COUNT DISTINCT, AVG of an integer column.

The body (`float_avg_group_count_distinct.rs`) is the prover's proof with the diagnostic `avg = 0.0` replaced by
the real quotient under the f64 idealization. It verifies, runs, and matches DuckDB within epsilon; a wrong
quotient is rejected.
"""

from __future__ import annotations

import random
from pathlib import Path

import duckdb
import pytest

from declarative_spec.bench import rows_from_stdout_general, rows_match_error
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.pipeline import run_declarative_metrics
from research_loop.decl_query_measure import write_query_measure
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

VERUS = Path("/home/emil/tools/verus/verus")
PROOFS = Path(__file__).parent / "fixtures" / "declarative_proofs"
needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")

Q2_SQL = """SELECT stmt, rfile, COUNT(*) AS cnt,
       COUNT(DISTINCT adsh) AS num_filings,
       AVG(line) AS avg_line_num
FROM pre
WHERE stmt IS NOT NULL
GROUP BY stmt, rfile
ORDER BY cnt DESC"""
Q2_SCHEMA = {"adsh": "varchar", "line": "bigint", "stmt": "varchar", "rfile": "varchar"}
Q2_CATALOG = CatalogAssumptions(
    tables={"pre": TableAssumptions(max_rows=250_000, columns={"line": ColumnAssumption(max_value_exclusive=2**20)})}
)


def _q2_db(path: Path) -> None:
    rng = random.Random(5)
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE pre (adsh VARCHAR, line BIGINT, stmt VARCHAR, rfile VARCHAR)")
    rows = [
        (f"a{rng.randint(0, 9)}", rng.randint(-40, 400), rng.choice(["BS", "IS", "CF"]), rng.choice(["H", "X"]))
        for _ in range(60)
    ]
    con.executemany("INSERT INTO pre VALUES (?, ?, ?, ?)", rows)
    con.close()


def _q2_run(tmp: Path, mutate: tuple[str, str] | None = None) -> tuple[dict, dict]:
    db = tmp / "pre.duckdb"
    _q2_db(db)
    prepared = write_query_measure(
        sql=Q2_SQL, schema=Q2_SCHEMA, catalog=Q2_CATALOG, db_path=db, dest=tmp / "data"
    )
    spec = emit_declarative_spec(Q2_SQL, Q2_SCHEMA, Q2_CATALOG)
    source = (PROOFS / "float_avg_group_count_distinct.rs").read_text()
    if mutate is not None:
        assert mutate[0] in source, mutate[0]
        source = source.replace(mutate[0], mutate[1], 1)
    metrics = run_declarative_metrics(
        spec_rs=spec, agent_source=source, work_dir=tmp / "run", column_bins=prepared["bins"]
    )
    return metrics, prepared


def test_q2_spec_states_avg_as_a_real_quotient() -> None:
    spec = emit_declarative_spec(Q2_SQL, Q2_SCHEMA, Q2_CATALOG)
    assert "avg_avg_line_num_sum(pre, i0, k) / ((c as real) * 1real)" in spec
    assert "f64_literals_ok()" in spec.split("pub fn run_query(")[1].split("ensures")[0]


@needs_verus
def test_q2_avg_group_count_distinct_proves_runs_and_matches_duckdb(tmp_path: Path) -> None:
    metrics, prepared = _q2_run(tmp_path)
    assert metrics["proof_verified"], str(metrics.get("compiler_error"))[-2500:]
    assert metrics["status"] == "SUCCESS", metrics.get("compiler_error")
    got = rows_from_stdout_general(metrics["stdout"])
    assert len(got) > 1
    assert rows_match_error(got, prepared["rows"], prepared["kinds"]) is None


@needs_verus
def test_q2_wrong_avg_is_rejected(tmp_path: Path) -> None:
    metrics, _prepared = _q2_run(tmp_path, ("let avg = fs / fc;", "let avg = fc / fc;"))
    assert not metrics["proof_verified"]
    assert "verification results::" in str(metrics.get("compiler_error"))
