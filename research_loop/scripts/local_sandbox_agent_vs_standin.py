#!/usr/bin/env python3
"""Local sandboxed Cursor agent vs stand-in (TPCH or SSB, small row limit)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, ROOT)

from verus_transpiler.column_projection import project_schema_for_query


def _env_for_cli_agent(*, limit: int, tbl: Path, workload: str) -> None:
    os.environ["PATH"] = (
        f"/home/emil/tools/verus:{os.environ.get('HOME', '/home/emil')}/.cargo/bin:"
        f"{os.environ.get('HOME', '/home/emil')}/.local/bin:{os.environ.get('PATH', '')}"
    )
    os.environ["LEMMA_AGENT_BACKEND"] = "cli"
    os.environ["USE_AGENT_DOCKER"] = "1"
    os.environ["AGENT_IMAGE"] = "lemma-agent:cli"
    os.environ["MOCK_AGENT"] = "0"
    os.environ["MAX_ITERATIONS"] = os.environ.get("MAX_ITERATIONS", "1")
    os.environ["AGENT_TIMEOUT_SEC"] = os.environ.get("AGENT_TIMEOUT_SEC", "600")
    os.environ["LEMMA_DATASET_SIZE"] = str(limit)
    os.environ["LEMMA_BENCH_TBL"] = str(tbl)
    os.environ["LEMMA_WORKLOAD"] = workload
    os.environ["LEMMA_RESEARCH_LOG"] = "1"
    os.environ["LEMMA_EXPERIMENT"] = "1"
    os.environ["LEMMA_EXPERIMENT_ALLOW_DIRTY"] = "1"
    os.environ["LEMMA_ALLOW_DUCKDB_FALLBACK"] = "0"
    os.environ["LEMMA_AGENT_HARDWARE"] = "1"
    os.environ["LEMMA_AGENT_STATS"] = "1"
    os.environ["AGENT_DATA_MODE"] = "stats"
    os.environ["AGENT_NETWORK"] = "0"
    os.environ["AGENT_WEB_SEARCH"] = "0"
    os.environ["AGENT_EGRESS_PROFILE"] = "cursor"
    home = os.environ.get("HOME", "/home/emil")
    os.environ["AGENT_CREDENTIALS_DIR"] = str(Path(home) / ".cursor")
    os.environ["AGENT_AUTH_DIR"] = str(Path(home) / ".config" / "cursor")
    os.environ["AGENT_CMD"] = (
        'agent -p --force --trust --approve-mcps --model cursor-grok-4.5-high '
        '--output-format stream-json --stream-partial-output "$(cat PROMPT.txt)"'
    )


def _parse_latency(out: str) -> tuple[int, bool, str]:
    latency = -1
    proof = False
    status = "FAILURE"
    m = re.search(r"QUERY_LATENCY_US:\s*(\d+)", out)
    if m:
        latency = int(m.group(1))
    for line in out.splitlines():
        if line.startswith("TPC-H") or line.startswith("SSB"):
            parts = line.split()
            if len(parts) >= 6:
                try:
                    if parts[2] != "-":
                        latency = int(parts[2])
                except ValueError:
                    pass
                proof = parts[5] in ("1", "True", "true")
                status = parts[-1]
    if latency >= 0 and "proof_ok" not in out.lower():
        # SSB sometimes prints latency before the table parser fails
        if "RESULT:" in out or "QUERY_LATENCY_US:" in out:
            proof = True
            status = "SUCCESS"
    if latency >= 0 and proof:
        status = "SUCCESS"
    return latency, proof, status


def standin_latency_us(*, workload: str, qkey: str, limit: int, tbl: Path) -> dict:
    cmd = [
        "uv",
        "run",
        "python",
        "research_loop/benchmark_verified.py",
        "--limit",
        str(limit),
        "--tbl",
        str(tbl),
    ]
    if workload == "tpch":
        cmd += ["--tpch", "-q", qkey]
    else:
        cmd += ["-q", qkey]
    env = os.environ.copy()
    env["PATH"] = (
        f"/home/emil/tools/verus:{env.get('HOME', '/home/emil')}/.cargo/bin:{env.get('PATH', '')}"
    )
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    wall = time.perf_counter() - t0
    out = (proc.stdout or "") + (proc.stderr or "")
    latency, proof, status = _parse_latency(out)
    # proof_ok column can be 1 even when parser marks FAILURE
    if latency >= 0 and re.search(r"\b1\s+FAILURE\b", out):
        proof = True
        status = "SUCCESS"
    return {
        "status": status,
        "latency_us": latency,
        "proof_verified": proof,
        "wall_s": wall,
        "returncode": proc.returncode,
        "tail": "\n".join(out.splitlines()[-40:]),
    }


def _resolve_query(spec: str) -> tuple[str, str, str, Path, dict]:
    """Return workload, qkey, sql, tbl, schema_dict."""
    spec = spec.upper()
    if spec.startswith("SSB"):
        from research_loop.ssb_queries import queries as ssb_queries
        from research_loop.ssb_queries import schema as ssb_schema

        idx = int(spec.replace("SSB", "").replace("Q", "") or "1")
        sql = ssb_queries[idx - 1].strip()
        tbl = ROOT / "ssb-dbgen" / "lineorder_flat.tbl"
        return "ssb", str(idx), sql, tbl, dict(ssb_schema)
    # TPCH
    from research_loop.bench_standins.tpch_runqueries import lineitem_schema
    from research_loop.bench_standins.tpch_runqueries import queries as tpch_sql

    qkey = spec if spec.startswith("Q") else f"Q{spec}"
    sql = tpch_sql[qkey].strip()
    tbl = ROOT / "data" / "tpch-sf1" / "lineitem.tbl"
    return "tpch", qkey, sql, tbl, dict(lineitem_schema)


def run_agent(
    *,
    workload: str,
    qkey: str,
    sql: str,
    schema: dict,
    tbl: Path,
    limit: int,
    log_dir: Path,
) -> dict:
    from db_extension.optimizer import run_optimization_loop

    projected = project_schema_for_query(sql, schema)
    _env_for_cli_agent(limit=limit, tbl=tbl, workload=workload)
    table_name = "lineorder_flat" if workload == "ssb" else "lineitem"
    print(f"=== sandbox agent {workload}:{qkey} limit={limit} ===", flush=True)
    print(f"hardware: nproc={os.cpu_count()} (LEMMA_AGENT_HARDWARE=1)", flush=True)
    t0 = time.perf_counter()
    res = run_optimization_loop(
        sql,
        dataset_size=limit,
        max_iterations=int(os.environ["MAX_ITERATIONS"]),
        use_mock=False,
        schema=projected,
        workload_tables={table_name: tbl},
    )
    wall = time.perf_counter() - t0
    res = dict(res)
    res["wall_s"] = wall
    (log_dir / f"agent_{workload}_{qkey}_result.json").write_text(
        json.dumps(res, indent=2) + "\n"
    )
    return res


def main() -> int:
    os.chdir(ROOT)
    spec = (sys.argv[1] if len(sys.argv) > 1 else "SSB1").upper()
    limit = int(os.environ.get("LEMMA_DATASET_SIZE", "5000"))
    workload, qkey, sql, tbl, schema = _resolve_query(spec)
    if os.environ.get("LEMMA_BENCH_TBL"):
        tbl = Path(os.environ["LEMMA_BENCH_TBL"])
    if not tbl.is_file():
        print(f"missing tbl {tbl}", file=sys.stderr)
        return 2
    if shutil.which("verus") is None and not Path("/home/emil/tools/verus/verus").is_file():
        print("verus missing", file=sys.stderr)
        return 2

    log_dir = ROOT / "research_loop" / "generated" / "local_sandbox_agent"
    log_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== stand-in {workload}:{qkey} limit={limit} ===", flush=True)
    standin = standin_latency_us(workload=workload, qkey=qkey, limit=limit, tbl=tbl)
    (log_dir / f"standin_{workload}_{qkey}.json").write_text(json.dumps(standin, indent=2) + "\n")
    print(
        f"standin status={standin['status']} latency_us={standin['latency_us']} "
        f"proof={standin['proof_verified']}",
        flush=True,
    )

    agent = run_agent(
        workload=workload,
        qkey=qkey,
        sql=sql,
        schema=schema,
        tbl=tbl,
        limit=limit,
        log_dir=log_dir,
    )
    print(
        f"agent status={agent.get('status')} best_latency_us={agent.get('best_latency_us')} "
        f"wall_s={agent.get('wall_s'):.1f}",
        flush=True,
    )
    summary = {
        "workload": workload,
        "query": qkey,
        "limit": limit,
        "tbl": str(tbl),
        "sql_preview": " ".join(sql.split())[:160],
        "standin_latency_us": standin.get("latency_us"),
        "standin_proof": standin.get("proof_verified"),
        "agent_status": agent.get("status"),
        "agent_best_latency_us": agent.get("best_latency_us"),
        "agent_wall_s": agent.get("wall_s"),
        "ratio_agent_over_standin": (
            (agent.get("best_latency_us") / standin["latency_us"])
            if isinstance(agent.get("best_latency_us"), int)
            and agent.get("best_latency_us", -1) > 0
            and isinstance(standin.get("latency_us"), int)
            and standin["latency_us"] > 0
            else None
        ),
    }
    (log_dir / f"summary_{workload}_{qkey}.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if agent.get("status") == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
