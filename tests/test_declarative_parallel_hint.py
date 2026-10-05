"""A proved but slow sequential body is bounced with the parallel-recipe hint when the spec has the Arc parameters."""

from __future__ import annotations

import pytest

from declarative_spec import parallel, pipeline
from declarative_spec.emit import emit_declarative_spec
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

SCHEMA = {"pre": {"line": "bigint"}}
CATALOG = CatalogAssumptions(tables={"pre": TableAssumptions(max_rows=2**31)})
SQL = "SELECT SUM(line) AS total FROM pre WHERE line > 5"
SLOW_BAR = {"duck_us": 1000, "duck1_us": 4000, "rows": [[1]], "kinds": ["int"], "table_rows": {"pre": 3}}


def _metrics(monkeypatch: pytest.MonkeyPatch, spec: str, body: str) -> dict:
    # Verus and the binary are replaced: the compiled run "proves" and takes 5000 us, the bar says 1000 us.
    monkeypatch.setattr(
        pipeline,
        "compile_and_run",
        lambda *_a, **_k: {
            "status": "SUCCESS",
            "proof_verified": True,
            "latency_us": 5000,
            "stdout": "ROW\x1f1\n",
            "compiler_error": "",
        },
    )
    monkeypatch.setattr("declarative_spec.bench.rows_match_error", lambda *a, **k: None)
    agent_source = f"// AGENT_EDIT_START\n{body}\n// AGENT_EDIT_END\n"
    return pipeline.run_declarative_metrics(spec_rs=spec, agent_source=agent_source, speed_bar=SLOW_BAR, column_bins={"pre": "/dev/null"})


def test_a_slow_sequential_body_on_a_parallel_spec_gets_the_parallel_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(parallel.ENV, "1")
    spec = emit_declarative_spec(SQL, SCHEMA, CATALOG)
    out = _metrics(monkeypatch, spec, "    let mut res: Vec<OutRow> = Vec::new();\n    res")
    assert out["status"] == "FAILURE" and "below the speed bar" in out["compiler_error"]
    assert "single-threaded" in out["compiler_error"] and "parallel_ungrouped_sum.rs" in out["compiler_error"]


def test_no_hint_for_a_body_that_already_spawns_threads_or_a_spec_without_arcs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(parallel.ENV, "1")
    par = emit_declarative_spec(SQL, SCHEMA, CATALOG)
    threaded = "    let h = vstd::thread::spawn(move || 0usize);\n    let mut res: Vec<OutRow> = Vec::new();\n    res"
    out = _metrics(monkeypatch, par, threaded)
    assert "below the speed bar" in out["compiler_error"] and "PARALLEL recipe" not in out["compiler_error"]
    monkeypatch.delenv(parallel.ENV)
    seq = emit_declarative_spec(SQL, SCHEMA, CATALOG)
    out = _metrics(monkeypatch, seq, "    let mut res: Vec<OutRow> = Vec::new();\n    res")
    assert "below the speed bar" in out["compiler_error"] and "PARALLEL recipe" not in out["compiler_error"]


def test_the_speed_fields_reach_the_agent_through_the_harness_metrics() -> None:
    from db_extension.verus_bridge import normalize_harness_metrics

    res = {
        "status": "SUCCESS",
        "proof_verified": True,
        "latency_us": 500,
        "duck_us": 1000,
        "duck1_us": 3000,
        "speedup": 2.0,
        "speedup_1t": 6.0,
        "latency_best_us": 450,
        "official_tables": {"num": 39401761},
    }
    out = normalize_harness_metrics(res)
    assert out["speedup"] == 2.0 and out["duck_us"] == 1000 and out["official_tables"] == {"num": 39401761}
    assert "speedup" not in normalize_harness_metrics({"status": "FAILURE", "latency_us": -1})  # absent stays absent


def test_a_slow_body_reports_the_official_tables_in_its_failure_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("declarative_spec.bench.rows_match_error", lambda *a, **k: None)
    bar = {"duck_us": 100, "rows": [[1]], "kinds": ["int"], "table_rows": {"pre": 9600799}}
    run = {"status": "SUCCESS", "proof_verified": True, "latency_us": 500, "stdout": "ROW\x1f1\n"}
    out = pipeline._apply_speed_bar(run, bar)
    assert out["status"] == "FAILURE" and out["official_tables"] == {"pre": 9600799}
