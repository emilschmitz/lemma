#!/usr/bin/env python3
"""Verus research harness: transpile → assemble → verus verify → verus --compile → run."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(CURRENT_DIR))
VERUS_SRC = os.path.join(ROOT_DIR, "verus", "src")
GENERATED = os.path.join(CURRENT_DIR, "generated")
FAILED_TRANSPILE_DIR = os.path.join(CURRENT_DIR, "agents", "failed_transpile")
PENDING_RUNQUERY_DIR = os.path.join(CURRENT_DIR, "agents", "pending_runquery")
WORKING = os.path.join(CURRENT_DIR, "working_query")
DEFAULT_SSB_TBL = os.path.join(ROOT_DIR, "ssb-dbgen", "lineorder_flat.tbl")
BENCH_BARE_DIR = os.path.join(ROOT_DIR, "research_loop", "bench_bare")

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if VERUS_SRC not in sys.path:
    sys.path.insert(0, VERUS_SRC)

from verus.research_loop._transpiler import (  # noqa: E402
    project_multi_schema_for_query,
    project_schema_for_query,
    transpile_sql_to_verus,
)
from verus.research_loop.assemble_verified_program import (  # noqa: E402
    assemble_verified_join_program,
    assemble_verified_nway_program,
    assemble_verified_program,
)
from verus.research_loop.ssb_queries import load_schema, queries as ssb_queries  # noqa: E402
from verus.research_loop.tpch_runqueries import (  # noqa: E402
    DEFAULT_TBL as DEFAULT_TPCH_TBL,
    TPCH_BENCH_EXEC,
    TPCH_BENCH_MAIN_PREFIX,
    TPCH_BENCH_POST_TIMING,
    TPCH_BENCH_TIMING_BODY,
    TPCH_DEFAULT_TBLS,
    TPCH_HOT_PATHS,
    TPCH_NWAY_SCHEMA,
    TPCH_NWAY_TABLE_ORDER,
    TPCH_QUERY_KIND,
    queries as tpch_queries,
    schema as tpch_schema,
)
from verus.research_loop.verified_runqueries import (  # noqa: E402
    SSB_BENCH_EXEC,
    SSB_BENCH_TIMING_BODY,
    SSB_HOT_PATHS,
    SSB_RETURN_TYPES,
    SSB_RUNQUERIES,
    TPCH_RETURN_TYPES,
    TPCH_RUNQUERIES,
)
from verus.research_loop.basic_sql_fixtures import (  # noqa: E402
    BASIC_SQL_FIXTURES,
)
from verus.research_loop.basic_sql_join_fixtures import (  # noqa: E402
    BASIC_SQL_JOIN_FIXTURES,
)
from verus.research_loop.basic_sql_set_cte_fixtures import (  # noqa: E402
    BASIC_SQL_SET_CTE_FIXTURES,
)
from verus.research_loop.basic_sql_proj_order_fixtures import (  # noqa: E402
    BASIC_SQL_PROJ_ORDER_FIXTURES,
)
from verus.research_loop.basic_sql_extended_fixtures import (  # noqa: E402
    BASIC_SQL_EXTENDED_FIXTURES,
)
from verus.research_loop.lemma_flags import enable_templates  # noqa: E402

ALL_BASIC_SQL_FIXTURES: dict = {
    **BASIC_SQL_FIXTURES,
    **BASIC_SQL_SET_CTE_FIXTURES,
    **BASIC_SQL_PROJ_ORDER_FIXTURES,
    **BASIC_SQL_EXTENDED_FIXTURES,
}

TESTDATA_DIR = os.path.join(CURRENT_DIR, "testdata")


def _schema_summary(schema: dict) -> dict:
    from verus_transpiler.parse_sql import normalize_schema

    flat, multi = normalize_schema(schema)
    if multi:
        return {
            "kind": "multi",
            "tables": {t: list(cols.keys()) for t, cols in multi.items()},
        }
    return {"kind": "flat", "columns": list(flat.keys())}


def _record_pipeline_json(
    dest_dir: str,
    stage: str,
    sql: str,
    error: str,
    schema: dict | None = None,
    *,
    extra: dict | None = None,
) -> str:
    """Write a JSON artifact for agent follow-up. Returns path."""
    os.makedirs(dest_dir, exist_ok=True)
    ts = datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%d_%H%M%S")
    digest = abs(hash((sql, stage, error))) % 1_000_000
    path = os.path.join(dest_dir, f"{stage}_{stamp}_{digest:06d}.json")
    payload: dict = {
        "timestamp": ts.isoformat(),
        "stage": stage,
        "sql": sql,
        "error": error,
        "schema_summary": _schema_summary(schema) if schema is not None else None,
    }
    if extra:
        payload.update(extra)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return path


def _record_pending_runquery(
    sql: str,
    error: str,
    schema: dict,
    spec_rs: str,
    *,
    tbl_paths: dict[str, str] | None = None,
    limit: int | None = None,
) -> str:
    """Write pending agent work: manifest + transpiled spec.rs + context.json."""
    from verus.research_loop.agent_context import build_agent_context, write_agent_context

    os.makedirs(PENDING_RUNQUERY_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%d_%H%M%S")
    digest = abs(hash((sql, error))) % 1_000_000
    artifact_dir = os.path.join(
        PENDING_RUNQUERY_DIR, f"pending_{stamp}_{digest:06d}"
    )
    os.makedirs(artifact_dir, exist_ok=True)
    spec_path = os.path.join(artifact_dir, "spec.rs")
    with open(spec_path, "w", encoding="utf-8") as f:
        f.write(spec_rs)
    context_path = os.path.join(artifact_dir, "context.json")
    ctx = build_agent_context(
        sql=sql,
        schema=schema,
        tbl_paths=tbl_paths,
        limit=limit,
    )
    write_agent_context(context_path, **ctx)
    manifest_path = os.path.join(artifact_dir, "manifest.json")
    payload = {
        "timestamp": ts.isoformat(),
        "stage": "awaiting_agent",
        "sql": sql,
        "error": error,
        "schema_summary": _schema_summary(schema),
        "spec_rs_path": os.path.relpath(spec_path, CURRENT_DIR),
        "context_json_path": os.path.relpath(context_path, CURRENT_DIR),
        "run_query_skeleton": "see spec.rs (commented RunQuery skeleton)",
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return manifest_path


def _pipeline_failure(
    stage: str,
    sql: str,
    error: str,
    schema: dict | None = None,
    *,
    agents_path: str | None = None,
    **extra: object,
) -> dict:
    if agents_path is None:
        if stage == "transpile":
            agents_path = _record_pipeline_json(
                FAILED_TRANSPILE_DIR, stage, sql, error, schema
            )
        elif stage == "awaiting_agent" and schema is not None:
            spec_rs = extra.pop("spec_rs", "")
            tbl_paths = extra.pop("tbl_paths", None)
            limit = extra.pop("limit", None)
            agents_path = _record_pending_runquery(
                sql, error, schema, str(spec_rs),
                tbl_paths=tbl_paths if isinstance(tbl_paths, dict) else None,
                limit=limit if isinstance(limit, int) else None,
            )
        else:
            agents_path = _record_pipeline_json(
                FAILED_TRANSPILE_DIR, stage, sql, error, schema
            )
    rel = os.path.relpath(agents_path, CURRENT_DIR)
    msg = f"CUSTOM_PIPELINE_FAILED [{stage}]: {error} → {rel}"
    if stage == "awaiting_agent":
        msg += "\nAgent must supply run_query_body ≡ method_spec."
    print(msg, file=sys.stderr)
    out: dict = {
        "status": "FAILURE",
        "error": error,
        "stage": stage,
        "agents_failure_path": agents_path,
        "workload": "custom",
    }
    out.update(extra)
    return out


def _resolve_custom_ret_type(
    query: object,
    projected: dict,
    *,
    multi: bool,
) -> str:
    """Map parsed SQL shape to assembler RET_TYPE_CONFIG key (no exec codegen)."""
    from verus_transpiler.codegen_exec import (
        _resolve_join_groupby_ret_type_key,
        resolve_ret_type_key,
    )
    from verus_transpiler.col_exprs import to_col_expr
    from verus_transpiler.joins import emit_join_spec_helpers
    from verus_transpiler.parse_sql import SQLQuery, _agg_value_type
    from verus_transpiler.transpiler import _emit_set_op_helpers, _emit_union_helpers

    assert isinstance(query, SQLQuery)
    if query.union_query is not None:
        if multi:
            raise ValueError("set-op custom query requires flat schema dict")
        _, _, ret_type = _emit_union_helpers(query, projected)
        return ret_type
    if query.intersect_query is not None:
        if multi:
            raise ValueError("set-op custom query requires flat schema dict")
        _, _, ret_type = _emit_set_op_helpers(query, projected, op="intersect")
        return ret_type
    if query.except_query is not None:
        if multi:
            raise ValueError("set-op custom query requires flat schema dict")
        _, _, ret_type = _emit_set_op_helpers(query, projected, op="except")
        return ret_type
    if query.joins and multi:
        multi_schema = projected  # type: ignore[assignment]
        if query.groupby_columns:
            return _resolve_join_groupby_ret_type_key(query, multi_schema)
        where_at = to_col_expr(query.where_expr, "li") if query.where_expr else None
        val_type = _agg_value_type(query.agg_expr)
        is_sum = query.agg_type in ("SUM", "AVG", "MIN", "MAX")
        _, _, ret_type = emit_join_spec_helpers(
            query,
            multi_schema,
            where_expr=where_at,
            agg_expr=query.agg_expr,
            is_sum=is_sum,
            val_type=val_type,
        )
        return ret_type
    if multi:
        raise ValueError("single-table custom query requires flat schema dict")
    if not query.groupby_columns:
        return "u64"
    return resolve_ret_type_key(query, projected)


def load_env(env_path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def resolve_verus_bin() -> str | None:
    found = shutil.which("verus")
    if found:
        return found
    for c in (
        os.path.expanduser("~/tools/verus/verus"),
        "/home/emil/tools/verus/verus",
    ):
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def verus_on_path() -> bool:
    return resolve_verus_bin() is not None


def _verus_env() -> dict[str, str]:
    env = os.environ.copy()
    verus_bin = resolve_verus_bin()
    if verus_bin:
        verus_dir = os.path.dirname(verus_bin)
        env["PATH"] = verus_dir + os.pathsep + env.get("PATH", "")
    env.setdefault("RUSTFLAGS", "-C target-cpu=native")
    return env


def run_verus_verify(rs_path: str, timeout: int) -> tuple[bool, str]:
    verus_bin = resolve_verus_bin()
    if not verus_bin:
        return False, "verus binary not found"
    cmd = [verus_bin, rs_path]
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=_verus_env()
        )
        ok = res.returncode == 0
        msg = (res.stdout + "\n" + res.stderr).strip()
        return ok, msg
    except subprocess.TimeoutExpired:
        return False, f"verus verify timed out after {timeout}s"
    except FileNotFoundError:
        return False, "verus binary not found"


def run_verus_compile(rs_path: str, timeout: int) -> tuple[bool, str, str | None]:
    """Verify + compile; binary basename matches .rs stem next to source.

    Pass rustc release-ish flags after ``--``: bare ``verus --compile`` defaults to
    unoptimized codegen (~10–20× slower than cargo release on join hot paths).
    """
    verus_bin = resolve_verus_bin()
    if not verus_bin:
        return False, "verus binary not found", None
    cmd = [
        verus_bin,
        rs_path,
        "--compile",
        "--",
        "-C",
        "opt-level=3",
        "-C",
        "target-cpu=native",
        "-C",
        "panic=abort",
        "-C",
        "codegen-units=1",
    ]
    rs_dir = os.path.dirname(os.path.abspath(rs_path))
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_verus_env(),
            cwd=rs_dir,
        )
        ok = res.returncode == 0
        msg = (res.stdout + "\n" + res.stderr).strip()
        binary = os.path.join(rs_dir, os.path.splitext(os.path.basename(rs_path))[0])
        if not ok or not os.path.isfile(binary):
            return ok, msg, None
        return ok, msg, binary
    except subprocess.TimeoutExpired:
        return False, f"verus --compile timed out after {timeout}s", None
    except FileNotFoundError:
        return False, "verus binary not found", None


_BENCH_BINARY_RUNS = 5
_BENCH_WARMUP_RUNS = 2


def _warmup_binary(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    run_env = env if env is not None else os.environ
    for _ in range(_BENCH_WARMUP_RUNS):
        subprocess.run(
            cmd,
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=120,
            env=run_env,
        )


def _parse_latency_us(stdout: str) -> int:
    m = re.search(r"QUERY_LATENCY_US:\s*(\d+)", stdout)
    return int(m.group(1)) if m else -1


def _median_us(latencies: list[int]) -> int:
    xs = sorted(latencies)
    return xs[len(xs) // 2]


def _run_binary_once(binary: str, tbl: str, limit: int) -> tuple[int, str, str]:
    res = subprocess.run(
        [binary, tbl, str(limit)],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = res.stdout.strip()
    stderr = res.stderr
    return _parse_latency_us(out), out, stderr


def _bench_bare_ssb_once(query_idx: int, tbl: str, limit: int) -> int:
    if query_idx == 1:
        cmd = [bare_bin_path("bench_q1") or "", tbl, str(limit)]
    else:
        cmd = [bare_bin_path("bench_q") or "", str(query_idx), tbl, str(limit)]
    if not cmd[0]:
        return -1
    bare_env = {**os.environ, "RUSTFLAGS": "-C target-cpu=native"}
    res = subprocess.run(
        cmd,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        env=bare_env,
    )
    if res.returncode != 0:
        return -1
    return _parse_latency_us(res.stdout)


def bench_ssb_paired(
    query_idx: int, binary: str, tbl: str, limit: int
) -> tuple[int, int, str, str]:
    """Interleave verus/bare runs so each pair sees similar system load."""
    _warmup_binary([binary, tbl, str(limit)])
    if query_idx == 1:
        bare_cmd = [bare_bin_path("bench_q1") or "", tbl, str(limit)]
    else:
        bare_cmd = [bare_bin_path("bench_q") or "", str(query_idx), tbl, str(limit)]
    bare_env = {**os.environ, "RUSTFLAGS": "-C target-cpu=native"}
    if bare_cmd[0]:
        _warmup_binary(bare_cmd, env=bare_env)

    verus_lats: list[int] = []
    bare_lats: list[int] = []
    out = ""
    stderr = ""
    for _ in range(_BENCH_BINARY_RUNS):
        lat, out, stderr = _run_binary_once(binary, tbl, limit)
        if lat < 0:
            return -1, -1, out, stderr
        verus_lats.append(lat)
        bare_lat = _bench_bare_ssb_once(query_idx, tbl, limit)
        if bare_lat < 0:
            return -1, -1, out, stderr
        bare_lats.append(bare_lat)
    return _median_us(verus_lats), _median_us(bare_lats), out, stderr


def run_binary(binary: str, tbl: str, limit: int) -> tuple[int, str, str]:
    _warmup_binary([binary, tbl, str(limit)])
    lats: list[int] = []
    out = ""
    stderr = ""
    for _ in range(_BENCH_BINARY_RUNS):
        res = subprocess.run(
            [binary, tbl, str(limit)],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = res.stdout.strip()
        stderr = res.stderr
        lat = _parse_latency_us(out)
        if lat < 0:
            return -1, out, stderr
        lats.append(lat)
    return _median_us(lats), out, stderr


def run_binary_join(
    binary: str, left_tbl: str, right_tbl: str, limit: int
) -> tuple[int, str, str]:
    lats: list[int] = []
    out = ""
    stderr = ""
    for _ in range(_BENCH_BINARY_RUNS):
        res = subprocess.run(
            [binary, left_tbl, right_tbl, str(limit)],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = res.stdout.strip()
        stderr = res.stderr
        lat = _parse_latency_us(out)
        if lat < 0:
            return -1, out, stderr
        lats.append(lat)
    return _median_us(lats), out, stderr


def bare_bin_path(name: str) -> str | None:
    path = os.path.join(BENCH_BARE_DIR, "target", "release", name)
    return path if os.path.isfile(path) else None


def bench_bare_ssb(query_idx: int, tbl: str, limit: int) -> int:
    if query_idx == 1:
        bin_name = "bench_q1"
        cmd = [bare_bin_path(bin_name) or "", tbl, str(limit)]
    else:
        bin_name = "bench_q"
        cmd = [bare_bin_path(bin_name) or "", str(query_idx), tbl, str(limit)]

    if not cmd[0]:
        return -1

    bare_env = {**os.environ, "RUSTFLAGS": "-C target-cpu=native"}
    _warmup_binary(cmd, env=bare_env)
    lats: list[int] = []
    for _ in range(_BENCH_BINARY_RUNS):
        res = subprocess.run(
            cmd,
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=120,
            env=bare_env,
        )
        if res.returncode != 0:
            return -1
        lat = _parse_latency_us(res.stdout)
        if lat < 0:
            return -1
        lats.append(lat)
    return _median_us(lats)


def run_binary_nway(
    binary: str,
    tbls: dict[str, str],
    limit: int,
    *,
    table_order: tuple[str, ...],
) -> tuple[int, str, str]:
    args = [binary, str(limit)] + [tbls[t] for t in table_order]
    lats: list[int] = []
    out = ""
    stderr = ""
    for _ in range(_BENCH_BINARY_RUNS):
        res = subprocess.run(
            args,
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = res.stdout.strip()
        stderr = res.stderr
        lat = _parse_latency_us(out)
        if lat < 0:
            return -1, out, stderr
        lats.append(lat)
    return _median_us(lats), out, stderr


def bench_bare_tpch(query_name: str, tbl: str, limit: int) -> int:
    qkey = query_name.upper()
    if qkey == "Q3":
        bin_path = bare_bin_path("bench_tpch")
        if not bin_path:
            return -1
        data_dir = os.path.dirname(tbl)
        cmd = [
            bin_path,
            "q3",
            os.path.join(data_dir, "lineitem.tbl"),
            os.path.join(data_dir, "orders.tbl"),
            os.path.join(data_dir, "customer.tbl"),
            str(limit),
        ]
    else:
        bin_path = bare_bin_path("bench_tpch")
        if not bin_path:
            return -1
        cmd = [bin_path, query_name.lower(), tbl, str(limit)]

    lats: list[int] = []
    bare_env = {**os.environ, "RUSTFLAGS": "-C target-cpu=native"}
    _warmup_binary(cmd, env=bare_env)
    for _ in range(_BENCH_BINARY_RUNS):
        res = subprocess.run(
            cmd,
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=120,
            env=bare_env,
        )
        if res.returncode != 0:
            return -1
        lat = _parse_latency_us(res.stdout)
        if lat < 0:
            return -1
        lats.append(lat)
    return _median_us(lats)


def bench_bare_join(feature_key: str, left_tbl: str, right_tbl: str, limit: int) -> int:
    """Bare Rust hash-join twin for basic_sql join fixtures."""
    bin_path = bare_bin_path("bench_joins")
    if not bin_path:
        return -1
    kind_map = {
        "inner_join_sum": "inner",
        "tpch_join_sum": "tpch",
        "left_join_sum": "left",
    }
    kind = kind_map.get(feature_key)
    if kind is None:
        return -1
    lats: list[int] = []
    for _ in range(_BENCH_BINARY_RUNS):
        res = subprocess.run(
            [bin_path, kind, left_tbl, right_tbl, str(limit)],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "RUSTFLAGS": "-C target-cpu=native"},
        )
        if res.returncode != 0:
            return -1
        lat = _parse_latency_us(res.stdout)
        if lat < 0:
            return -1
        lats.append(lat)
    return _median_us(lats)


def write_unified_join_program(
    *,
    rs_path: str,
    sql: str,
    multi_schema: dict[str, dict[str, str]],
    table_order: tuple[str, str],
    runquery_body: str,
    ret_type: str,
    default_tbls: dict[str, str],
    workload: str,
    query_key: str,
    hot_path_rs: str = "",
    bench_exec: str = "",
) -> str:
    projected = project_multi_schema_for_query(sql, multi_schema)
    spec_rs = transpile_sql_to_verus(sql, projected, enable_templates=enable_templates())
    program = assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=runquery_body,
        multi_schema=projected,
        table_order=table_order,
        ret_type=ret_type,
        default_tbls=default_tbls,
        hot_path_rs=hot_path_rs,
        bench_exec=bench_exec,
    )
    os.makedirs(os.path.dirname(rs_path), exist_ok=True)
    with open(rs_path, "w") as f:
        f.write(program)
    return rs_path


def write_unified_nway_program(
    *,
    rs_path: str,
    sql: str,
    multi_schema: dict[str, dict[str, str]],
    table_order: tuple[str, ...],
    runquery_body: str,
    ret_type: str,
    default_tbls: dict[str, str],
    workload: str,
    query_key: str,
    hot_path_rs: str = "",
    bench_exec: str = "",
) -> str:
    projected = project_multi_schema_for_query(sql, multi_schema)
    spec_rs = transpile_sql_to_verus(sql, projected, enable_templates=enable_templates())
    program = assemble_verified_nway_program(
        spec_rs=spec_rs,
        run_query_body=runquery_body,
        multi_schema=projected,
        table_order=table_order,
        ret_type=ret_type,
        default_tbls=default_tbls,
        hot_path_rs=hot_path_rs,
        bench_exec=bench_exec,
    )
    os.makedirs(os.path.dirname(rs_path), exist_ok=True)
    with open(rs_path, "w") as f:
        f.write(program)
    return rs_path


def write_unified_program(
    *,
    rs_path: str,
    sql: str,
    schema: dict[str, str],
    runquery_body: str,
    ret_type: str,
    default_tbl: str,
    workload: str,
    query_key: str | int,
    hot_path_rs: str = "",
    bench_exec: str = "",
    bench_timing_body: str = "",
    bench_post_timing: str = "",
    bench_main_prefix: str = "",
) -> str:
    # Prefer projected schema; fall back to full schema when projection
    # drops subquery/CTE columns (EXISTS / IN / WITH).
    try:
        projected = project_schema_for_query(sql, schema)
        spec_rs = transpile_sql_to_verus(sql, projected, enable_templates=enable_templates())
        schema_for_load = projected
    except Exception:
        projected = schema
        spec_rs = transpile_sql_to_verus(sql, projected, enable_templates=enable_templates())
        schema_for_load = projected
    program = assemble_verified_program(
        spec_rs=spec_rs,
        run_query_body=runquery_body,
        schema_dict=schema_for_load,
        ret_type=ret_type,
        default_tbl=default_tbl,
        hot_path_rs=hot_path_rs,
        bench_exec=bench_exec,
        bench_timing_body=bench_timing_body,
        bench_post_timing=bench_post_timing,
        bench_main_prefix=bench_main_prefix,
    )
    os.makedirs(os.path.dirname(rs_path), exist_ok=True)
    with open(rs_path, "w") as f:
        f.write(program)
    return rs_path


def _legacy_unproved_enabled() -> bool:
    return os.environ.get("LEGACY_UNPROVED_EXEC", "0") == "1"


def run_ssb_pipeline(
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

    if _legacy_unproved_enabled():
        from verus.research_loop.harness_legacy import run_ssb_pipeline_legacy

        return run_ssb_pipeline_legacy(
            query_idx,
            limit=limit,
            tbl=tbl,
            skip_bench=skip_bench,
            skip_bare=skip_bare,
        )

    verify_timeout = int(os.environ.get("VERUS_VERIFY_TIMEOUT_SEC", "120"))
    compile_timeout = int(os.environ.get("COMPILE_TIMEOUT_SEC", "180"))
    enable_verify = os.environ.get("ENABLE_VERUS_VERIFY", "1") == "1"
    require_proof = os.environ.get(
        "REQUIRE_PROOF", "1" if enable_verify else "0"
    ) == "1"

    if query_idx < 1 or query_idx > len(ssb_queries):
        return {"status": "FAILURE", "error": f"invalid query index 1..{len(ssb_queries)}"}
    if query_idx not in SSB_RUNQUERIES:
        return {"status": "FAILURE", "error": f"no verified fixture for SSB query {query_idx}"}

    sql = ssb_queries[query_idx - 1]
    schema = load_schema()
    ret_type = SSB_RETURN_TYPES[query_idx]
    runquery_body = SSB_RUNQUERIES[query_idx]

    rs_path = os.path.join(GENERATED, f"ssb_q{query_idx}.rs")
    write_unified_program(
        rs_path=rs_path,
        sql=sql,
        schema=schema,
        runquery_body=runquery_body,
        ret_type=ret_type,
        default_tbl="ssb-dbgen/lineorder_flat.tbl",
        workload="ssb",
        query_key=query_idx,
        hot_path_rs=SSB_HOT_PATHS.get(query_idx, ""),
        bench_exec=SSB_BENCH_EXEC.get(query_idx, ""),
        bench_timing_body=SSB_BENCH_TIMING_BODY.get(query_idx, ""),
    )

    proof_verified = False
    verify_msg = ""
    if enable_verify and verus_on_path():
        proof_verified, verify_msg = run_verus_verify(rs_path, verify_timeout)
        if not proof_verified:
            log_path = os.path.join(GENERATED, f"verify_error_ssb_q{query_idx}.log")
            with open(log_path, "w") as f:
                f.write(verify_msg)
            if require_proof:
                return {
                    "status": "FAILURE",
                    "proof_verified": False,
                    "error": f"verus verify failed (REQUIRE_PROOF=1): see {log_path}",
                    "verify_msg": verify_msg[:2000],
                    "workload": "ssb",
                    "query_key": query_idx,
                    "query_label": f"SSB Q{query_idx}",
                }
            verify_msg = f"failed (see {log_path})"
    elif enable_verify:
        verify_msg = "skipped: verus not on PATH"
        if require_proof:
            return {
                "status": "FAILURE",
                "proof_verified": False,
                "error": "verus not on PATH but REQUIRE_PROOF=1 / ENABLE_VERUS_VERIFY=1",
                "verify_msg": verify_msg,
                "workload": "ssb",
                "query_key": query_idx,
                "query_label": f"SSB Q{query_idx}",
            }

    ok, compile_msg, binary = run_verus_compile(rs_path, compile_timeout)
    if not ok or not binary:
        log_path = os.path.join(GENERATED, f"compile_error_ssb_q{query_idx}.log")
        with open(log_path, "w") as f:
            f.write(compile_msg)
        return {
            "status": "FAILURE",
            "proof_verified": proof_verified,
            "error": f"verus --compile failed: see {log_path}",
            "verify_msg": verify_msg,
            "workload": "ssb",
            "query_key": query_idx,
        }

    result: dict = {
        "status": "SUCCESS" if proof_verified or not require_proof else "SUCCESS_UNVERIFIED",
        "proof_verified": proof_verified,
        "verify_msg": verify_msg,
        "workload": "ssb",
        "query_key": query_idx,
        "query_label": f"SSB Q{query_idx}",
        "rs_path": rs_path,
        "binary": binary,
    }

    if skip_bench:
        return result

    time.sleep(0.05)

    tbl_path = tbl or DEFAULT_SSB_TBL
    if not os.path.exists(tbl_path):
        result["bench_skipped"] = True
        result["bench_msg"] = f"tbl missing: {tbl_path}"
        return result

    if not skip_bare:
        latency, bare_us, stdout, stderr = bench_ssb_paired(
            query_idx, binary, tbl_path, limit
        )
    else:
        latency, stdout, stderr = run_binary(binary, tbl_path, limit)
        bare_us = -1

    result["latency_us"] = latency
    result["stdout"] = stdout
    if latency < 0:
        result["status"] = "FAILURE"
        result["error"] = f"no QUERY_LATENCY_US in output\n{stdout}\n{stderr}"
        return result

    if bare_us >= 0:
        result["bare_us"] = bare_us

    return result


def run_tpch_pipeline(
    query_name: str,
    *,
    limit: int = 50_000,
    tbl: str | None = None,
    skip_bench: bool = False,
    skip_bare: bool = False,
) -> dict:
    cfg = load_env(os.path.join(CURRENT_DIR, "config.env"))
    for k, v in cfg.items():
        os.environ.setdefault(k, v)

    if _legacy_unproved_enabled():
        from verus.research_loop.harness_legacy import run_tpch_pipeline_legacy

        return run_tpch_pipeline_legacy(
            query_name,
            limit=limit,
            tbl=tbl,
            skip_bench=skip_bench,
            skip_bare=skip_bare,
        )

    verify_timeout = int(os.environ.get("VERUS_VERIFY_TIMEOUT_SEC", "120"))
    compile_timeout = int(os.environ.get("COMPILE_TIMEOUT_SEC", "180"))
    enable_verify = os.environ.get("ENABLE_VERUS_VERIFY", "1") == "1"
    require_proof = os.environ.get(
        "REQUIRE_PROOF", "1" if enable_verify else "0"
    ) == "1"

    qkey = query_name.upper()
    if qkey not in TPCH_RUNQUERIES:
        return {"status": "FAILURE", "error": f"no verified fixture for TPC-H {qkey}"}

    sql = tpch_queries[qkey]
    ret_type = TPCH_RETURN_TYPES[qkey]
    runquery_body = TPCH_RUNQUERIES[qkey]
    kind = TPCH_QUERY_KIND.get(qkey, "single")

    if kind == "nway":
        rs_path = os.path.join(GENERATED, f"tpch_{qkey.lower()}.rs")
        default_tbls = dict(TPCH_DEFAULT_TBLS[qkey])
        write_unified_nway_program(
            rs_path=rs_path,
            sql=sql,
            multi_schema=dict(TPCH_NWAY_SCHEMA),
            table_order=TPCH_NWAY_TABLE_ORDER,
            runquery_body=runquery_body,
            ret_type=ret_type,
            default_tbls=default_tbls,
            workload="tpch",
            query_key=qkey,
            hot_path_rs=TPCH_HOT_PATHS.get(qkey, ""),
            bench_exec=TPCH_BENCH_EXEC.get(qkey, ""),
        )
    else:
        rs_path = os.path.join(GENERATED, f"tpch_{qkey.lower()}.rs")
        write_unified_program(
            rs_path=rs_path,
            sql=sql,
            schema=dict(tpch_schema),
            runquery_body=runquery_body,
            ret_type=ret_type,
            default_tbl="data/tpch-sf1/lineitem.tbl",
            workload="tpch",
            query_key=qkey,
            hot_path_rs=TPCH_HOT_PATHS.get(qkey, ""),
            bench_exec=TPCH_BENCH_EXEC.get(qkey, ""),
            bench_timing_body=TPCH_BENCH_TIMING_BODY.get(qkey, ""),
            bench_post_timing=TPCH_BENCH_POST_TIMING.get(qkey, ""),
            bench_main_prefix=TPCH_BENCH_MAIN_PREFIX.get(qkey, ""),
        )

    proof_verified = False
    verify_msg = ""
    if enable_verify and verus_on_path():
        proof_verified, verify_msg = run_verus_verify(rs_path, verify_timeout)
        if not proof_verified:
            log_path = os.path.join(GENERATED, f"verify_error_tpch_{qkey}.log")
            with open(log_path, "w") as f:
                f.write(verify_msg)
            if require_proof:
                return {
                    "status": "FAILURE",
                    "proof_verified": False,
                    "error": f"verus verify failed (REQUIRE_PROOF=1): see {log_path}",
                    "verify_msg": verify_msg[:2000],
                    "workload": "tpch",
                    "query_key": qkey,
                    "query_label": f"TPC-H {qkey}",
                }
            verify_msg = f"failed (see {log_path})"
    elif enable_verify:
        verify_msg = "skipped: verus not on PATH"
        if require_proof:
            return {
                "status": "FAILURE",
                "proof_verified": False,
                "error": "verus not on PATH but REQUIRE_PROOF=1 / ENABLE_VERUS_VERIFY=1",
                "verify_msg": verify_msg,
                "workload": "tpch",
                "query_key": qkey,
                "query_label": f"TPC-H {qkey}",
            }

    ok, compile_msg, binary = run_verus_compile(rs_path, compile_timeout)
    if not ok or not binary:
        log_path = os.path.join(GENERATED, f"compile_error_tpch_{qkey}.log")
        with open(log_path, "w") as f:
            f.write(compile_msg)
        return {
            "status": "FAILURE",
            "proof_verified": proof_verified,
            "error": f"verus --compile failed: see {log_path}",
            "verify_msg": verify_msg,
            "workload": "tpch",
            "query_key": qkey,
        }

    result: dict = {
        "status": "SUCCESS" if proof_verified or not require_proof else "SUCCESS_UNVERIFIED",
        "proof_verified": proof_verified,
        "verify_msg": verify_msg,
        "workload": "tpch",
        "query_key": qkey,
        "query_label": f"TPC-H {qkey}",
        "rs_path": rs_path,
        "binary": binary,
    }

    if skip_bench:
        return result

    if kind == "nway":
        default_tbls = TPCH_DEFAULT_TBLS[qkey]
        resolved_tbls = {
            table: os.path.join(ROOT_DIR, rel) for table, rel in default_tbls.items()
        }
        missing = [t for t, p in resolved_tbls.items() if not os.path.exists(p)]
        if missing:
            result["bench_skipped"] = True
            result["bench_msg"] = f"tbl missing for {missing}"
            return result

        if not skip_bare:
            bare_us = bench_bare_tpch(qkey, resolved_tbls["lineitem"], limit)
            if bare_us >= 0:
                result["bare_us"] = bare_us

        latency, stdout, stderr = run_binary_nway(
            binary, resolved_tbls, limit, table_order=TPCH_NWAY_TABLE_ORDER
        )
    else:
        tbl_path = tbl or str(DEFAULT_TPCH_TBL)
        if not os.path.exists(tbl_path):
            result["bench_skipped"] = True
            result["bench_msg"] = f"tbl missing: {tbl_path}"
            return result

        if not skip_bare:
            bare_us = bench_bare_tpch(qkey, tbl_path, limit)
            if bare_us >= 0:
                result["bare_us"] = bare_us

        latency, stdout, stderr = run_binary(binary, tbl_path, limit)
    result["latency_us"] = latency
    result["stdout"] = stdout
    if latency < 0:
        result["status"] = "FAILURE"
        result["error"] = f"no QUERY_LATENCY_US in output\n{stdout}\n{stderr}"
    return result


def basic_sql_tbl_path(feature_key: str) -> str:
    return os.path.join(TESTDATA_DIR, f"basic_{feature_key}.tbl")


def _extended_join_testdata_paths(feature_key: str) -> dict[str, str]:
    fx = BASIC_SQL_EXTENDED_FIXTURES[feature_key]
    assert fx.default_tbls is not None
    return {
        table: os.path.join(ROOT_DIR, rel) for table, rel in fx.default_tbls.items()
    }


def run_basic_sql_nway_pipeline(
    feature_key: str,
    *,
    limit: int = 50_000,
    tbls: dict[str, str] | None = None,
    skip_bench: bool = False,
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

    if feature_key not in BASIC_SQL_EXTENDED_FIXTURES:
        return {
            "status": "FAILURE",
            "error": f"unknown basic-sql nway feature {feature_key!r}",
        }

    fx = BASIC_SQL_EXTENDED_FIXTURES[feature_key]
    if not fx.is_nway_join:
        return {"status": "FAILURE", "error": f"{feature_key!r} is not an nway join fixture"}

    assert fx.table_order is not None and fx.default_tbls is not None
    rs_path = os.path.join(GENERATED, f"basic_{feature_key}.rs")
    default_tbls = dict(fx.default_tbls)
    write_unified_nway_program(
        rs_path=rs_path,
        sql=fx.sql,
        multi_schema=fx.schema,  # type: ignore[arg-type]
        table_order=fx.table_order,
        runquery_body=fx.run_query,
        ret_type=fx.ret_type,
        default_tbls=default_tbls,
        workload="basic_sql",
        query_key=feature_key,
    )

    proof_verified = False
    verify_msg = ""
    if enable_verify and verus_on_path():
        proof_verified, verify_msg = run_verus_verify(rs_path, verify_timeout)
        if not proof_verified:
            log_path = os.path.join(GENERATED, f"verify_error_basic_{feature_key}.log")
            with open(log_path, "w") as f:
                f.write(verify_msg)
            if require_proof:
                return {
                    "status": "FAILURE",
                    "proof_verified": False,
                    "error": f"verus verify failed (REQUIRE_PROOF=1): see {log_path}",
                    "verify_msg": verify_msg[:2000],
                    "workload": "basic_sql",
                    "query_key": feature_key,
                    "query_label": f"basic_sql:{feature_key}",
                }
            verify_msg = f"failed (see {log_path})"
    elif enable_verify:
        verify_msg = "skipped: verus not on PATH"
        if require_proof:
            return {
                "status": "FAILURE",
                "proof_verified": False,
                "error": "verus not on PATH but REQUIRE_PROOF=1 / ENABLE_VERUS_VERIFY=1",
                "verify_msg": verify_msg,
                "workload": "basic_sql",
                "query_key": feature_key,
                "query_label": f"basic_sql:{feature_key}",
            }

    ok, compile_msg, binary = run_verus_compile(rs_path, compile_timeout)
    if not ok or not binary:
        log_path = os.path.join(GENERATED, f"compile_error_basic_{feature_key}.log")
        with open(log_path, "w") as f:
            f.write(compile_msg)
        return {
            "status": "FAILURE",
            "proof_verified": proof_verified,
            "error": f"verus --compile failed: see {log_path}",
            "verify_msg": verify_msg,
            "workload": "basic_sql",
            "query_key": feature_key,
        }

    result: dict = {
        "status": "SUCCESS" if proof_verified or not require_proof else "SUCCESS_UNVERIFIED",
        "proof_verified": proof_verified,
        "verify_msg": verify_msg,
        "workload": "basic_sql",
        "query_key": feature_key,
        "query_label": f"basic_sql:{feature_key}",
        "rs_path": rs_path,
        "binary": binary,
    }

    if skip_bench:
        return result

    resolved_tbls = tbls or _extended_join_testdata_paths(feature_key)
    missing = [t for t, p in resolved_tbls.items() if not os.path.exists(p)]
    if missing:
        result["bench_skipped"] = True
        result["bench_msg"] = f"tbl missing for {missing}"
        return result

    latency, stdout, stderr = run_binary_nway(
        binary, resolved_tbls, limit, table_order=fx.table_order
    )
    result["latency_us"] = latency
    result["stdout"] = stdout
    if latency < 0:
        result["status"] = "FAILURE"
        result["error"] = f"no QUERY_LATENCY_US in output\n{stdout}\n{stderr}"
    return result


def run_basic_sql_extended_join_pipeline(
    feature_key: str,
    *,
    limit: int = 50_000,
    tbls: dict[str, str] | None = None,
    skip_bench: bool = False,
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

    if feature_key not in BASIC_SQL_EXTENDED_FIXTURES:
        return {
            "status": "FAILURE",
            "error": f"unknown basic-sql extended join feature {feature_key!r}",
        }

    fx = BASIC_SQL_EXTENDED_FIXTURES[feature_key]
    if not fx.is_join or fx.is_nway_join:
        return {
            "status": "FAILURE",
            "error": f"{feature_key!r} is not a two-table join fixture",
        }

    assert fx.table_order is not None and len(fx.table_order) == 2
    assert fx.default_tbls is not None
    rs_path = os.path.join(GENERATED, f"basic_{feature_key}.rs")
    default_tbls = dict(fx.default_tbls)
    write_unified_join_program(
        rs_path=rs_path,
        sql=fx.sql,
        multi_schema=fx.schema,  # type: ignore[arg-type]
        table_order=fx.table_order,  # type: ignore[arg-type]
        runquery_body=fx.run_query,
        ret_type=fx.ret_type,
        default_tbls=default_tbls,
        workload="basic_sql",
        query_key=feature_key,
    )

    proof_verified = False
    verify_msg = ""
    if enable_verify and verus_on_path():
        proof_verified, verify_msg = run_verus_verify(rs_path, verify_timeout)
        if not proof_verified:
            log_path = os.path.join(GENERATED, f"verify_error_basic_{feature_key}.log")
            with open(log_path, "w") as f:
                f.write(verify_msg)
            if require_proof:
                return {
                    "status": "FAILURE",
                    "proof_verified": False,
                    "error": f"verus verify failed (REQUIRE_PROOF=1): see {log_path}",
                    "verify_msg": verify_msg[:2000],
                    "workload": "basic_sql",
                    "query_key": feature_key,
                    "query_label": f"basic_sql:{feature_key}",
                }
            verify_msg = f"failed (see {log_path})"
    elif enable_verify:
        verify_msg = "skipped: verus not on PATH"
        if require_proof:
            return {
                "status": "FAILURE",
                "proof_verified": False,
                "error": "verus not on PATH but REQUIRE_PROOF=1 / ENABLE_VERUS_VERIFY=1",
                "verify_msg": verify_msg,
                "workload": "basic_sql",
                "query_key": feature_key,
                "query_label": f"basic_sql:{feature_key}",
            }

    ok, compile_msg, binary = run_verus_compile(rs_path, compile_timeout)
    if not ok or not binary:
        log_path = os.path.join(GENERATED, f"compile_error_basic_{feature_key}.log")
        with open(log_path, "w") as f:
            f.write(compile_msg)
        return {
            "status": "FAILURE",
            "proof_verified": proof_verified,
            "error": f"verus --compile failed: see {log_path}",
            "verify_msg": verify_msg,
            "workload": "basic_sql",
            "query_key": feature_key,
        }

    result: dict = {
        "status": "SUCCESS" if proof_verified or not require_proof else "SUCCESS_UNVERIFIED",
        "proof_verified": proof_verified,
        "verify_msg": verify_msg,
        "workload": "basic_sql",
        "query_key": feature_key,
        "query_label": f"basic_sql:{feature_key}",
        "rs_path": rs_path,
        "binary": binary,
    }

    if skip_bench:
        return result

    resolved_tbls = tbls or _extended_join_testdata_paths(feature_key)
    missing = [t for t, p in resolved_tbls.items() if not os.path.exists(p)]
    if missing:
        result["bench_skipped"] = True
        result["bench_msg"] = f"tbl missing for {missing}"
        return result

    left_table, right_table = fx.table_order
    latency, stdout, stderr = run_binary_join(
        binary,
        resolved_tbls[left_table],
        resolved_tbls[right_table],
        limit,
    )
    result["latency_us"] = latency
    result["stdout"] = stdout
    if latency < 0:
        result["status"] = "FAILURE"
        result["error"] = f"no QUERY_LATENCY_US in output\n{stdout}\n{stderr}"
    return result


def run_basic_sql_pipeline(
    feature_key: str,
    *,
    limit: int = 50_000,
    tbl: str | None = None,
    skip_bench: bool = False,
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

    if feature_key not in ALL_BASIC_SQL_FIXTURES:
        return {
            "status": "FAILURE",
            "error": f"unknown basic-sql feature {feature_key!r}",
        }

    fx = ALL_BASIC_SQL_FIXTURES[feature_key]
    rs_path = os.path.join(GENERATED, f"basic_{feature_key}.rs")
    default_tbl = f"verus/research_loop/testdata/basic_{feature_key}.tbl"
    write_unified_program(
        rs_path=rs_path,
        sql=fx.sql,
        schema=fx.schema,
        runquery_body=fx.run_query,
        ret_type=fx.ret_type,
        default_tbl=default_tbl,
        workload="basic_sql",
        query_key=feature_key,
    )

    proof_verified = False
    verify_msg = ""
    if enable_verify and verus_on_path():
        proof_verified, verify_msg = run_verus_verify(rs_path, verify_timeout)
        if not proof_verified:
            log_path = os.path.join(GENERATED, f"verify_error_basic_{feature_key}.log")
            with open(log_path, "w") as f:
                f.write(verify_msg)
            if require_proof:
                return {
                    "status": "FAILURE",
                    "proof_verified": False,
                    "error": f"verus verify failed (REQUIRE_PROOF=1): see {log_path}",
                    "verify_msg": verify_msg[:2000],
                    "workload": "basic_sql",
                    "query_key": feature_key,
                    "query_label": f"basic_sql:{feature_key}",
                }
            verify_msg = f"failed (see {log_path})"
    elif enable_verify:
        verify_msg = "skipped: verus not on PATH"
        if require_proof:
            return {
                "status": "FAILURE",
                "proof_verified": False,
                "error": "verus not on PATH but REQUIRE_PROOF=1 / ENABLE_VERUS_VERIFY=1",
                "verify_msg": verify_msg,
                "workload": "basic_sql",
                "query_key": feature_key,
                "query_label": f"basic_sql:{feature_key}",
            }

    ok, compile_msg, binary = run_verus_compile(rs_path, compile_timeout)
    if not ok or not binary:
        log_path = os.path.join(GENERATED, f"compile_error_basic_{feature_key}.log")
        with open(log_path, "w") as f:
            f.write(compile_msg)
        return {
            "status": "FAILURE",
            "proof_verified": proof_verified,
            "error": f"verus --compile failed: see {log_path}",
            "verify_msg": verify_msg,
            "workload": "basic_sql",
            "query_key": feature_key,
        }

    result: dict = {
        "status": "SUCCESS" if proof_verified or not require_proof else "SUCCESS_UNVERIFIED",
        "proof_verified": proof_verified,
        "verify_msg": verify_msg,
        "workload": "basic_sql",
        "query_key": feature_key,
        "query_label": f"basic_sql:{feature_key}",
        "rs_path": rs_path,
        "binary": binary,
    }

    if skip_bench:
        return result

    tbl_path = tbl or basic_sql_tbl_path(feature_key)
    if not os.path.exists(tbl_path):
        result["bench_skipped"] = True
        result["bench_msg"] = f"tbl missing: {tbl_path}"
        return result

    latency, stdout, stderr = run_binary(binary, tbl_path, limit)
    result["latency_us"] = latency
    result["stdout"] = stdout
    if latency < 0:
        result["status"] = "FAILURE"
        result["error"] = f"no QUERY_LATENCY_US in output\n{stdout}\n{stderr}"
    return result


def _join_testdata_paths(feature_key: str) -> dict[str, str]:
    fx = BASIC_SQL_JOIN_FIXTURES[feature_key]
    return {
        table: os.path.join(ROOT_DIR, rel) for table, rel in fx.default_tbls.items()
    }


def run_basic_sql_join_pipeline(
    feature_key: str,
    *,
    limit: int | None = None,
    tbls: dict[str, str] | None = None,
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

    if feature_key not in BASIC_SQL_JOIN_FIXTURES:
        return {
            "status": "FAILURE",
            "error": f"unknown basic-sql join feature {feature_key!r}",
        }

    fx = BASIC_SQL_JOIN_FIXTURES[feature_key]
    bench_limit = limit if limit is not None else fx.bench_limit
    rs_path = os.path.join(GENERATED, f"basic_join_{feature_key}.rs")
    default_tbls = dict(fx.default_tbls)
    write_unified_join_program(
        rs_path=rs_path,
        sql=fx.sql,
        multi_schema=fx.schema,
        table_order=fx.table_order,
        runquery_body=fx.run_query,
        ret_type=fx.ret_type,
        default_tbls=default_tbls,
        workload="basic_sql_join",
        query_key=feature_key,
        hot_path_rs=fx.hot_path,
        bench_exec=fx.bench_exec,
    )

    proof_verified = False
    verify_msg = ""
    if enable_verify and verus_on_path():
        proof_verified, verify_msg = run_verus_verify(rs_path, verify_timeout)
        if not proof_verified:
            log_path = os.path.join(
                GENERATED, f"verify_error_basic_join_{feature_key}.log"
            )
            with open(log_path, "w") as f:
                f.write(verify_msg)
            if require_proof:
                return {
                    "status": "FAILURE",
                    "proof_verified": False,
                    "error": f"verus verify failed (REQUIRE_PROOF=1): see {log_path}",
                    "verify_msg": verify_msg[:2000],
                    "workload": "basic_sql_join",
                    "query_key": feature_key,
                    "query_label": f"basic_sql_join:{feature_key}",
                }
            verify_msg = f"failed (see {log_path})"
    elif enable_verify:
        verify_msg = "skipped: verus not on PATH"
        if require_proof:
            return {
                "status": "FAILURE",
                "proof_verified": False,
                "error": "verus not on PATH but REQUIRE_PROOF=1 / ENABLE_VERUS_VERIFY=1",
                "verify_msg": verify_msg,
                "workload": "basic_sql_join",
                "query_key": feature_key,
                "query_label": f"basic_sql_join:{feature_key}",
            }

    ok, compile_msg, binary = run_verus_compile(rs_path, compile_timeout)
    if not ok or not binary:
        log_path = os.path.join(
            GENERATED, f"compile_error_basic_join_{feature_key}.log"
        )
        with open(log_path, "w") as f:
            f.write(compile_msg)
        return {
            "status": "FAILURE",
            "proof_verified": proof_verified,
            "error": f"verus --compile failed: see {log_path}",
            "verify_msg": verify_msg,
            "workload": "basic_sql_join",
            "query_key": feature_key,
        }

    result: dict = {
        "status": "SUCCESS" if proof_verified or not require_proof else "SUCCESS_UNVERIFIED",
        "proof_verified": proof_verified,
        "verify_msg": verify_msg,
        "workload": "basic_sql_join",
        "query_key": feature_key,
        "query_label": f"basic_sql_join:{feature_key}",
        "rs_path": rs_path,
        "binary": binary,
    }

    if skip_bench:
        return result

    resolved_tbls = tbls or _join_testdata_paths(feature_key)
    missing = [t for t, p in resolved_tbls.items() if not os.path.exists(p)]
    if missing:
        result["bench_skipped"] = True
        result["bench_msg"] = f"tbl missing for {missing}"
        return result

    left_table, right_table = fx.table_order
    if not skip_bare:
        bare_us = bench_bare_join(
            feature_key,
            resolved_tbls[left_table],
            resolved_tbls[right_table],
            bench_limit,
        )
        if bare_us >= 0:
            result["bare_us"] = bare_us

    latency, stdout, stderr = run_binary_join(
        binary,
        resolved_tbls[left_table],
        resolved_tbls[right_table],
        bench_limit,
    )
    result["latency_us"] = latency
    result["stdout"] = stdout
    result["bench_limit"] = bench_limit
    if latency < 0:
        result["status"] = "FAILURE"
        result["error"] = f"no QUERY_LATENCY_US in output\n{stdout}\n{stderr}"
    return result


def run_custom_sql_pipeline(
    sql: str,
    schema: dict,
    *,
    run_query_body: str | None = None,
    tbl: str | None = None,
    tbls: dict[str, str] | None = None,
    limit: int = 50_000,
    table_order: tuple[str, ...] | None = None,
    skip_bench: bool = False,
) -> dict:
    """Transpile MethodSpec → agent run_query → assemble → verify → compile → run.

    Never falls back to DuckDB or auto-codegen — unsupported SQL or missing
    ``run_query_body`` fail loudly with artifacts under ``agents/``.
    """
    from verus_transpiler.parse_sql import normalize_schema, parse_sql

    cfg = load_env(os.path.join(CURRENT_DIR, "config.env"))
    for k, v in cfg.items():
        os.environ.setdefault(k, v)

    verify_timeout = int(os.environ.get("VERUS_VERIFY_TIMEOUT_SEC", "120"))
    compile_timeout = int(os.environ.get("COMPILE_TIMEOUT_SEC", "180"))
    enable_verify = os.environ.get("ENABLE_VERUS_VERIFY", "1") == "1"
    require_proof = os.environ.get(
        "REQUIRE_PROOF", "1" if enable_verify else "0"
    ) == "1"

    try:
        _flat, multi = normalize_schema(schema)
    except Exception as e:
        return _pipeline_failure("parse", sql, f"schema: {e}", schema)

    try:
        query = parse_sql(sql, schema)
    except Exception as e:
        return _pipeline_failure("parse", sql, str(e), schema)

    try:
        if multi:
            projected = project_multi_schema_for_query(sql, multi)
        else:
            projected = project_schema_for_query(sql, _flat)
    except Exception:
        projected = schema

    try:
        spec_rs = transpile_sql_to_verus(sql, projected, enable_templates=enable_templates())
    except Exception as e:
        return _pipeline_failure("transpile", sql, str(e), schema)

    body = (run_query_body or "").strip()
    if not body:
        tbl_paths: dict[str, str] | None = None
        if tbl:
            tbl_paths = {"t": tbl}
        elif tbls:
            tbl_paths = dict(tbls)
        return _pipeline_failure(
            "awaiting_agent",
            sql,
            "missing run_query_body — agent must supply proved run_query ≡ method_spec",
            schema,
            spec_rs=spec_rs,
            tbl_paths=tbl_paths,
            limit=limit,
        )

    try:
        ret_type = _resolve_custom_ret_type(query, projected, multi=bool(multi))
    except Exception as e:
        return _pipeline_failure("assemble", sql, f"ret_type: {e}", schema)

    rs_path = os.path.join(GENERATED, "custom_query.rs")

    try:
        if query.joins and multi:
            tables = tuple(query.tables)
            if len(tables) == 2:
                order = table_order or tables
                left_t, right_t = order[0], order[1]
                default_tbls = tbls or {left_t: "", right_t: ""}
                multi_schema = projected if isinstance(projected, dict) else schema
                program = assemble_verified_join_program(
                    spec_rs=spec_rs,
                    run_query_body=body,
                    multi_schema=multi_schema,
                    table_order=(left_t, right_t),
                    ret_type=ret_type,
                    default_tbls=default_tbls,
                )
            elif len(tables) >= 3:
                order = table_order or tables
                default_tbls = tbls or {t: "" for t in order}
                multi_schema = projected if isinstance(projected, dict) else schema
                program = assemble_verified_nway_program(
                    spec_rs=spec_rs,
                    run_query_body=body,
                    multi_schema=multi_schema,
                    table_order=order,
                    ret_type=ret_type,
                    default_tbls=default_tbls,
                )
            else:
                return _pipeline_failure(
                    "assemble", sql, "join requires at least two tables", schema
                )
        else:
            if multi:
                return _pipeline_failure(
                    "assemble",
                    sql,
                    "single-table custom query requires flat schema dict",
                    schema,
                )
            schema_dict = projected if isinstance(projected, dict) else _flat
            default_tbl = tbl or ""
            program = assemble_verified_program(
                spec_rs=spec_rs,
                run_query_body=body,
                schema_dict=schema_dict,
                ret_type=ret_type,
                default_tbl=default_tbl,
            )
    except Exception as e:
        return _pipeline_failure("assemble", sql, str(e), schema)

    os.makedirs(os.path.dirname(rs_path), exist_ok=True)
    with open(rs_path, "w") as f:
        f.write(program)

    proof_verified = False
    verify_msg = ""
    if enable_verify and verus_on_path():
        proof_verified, verify_msg = run_verus_verify(rs_path, verify_timeout)
        if not proof_verified:
            log_path = os.path.join(GENERATED, "verify_error_custom.log")
            with open(log_path, "w") as f:
                f.write(verify_msg)
            if require_proof:
                return _pipeline_failure(
                    "verify",
                    sql,
                    f"verus verify failed: see {log_path}",
                    schema,
                    proof_verified=False,
                    verify_msg=verify_msg[:2000],
                )
    elif enable_verify and require_proof:
        return _pipeline_failure("verify", sql, "verus not on PATH", schema)

    ok, compile_msg, binary = run_verus_compile(rs_path, compile_timeout)
    if not ok or not binary:
        log_path = os.path.join(GENERATED, "compile_error_custom.log")
        with open(log_path, "w") as f:
            f.write(compile_msg)
        return _pipeline_failure(
            "compile",
            sql,
            f"verus --compile failed: see {log_path}",
            schema,
            proof_verified=proof_verified,
        )

    result: dict = {
        "status": "SUCCESS" if proof_verified or not require_proof else "SUCCESS_UNVERIFIED",
        "proof_verified": proof_verified,
        "verify_msg": verify_msg,
        "workload": "custom",
        "ret_type": ret_type,
        "rs_path": rs_path,
        "binary": binary,
    }

    if skip_bench:
        return result

    if query.joins and multi:
        tables = tuple(query.tables)
        if len(tables) == 2:
            order = table_order or tables
            resolved = tbls or {}
            left_p = resolved.get(order[0], "")
            right_p = resolved.get(order[1], "")
            if (
                not left_p
                or not right_p
                or not os.path.exists(left_p)
                or not os.path.exists(right_p)
            ):
                result["bench_skipped"] = True
                return result
            latency, stdout, stderr = run_binary_join(
                binary, left_p, right_p, limit
            )
        elif len(tables) >= 3:
            order = table_order or tables
            resolved = tbls or {}
            paths = [resolved.get(t, "") for t in order]
            if any(not p or not os.path.exists(p) for p in paths):
                result["bench_skipped"] = True
                return result
            latency, stdout, stderr = run_binary_nway(
                binary, resolved, limit, table_order=order
            )
        else:
            result["bench_skipped"] = True
            return result
    else:
        tbl_path = tbl or ""
        if not tbl_path or not os.path.exists(tbl_path):
            result["bench_skipped"] = True
            return result
        latency, stdout, stderr = run_binary(binary, tbl_path, limit)

    if latency >= 0:
        result["latency_us"] = latency
        result["stdout"] = stdout
    else:
        result["bench_error"] = stderr
    return result


def run_pipeline(
    query_idx: int = 1,
    *,
    limit: int = 50_000,
    tbl: str | None = None,
    skip_bench: bool = False,
    skip_bare: bool = False,
    **_: object,
) -> dict:
    return run_ssb_pipeline(
        query_idx,
        limit=limit,
        tbl=tbl,
        skip_bench=skip_bench,
        skip_bare=skip_bare,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Verus research loop harness")
    parser.add_argument(
        "-q",
        "--query",
        type=str,
        default="1",
        help="SSB query index or 'all' (default 1)",
    )
    parser.add_argument("--tpch", action="store_true", help="Run TPC-H fixtures (Q1/Q6)")
    parser.add_argument(
        "--basic-sql",
        type=str,
        default=None,
        help="Run basic-sql fixture key or 'all'",
    )
    parser.add_argument("--limit", type=int, default=50_000, help="Row limit from tbl")
    parser.add_argument("--tbl", type=str, default=None, help="Path to workload tbl")
    parser.add_argument("--skip-bench", action="store_true")
    parser.add_argument(
        "--runquery-file",
        type=str,
        default=None,
        help="Path to agent-supplied run_query body for --sql (required)",
    )
    parser.add_argument(
        "--sql",
        type=str,
        default=None,
        help="Ad-hoc SQL for custom agent pipeline (requires --runquery-file)",
    )
    parser.add_argument(
        "--schema-json",
        type=str,
        default=None,
        help="Path to JSON schema (flat or multi-table) for --sql",
    )
    args = parser.parse_args()

    if args.sql is not None:
        import json

        if not args.schema_json:
            print("error: --sql requires --schema-json", file=sys.stderr)
            sys.exit(1)
        with open(args.schema_json) as f:
            schema = json.load(f)
        runquery_body: str | None = None
        if args.runquery_file:
            with open(args.runquery_file, encoding="utf-8") as f:
                runquery_body = f.read()
        t0 = time.perf_counter()
        res = run_custom_sql_pipeline(
            args.sql,
            schema,
            run_query_body=runquery_body,
            tbl=args.tbl,
            limit=args.limit,
            skip_bench=args.skip_bench,
        )
        res["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
        _print_single_result(res)
        if res.get("status") not in ("SUCCESS", "SUCCESS_UNVERIFIED"):
            sys.exit(1)
        return

    if args.basic_sql is not None:
        if args.basic_sql.lower() == "all":
            keys = (
                sorted(ALL_BASIC_SQL_FIXTURES.keys())
                + sorted(BASIC_SQL_JOIN_FIXTURES.keys())
            )
        else:
            keys = [args.basic_sql]
        for key in keys:
            t0 = time.perf_counter()
            if key in BASIC_SQL_JOIN_FIXTURES:
                res = run_basic_sql_join_pipeline(
                    key,
                    limit=args.limit if args.limit != 50_000 else None,
                    skip_bench=args.skip_bench,
                )
            elif key in BASIC_SQL_EXTENDED_FIXTURES:
                fx = BASIC_SQL_EXTENDED_FIXTURES[key]
                if fx.is_nway_join:
                    res = run_basic_sql_nway_pipeline(
                        key, limit=args.limit, skip_bench=args.skip_bench
                    )
                elif fx.is_join:
                    res = run_basic_sql_extended_join_pipeline(
                        key, limit=args.limit, skip_bench=args.skip_bench
                    )
                else:
                    res = run_basic_sql_pipeline(
                        key,
                        limit=args.limit,
                        tbl=args.tbl,
                        skip_bench=args.skip_bench,
                    )
            else:
                res = run_basic_sql_pipeline(
                    key,
                    limit=args.limit,
                    tbl=args.tbl,
                    skip_bench=args.skip_bench,
                )
            res["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            _print_single_result(res)
            if res.get("status") not in ("SUCCESS", "SUCCESS_UNVERIFIED"):
                sys.exit(1)
        return

    if args.tpch:
        keys = sorted(TPCH_RUNQUERIES.keys()) if args.query.lower() == "all" else [args.query.upper()]
        for q in keys:
            t0 = time.perf_counter()
            res = run_tpch_pipeline(q, limit=args.limit, tbl=args.tbl, skip_bench=args.skip_bench)
            res["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            _print_single_result(res)
            if res.get("status") not in ("SUCCESS", "SUCCESS_UNVERIFIED"):
                sys.exit(1)
        return

    if args.query.lower() == "all":
        keys = sorted(SSB_RUNQUERIES.keys())
    else:
        keys = [int(args.query)]

    for qidx in keys:
        t0 = time.perf_counter()
        res = run_ssb_pipeline(
            qidx,
            limit=args.limit,
            tbl=args.tbl,
            skip_bench=args.skip_bench,
        )
        res["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
        _print_single_result(res)
        if res.get("status") not in ("SUCCESS", "SUCCESS_UNVERIFIED"):
            sys.exit(1)


def _print_single_result(res: dict) -> None:
    if res.get("status") not in ("SUCCESS", "SUCCESS_UNVERIFIED"):
        agents_path = res.get("agents_failure_path")
        if agents_path:
            rel = os.path.relpath(agents_path, CURRENT_DIR)
            print(
                f"CUSTOM_PIPELINE_FAILED: {res.get('error', res)} → {rel}",
                file=sys.stderr,
            )
        else:
            print(res.get("error", res), file=sys.stderr)
        return
    if res.get("bench_skipped"):
        print(f"{res.get('query_label')}: {res['bench_msg']}")
    else:
        print(res.get("stdout", ""))
    if res.get("verify_msg"):
        print(f"verify: {res['verify_msg']}", file=sys.stderr)
    print(f"proof_verified={res.get('proof_verified')}")


if __name__ == "__main__":
    main()
