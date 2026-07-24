"""Legacy dual-path harness: verify spec.rs + cargo unproved query.rs (debug only)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess

from research_loop.admit_runquery import admit_runquery_body
from research_loop.assemble_runquery import (
    assemble_query_rs,
    extract_agent_body,
    generate_main_rs,
)
from research_loop.benchmark_runqueries import RETURN_TYPES as SSB_RETURN_TYPES
from research_loop.benchmark_runqueries import RUNQUERIES as SSB_LEGACY_RUNQUERIES
from research_loop.exec_cols import generate_cols_exec_rs
from research_loop.harness import (  # noqa: E402
    BENCH_BARE_DIR,
    CURRENT_DIR,
    DEFAULT_SSB_TBL,
    ROOT_DIR,
    WORKING,
    bench_bare_ssb,
    bench_bare_tpch,
    load_env,
    resolve_verus_bin,
    run_binary,
    run_verus_verify,
    verus_on_path,
)
from research_loop._transpiler import project_schema_for_query, transpile_sql_to_verus
from research_loop.ssb_queries import load_schema, queries as ssb_queries
from research_loop.tpch_runqueries import (
    DEFAULT_TBL as DEFAULT_TPCH_TBL,
    RETURN_TYPES as TPCH_RETURN_TYPES,
    RUNQUERIES as TPCH_LEGACY_RUNQUERIES,
    queries as tpch_queries,
    schema as tpch_schema,
)


def _write_legacy(
    *,
    sql: str,
    schema: dict[str, str],
    runquery_body: str,
    ret_type: str,
    default_tbl: str,
) -> str:
    projected = project_schema_for_query(sql, schema)
    spec_rs = transpile_sql_to_verus(sql, projected, enable_templates=False)
    if "fn main()" not in spec_rs:
        spec_rs = spec_rs.rstrip() + "\n\nfn main() {}\n"
    cols_rs = generate_cols_exec_rs(projected)
    query_rs = assemble_query_rs(runquery_body, ret_type=ret_type)
    main_rs = generate_main_rs(default_tbl=default_tbl)

    src = os.path.join(WORKING, "src")
    os.makedirs(src, exist_ok=True)
    spec_path = os.path.join(src, "spec.rs")
    with open(os.path.join(src, "spec.rs"), "w") as f:
        f.write(spec_rs)
    with open(os.path.join(src, "cols.rs"), "w") as f:
        f.write(cols_rs)
    with open(os.path.join(src, "query.rs"), "w") as f:
        f.write(query_rs)
    with open(os.path.join(src, "main.rs"), "w") as f:
        f.write(main_rs)
    return spec_path


def cargo_build_release(manifest: str, timeout: int) -> tuple[bool, str]:
    env = os.environ.copy()
    env["RUSTFLAGS"] = "-C target-cpu=native"
    try:
        res = subprocess.run(
            ["cargo", "build", "--release", "--manifest-path", manifest],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return res.returncode == 0, (res.stdout + "\n" + res.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, f"cargo build timed out after {timeout}s"


def run_ssb_pipeline_legacy(
    query_idx: int,
    *,
    limit: int = 50_000,
    tbl: str | None = None,
    skip_bench: bool = False,
    skip_bare: bool = False,
) -> dict:
    cfg = load_env(os.path.join(CURRENT_DIR, "config.env"))
    for k, v in cfg.items():
        os.environ.setdefault(k, v)

    verify_timeout = int(os.environ.get("VERUS_VERIFY_TIMEOUT_SEC", "120"))
    compile_timeout = int(os.environ.get("COMPILE_TIMEOUT_SEC", "180"))
    enable_verify = os.environ.get("ENABLE_VERUS_VERIFY", "1") == "1"
    require_proof = os.environ.get(
        "REQUIRE_PROOF", "1" if enable_verify else "0"
    ) == "1"

    sql = ssb_queries[query_idx - 1]
    ret_type = SSB_RETURN_TYPES[query_idx]
    runquery_body = SSB_LEGACY_RUNQUERIES[query_idx]
    admission = admit_runquery_body(extract_agent_body(runquery_body))
    if not admission.ok:
        return {"status": "FAILURE", "error": "admission: " + "; ".join(admission.violations)}

    spec_path = _write_legacy(
        sql=sql,
        schema=load_schema(),
        runquery_body=runquery_body,
        ret_type=ret_type,
        default_tbl="ssb-dbgen/lineorder_flat.tbl",
    )

    proof_verified = False
    verify_msg = ""
    if enable_verify and verus_on_path():
        proof_verified, verify_msg = run_verus_verify(spec_path, verify_timeout)
        if not proof_verified and require_proof:
            return {
                "status": "FAILURE",
                "proof_verified": False,
                "error": "legacy: verus verify spec.rs failed",
                "verify_msg": verify_msg[:2000],
                "workload": "ssb",
                "query_key": query_idx,
                "query_label": f"SSB Q{query_idx}",
            }

    manifest = os.path.join(WORKING, "Cargo.toml")
    ok, build_msg = cargo_build_release(manifest, compile_timeout)
    if not ok:
        return {"status": "FAILURE", "error": f"legacy cargo build failed:\n{build_msg}"}

    result: dict = {
        "status": "SUCCESS",
        "proof_verified": proof_verified,
        "verify_msg": verify_msg + " (legacy: spec only)",
        "workload": "ssb",
        "query_key": query_idx,
        "query_label": f"SSB Q{query_idx}",
    }
    if skip_bench:
        return result

    tbl_path = tbl or DEFAULT_SSB_TBL
    if not os.path.exists(tbl_path):
        result["bench_skipped"] = True
        result["bench_msg"] = f"tbl missing: {tbl_path}"
        return result

    if not skip_bare:
        bare_us = bench_bare_ssb(query_idx, tbl_path, limit)
        if bare_us >= 0:
            result["bare_us"] = bare_us

    binary = os.path.join(WORKING, "target", "release", "working_query")
    latency, stdout, stderr = run_binary(binary, tbl_path, limit)
    result["latency_us"] = latency
    result["stdout"] = stdout
    if latency < 0:
        result["status"] = "FAILURE"
        result["error"] = f"no QUERY_LATENCY_US in output\n{stdout}\n{stderr}"
    return result


def run_tpch_pipeline_legacy(
    query_name: str,
    *,
    limit: int = 50_000,
    tbl: str | None = None,
    skip_bench: bool = False,
    skip_bare: bool = False,
) -> dict:
    qkey = query_name.upper()
    sql = tpch_queries[qkey]
    ret_type = TPCH_RETURN_TYPES[qkey]
    runquery_body = TPCH_LEGACY_RUNQUERIES[qkey]
    admission = admit_runquery_body(extract_agent_body(runquery_body))
    if not admission.ok:
        return {"status": "FAILURE", "error": "admission: " + "; ".join(admission.violations)}

    spec_path = _write_legacy(
        sql=sql,
        schema=dict(tpch_schema),
        runquery_body=runquery_body,
        ret_type=ret_type,
        default_tbl="data/tpch-sf1/lineitem.tbl",
    )

    verify_timeout = int(os.environ.get("VERUS_VERIFY_TIMEOUT_SEC", "120"))
    compile_timeout = int(os.environ.get("COMPILE_TIMEOUT_SEC", "180"))
    proof_verified = False
    verify_msg = ""
    if verus_on_path():
        proof_verified, verify_msg = run_verus_verify(spec_path, verify_timeout)

    manifest = os.path.join(WORKING, "Cargo.toml")
    ok, build_msg = cargo_build_release(manifest, compile_timeout)
    if not ok:
        return {"status": "FAILURE", "error": f"legacy cargo build failed:\n{build_msg}"}

    result: dict = {
        "status": "SUCCESS",
        "proof_verified": proof_verified,
        "verify_msg": verify_msg + " (legacy: spec only)",
        "workload": "tpch",
        "query_key": qkey,
        "query_label": f"TPC-H {qkey}",
    }
    if skip_bench:
        return result

    tbl_path = tbl or str(DEFAULT_TPCH_TBL)
    if not os.path.exists(tbl_path):
        result["bench_skipped"] = True
        result["bench_msg"] = f"tbl missing: {tbl_path}"
        return result

    if not skip_bare:
        bare_us = bench_bare_tpch(qkey, tbl_path, limit)
        if bare_us >= 0:
            result["bare_us"] = bare_us

    binary = os.path.join(WORKING, "target", "release", "working_query")
    latency, stdout, stderr = run_binary(binary, tbl_path, limit)
    result["latency_us"] = latency
    result["stdout"] = stdout
    if latency < 0:
        result["status"] = "FAILURE"
        result["error"] = f"no QUERY_LATENCY_US in output\n{stdout}\n{stderr}"
    return result
