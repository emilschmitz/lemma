"""Tests for measure_core validate + mark_submit (no full harness)."""
from __future__ import annotations

import json
from pathlib import Path

from db_extension.agent import measure_core as mc
from db_extension.agent.extract import wrap_body_with_markers
from verus_transpiler import transpile_sql_to_verus


def _write_workspace_spec(ws: Path) -> None:
    ro = ws / "context" / "ro"
    ro.mkdir(parents=True)
    spec = transpile_sql_to_verus("SELECT SUM(V) FROM t", {"V": "bigint"})
    (ro / "spec.rs").write_text(spec, encoding="utf-8")
    (ro / "query.sql").write_text("SELECT SUM(V) FROM t", encoding="utf-8")
    (ro / "schema.json").write_text('{"V": "bigint"}', encoding="utf-8")


def test_validate_solution_ok(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    _write_workspace_spec(tmp_path)
    body = "let x = 1;"
    out = mc.validate_solution(body=body, ws=tmp_path)
    assert out["ok"] is True
    assert (tmp_path / "runquery_agent.rs").is_file()


def test_validate_solution_rejects_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    out = mc.validate_solution(body="  // only comment\n", ws=tmp_path)
    assert out["ok"] is False
    assert out["errors"]


def test_mark_submit_unknown_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    out = mc.mark_submit("missing-id", ws=tmp_path)
    assert out["ok"] is False


def test_mark_submit_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    run_id = "testrun001"
    rq = tmp_path / "runquery_agent.rs"
    rq.write_text("// winning body\nlet x = 1;", encoding="utf-8")
    record = {
        "ok": True,
        "run_id": run_id,
        "metrics": {"status": "SUCCESS", "proof_verified": True, "latency_us": 42},
        "latency_us": 42,
        "dataset_size": 50_000,
        "runquery_path": str(rq),
    }
    mc.runs_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    (mc.runs_dir(tmp_path) / f"{run_id}.json").write_text(json.dumps(record))

    marked = mc.mark_submit(run_id, ws=tmp_path)
    assert marked["ok"] is True
    submitted = mc.get_submitted(ws=tmp_path)
    assert submitted is not None
    assert submitted["run_id"] == run_id
    assert submitted["latency_us"] == 42
    assert submitted["runquery_body"] == "// winning body\nlet x = 1;"
    assert submitted["iterate_dataset_size"] == 50_000


def test_run_solution_mock_harness(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    _write_workspace_spec(tmp_path)
    (tmp_path / "runquery_agent.rs").write_text(wrap_body_with_markers("let x = 1;"))

    def fake_harness(*, query_id: int, dataset_size: int, ws: Path, sql=None, schema=None):
        assert query_id == 3
        assert dataset_size == 1000
        return (
            {
                "status": "SUCCESS",
                "proof_verified": True,
                "latency_us": 99,
                "compiler_error": "",
            },
            0,
        )

    monkeypatch.setattr(mc, "_invoke_harness", fake_harness)
    out = mc.run_solution(path="runquery_agent.rs", query_id=3, dataset_size=1000, ws=tmp_path)
    assert out["ok"] is True
    assert out["run_id"]
    assert out["latency_us"] == 99
    assert (mc.results_dir(tmp_path) / "latest_run.json").is_file()


def test_run_solution_default_uses_iterate_cap(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    _write_workspace_spec(tmp_path)
    (tmp_path / "runquery_agent.rs").write_text(wrap_body_with_markers("let x = 1;"))

    seen: list[int] = []

    def fake_harness(*, query_id: int, dataset_size: int, ws: Path, sql=None, schema=None):
        seen.append(dataset_size)
        return (
            {
                "status": "SUCCESS",
                "proof_verified": True,
                "latency_us": 12,
                "compiler_error": "",
            },
            0,
        )

    monkeypatch.setattr(mc, "_invoke_harness", fake_harness)
    monkeypatch.setattr(mc, "mcp_iterate_dataset_size", lambda: 50_000)
    out = mc.run_solution(path="runquery_agent.rs", query_id=1, ws=tmp_path)
    assert out["ok"] is True
    assert seen == [50_000]
