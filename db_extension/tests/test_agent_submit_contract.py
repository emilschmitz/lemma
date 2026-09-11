"""Agent session contract: verify ≠ submit; submit is frozen verified body only.

Real agents may run_runquery without submitting. After the process exits, the host
must official-measure a marked verified snapshot or fail. Leftover runquery is
never assembled. This is not the old host-codegen / transpile suite.
"""
from __future__ import annotations

import json
from pathlib import Path

from db_extension.agent import measure_core as mc
from db_extension.agent.extract import wrap_body_with_markers
from db_extension.agent.mcp_tool_registry import dispatch_host_tool
from db_extension.agent.measure_core import MeasureContext
from db_extension.optimizer import (
    agent_meta_from_workspace_submit,
    post_agent_next_step,
    should_assemble_leftover_after_agent,
)
from research_loop.scripts.classify_product_failures import classify_optimizer_log
from verus_transpiler import transpile_sql_to_verus


def _write_workspace_spec(ws: Path) -> None:
    ro = ws / "context" / "ro"
    ro.mkdir(parents=True)
    spec = transpile_sql_to_verus("SELECT SUM(V) FROM t", {"V": "bigint"})
    (ro / "spec.rs").write_text(spec, encoding="utf-8")
    (ro / "query.sql").write_text("SELECT SUM(V) FROM t", encoding="utf-8")
    (ro / "schema.json").write_text('{"V": "bigint"}', encoding="utf-8")


def _store_run(ws: Path, record: dict) -> None:
    mc.runs_dir(ws).mkdir(parents=True, exist_ok=True)
    rid = record["run_id"]
    (mc.runs_dir(ws) / f"{rid}.json").write_text(json.dumps(record) + "\n")


def _verified(run_id: str, body: str, **extra: object) -> dict:
    rec = {
        "ok": True,
        "run_id": run_id,
        "metrics": {"status": "SUCCESS", "proof_verified": True, "latency_us": 10},
        "latency_us": 10,
        "dataset_size": 50_000,
        "runquery_body": body,
        "runquery_sha256": mc.runquery_sha256(body),
    }
    rec.update(extra)
    return rec


def _fake_ok_harness():
    def fake(*, query_id: int, dataset_size: int, ws: Path, sql=None, schema=None):
        return (
            {"status": "SUCCESS", "proof_verified": True, "latency_us": 50, "compiler_error": ""},
            0,
        )

    return fake


def test_post_agent_verify_without_submit_is_fail_not_leftover() -> None:
    assert post_agent_next_step(use_mock=False, submitted=None) == "no_submit_fail"
    assert should_assemble_leftover_after_agent(use_mock=False, submitted=None) is False


def test_post_agent_empty_or_unverified_mark_is_fail() -> None:
    assert post_agent_next_step(use_mock=False, submitted={}) == "no_submit_fail"
    assert post_agent_next_step(use_mock=False, submitted={"ok": True}) == "no_submit_fail"
    assert (
        post_agent_next_step(
            use_mock=False,
            submitted={"ok": False, "runquery_body": "x", "runquery_sha256": "ab"},
        )
        == "no_submit_fail"
    )


def test_post_agent_verified_mark_is_official_measure_not_leftover() -> None:
    body = "// winner\n"
    submitted = {
        "ok": True,
        "runquery_body": body,
        "runquery_sha256": mc.runquery_sha256(body),
    }
    assert post_agent_next_step(use_mock=False, submitted=submitted) == "official_measure"
    assert should_assemble_leftover_after_agent(use_mock=False, submitted=submitted) is False


def test_post_agent_mock_may_assemble_leftover() -> None:
    assert post_agent_next_step(use_mock=True, submitted=None) == "assemble_leftover"
    assert should_assemble_leftover_after_agent(use_mock=True, submitted=None) is True


