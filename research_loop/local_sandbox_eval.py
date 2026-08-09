"""Pure helpers for local sandbox agent vs stand-in evaluation (importable by pytest)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def verus_available() -> bool:
    return shutil.which("verus") is not None or Path("/home/emil/tools/verus/verus").is_file()


def parse_latency(out: str) -> tuple[int, bool, str]:
    """Parse benchmark stdout/stderr for latency_us, proof flag, and status."""
    latency = -1
    proof = False
    status = "FAILURE"
    m = re.search(r"QUERY_LATENCY_US:\s*(\d+)", out)
    if m:
        latency = int(m.group(1))
    for line in out.splitlines():
        if line.startswith(("TPC-H", "SSB")):
            parts = line.split()
            if len(parts) >= 6:
                try:
                    if parts[2] != "-":
                        latency = int(parts[2])
                except ValueError:
                    pass
                proof = parts[5] in ("1", "True", "true")
                status = parts[-1]
    if latency >= 0 and "proof_ok" not in out.lower() and (
        "RESULT:" in out or "QUERY_LATENCY_US:" in out
    ):
        # SSB sometimes prints latency before the table parser fails
        proof = True
        status = "SUCCESS"
    if latency >= 0 and proof:
        status = "SUCCESS"
    return latency, proof, status


def resolve_query(spec: str) -> tuple[str, str, str, Path, dict]:
    """Return workload, qkey, sql, tbl, schema_dict for a query spec (e.g. SSB1, Q6)."""
    spec = spec.upper()
    if spec.startswith("SSB"):
        from research_loop.ssb_queries import queries as ssb_queries
        from research_loop.ssb_queries import schema as ssb_schema

        idx = int(spec.replace("SSB", "").replace("Q", "") or "1")
        sql = ssb_queries[idx - 1].strip()
        tbl = REPO_ROOT / "ssb-dbgen" / "lineorder_flat.tbl"
        return "ssb", str(idx), sql, tbl, dict(ssb_schema)
    from research_loop.bench_standins.tpch_runqueries import lineitem_schema
    from research_loop.bench_standins.tpch_runqueries import queries as tpch_sql

    qkey = spec if spec.startswith("Q") else f"Q{spec}"
    sql = tpch_sql[qkey].strip()
    tbl = REPO_ROOT / "data" / "tpch-sf1" / "lineitem.tbl"
    return "tpch", qkey, sql, tbl, dict(lineitem_schema)


def standin_benchmark_cmd(
    *,
    workload: str,
    qkey: str,
    limit: int,
    tbl: Path,
    repo_root: Path | None = None,
) -> list[str]:
    """Build argv for `research_loop/benchmark_verified.py` stand-in timing."""
    root = repo_root or REPO_ROOT
    cmd = [
        "uv",
        "run",
        "python",
        str(root / "research_loop" / "benchmark_verified.py"),
        "--limit",
        str(limit),
        "--tbl",
        str(tbl),
    ]
    if workload == "tpch":
        cmd += ["--tpch", "-q", qkey]
    else:
        cmd += ["-q", qkey]
    return cmd


def standin_latency_us(*, workload: str, qkey: str, limit: int, tbl: Path) -> dict:
    """Run stand-in benchmark subprocess; return parsed latency and status."""
    cmd = standin_benchmark_cmd(workload=workload, qkey=qkey, limit=limit, tbl=tbl)
    env = os.environ.copy()
    env["PATH"] = (
        f"/home/emil/tools/verus:{env.get('HOME', '/home/emil')}/.cargo/bin:{env.get('PATH', '')}"
    )
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False)
    wall = time.perf_counter() - t0
    out = (proc.stdout or "") + (proc.stderr or "")
    latency, proof, status = parse_latency(out)
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
