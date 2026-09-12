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


def _verified_run_record(
    *,
    run_id: str,
    body: str,
    rq_path: Path,
    ok: bool = True,
    proof_verified: bool = True,
) -> dict:
    record = {
        "ok": ok,
        "run_id": run_id,
        "metrics": {
            "status": "SUCCESS" if proof_verified else "FAILURE",
            "proof_verified": proof_verified,
            "latency_us": 42,
        },
        "latency_us": 42,
        "dataset_size": 50_000,
        "runquery_path": str(rq_path),
    }
    if ok and proof_verified:
        record["runquery_body"] = body
        record["runquery_sha256"] = mc.runquery_sha256(body)
    return record


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


def test_mark_submit_rejects_probe_dataset_size(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(mc, "mcp_iterate_dataset_size", lambda: 50_000)
    run_id = "probe_run"
    rq = tmp_path / "runquery_agent.rs"
    body = "// probe body\nlet x = 1;"
    rq.write_text(body, encoding="utf-8")
    record = _verified_run_record(run_id=run_id, body=body, rq_path=rq)
    record["dataset_size"] = 8
    mc.runs_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    (mc.runs_dir(tmp_path) / f"{run_id}.json").write_text(json.dumps(record))

    out = mc.mark_submit(run_id, ws=tmp_path)
    assert out["ok"] is False
    assert "probe pin" in out["error"]
    assert "without dataset_size" in out["error"]
    assert mc.get_submitted(ws=tmp_path) is None


def test_mark_submit_accepts_iterate_cap_dataset_size(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(mc, "mcp_iterate_dataset_size", lambda: 50_000)
    run_id = "full_run"
    rq = tmp_path / "runquery_agent.rs"
    body = "// full cap body\nlet x = 1;"
    rq.write_text(body, encoding="utf-8")
    record = _verified_run_record(run_id=run_id, body=body, rq_path=rq)
    record["dataset_size"] = 50_000
    mc.runs_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    (mc.runs_dir(tmp_path) / f"{run_id}.json").write_text(json.dumps(record))

    out = mc.mark_submit(run_id, ws=tmp_path)
    assert out["ok"] is True
    submitted = mc.get_submitted(ws=tmp_path)
    assert submitted is not None
    assert submitted["run_id"] == run_id


def test_mark_submit_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    run_id = "testrun001"
    rq = tmp_path / "runquery_agent.rs"
    body = "// winning body\nlet x = 1;"
    rq.write_text(body, encoding="utf-8")
    record = _verified_run_record(run_id=run_id, body=body, rq_path=rq)
    mc.runs_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    (mc.runs_dir(tmp_path) / f"{run_id}.json").write_text(json.dumps(record))

    marked = mc.mark_submit(run_id, ws=tmp_path)
    assert marked["ok"] is True
    submitted = mc.get_submitted(ws=tmp_path)
    assert submitted is not None
    assert submitted["run_id"] == run_id
    assert submitted["latency_us"] == 42
    assert submitted["runquery_body"] == body
    assert submitted["runquery_sha256"] == mc.runquery_sha256(body)
    assert submitted["iterate_dataset_size"] == 50_000


def test_run_solution_success_stores_body_and_sha256(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    _write_workspace_spec(tmp_path)
    (tmp_path / "runquery_agent.rs").write_text(wrap_body_with_markers("let x = 1;"))

    def fake_harness(*, query_id: int, dataset_size: int, ws: Path, sql=None, schema=None):
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
    assert out["runquery_body"]
    assert out["runquery_sha256"] == mc.runquery_sha256(out["runquery_body"])
    on_disk = json.loads((mc.runs_dir(tmp_path) / f"{out['run_id']}.json").read_text())
    assert on_disk["runquery_body"] == out["runquery_body"]
    assert on_disk["runquery_sha256"] == out["runquery_sha256"]
    file_text = (tmp_path / "runquery_agent.rs").read_text(encoding="utf-8")
    assert out["runquery_sha256"] == mc.runquery_sha256(file_text)


def test_run_solution_harness_fail_not_submission_ready(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    _write_workspace_spec(tmp_path)
    (tmp_path / "runquery_agent.rs").write_text(wrap_body_with_markers("let x = 1;"))

    def fake_harness(*, query_id: int, dataset_size: int, ws: Path, sql=None, schema=None):
        return (
            {
                "status": "FAILURE",
                "proof_verified": False,
                "latency_us": -1,
                "compiler_error": "verify failed",
            },
            1,
        )

    monkeypatch.setattr(mc, "_invoke_harness", fake_harness)
    out = mc.run_solution(path="runquery_agent.rs", query_id=1, ws=tmp_path)
    assert out["ok"] is False
    assert "runquery_body" not in out
    assert "runquery_sha256" not in out
    reject = mc.mark_submit(out["run_id"], ws=tmp_path)
    assert reject["ok"] is False
    assert "not verified" in reject["error"]


def test_mark_submit_rejects_unverified_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    run_id = "unverified1"
    rq = tmp_path / "runquery_agent.rs"
    body = "// body\nlet x = 1;"
    rq.write_text(body, encoding="utf-8")
    record = _verified_run_record(
        run_id=run_id, body=body, rq_path=rq, ok=False, proof_verified=False
    )
    record.pop("runquery_body", None)
    record.pop("runquery_sha256", None)
    mc.runs_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    (mc.runs_dir(tmp_path) / f"{run_id}.json").write_text(json.dumps(record))
    out = mc.mark_submit(run_id, ws=tmp_path)
    assert out["ok"] is False
    assert "not verified" in out["error"]


def test_mark_submit_rejects_missing_frozen_body(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    run_id = "legacy1"
    record = {
        "ok": True,
        "run_id": run_id,
        "metrics": {"status": "SUCCESS", "proof_verified": True, "latency_us": 1},
        "latency_us": 1,
    }
    mc.runs_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    (mc.runs_dir(tmp_path) / f"{run_id}.json").write_text(json.dumps(record))
    out = mc.mark_submit(run_id, ws=tmp_path)
    assert out["ok"] is False
    assert "missing frozen" in out["error"]


def test_mark_submit_uses_frozen_body_not_dirty_live_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    run_id = "frozen1"
    rq = tmp_path / "runquery_agent.rs"
    frozen = "// verified winner\nlet ok = 1;"
    rq.write_text(frozen, encoding="utf-8")
    record = _verified_run_record(run_id=run_id, body=frozen, rq_path=rq)
    mc.runs_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    (mc.runs_dir(tmp_path) / f"{run_id}.json").write_text(json.dumps(record))

    rq.write_text("// dirty leftover\nbroken();", encoding="utf-8")
    marked = mc.mark_submit(run_id, ws=tmp_path)
    assert marked["ok"] is True
    submitted = mc.get_submitted(ws=tmp_path)
    assert submitted is not None
    assert submitted["runquery_body"] == frozen
    assert "dirty leftover" not in submitted["runquery_body"]


def test_mark_submit_older_verified_run_overwrites_newer(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    rq = tmp_path / "runquery_agent.rs"
    first_body = "// first verified\nlet a = 1;"
    second_body = "// second verified\nlet b = 2;"
    rq.write_text(first_body, encoding="utf-8")
    first_id = "run_first"
    second_id = "run_second"
    mc.runs_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    (mc.runs_dir(tmp_path) / f"{first_id}.json").write_text(
        json.dumps(_verified_run_record(run_id=first_id, body=first_body, rq_path=rq))
    )
    rq.write_text(second_body, encoding="utf-8")
    (mc.runs_dir(tmp_path) / f"{second_id}.json").write_text(
        json.dumps(_verified_run_record(run_id=second_id, body=second_body, rq_path=rq))
    )

    assert mc.mark_submit(second_id, ws=tmp_path)["ok"] is True
    assert mc.mark_submit(first_id, ws=tmp_path)["ok"] is True
    submitted = mc.get_submitted(ws=tmp_path)
    assert submitted is not None
    assert submitted["run_id"] == first_id
    assert submitted["runquery_body"] == first_body


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