def test_run_runquery_success_does_not_mark_submit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    _write_workspace_spec(tmp_path)
    (tmp_path / "runquery_agent.rs").write_text(wrap_body_with_markers("let x = 1;"))
    monkeypatch.setattr(mc, "_invoke_harness", _fake_ok_harness())
    out = mc.run_solution(path="runquery_agent.rs", query_id=1, dataset_size=100, ws=tmp_path)
    assert out["ok"] is True
    assert out["runquery_sha256"]
    assert mc.get_submitted(ws=tmp_path) is None
    assert post_agent_next_step(use_mock=False, submitted=None) == "no_submit_fail"


def test_run_runquery_then_submit_uses_frozen_hash(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    _write_workspace_spec(tmp_path)
    (tmp_path / "runquery_agent.rs").write_text(wrap_body_with_markers("let x = 1;"))
    monkeypatch.setattr(mc, "_invoke_harness", _fake_ok_harness())
    out = mc.run_solution(path="runquery_agent.rs", query_id=1, dataset_size=100, ws=tmp_path)
    frozen = out["runquery_body"]
    (tmp_path / "runquery_agent.rs").write_text("// leftover unbalanced {\n", encoding="utf-8")
    marked = mc.mark_submit(out["run_id"], ws=tmp_path)
    assert marked["ok"] is True
    submitted = mc.get_submitted(ws=tmp_path)
    assert submitted is not None
    assert submitted["runquery_body"] == frozen
    assert "{" not in submitted["runquery_body"] or "leftover" not in submitted["runquery_body"]
    assert "leftover" not in submitted["runquery_body"]
    assert submitted["runquery_sha256"] == out["runquery_sha256"]
    assert post_agent_next_step(use_mock=False, submitted=submitted) == "official_measure"


def test_submit_rejects_ok_false_even_if_proof_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    body = "// x\n"
    rec = _verified("r_okfalse", body, ok=False)
    rec["metrics"]["proof_verified"] = True
    _store_run(tmp_path, rec)
    out = mc.mark_submit("r_okfalse", ws=tmp_path)
    assert out["ok"] is False
    assert "not verified" in out["error"]


def test_submit_rejects_proof_false_even_if_ok(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    rec = {
        "ok": True,
        "run_id": "r_noproof",
        "metrics": {"status": "FAILURE", "proof_verified": False, "latency_us": -1},
        "runquery_body": "// x\n",
        "runquery_sha256": mc.runquery_sha256("// x\n"),
    }
    _store_run(tmp_path, rec)
    out = mc.mark_submit("r_noproof", ws=tmp_path)
    assert out["ok"] is False
    assert "not verified" in out["error"]


def test_submit_rejects_corrupt_frozen_hash(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    rec = _verified("r_badhash", "// body\n")
    rec["runquery_sha256"] = "0" * 64
    _store_run(tmp_path, rec)
    out = mc.mark_submit("r_badhash", ws=tmp_path)
    assert out["ok"] is False
    assert "corrupt" in out["error"]


def test_submit_rejects_empty_frozen_body(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    rec = _verified("r_empty", "x")
    rec["runquery_body"] = ""
    _store_run(tmp_path, rec)
    out = mc.mark_submit("r_empty", ws=tmp_path)
    assert out["ok"] is False
    assert "missing frozen" in out["error"]


def test_timeout_run_is_not_submittable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    _write_workspace_spec(tmp_path)
    (tmp_path / "runquery_agent.rs").write_text(wrap_body_with_markers("let x = 1;"))

    def boom(*, query_id: int, dataset_size: int, ws: Path, sql=None, schema=None):
        raise TimeoutError("harness timed out after 1s")

    monkeypatch.setattr(mc, "_invoke_harness", boom)
    out = mc.run_solution(path="runquery_agent.rs", query_id=1, ws=tmp_path)
    assert out["ok"] is False
    assert "runquery_body" not in out
    reject = mc.mark_submit(out["run_id"], ws=tmp_path)
    assert reject["ok"] is False
    assert "not verified" in reject["error"]


def test_two_verifies_submit_either_run_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    _write_workspace_spec(tmp_path)
    monkeypatch.setattr(mc, "_invoke_harness", _fake_ok_harness())
    (tmp_path / "runquery_agent.rs").write_text(wrap_body_with_markers("let a = 1;"))
    first = mc.run_solution(path="runquery_agent.rs", query_id=1, dataset_size=10, ws=tmp_path)
    (tmp_path / "runquery_agent.rs").write_text(wrap_body_with_markers("let b = 2;"))
    second = mc.run_solution(path="runquery_agent.rs", query_id=1, dataset_size=10, ws=tmp_path)
    assert first["runquery_sha256"] != second["runquery_sha256"]
    assert mc.mark_submit(second["run_id"], ws=tmp_path)["ok"] is True
    assert mc.get_submitted(ws=tmp_path)["runquery_body"] == second["runquery_body"]
    assert mc.mark_submit(first["run_id"], ws=tmp_path)["ok"] is True
    assert mc.get_submitted(ws=tmp_path)["runquery_body"] == first["runquery_body"]
    assert mc.get_submitted(ws=tmp_path)["run_id"] == first["run_id"]


def test_dispatch_submit_rejects_unverified(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    _store_run(
        tmp_path,
        {
            "ok": False,
            "run_id": "bad",
            "metrics": {"proof_verified": False},
        },
    )
    ctx = MeasureContext(query_id=1, workspace=tmp_path)
    out = dispatch_host_tool("submit_runquery", {"run_id": "bad"}, ctx)
    assert out["ok"] is False
    assert "not verified" in out.get("error", "")


def test_dispatch_submit_missing_run_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    ctx = MeasureContext(query_id=1, workspace=tmp_path)
    out = dispatch_host_tool("submit_runquery", {}, ctx)
    assert out["ok"] is False
    assert "run_id" in out.get("error", "")


def test_dispatch_submit_verified_then_get(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    body = "// verified via mcp\n"
    _store_run(tmp_path, _verified("okrun", body))
    ctx = MeasureContext(query_id=1, workspace=tmp_path)
    out = dispatch_host_tool("submit_runquery", {"run_id": "okrun"}, ctx)
    assert out["ok"] is True
    got = dispatch_host_tool("get_submit_result", {}, ctx)
    assert got["ok"] is True
    assert got["submitted"]["runquery_body"] == body


def test_workspace_meta_from_submit_does_not_use_leftover_file(tmp_path: Path) -> None:
    (tmp_path / "runquery_agent.rs").write_text("// leftover {\n", encoding="utf-8")
    body = "// frozen verified\n"
    submitted = {
        "ok": True,
        "run_id": "r1",
        "metrics": {"status": "SUCCESS", "proof_verified": True, "latency_us": 3},
        "latency_us": 3,
        "runquery_body": body,
        "runquery_sha256": mc.runquery_sha256(body),
    }
    mc.results_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    (mc.results_dir(tmp_path) / "submitted.json").write_text(json.dumps(submitted) + "\n")
    meta = agent_meta_from_workspace_submit(tmp_path)
    assert meta is not None
    assert meta["runquery_body"] == body
    assert "leftover" not in meta["runquery_body"]
    assert post_agent_next_step(use_mock=False, submitted=mc.get_submitted(ws=tmp_path)) == (
        "official_measure"
    )


def test_classify_no_marked_submit_is_not_agent_step() -> None:
    log = (
        "  - Running agent in Docker sandbox... OK (10 s)\n"
        "FAILED\n"
        "    no marked submit\n"
        "proof_verified=False latency_us=-1\n"
        'LEMMA_METRICS_JSON: {"status": "FAILURE", "proof_verified": false, '
        '"latency_us": -1, "compiler_error": "no marked submit"}\n'
    )
    out = classify_optimizer_log(log)
    assert out["class"] == "infra"
    assert out["step"] == 5
    assert "unclassified" in out.get("detail", "")
