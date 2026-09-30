"""Unit tests for optimizer timed-success stop helper."""
from __future__ import annotations

import os
from pathlib import Path

from db_extension.optimizer import (
    agent_meta_from_workspace_submit,
    harness_timeout_sec,
    is_timed_verified_success,
    official_measure_timeout_sec,
    _maybe_stop_on_timed_success,
)

_OPTIMIZER_PY = Path(__file__).resolve().parents[1] / "optimizer.py"


def test_harness_timeout_sec_defaults() -> None:
    env = os.environ
    old_compile = env.pop("COMPILE_TIMEOUT_SEC", None)
    old_verify = env.pop("VERUS_VERIFY_TIMEOUT_SEC", None)
    try:
        assert harness_timeout_sec(config_env_path="/nonexistent") == max(180, 120) + 120
    finally:
        if old_compile is not None:
            env["COMPILE_TIMEOUT_SEC"] = old_compile
        if old_verify is not None:
            env["VERUS_VERIFY_TIMEOUT_SEC"] = old_verify


def test_harness_timeout_sec_config_env_file(tmp_path: Path) -> None:
    env = os.environ
    old_compile = env.pop("COMPILE_TIMEOUT_SEC", None)
    old_verify = env.pop("VERUS_VERIFY_TIMEOUT_SEC", None)
    cfg = tmp_path / "config.env"
    cfg.write_text("COMPILE_TIMEOUT_SEC=180\n# verify uses default\n")
    try:
        assert harness_timeout_sec(config_env_path=str(cfg)) == 300
    finally:
        if old_compile is not None:
            env["COMPILE_TIMEOUT_SEC"] = old_compile
        if old_verify is not None:
            env["VERUS_VERIFY_TIMEOUT_SEC"] = old_verify


def test_harness_timeout_sec_env_override() -> None:
    env = os.environ
    old_compile = env.get("COMPILE_TIMEOUT_SEC")
    old_verify = env.get("VERUS_VERIFY_TIMEOUT_SEC")
    env["COMPILE_TIMEOUT_SEC"] = "200"
    env["VERUS_VERIFY_TIMEOUT_SEC"] = "90"
    try:
        assert harness_timeout_sec(config_env_path="/nonexistent") == 320
    finally:
        if old_compile is None:
            env.pop("COMPILE_TIMEOUT_SEC", None)
        else:
            env["COMPILE_TIMEOUT_SEC"] = old_compile
        if old_verify is None:
            env.pop("VERUS_VERIFY_TIMEOUT_SEC", None)
        else:
            env["VERUS_VERIFY_TIMEOUT_SEC"] = old_verify


def test_optimizer_timeout_message_uses_dynamic_harness_timeout() -> None:
    text = _OPTIMIZER_PY.read_text(encoding="utf-8")
    assert "after 90s" not in text
    assert "after {harness_timeout}s" in text


def test_is_timed_verified_success_happy_path() -> None:
    assert is_timed_verified_success(
        {
            "status": "SUCCESS",
            "proof_verified": True,
            "latency_us": 8,
            "bench_skipped": False,
        }
    )


def test_is_timed_verified_success_rejects_bench_skipped() -> None:
    assert not is_timed_verified_success(
        {
            "status": "SUCCESS",
            "proof_verified": True,
            "latency_us": 8,
            "bench_skipped": True,
        }
    )


def test_is_timed_verified_success_rejects_instant() -> None:
    assert not is_timed_verified_success(
        {
            "status": "SUCCESS",
            "proof_verified": True,
            "latency_us": 0,
            "bench_skipped": False,
        }
    )


def test_is_timed_verified_success_rejects_untimed() -> None:
    assert not is_timed_verified_success(
        {
            "status": "SUCCESS",
            "proof_verified": True,
            "latency_us": -1,
        }
    )


def test_is_timed_verified_success_rejects_verify_fail() -> None:
    assert not is_timed_verified_success(
        {
            "status": "SUCCESS",
            "proof_verified": False,
            "latency_us": 8,
        }
    )


def test_is_timed_verified_success_rejects_failure_status() -> None:
    assert not is_timed_verified_success(
        {
            "status": "FAILURE",
            "proof_verified": True,
            "latency_us": 8,
        }
    )


def test_agent_meta_from_workspace_submit(tmp_path: Path) -> None:
    assert agent_meta_from_workspace_submit(tmp_path) is None
    submitted = tmp_path / "mcp_results" / "submitted.json"
    submitted.parent.mkdir(parents=True, exist_ok=True)
    submitted.write_text(
        '{"run_id": "r1", "ok": true, "latency_us": 66, '
        '"metrics": {"status": "SUCCESS", "proof_verified": true, "latency_us": 66}}\n'
    )
    meta = agent_meta_from_workspace_submit(tmp_path)
    assert meta is not None
    assert meta["ok"] is True
    assert meta["submitted_run_id"] == "r1"
    assert meta["submitted_metrics"]["proof_verified"] is True
    assert meta["latency_us"] == 66


_TIMED_SUCCESS = {
    "status": "SUCCESS",
    "proof_verified": True,
    "latency_us": 8,
    "bench_skipped": False,
}


def test_maybe_stop_on_timed_success_false_by_default(monkeypatch) -> None:
    monkeypatch.delenv("LEMMA_STOP_ON_TIMED_SUCCESS", raising=False)
    monkeypatch.delenv("LEMMA_KEEP_OPTIMIZING", raising=False)
    assert _maybe_stop_on_timed_success(metrics=_TIMED_SUCCESS, iteration=1) is False


def test_maybe_stop_on_timed_success_true_with_stop_flag(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_STOP_ON_TIMED_SUCCESS", "1")
    monkeypatch.delenv("LEMMA_KEEP_OPTIMIZING", raising=False)
    assert _maybe_stop_on_timed_success(metrics=_TIMED_SUCCESS, iteration=1) is True


def test_maybe_stop_on_timed_success_keep_wins_over_stop(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_STOP_ON_TIMED_SUCCESS", "1")
    monkeypatch.setenv("LEMMA_KEEP_OPTIMIZING", "1")
    assert _maybe_stop_on_timed_success(metrics=_TIMED_SUCCESS, iteration=1) is False


def test_official_measure_timeout_at_least_harness(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_BENCH_TIMEOUT_SEC", "600")
    monkeypatch.setenv("COMPILE_TIMEOUT_SEC", "180")
    monkeypatch.setenv("VERUS_VERIFY_TIMEOUT_SEC", "120")
    harness = harness_timeout_sec(config_env_path="/nonexistent")
    assert official_measure_timeout_sec(config_env_path="/nonexistent") >= harness
    assert official_measure_timeout_sec(config_env_path="/nonexistent") >= 600
