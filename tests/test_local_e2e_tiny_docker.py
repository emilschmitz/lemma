"""Local SEC tiny Docker e2e harness: SQL shell checks + host pipeline + optional live agent."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.column_projection import project_multi_schema_for_query

from research_loop.method_spec_ret_type import (
    parse_method_spec_return_type,
    resolve_ret_type_from_method_spec,
)
from research_loop.scripts.local_e2e_tiny_docker import (
    SQL_FILE,
    docker_preflight_error,
    load_tiny_queries,
    repo_root,
    run_local_e2e,
    select_query_ids,
)
from research_loop.scripts.sqlsmith_trusted_coverage import (
    classify_query,
    load_sec_schema,
)
from research_loop.trusted_ret_bridge import bridge_from_method_spec_type, get_bridge
from tests.test_sec_holdout_parse import SEC_SCHEMA

ROOT = repo_root()
TINY_DB = ROOT / "holdout/gendb_sec_edgar/duckdb/sec_edgar_tiny.duckdb"
LIBDUCKDB = ROOT / "build/libduckdb/libduckdb.so"

Q1_SQL = load_tiny_queries()["Q1"]
Q3_SQL = load_tiny_queries()["Q3"]


def _catalog_for_qid(qid: str) -> dict:
    schema = load_sec_schema()
    if qid == "Q1":
        return {"pre": schema["pre"]}
    return {"num": schema["num"], "pre": schema["pre"]}


def _stub_run_query(ret_type: str, *, multi: bool = False) -> str:
    bridge = get_bridge(ret_type)
    if bridge is None:
        qid = "Q3" if multi else "Q1"
        catalog = _catalog_for_qid(qid)
        projected = (
            project_multi_schema_for_query(load_tiny_queries()[qid], catalog)
            if multi
            else {"pre": catalog["pre"]}
        )
        spec_rs = transpile_sql_to_verus(load_tiny_queries()[qid], projected)
        bridge = bridge_from_method_spec_type(parse_method_spec_return_type(spec_rs))
    body = bridge.default_stub
    if "HashMap" in bridge.rust_ret and body == "HashMapWithView::new()":
        stub_expr = "HashMapWithView::new()"
    elif bridge.rust_ret.startswith("Vec"):
        stub_expr = "Vec::new()"
    else:
        stub_expr = body
    ensures = bridge.ensures.rstrip().removesuffix(",")
    if multi:
        ensures = ensures.replace("method_spec(cols)", "method_spec(cols, pre)")
        return f"""#[verifier::external_body]
