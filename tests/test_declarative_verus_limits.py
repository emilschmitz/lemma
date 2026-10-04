"""The host's Verus rlimit and wall timeout are explicit config, and a timeout is not a proof error."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from declarative_spec import pipeline
from declarative_spec.verus_limits import (
    DEFAULT_RLIMIT,
    DEFAULT_TIMEOUT_SEC,
    RLIMIT_ENV,
    TIMEOUT_ENV,
    failure_prefix,
    timeout_message,
    verus_limit_args,
    verus_rlimit,
    verus_timeout_sec,
)


def _fake_verus(tmp_path: Path, script: str) -> str:
    path = tmp_path / "fake_verus"
    path.write_text("#!/usr/bin/env python3\nimport sys, time\n" + script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


# ---- rlimit config ----------------------------------------------------------------------


def test_rlimit_and_timeout_defaults_and_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(RLIMIT_ENV, raising=False)
    monkeypatch.delenv(TIMEOUT_ENV, raising=False)
    assert verus_rlimit() == DEFAULT_RLIMIT
    assert verus_timeout_sec() == DEFAULT_TIMEOUT_SEC
    assert verus_limit_args() == ["--rlimit", f"{DEFAULT_RLIMIT:g}"]
    monkeypatch.setenv(RLIMIT_ENV, "0.5")
    monkeypatch.setenv(TIMEOUT_ENV, "42")
    assert verus_limit_args() == ["--rlimit", "0.5"]
    assert verus_timeout_sec() == 42


@pytest.mark.parametrize("name,bad", [(RLIMIT_ENV, "fast"), (RLIMIT_ENV, "0"), (TIMEOUT_ENV, "-3"), (TIMEOUT_ENV, "1.5s")])
def test_a_bad_limit_fails_loudly(monkeypatch: pytest.MonkeyPatch, name: str, bad: str) -> None:
    monkeypatch.setenv(name, bad)
    with pytest.raises(ValueError):
        verus_rlimit() if name == RLIMIT_ENV else verus_timeout_sec()


def test_the_rlimit_reaches_the_verus_command_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_verus(tmp_path, "print(' '.join(sys.argv[1:]))\nprint('verification results:: 1 verified, 0 errors')\nsys.exit(1)\n")
    monkeypatch.setattr(pipeline, "_verus_binary", lambda: fake)
    monkeypatch.setenv(RLIMIT_ENV, "2.5")
    metrics = pipeline.compile_and_run("// program", work_dir=tmp_path / "w")
    assert "--rlimit 2.5" in metrics["verify_msg"]
    assert "--compile" in metrics["verify_msg"]


# ---- timeout versus proof error ---------------------------------------------------------


def test_wall_timeout_during_verification_is_labelled_not_a_proof_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_verus(tmp_path, "print('verifying...', flush=True)\ntime.sleep(30)\n")
    monkeypatch.setattr(pipeline, "_verus_binary", lambda: fake)
    metrics = pipeline.compile_and_run("// program", work_dir=tmp_path / "w", timeout_sec=1)
    assert metrics["status"] == "FAILURE" and metrics["proof_verified"] is False
    assert metrics["compiler_error"].startswith("VERIFY TIMEOUT")
    assert "not a proof error" in metrics["compiler_error"]


def test_wall_timeout_after_verification_is_a_compile_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_verus(
        tmp_path, "print('verification results:: 17 verified, 0 errors', flush=True)\ntime.sleep(30)\n"
    )
    monkeypatch.setattr(pipeline, "_verus_binary", lambda: fake)
    metrics = pipeline.compile_and_run("// program", work_dir=tmp_path / "w", timeout_sec=1)
    assert metrics["compiler_error"].startswith("COMPILE TIMEOUT")


def test_verify_assembled_timeout_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_verus(tmp_path, "time.sleep(30)\n")
    monkeypatch.setattr(pipeline, "_verus_binary", lambda: fake)
    ok, out = pipeline.verify_assembled("// program", timeout_sec=1)
    assert not ok and out.startswith("VERIFY TIMEOUT")


def test_timeout_message_names_the_phase() -> None:
    assert timeout_message("", 9).startswith("VERIFY TIMEOUT")
    assert timeout_message("verification results:: 1 verified, 0 errors", 9).startswith("COMPILE TIMEOUT")


def test_rlimit_failure_is_labelled_a_proof_error_not_a_timeout() -> None:
    log = (
        "error: while loop: Resource limit (rlimit) exceeded; consider rerunning with --profile\n"
        "error: function body check: Resource limit (rlimit) exceeded; consider rerunning with --profile\n"
        "verification results:: 12 verified, 2 errors\n"
    )
    prefix = failure_prefix(log)
    assert prefix.startswith("RLIMIT: Z3 ran out of resources on 2 query")
    assert "not a wall timeout" in prefix


def test_plain_proof_failure_is_labelled_with_the_verus_summary() -> None:
    log = "error: assertion failed\nverification results:: 15 verified, 2 errors\n"
    assert failure_prefix(log) == "PROOF ERROR: verification results:: 15 verified, 2 errors.\n"
    assert failure_prefix("error[E0425]: cannot find value") == ""
