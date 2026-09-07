"""Unit tests for measure_core harness timeout wiring."""
from __future__ import annotations

from concurrent import futures
from pathlib import Path
from typing import Self

import pytest

from db_extension.agent import measure_core as mc
from db_extension.optimizer import harness_timeout_sec


def test_measure_core_harness_timeout_matches_optimizer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "config.env"
    cfg.write_text("COMPILE_TIMEOUT_SEC=180\nVERUS_VERIFY_TIMEOUT_SEC=60\n")
    monkeypatch.setattr(mc, "CONFIG_ENV", cfg)
    expected = harness_timeout_sec(config_env_path=str(cfg))
    assert mc._harness_timeout_sec() == expected
    assert expected == 300


def test_invoke_harness_future_timeout_raises_timeout_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mc, "_harness_timeout_sec", lambda: 42)

    class FakeFuture:
        def result(self, timeout: int | None = None) -> dict:
            raise futures.TimeoutError()

    class FakePool:
        def __init__(self, max_workers: int = 1) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def submit(self, *args: object, **kwargs: object) -> FakeFuture:
            return FakeFuture()

    monkeypatch.setattr(mc.futures, "ThreadPoolExecutor", FakePool)

    with pytest.raises(TimeoutError, match=r"after 42s"):
        mc._invoke_harness(
            query_id=1,
            dataset_size=1000,
            ws=tmp_path,
            sql="SELECT 1",
            schema={"V": "int"},
        )


def test_run_solution_harness_timeout_surfaces_numeric_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    rq = tmp_path / "runquery_agent.rs"
    rq.write_text("stub")

    monkeypatch.setattr(
        mc,
        "validate_solution",
        lambda **kwargs: {"ok": True, "runquery_path": str(rq)},
    )
    monkeypatch.setattr(mc, "_harness_timeout_sec", lambda: 42)

    def raise_timeout(**kwargs: object) -> tuple[dict, int]:
        raise TimeoutError("harness timed out after 42s")

    monkeypatch.setattr(mc, "_invoke_harness", raise_timeout)

    out = mc.run_solution(path="runquery_agent.rs", query_id=1, ws=tmp_path)
    assert out["ok"] is False
    assert out["phase"] == "harness"
    assert out["errors"] == ["harness timed out after 42s"]
    assert "90s" not in out["errors"][0]
