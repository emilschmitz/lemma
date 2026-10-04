"""Verus is started with the source file's directory as cwd for compile.

A relative path is then resolved inside that directory and rustc reports
``cannot find directory for source file``. Both verify and compile must pass
an absolute path.
"""

from __future__ import annotations

import os

from research_loop.harness import run_verus_compile, run_verus_verify


class _Result:
    returncode = 1
    stdout = ""
    stderr = "stopped by test"


def test_verify_passes_an_absolute_source_path(tmp_path, monkeypatch) -> None:
    recorded: dict = {}

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        recorded["cwd"] = kwargs.get("cwd")
        return _Result()

    rs = tmp_path / "custom_query.rs"
    rs.write_text("fn main() {}\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("research_loop.harness.resolve_verus_bin", lambda: "/bin/verus")
    monkeypatch.setattr("research_loop.harness.subprocess.run", fake_run)
    run_verus_verify("custom_query.rs", timeout=5)
    assert os.path.isabs(recorded["cmd"][1])
    assert recorded["cmd"][1] == str(rs)


def test_compile_passes_an_absolute_source_path_when_cwd_is_the_source_dir(
    tmp_path, monkeypatch
) -> None:
    recorded: dict = {}

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        recorded["cwd"] = kwargs.get("cwd")
        return _Result()

    nested = tmp_path / "workspace"
    nested.mkdir()
    rs = nested / "custom_query.rs"
    rs.write_text("fn main() {}\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("research_loop.harness.resolve_verus_bin", lambda: "/bin/verus")
    monkeypatch.setattr("research_loop.harness.subprocess.run", fake_run)
    run_verus_compile(os.path.join("workspace", "custom_query.rs"), timeout=5)
    assert recorded["cwd"] == str(nested)
    assert os.path.isabs(recorded["cmd"][1])
    assert recorded["cmd"][1] == str(rs)
    assert "workspace" not in os.path.relpath(recorded["cmd"][1], recorded["cwd"])
