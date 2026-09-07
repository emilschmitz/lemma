#!/usr/bin/env python3
"""Overnight Lemma batch: SEC resample queries from an external SQL file.

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

from gendb_published_one_run import (
    env_for_lemma,
    git_sha,
    parse_optimizer_output,
    parse_queries,
)

DEFAULT_SQL = ROOT / "holdout/gendb_sec_edgar/queries_resample_r15.sql"
PY = ROOT / ".venv/bin/python"


def lemma_job_ok(rec: dict) -> bool:
    """Success: verified proof, rc=0, and timed latency (int >= 0)."""
    if rec.get("proof_verified") is not True:
        return False
    if rec.get("returncode") != 0:
        return False
    lat = rec.get("latency_us")
    return isinstance(lat, int) and lat >= 0


def jobs_from_sql(sql_file: Path, family: str, sec_db: str) -> list[dict]:
    queries = parse_queries(sql_file)
    return [
        {
            "family": family,
            "qid": qid,
            "sql": queries[qid],
            "workload": "sec",
            "duckdb": sec_db,
        }
        for qid in sorted(queries, key=lambda x: int(x[1:]))
    ]


def jobs_full(sql_file: Path, family: str, sec_db: str, tpch_db: str) -> list[dict]:
    del tpch_db
    return jobs_from_sql(sql_file, family, sec_db)


def jobs_smoke(sql_file: Path, family: str, sec_db: str) -> list[dict]:
    queries = parse_queries(sql_file)
    return [
        {
            "family": family,
            "qid": "Q1",
            "sql": queries["Q1"],
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


def append_progress(out_dir: Path, rec: dict) -> None:
    summary = {
        "qid": rec.get("qid"),
        "ok": lemma_job_ok(rec),
        "proof": rec.get("proof_verified"),
        "latency_us": rec.get("latency_us"),
        "elapsed_s": rec.get("elapsed_s"),
        "returncode": rec.get("returncode"),
        "ts": datetime.now(UTC).isoformat(),
    }
    progress = out_dir / "progress.ndjson"
    with progress.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


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
        **fields,
    }
    rec["lemma_ok"] = lemma_job_ok(rec)
    print(
        f"DONE {tag} rc={proc.returncode} proof={fields.get('proof_verified')} "
        f"lat={fields.get('latency_us')} {elapsed}s ok={rec['lemma_ok']}",
        flush=True,
    )
    return rec


def _fsync_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())


def log_finished(text: str) -> bool:
    return "--- Optimization Finished ---" in text or "CUSTOM_PIPELINE_FAILED" in text


def rec_ok(rec: dict) -> bool:
    return lemma_job_ok(rec)


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
    p.add_argument("--sql-file", type=Path, default=DEFAULT_SQL)
    p.add_argument("--family", default="r17")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--smoke", action="store_true")
    p.add_argument(
        "--fail-streak",
        type=int,
        default=int(os.environ.get("LEMMA_FAIL_STREAK", "0")),
        help="Abort after this many consecutive failed queries (0=never).",
    )
    args = p.parse_args()

    sql_file = args.sql_file.resolve()
    if not sql_file.is_file():
        print(f"ERROR: missing sql-file: {sql_file}", file=sys.stderr)
        return 1

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = out_dir / "logs"
    jobs = (
        jobs_smoke(sql_file, args.family, args.sec_db)
        if args.smoke
        else jobs_full(sql_file, args.family, args.sec_db, args.tpch_db)
    )

    workers_env = os.environ.get("LEMMA_PARALLEL")
    meta = {
        "started_at": datetime.now(UTC).isoformat(),
        "git_sha": git_sha(),
        "hostname": socket.gethostname(),
        "smoke": args.smoke,
        "sql_file": str(sql_file),
        "family": args.family,
        "workers": args.workers,
        "LEMMA_PARALLEL": workers_env,
        "fail_streak": max(0, int(args.fail_streak)),
        "n_jobs": len(jobs),
        "MAX_ITERATIONS": os.environ.get("MAX_ITERATIONS"),
        "AGENT_TIMEOUT_SEC": os.environ.get("AGENT_TIMEOUT_SEC"),
        "AGENT_CMD": os.environ.get("AGENT_CMD", ""),
        "note": (
            f"SEC product path ({args.family}); sql_file outside git tree when "
            "launched via overnight_lemma.sh. DuckDB session-hot baseline pinned "
            "on same hardware before agents. Success requires proof_verified, "
            "returncode=0, and latency_us int >= 0."
        ),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: meta[k]
                for k in (
                    "hostname",
                    "git_sha",
                    "smoke",
                    "family",
                    "sql_file",
                    "n_jobs",
                    "workers",
                    "fail_streak",
                )
            }
        ),
        flush=True,
    )

    results: list[dict] = []
    consecutive_fail = 0
    aborted: str | None = None
    fail_streak = max(0, int(args.fail_streak))
    workers = 1 if args.smoke else max(1, args.workers)

    def on_done(rec: dict) -> bool:
        nonlocal consecutive_fail, aborted
        results.append(rec)
        persist_rec(out_dir, meta, results, rec)
        append_progress(out_dir, rec)
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
