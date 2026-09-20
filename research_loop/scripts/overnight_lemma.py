#!/usr/bin/env python3
"""Overnight Lemma batch: SEC resample queries from an external SQL file.

Writes artifacts under --out-dir so the git worktree stays clean.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import re
import socket
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research_loop" / "scripts"))

from classify_product_failures import classify_optimizer_log
from gendb_published_one_run import (
    env_for_lemma,
    git_sha,
    parse_optimizer_output,
    parse_queries,
)

from research_loop.harvest_traces import copy_workspace_traces
from research_loop.scripts.local_e2e_tiny_docker import parse_run_dir

DEFAULT_SQL = ROOT / "holdout/gendb_sec_edgar/queries_resample_r15.sql"
IMMANUEL_SQL = ROOT / "holdout/gendb_sec_edgar/queries.sql"
IMMANUEL_SOURCE_QIDS = ("Q1", "Q2", "Q3", "Q4", "Q6", "Q24")
IMMANUEL_JOB_QIDS = ("Q101", "Q102", "Q103", "Q104", "Q105", "Q106")
TPCH_PAPER_SQL = ROOT / "holdout/tpch_sf10/queries_paper_subset.sql"
TPCH_PAPER_SOURCE_QIDS = ("Q1", "Q3", "Q6", "Q9", "Q18")
TPCH_PAPER_JOB_QIDS = ("Q201", "Q202", "Q203", "Q204", "Q205")
PY = ROOT / ".venv/bin/python"
DEFAULT_FAIL_STREAK = 6
DEFAULT_HEARTBEAT_INTERVAL_SEC = 60


def lemma_job_ok(rec: dict) -> bool:
    """Success: verified proof, rc=0, full-table latency (int >= 0), no measure error."""
    if rec.get("official_measure_error"):
        return False
    if rec.get("proof_verified") is not True:
        return False
    if rec.get("returncode") != 0:
        return False
    lat = rec.get("latency_us")
    return isinstance(lat, int) and lat >= 0


def _metrics_objects_from_log(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("LEMMA_METRICS_JSON:"):
            continue
        try:
            metrics = json.loads(line[len("LEMMA_METRICS_JSON:") :].strip())
        except json.JSONDecodeError:
            continue
        if isinstance(metrics, dict):
            out.append(metrics)
    return out


def harvest_optimizer_output(text: str) -> dict[str, Any]:
    """Parse optimizer log for overnight harvest; never treat iterate-only as full-table win."""
    fields = parse_optimizer_output(text)
    metrics_objects = _metrics_objects_from_log(text)

    official_full_latencies: list[int] = []
    official_latencies: list[int] = []
    proved_measure_errors: list[dict[str, Any]] = []

    for metrics in metrics_objects:
        if metrics.get("proof_verified") is not True:
            continue
        if metrics.get("official_measure_error"):
            proved_measure_errors.append(metrics)
            continue
        if metrics.get("status") != "SUCCESS":
            continue
        try:
            lat = int(metrics.get("latency_us", -1))
        except (TypeError, ValueError):
            continue
        if lat < 0:
            continue
        if metrics.get("measure_path") == "official_full":
            official_full_latencies.append(lat)
        else:
            official_latencies.append(lat)

    if official_full_latencies:
        fields["latency_us"] = min(official_full_latencies)
        fields.pop("official_measure_error", None)
        fields.pop("iterate_latency_us", None)
    elif proved_measure_errors:
        err_metrics = proved_measure_errors[-1]
        fields["official_measure_error"] = err_metrics["official_measure_error"]
        fields["proof_verified"] = True
        iterate_lat = err_metrics.get("iterate_latency_us")
        if iterate_lat is not None:
            try:
                fields["iterate_latency_us"] = int(iterate_lat)
            except (TypeError, ValueError):
                pass
        fields["latency_us"] = -1
    elif official_latencies:
        fields["latency_us"] = min(official_latencies)
        fields.pop("official_measure_error", None)

    if fields.get("official_measure_error"):
        fields["latency_us"] = -1

    if fields.get("proof_verified") is not True:
        found = list(re.finditer(r"proof_verified=(True|False)", text))
        if (found and found[-1].group(1) == "True") or proved_measure_errors:
            fields["proof_verified"] = True

    return fields


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


def _append_paper_jobs(
    jobs: list[dict],
    *,
    family: str,
    sec_db: str,
    tpch_db: str,
) -> None:
    if IMMANUEL_SQL.is_file():
        immanuel = parse_queries(IMMANUEL_SQL)
        for src_qid, job_qid in zip(IMMANUEL_SOURCE_QIDS, IMMANUEL_JOB_QIDS, strict=True):
            sql = immanuel.get(src_qid)
            if sql:
                jobs.append(
                    {
                        "family": family,
                        "qid": job_qid,
                        "sql": sql,
                        "workload": "sec",
                        "duckdb": sec_db,
                    }
                )
    if TPCH_PAPER_SQL.is_file():
        tpch = parse_queries(TPCH_PAPER_SQL)
        for src_qid, job_qid in zip(TPCH_PAPER_SOURCE_QIDS, TPCH_PAPER_JOB_QIDS, strict=True):
            sql = tpch.get(src_qid)
            if sql:
                jobs.append(
                    {
                        "family": family,
                        "qid": job_qid,
                        "sql": sql,
                        "workload": "tpch",
                        "duckdb": tpch_db,
                    }
                )


def jobs_full(sql_file: Path, family: str, sec_db: str, tpch_db: str) -> list[dict]:
    jobs = jobs_from_sql(sql_file, family, sec_db)
    _append_paper_jobs(jobs, family=family, sec_db=sec_db, tpch_db=tpch_db)
    return jobs


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


def harvest_job_traces(log_text: str, log_dir: Path, qid: str) -> dict[str, Any] | None:
    """Copy the full run tree under ``{log_dir.parent}/traces/{qid}/``."""
    run_dir = parse_run_dir(log_text)
    if run_dir is None:
        return None
    traces_dest = log_dir.parent / "traces" / qid
    workspace = run_dir / "workspace"
    try:
        copy_workspace_traces(workspace=workspace, run_dir=run_dir, dest=traces_dest)
    except OSError:
        pass
    return {"traces": str(traces_dest), "run_dir": str(run_dir)}


def _backfill_traces_from_logs(out_dir: Path, log_dir: Path) -> None:
    """Harvest traces for logs whose workers were terminated before run_one finished."""
    qid_re = re.compile(r"_(Q\d+)\.log$")
    if not log_dir.is_dir():
        return
    for log_path in sorted(log_dir.glob("*.log")):
        m = qid_re.search(log_path.name)
        if not m:
            continue
        qid = m.group(1)
        index_path = out_dir / "traces" / qid / "traces_index.json"
        if index_path.is_file():
            continue
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        harvest_job_traces(log_text, log_dir, qid)


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
    fields = harvest_optimizer_output(text)
    rec = {
        "family": job["family"],
        "qid": job["qid"],
        "returncode": proc.returncode,
        "elapsed_s": elapsed,
        "log": str(log_path),
        **fields,
    }
    rec["lemma_ok"] = lemma_job_ok(rec)
    trace_info = harvest_job_traces(text, log_dir_p, job["qid"])
    if trace_info:
        rec.update(trace_info)
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


def _append_ndjson_fsync(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def resolve_heartbeat_interval_sec(raw: str | int | None = None) -> int:
    if raw is None:
        raw = os.environ.get(
            "LEMMA_HEARTBEAT_INTERVAL_SEC",
            str(DEFAULT_HEARTBEAT_INTERVAL_SEC),
        )
    return max(1, int(raw))


class JobTracker:
    """Track submitted vs persisted jobs; crash-safe heartbeat.ndjson."""

    def __init__(
        self,
        out_dir: Path,
        meta: dict,
        *,
        heartbeat_interval_sec: int = DEFAULT_HEARTBEAT_INTERVAL_SEC,
    ) -> None:
        self.out_dir = out_dir
        self.meta = meta
        self.heartbeat_interval_sec = max(1, int(heartbeat_interval_sec))
        self.in_flight: list[dict[str, Any]] = []
        self.submitted_jobs: list[dict] = []
        self.finished_qids: set[str] = set()
        self._last_heartbeat_mono = 0.0

    def job_started(self, job: dict) -> None:
        self.submitted_jobs.append(job)
        self.in_flight.append(
            {
                "qid": job["qid"],
                "family": job.get("family"),
                "started_at": datetime.now(UTC).isoformat(),
                "pid": os.getpid(),
            }
        )
        self.write_heartbeat()

    def job_finished(self, qid: str) -> None:
        self.finished_qids.add(qid)
        self.in_flight = [entry for entry in self.in_flight if entry["qid"] != qid]
        self.write_heartbeat()

    def maybe_timer_heartbeat(self) -> None:
        now = time.monotonic()
        if now - self._last_heartbeat_mono >= self.heartbeat_interval_sec:
            self.write_heartbeat()

    def write_heartbeat(self) -> None:
        doc = {
            "ts": datetime.now(UTC).isoformat(),
            "host_pid": os.getpid(),
            "family": self.meta.get("family"),
            "in_flight": list(self.in_flight),
        }
        _append_ndjson_fsync(self.out_dir / "heartbeat.ndjson", doc)
        self._last_heartbeat_mono = time.monotonic()

    def unfinished_jobs(self) -> list[dict]:
        finished = self.finished_qids
        return [job for job in self.submitted_jobs if job["qid"] not in finished]


def write_unfinished_json(
    out_dir: Path,
    meta: dict,
    unfinished: list[dict],
) -> None:
    doc = {
        **meta,
        "written_at": datetime.now(UTC).isoformat(),
        "n_unfinished": len(unfinished),
        "jobs": [
            {
                "family": job.get("family"),
                "qid": job.get("qid"),
                "workload": job.get("workload"),
            }
            for job in unfinished
        ],
    }
    _fsync_write(out_dir / "unfinished.json", json.dumps(doc, indent=2, default=str) + "\n")


def write_failure_classify(out_dir: Path, results: list[dict]) -> dict[str, Any]:
    """Classify finished harvest rows from optimizer logs.

    Bare no-submit is step 3 (prove miss). Leftover host E0425 tN / E0308
    case_when stay assemble/transpile. Official 600s measure is step 7,
    proved + lat=-1, not a fake time.
    """
    entries: list[dict[str, Any]] = []
    for rec in results:
        log_path = rec.get("log")
        base: dict[str, Any] = {
            "family": rec.get("family"),
            "qid": rec.get("qid"),
            "log": log_path,
        }
        if not log_path:
            cls = classify_optimizer_log("")
            entries.append({**base, **cls})
            continue
        path = Path(str(log_path))
        if not path.is_file():
            cls = classify_optimizer_log("")
            entries.append({**base, **cls, "detail": f"missing_log:{path}"})
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        cls = classify_optimizer_log(text)
        entries.append({**base, **cls})
    doc: dict[str, Any] = {
        "written_at": datetime.now(UTC).isoformat(),
        "n_results": len(results),
        "entries": entries,
    }
    _fsync_write(out_dir / "failure_classify.json", json.dumps(doc, indent=2, default=str) + "\n")
    return doc


def finalize_run(
    out_dir: Path,
    meta: dict,
    results: list[dict],
    tracker: JobTracker,
    streak: FailStreakTracker,
    *,
    exit_error: str | None = None,
) -> int:
    """Write results.json, unfinished.json, failure_classify.json; loud on gaps."""
    _backfill_traces_from_logs(out_dir, out_dir / "logs")
    unfinished = tracker.unfinished_jobs()
    if unfinished:
        write_unfinished_json(out_dir, meta, unfinished)
        print(
            f"ERROR: {len(unfinished)} jobs never persisted harvest: "
            f"{[j['qid'] for j in unfinished]}",
            file=sys.stderr,
        )

    write_failure_classify(out_dir, results)

    payload: dict[str, Any] = {
        **meta,
        "finished_at": datetime.now(UTC).isoformat(),
        "aborted": streak.aborted,
        "results": results,
        "n_unfinished": len(unfinished),
    }
    if unfinished:
        payload["unfinished"] = [
            {"family": j.get("family"), "qid": j.get("qid")} for j in unfinished
        ]
        payload["error"] = (
            exit_error
            or f"{len(unfinished)} jobs never persisted harvest (see unfinished.json)"
        )
    elif exit_error:
        payload["error"] = exit_error

    _fsync_write(out_dir / "results.json", json.dumps(payload, indent=2, default=str) + "\n")
    print(f"Wrote {out_dir / 'results.json'}", flush=True)

    rc = 0
    if streak.aborted:
        rc = 1
    if unfinished:
        rc = 1
    if exit_error and not unfinished:
        rc = 1
    return rc


def log_finished(text: str) -> bool:
    return "--- Optimization Finished ---" in text or "CUSTOM_PIPELINE_FAILED" in text


def rec_ok(rec: dict) -> bool:
    return lemma_job_ok(rec)


def resolve_fail_streak(raw: str | int | None = None) -> int:
    """Parse fail-streak limit; 0 means never abort."""
    if raw is None:
        raw = os.environ.get("LEMMA_FAIL_STREAK", str(DEFAULT_FAIL_STREAK))
    return max(0, int(raw))


def rec_fail_streak_increments(rec: dict) -> bool:
    """True when a finished job should count toward consecutive fail streak."""
    if rec_ok(rec):
        return False
    # Proved but official/iterate timeout: continue overnight, not abort streak.
    if rec.get("proof_verified") is True:
        lat = rec.get("latency_us")
        if isinstance(lat, int) and lat < 0:
            return False
    return True


def next_consecutive_fail(consecutive_fail: int, rec: dict) -> int:
    if rec_ok(rec):
        return 0
    if not rec_fail_streak_increments(rec):
        return consecutive_fail
    return consecutive_fail + 1


def fail_streak_abort_reason(fail_streak: int, consecutive_fail: int) -> str | None:
    if fail_streak and consecutive_fail >= fail_streak:
        return f"fail_streak_{fail_streak}"
    return None


def consecutive_fail_from_tail(results: list[dict]) -> int:
    """Count consecutive lemma_ok=false at the end of a prior results list."""
    streak = 0
    for rec in reversed(results):
        if rec_ok(rec):
            break
        if not rec_fail_streak_increments(rec):
            continue
        streak += 1
    return streak


def load_partial_resume(
    out_dir: Path,
    family: str,
) -> tuple[list[dict], set[str], int]:
    """Load prior partial harvest; return (seeded_ok_results, skip_qids, fail_streak)."""
    partial_path = out_dir / "results.partial.json"
    if not partial_path.is_file():
        return [], set(), 0
    try:
        data = json.loads(partial_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [], set(), 0
    prior = [r for r in data.get("results") or [] if r.get("family") == family]
    skip_qids = {r["qid"] for r in prior if r.get("lemma_ok") is True and isinstance(r.get("qid"), str)}
    seeded = [r for r in prior if r.get("qid") in skip_qids]
    return seeded, skip_qids, consecutive_fail_from_tail(prior)


class FailStreakTracker:
    """Tracks consecutive lemma_ok=false results and abort threshold."""

    def __init__(self, fail_streak: int) -> None:
        self.fail_streak = max(0, int(fail_streak))
        self.consecutive_fail = 0
        self.aborted: str | None = None

    def record(self, rec: dict) -> bool:
        """Update streak from one finished job; return True if abort threshold hit."""
        self.consecutive_fail = next_consecutive_fail(self.consecutive_fail, rec)
        reason = fail_streak_abort_reason(self.fail_streak, self.consecutive_fail)
        if reason is not None:
            self.aborted = reason
            return True
        return False


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
        default=resolve_fail_streak(),
        help=f"Abort after this many consecutive failed queries (0=never; default {DEFAULT_FAIL_STREAK}).",
    )
    args = p.parse_args()

    sql_file = args.sql_file.resolve()
    if not sql_file.is_file():
        print(f"ERROR: missing sql-file: {sql_file}", file=sys.stderr)
        return 1

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = out_dir / "logs"
    all_jobs = (
        jobs_smoke(sql_file, args.family, args.sec_db)
        if args.smoke
        else jobs_full(sql_file, args.family, args.sec_db, args.tpch_db)
    )

    resume_seeded: list[dict] = []
    resume_skip: set[str] = set()
    resume_streak = 0
    if not args.smoke:
        resume_seeded, resume_skip, resume_streak = load_partial_resume(out_dir, args.family)
        if resume_skip:
            print(
                f"RESUME skip {len(resume_skip)} lemma_ok qids: "
                f"{sorted(resume_skip, key=lambda x: int(x[1:]))}",
                flush=True,
            )
    jobs = [job for job in all_jobs if job["qid"] not in resume_skip]

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
        "n_jobs": len(all_jobs),
        "n_jobs_remaining": len(jobs),
        "resume_skipped": sorted(resume_skip, key=lambda x: int(x[1:])),
        "MAX_ITERATIONS": os.environ.get("MAX_ITERATIONS"),
        "AGENT_TIMEOUT_SEC": os.environ.get("AGENT_TIMEOUT_SEC"),
        "AGENT_CMD": os.environ.get("AGENT_CMD", ""),
        "note": (
            f"SEC product path ({args.family}); sql_file outside git tree when "
            "launched via overnight_lemma.sh. DuckDB session-hot baseline runs "
            "only when LEMMA_SERIOUS=1 (skipped in dev overnights). MCP iterate "
            "proves on capped rows; official harvest latency_us is full-table "
            "execute after marked submit. Success requires proof_verified, "
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

    results: list[dict] = list(resume_seeded)
    streak = FailStreakTracker(args.fail_streak)
    streak.consecutive_fail = resume_streak
    workers = 1 if args.smoke else max(1, args.workers)
    tracker = JobTracker(
        out_dir,
        meta,
        heartbeat_interval_sec=resolve_heartbeat_interval_sec(),
    )
    tracker.finished_qids.update(resume_skip)
    exit_error: str | None = None
    if resume_streak:
        print(
            f"RESUME fail_streak tail={resume_streak} (from partial results)",
            flush=True,
        )
    resume_after_abort = os.environ.get("LEMMA_RESUME_AFTER_ABORT", "").strip() == "1"
    already_aborted = fail_streak_abort_reason(args.fail_streak, resume_streak)
    if resume_after_abort and already_aborted:
        print(
            "RESUME_AFTER_ABORT=1: reset fail streak after host fix; will retry lemma_ok=false",
            flush=True,
        )
        streak.consecutive_fail = 0
        abort_path = out_dir / "aborted.json"
        if abort_path.is_file():
            abort_path.unlink()
        already_aborted = None
    if already_aborted:
        streak.aborted = already_aborted
        abort_doc = {
            **meta,
            "aborted": streak.aborted,
            "consecutive_fail": streak.consecutive_fail,
            "finished_at": datetime.now(UTC).isoformat(),
            "results": results,
            "resume_immediate_abort": True,
        }
        _fsync_write(
            out_dir / "aborted.json",
            json.dumps(abort_doc, indent=2, default=str) + "\n",
        )
        print(
            f"ABORT on resume {streak.aborted} after {streak.consecutive_fail} "
            "consecutive failures (no new jobs)",
            flush=True,
        )
        return finalize_run(
            out_dir,
            meta,
            results,
            tracker,
            streak,
            exit_error=None,
        )

    def on_done(rec: dict) -> bool:
        results.append(rec)
        persist_rec(out_dir, meta, results, rec)
        append_progress(out_dir, rec)
        tracker.job_finished(rec["qid"])
        should_abort = streak.record(rec)
        print(
            f"HARVEST n_done={len(results)} consecutive_fail={streak.consecutive_fail} "
            f"ok={rec_ok(rec)}",
            flush=True,
        )
        if should_abort:
            abort_doc = {
                **meta,
                "aborted": streak.aborted,
                "consecutive_fail": streak.consecutive_fail,
                "finished_at": datetime.now(UTC).isoformat(),
                "results": results,
            }
            _fsync_write(
                out_dir / "aborted.json",
                json.dumps(abort_doc, indent=2, default=str) + "\n",
            )
            print(
                f"ABORT {streak.aborted} after {streak.consecutive_fail} consecutive failures",
                flush=True,
            )
            return True
        return False

    try:
        if workers == 1:
            for job in jobs:
                tracker.job_started(job)
                if on_done(run_one(job, str(log_dir))):
                    break
        else:
            job_iter = iter(jobs)
            ex = ProcessPoolExecutor(max_workers=workers)
            try:
                futs: dict = {}
                for _ in range(min(workers, len(jobs))):
                    job = next(job_iter, None)
                    if job is None:
                        break
                    tracker.job_started(job)
                    futs[ex.submit(run_one, job, str(log_dir))] = job
                while futs:
                    tracker.maybe_timer_heartbeat()
                    done, _pending = wait(
                        futs,
                        timeout=tracker.heartbeat_interval_sec,
                        return_when=FIRST_COMPLETED,
                    )
                    if not done:
                        continue
                    stop = False
                    for fut in done:
                        futs.pop(fut, None)
                        if on_done(fut.result()):
                            stop = True
                    if stop:
                        # Do not join in-flight workers: `with` shutdown(wait=True)
                        # kept the VM up ~40min after fail_streak_6 on r18.
                        break
                    while len(futs) < workers:
                        job = next(job_iter, None)
                        if job is None:
                            break
                        tracker.job_started(job)
                        futs[ex.submit(run_one, job, str(log_dir))] = job
            finally:
                if streak.aborted:
                    ex.shutdown(wait=False, cancel_futures=True)
                    for proc in multiprocessing.active_children():
                        proc.terminate()
                else:
                    ex.shutdown(wait=True)
    except KeyboardInterrupt:
        exit_error = "KeyboardInterrupt"
    except Exception as exc:
        exit_error = f"driver exception: {type(exc).__name__}: {exc}"
        raise
    finally:
        rc = finalize_run(
            out_dir,
            meta,
            results,
            tracker,
            streak,
            exit_error=exit_error,
        )

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
