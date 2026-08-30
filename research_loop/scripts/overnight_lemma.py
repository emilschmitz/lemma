#!/usr/bin/env python3
"""Overnight Lemma batch: SEC Immanuel 6 + TPC-H Q1/Q3/Q6 (Lemma SQL).

Writes all artifacts under --out-dir (default /home/emil/lemma-overnight-out)
so the git worktree stays clean. Parallel run_optimizer workers.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research_loop" / "scripts"))

from gendb_published_one_run import (  # noqa: E402
    env_for_lemma,
    git_sha,
    parse_optimizer_output,
    parse_queries,
)

SEC_SQL = ROOT / "holdout/gendb_sec_edgar/queries.sql"
TPCH_LEMMA_SQL = ROOT / "holdout/tpch_sf10/queries_paper_subset_lemma.sql"
R16_SQL = ROOT / "holdout/gendb_sec_edgar/queries_resample_r16.sql"
PY = ROOT / ".venv/bin/python"


def jobs_full(sec_db: str, tpch_db: str) -> list[dict]:
    out: list[dict] = []
    sec = parse_queries(SEC_SQL)
    for qid in ["Q1", "Q2", "Q3", "Q4", "Q6", "Q24"]:
        out.append(
            {
                "family": "sec",
                "qid": qid,
                "sql": sec[qid],
                "workload": "sec",
                "duckdb": sec_db,
            }
        )
    tpch = parse_queries(TPCH_LEMMA_SQL)
    for qid in ["Q1", "Q3", "Q6"]:
        out.append(
            {
                "family": "tpch_lemma",
                "qid": qid,
                "sql": tpch[qid],
                "workload": "tpch",
                "duckdb": tpch_db,
            }
        )
    if R16_SQL.is_file():
        r16 = parse_queries(R16_SQL)
        for qid in sorted(r16, key=lambda x: int(x[1:])):
            out.append(
                {
                    "family": "r16",
                    "qid": qid,
                    "sql": r16[qid],
                    "workload": "sec",
                    "duckdb": sec_db,
                }
            )
    return out


def jobs_smoke(sec_db: str) -> list[dict]:
    sec = parse_queries(SEC_SQL)
    return [
        {
            "family": "sec",
            "qid": "Q1",
            "sql": sec["Q1"],
            "workload": "sec",
            "duckdb": sec_db,
        }
    ]


def run_one(job: dict, log_dir: str) -> dict:
    log_dir_p = Path(log_dir)
    log_dir_p.mkdir(parents=True, exist_ok=True)
    tag = f"{job['family']}_{job['qid']}"
    log_path = log_dir_p / f"{tag}.log"
    env = env_for_lemma(workload=job["workload"], duckdb_path=job["duckdb"])
    python = str(PY) if PY.is_file() else sys.executable
    t0 = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(
            [python, "-m", "db_extension.run_optimizer", job["sql"]],
            cwd=ROOT,
            env=env,
            stdout=fh,
            stderr=subprocess.STDOUT,
            check=False,
        )
    elapsed = round(time.perf_counter() - t0, 1)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    fields = parse_optimizer_output(text)
    rec = {
        "family": job["family"],
        "qid": job["qid"],
        "returncode": proc.returncode,
        "elapsed_s": elapsed,
        "log": str(log_path),
        "lemma_ok": fields.get("proof_verified") is True and proc.returncode == 0,
        **fields,
    }
    print(
        f"DONE {tag} rc={proc.returncode} proof={fields.get('proof_verified')} "
        f"lat={fields.get('latency_us')} {elapsed}s",
        flush=True,
    )
    return rec


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", type=Path, default=Path("/home/emil/lemma-overnight-out"))
    p.add_argument(
        "--sec-db",
        default=str(ROOT / "holdout/gendb_sec_edgar/duckdb/sec_edgar.duckdb"),
    )
    p.add_argument(
        "--tpch-db",
        default="/home/emil/lemma/build/tpch_sf10/tpch_sf10.duckdb",
    )
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--smoke", action="store_true")
    args = p.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = out_dir / "logs"
    jobs = jobs_smoke(args.sec_db) if args.smoke else jobs_full(args.sec_db, args.tpch_db)

    meta = {
        "started_at": datetime.now(UTC).isoformat(),
        "git_sha": git_sha(),
        "hostname": socket.gethostname(),
        "smoke": args.smoke,
        "workers": args.workers,
        "n_jobs": len(jobs),
        "MAX_ITERATIONS": os.environ.get("MAX_ITERATIONS"),
        "AGENT_TIMEOUT_SEC": os.environ.get("AGENT_TIMEOUT_SEC"),
        "AGENT_CMD": os.environ.get("AGENT_CMD", ""),
        "note": (
            "TPC-H Q9/Q18 omitted. SEC measure may still be latency_us=-1 "
            "(bench wants .tbl files, SEC is DuckDB-only)."
        ),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps({k: meta[k] for k in ("hostname", "git_sha", "smoke", "n_jobs", "workers")}), flush=True)

    results: list[dict] = []
    workers = 1 if args.smoke else max(1, args.workers)
    if workers == 1:
        for job in jobs:
            results.append(run_one(job, str(log_dir)))
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(run_one, job, str(log_dir)): job for job in jobs}
            for fut in as_completed(futs):
                results.append(fut.result())

    payload = {
        **meta,
        "finished_at": datetime.now(UTC).isoformat(),
        "results": results,
    }
    (out_dir / "results.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")
    print(f"Wrote {out_dir / 'results.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