pub exec fn run_query(cols: &Cols, pre: &Cols_pre) -> (res: {bridge.rust_ret})
    requires valid_cols(cols) && valid_cols_pre(pre),
    ensures {ensures},
{{
    {stub_expr}
}}"""
    return f"""#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: {bridge.rust_ret})
    requires valid_cols(cols),
    ensures {ensures},
{{
    {stub_expr}
}}"""


@pytest.mark.parametrize("qid", ["Q1", "Q2", "Q3"])
def test_tiny_queries_ok_shell(qid: str) -> None:
    queries = load_tiny_queries()
    sql = queries[qid]
    catalog = _catalog_for_qid(qid)
    result = classify_query(sql, qid, catalog)
    assert result.status == "ok_shell", f"{qid}: {result.status} {result.reason}"
    projected = (
        project_multi_schema_for_query(sql, catalog)
        if qid != "Q1"
        else {"pre": catalog["pre"]}
    )
    spec_rs = transpile_sql_to_verus(sql, projected)
    assert "method_spec" in spec_rs
    assert "arbitrary()" not in spec_rs
    assert resolve_ret_type_from_method_spec(spec_rs)


def test_select_query_ids_defaults_to_q1() -> None:
    assert select_query_ids([]) == ["Q1"]
    assert select_query_ids(["all"]) == ["Q1", "Q2", "Q3"]
    assert select_query_ids(["Q1", "Q3"]) == ["Q1", "Q3"]


def test_preflight_fails_loud_without_docker(tmp_path: Path) -> None:
    msg = docker_preflight_error(str(tmp_path))
    assert msg is not None
    assert "docker" in msg.lower()
    assert "USE_AGENT_DOCKER" in msg


def test_preflight_fails_loud_when_docker_sock_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\nexit 1\n")
    docker.chmod(0o755)

    def fake_run(args, **kwargs):
        combined = " ".join(str(a) for a in args)
        if "info" in combined:
            return subprocess.CompletedProcess(
                args,
                1,
                "",
                "permission denied while trying to connect to the docker API at unix:///var/run/docker.sock",
            )
        raise AssertionError(f"unexpected subprocess: {args}")

    monkeypatch.setattr(
        "research_loop.scripts.local_e2e_tiny_docker.subprocess.run",
        fake_run,
    )
    msg = docker_preflight_error(str(tmp_path))
    assert msg is not None
    assert "permission denied" in msg.lower()
    assert "newgrp docker" in msg


def test_run_local_e2e_preflight_exits_without_docker(tmp_path: Path) -> None:
    _, code = run_local_e2e(["Q1"], path_env=str(tmp_path), skip_docker_build=True)
    assert code != 0


def test_shell_script_preflight_without_docker(tmp_path: Path) -> None:
    script = ROOT / "research_loop/scripts/local_e2e_tiny_docker.sh"
    # Isolate docker off PATH without hiding bash/git (same dir as docker on many distros).
    for name in ("bash", "git", "dirname"):
        src = shutil.which(name)
        if src:
            dest = tmp_path / name
            if not dest.exists():
                dest.symlink_to(src)
    env = {**os.environ, "PATH": str(tmp_path)}
    proc = subprocess.run(
        [str(tmp_path / "bash"), str(script)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "docker" in combined.lower()
    assert "USE_AGENT_DOCKER" in combined


@pytest.mark.skipif(not TINY_DB.is_file(), reason="tiny SEC duckdb missing")
@pytest.mark.skipif(not LIBDUCKDB.is_file(), reason="libduckdb.so missing")
def test_q1_host_pipeline_verify_compile_pin_execute(tmp_path, monkeypatch) -> None:
    from research_loop.harness import resolve_verus_bin, run_custom_sql_pipeline

    if resolve_verus_bin() is None:
        pytest.skip("verus not found")

    monkeypatch.setenv("LEMMA_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(TINY_DB))
    monkeypatch.setenv("LEMMA_DUCKDB_LIB_DIR", str(LIBDUCKDB.parent))
    monkeypatch.setenv("ENABLE_VERUS_VERIFY", "1")
    monkeypatch.setenv("REQUIRE_PROOF", "1")
    monkeypatch.setenv("VERUS_VERIFY_TIMEOUT_SEC", "120")
    monkeypatch.setenv("COMPILE_TIMEOUT_SEC", "180")

    catalog = {"pre": SEC_SCHEMA["pre"]}
    projected = {"pre": catalog["pre"]}
    spec_rs = transpile_sql_to_verus(Q1_SQL, projected)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    res = run_custom_sql_pipeline(
        Q1_SQL,
        catalog,
        run_query_body=_stub_run_query(ret_type),
        skip_bench=False,
        workload="sec",
        duckdb_path=str(TINY_DB),
        limit=500,
    )
    assert res.get("stage") not in {"assemble", "verify", "transpile"}, res
    assert res.get("proof_verified") is True, res.get("verify_msg") or res.get("error")
    assert res.get("load_mode") == "duckdb", res
    assert res.get("latency_us", -1) >= 0, res.get("error") or res.get("bench_error")


@pytest.mark.skipif(not TINY_DB.is_file(), reason="tiny SEC duckdb missing")
@pytest.mark.skipif(not LIBDUCKDB.is_file(), reason="libduckdb.so missing")
def test_q3_host_pipeline_verify_compile_pin_execute(tmp_path, monkeypatch) -> None:
    from research_loop.harness import resolve_verus_bin, run_custom_sql_pipeline

    if resolve_verus_bin() is None:
        pytest.skip("verus not found")

    monkeypatch.setenv("LEMMA_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(TINY_DB))
    monkeypatch.setenv("LEMMA_DUCKDB_LIB_DIR", str(LIBDUCKDB.parent))
    monkeypatch.setenv("ENABLE_VERUS_VERIFY", "1")
    monkeypatch.setenv("REQUIRE_PROOF", "1")
    monkeypatch.setenv("VERUS_VERIFY_TIMEOUT_SEC", "120")
    monkeypatch.setenv("COMPILE_TIMEOUT_SEC", "180")

    catalog = {"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]}
    projected = project_multi_schema_for_query(Q3_SQL, catalog)
    spec_rs = transpile_sql_to_verus(Q3_SQL, projected)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    res = run_custom_sql_pipeline(
        Q3_SQL,
        catalog,
        run_query_body=_stub_run_query(ret_type, multi=True),
        skip_bench=False,
        workload="sec",
        duckdb_path=str(TINY_DB),
        limit=500,
    )
    assert res.get("stage") not in {"assemble", "verify", "transpile"}, res
    assert res.get("proof_verified") is True, res.get("verify_msg") or res.get("error")
    assert res.get("load_mode") == "duckdb", res
    assert res.get("latency_us", -1) >= 0, res.get("error") or res.get("bench_error")


def _docker_image_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    proc = subprocess.run(
        ["docker", "image", "inspect", "lemma-agent:cli"],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


@pytest.mark.skipif(
    shutil.which("docker") is None or not _docker_image_ready(),
    reason="docker or lemma-agent:cli image missing",
)
@pytest.mark.skipif(
    os.environ.get("LEMMA_LIVE_DOCKER_E2E") != "1",
    reason="set LEMMA_LIVE_DOCKER_E2E=1 to run live Docker agent e2e",
)
def test_live_docker_agent_q1() -> None:
    _, code = run_local_e2e(["Q1"])
    assert code == 0


def test_sql_file_exists_and_has_three_queries() -> None:
    assert SQL_FILE.is_file()
    queries = load_tiny_queries()
    assert set(queries) == {"Q1", "Q2", "Q3"}
