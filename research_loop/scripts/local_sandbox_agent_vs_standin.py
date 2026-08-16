#!/usr/bin/env python3
"""Local sandboxed Cursor agent vs stand-in (TPCH or SSB, small row limit)."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verus_transpiler.column_projection import project_schema_for_query

from research_loop.local_sandbox_eval import (
    REPO_ROOT,
    resolve_query,
    standin_latency_us,
    verus_available,
)


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
        'agent -p --force --trust --approve-mcps --model cursor-grok-4.6-high '
        '--output-format stream-json --stream-partial-output "$(cat PROMPT.txt)"'
    )


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
    os.chdir(REPO_ROOT)
    spec = (sys.argv[1] if len(sys.argv) > 1 else "SSB1").upper()
    limit = int(os.environ.get("LEMMA_DATASET_SIZE", "5000"))
    workload, qkey, sql, tbl, schema = resolve_query(spec)
    if os.environ.get("LEMMA_BENCH_TBL"):
        tbl = Path(os.environ["LEMMA_BENCH_TBL"])
    if not tbl.is_file():
        print(f"missing tbl {tbl}", file=sys.stderr)
        return 2
    if not verus_available():
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
