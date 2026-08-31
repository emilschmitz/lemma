#!/usr/bin/env python3
"""Overnight Lemma batch: fresh SEC resample r15 only (50 queries).

Writes artifacts under --out-dir so the git worktree stays clean.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
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

R15_SQL = ROOT / "holdout/gendb_sec_edgar/queries_resample_r15.sql"
PY = ROOT / ".venv/bin/python"


def jobs_full(sec_db: str, tpch_db: str) -> list[dict]:
    del tpch_db
    r15 = parse_queries(R15_SQL)
    return [
        {
            "family": "r15",
            "qid": qid,
            "sql": r15[qid],
            "workload": "sec",
            "duckdb": sec_db,
        }
        for qid in sorted(r15, key=lambda x: int(x[1:]))
    ]


def jobs_smoke(sec_db: str) -> list[dict]:
    sec = parse_queries(R15_SQL)
    return [
        {
            "family": "sec",
            "qid": "Q1",
            "sql": sec["Q1"],
            "workload": "sec",
            "duckdb": sec_db,
        }
    ]


def persist_rec(out_dir: Path, meta: dict, results: list[dict], rec: dict) -> None:
    """Append one finished job and rewrite the partial harvest (crash-safe)."""
    harvest = out_dir / "harvest.ndjson"
    with harvest.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    partial = {
        **meta,
        "updated_at": datetime.now(UTC).isoformat(),
        "n_done": len(results),
        "results": results,
    }
    tmp = out_dir / "results.partial.json.tmp"
    tmp.write_text(json.dumps(partial, indent=2, default=str) + "\n")
    tmp.replace(out_dir / "results.partial.json")


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


def _fsync_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())


def append_harvest(out_dir: Path, rec: dict) -> None:
    line = json.dumps(rec, ensure_ascii=False, default=str) + "\n"
    harvest = out_dir / "harvest.ndjson"
    with harvest.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


def write_partial(out_dir: Path, meta: dict, results: list[dict], **extra: object) -> None:
    payload = {**meta, "results": results, **extra}
    _fsync_write(out_dir / "results.partial.json", json.dumps(payload, indent=2, default=str) + "\n")


def log_finished(text: str) -> bool:
    return "--- Optimization Finished ---" in text or "CUSTOM_PIPELINE_FAILED" in text


def rec_ok(rec: dict) -> bool:
    return rec.get("lemma_ok") is True


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
    p.add_argument(
        "--fail-streak",
        type=int,
        default=int(os.environ.get("LEMMA_FAIL_STREAK", "6")),
        help="Abort after this many consecutive failed queries (0=never).",
    )
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
            "r15 only (queries_resample_r15.sql, 50 queries). "
            "No Immanuel six, no TPC-H. SEC measure may still be latency_us=-1."
        ),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps({k: meta[k] for k in ("hostname", "git_sha", "smoke", "n_jobs", "workers")}), flush=True)

    results: list[dict] = []
    consecutive_fail = 0
    aborted: str | None = None
    fail_streak = max(0, int(args.fail_streak))
    workers = 1 if args.smoke else max(1, args.workers)

    def on_done(rec: dict) -> bool:
        nonlocal consecutive_fail, aborted
        results.append(rec)
        persist_rec(out_dir, meta, results, rec)
        if rec_ok(rec):
            consecutive_fail = 0
        else:
            consecutive_fail += 1
        print(
            f"HARVEST n_done={len(results)} consecutive_fail={consecutive_fail} "
            f"ok={rec_ok(rec)}",
            flush=True,
        )
        if fail_streak and consecutive_fail >= fail_streak:
            aborted = f"fail_streak_{fail_streak}"
            abort_doc = {
                **meta,
                "aborted": aborted,
                "consecutive_fail": consecutive_fail,
                "finished_at": datetime.now(UTC).isoformat(),
                "results": results,
            }
            _fsync_write(out_dir / "aborted.json", json.dumps(abort_doc, indent=2, default=str) + "\n")
            print(f"ABORT {aborted} after {consecutive_fail} consecutive failures", flush=True)
            return True
        return False

    if workers == 1:
        for job in jobs:
            if on_done(run_one(job, str(log_dir))):
                break
    else:
        job_iter = iter(jobs)
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs: dict = {}
            for _ in range(min(workers, len(jobs))):
                job = next(job_iter, None)
                if job is None:
                    break
                futs[ex.submit(run_one, job, str(log_dir))] = job
            while futs:
                done, _pending = wait(futs, return_when=FIRST_COMPLETED)
                stop = False
                for fut in done:
                    futs.pop(fut, None)
                    if on_done(fut.result()):
                        stop = True
                if stop:
                    break
                while len(futs) < workers:
                    job = next(job_iter, None)
                    if job is None:
                        break
                    futs[ex.submit(run_one, job, str(log_dir))] = job

    payload = {
        **meta,
        "finished_at": datetime.now(UTC).isoformat(),
        "aborted": aborted,
        "results": results,
    }
    _fsync_write(out_dir / "results.json", json.dumps(payload, indent=2, default=str) + "\n")
    print(f"Wrote {out_dir / 'results.json'}", flush=True)
    return 1 if aborted else 0


if __name__ == "__main__":
    raise SystemExit(main())
