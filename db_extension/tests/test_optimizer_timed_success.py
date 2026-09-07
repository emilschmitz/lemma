"""Unit tests for optimizer timed-success stop helper."""
from __future__ import annotations

import os
from pathlib import Path

from db_extension.optimizer import harness_timeout_sec, is_timed_verified_success

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
