#!/usr/bin/env python3
"""Local sandboxed Cursor agent on TPCH Q1/Q6 vs stand-in (small row limit)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, ROOT)

from research_loop.bench_standins.tpch_runqueries import queries as TPCH_SQL
from research_loop.bench_standins.tpch_runqueries import lineitem_schema
from verus_transpiler.column_projection import project_schema_for_query


def _env_for_cli_agent(*, limit: int, tbl: Path) -> None:
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
    os.environ["LEMMA_WORKLOAD"] = "tpch"
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


def standin_latency_us(qkey: str, limit: int, tbl: Path) -> dict:
    """Run verified stand-in through research_loop harness (same limit)."""
    cmd = [
        "uv",
        "run",
        "python",
        "research_loop/benchmark_verified.py",
        "--tpch",
        "-q",
        qkey,
        "--limit",
        str(limit),
        "--tbl",
        str(tbl),
    ]
    env = os.environ.copy()
    env["PATH"] = (
        f"/home/emil/tools/verus:{env.get('HOME', '/home/emil')}/.cargo/bin:{env.get('PATH', '')}"
    )
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    wall = time.perf_counter() - t0
    out = (proc.stdout or "") + (proc.stderr or "")
    # parse table line: TPC-H Q1  <verus_us> ...
    latency = -1
    proof = False
    status = "FAILURE"
    for line in out.splitlines():
        if line.startswith("TPC-H"):
            parts = line.split()
            # Query verus_us bare_us ratio proof_ok status
            if len(parts) >= 6:
                try:
                    latency = int(parts[2]) if parts[2] != "-" else -1
                except ValueError:
                    latency = -1
                proof = parts[5] in ("1", "True", "true")
                status = parts[6] if len(parts) > 6 else parts[-1]
    return {
        "status": status if proc.returncode == 0 else "FAILURE",
        "latency_us": latency,
        "proof_verified": proof,
        "wall_s": wall,
        "returncode": proc.returncode,
        "tail": "\n".join(out.splitlines()[-30:]),
    }


def run_agent(qkey: str, limit: int, tbl: Path, log_dir: Path) -> dict:
    from db_extension.optimizer import run_optimization_loop

    sql = TPCH_SQL[qkey].strip()
    schema = project_schema_for_query(sql, dict(lineitem_schema))
    _env_for_cli_agent(limit=limit, tbl=tbl)

    print(f"=== sandbox agent {qkey} limit={limit} ===", flush=True)
    print(
        f"hardware hint: nproc will be sampled into context "
        f"(LEMMA_AGENT_HARDWARE=1); local nproc={os.cpu_count()}",
        flush=True,
    )
    t0 = time.perf_counter()
    res = run_optimization_loop(
        sql,
        dataset_size=limit,
        max_iterations=int(os.environ["MAX_ITERATIONS"]),
        use_mock=False,
        schema=schema,
        workload_tables={"lineitem": tbl},
    )
    wall = time.perf_counter() - t0
    res = dict(res)
    res["wall_s"] = wall
    (log_dir / f"agent_{qkey}_result.json").write_text(json.dumps(res, indent=2) + "\n")
    return res


def main() -> int:
    os.chdir(ROOT)
    qkey = (sys.argv[1] if len(sys.argv) > 1 else "Q1").upper()
    if qkey not in ("Q1", "Q6"):
        print("usage: local_sandbox_agent_vs_standin.py [Q1|Q6]", file=sys.stderr)
        return 2
    limit = int(os.environ.get("LEMMA_DATASET_SIZE", "50000"))
    tbl = Path(os.environ.get("LEMMA_BENCH_TBL", str(ROOT / "data/tpch-sf1/lineitem.tbl")))
    if not tbl.is_file():
        print(f"missing tbl {tbl}", file=sys.stderr)
        return 2
    if shutil.which("verus") is None and not Path("/home/emil/tools/verus/verus").is_file():
        print("verus missing — export PATH=/home/emil/tools/verus:$PATH", file=sys.stderr)
        return 2

    log_dir = ROOT / "research_loop" / "generated" / "local_sandbox_agent"
    log_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== stand-in {qkey} limit={limit} ===", flush=True)
    standin = standin_latency_us(qkey, limit, tbl)
    (log_dir / f"standin_{qkey}.json").write_text(json.dumps(standin, indent=2) + "\n")
    print(
        f"standin status={standin['status']} latency_us={standin['latency_us']} "
        f"proof={standin['proof_verified']}",
        flush=True,
    )

    agent = run_agent(qkey, limit, tbl, log_dir)
    print(
        f"agent status={agent.get('status')} best_latency_us={agent.get('best_latency_us')} "
        f"wall_s={agent.get('wall_s'):.1f}",
        flush=True,
    )

    summary = {
        "query": qkey,
        "limit": limit,
        "tbl": str(tbl),
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
    (log_dir / f"summary_{qkey}.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if agent.get("status") == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
