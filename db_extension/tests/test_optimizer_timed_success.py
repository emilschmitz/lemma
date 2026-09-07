"""Unit tests for optimizer timed-success stop helper."""
from __future__ import annotations

from db_extension.optimizer import is_timed_verified_success


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
