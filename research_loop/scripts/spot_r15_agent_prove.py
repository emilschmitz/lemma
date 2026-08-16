#!/usr/bin/env python3
"""Parallel r15 agent-prove via product-path run_optimizer (Grok 4.5 CLI).

Not Docker — isolated processes. Each run writes assembled Verus into its own
``LEMMA_RUN_DIR/workspace/custom_query.rs`` so workers do not clobber each other.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_loop.scripts.sqlsmith_trusted_coverage import parse_sql_file

SQL_FILE = ROOT / "holdout/gendb_sec_edgar/queries_resample_r15.sql"
OUT_DIR = ROOT / "research_loop/generated/r15"
STATUS = OUT_DIR / "agent_prove_status.json"
PY = ROOT / ".venv" / "bin" / "python"


def env_for_experiment() -> dict[str, str]:
    e = os.environ.copy()
    home = os.environ.get("HOME", "/home/emil")
    e["PATH"] = (
        f"{home}/.local/bin:{home}/src/verus/source/target-verus/release:"
        f"{home}/.cargo/bin:" + e.get("PATH", "")
    )
    e["VERUS_Z3_PATH"] = f"{home}/src/verus/source/z3"
    e["LEMMA_EXPERIMENT"] = "1"
    e["LEMMA_RESEARCH_LOG"] = "1"
    e["LEMMA_AGENT_BACKEND"] = "cli"
    e["USE_AGENT_DOCKER"] = "0"
    e["MOCK_AGENT"] = "0"
    e["LEMMA_ALLOW_DUCKDB_FALLBACK"] = "0"
    e["LEMMA_WORKLOAD"] = "sec"
    e["LEMMA_DUCKDB_PATH"] = str(ROOT / "holdout/gendb_sec_edgar/duckdb/sec_edgar.duckdb")
    e["AGENT_TIMEOUT_SEC"] = "600"
    e["MAX_ITERATIONS"] = "1"
    e["LEMMA_DATASET_SIZE"] = "65536"
    e["AGENT_NETWORK"] = "1"
    e["LEMMA_EXPERIMENT_EVENT_FILE"] = str(
        ROOT / "research_loop/generated/experiment_events/r15.ndjson"
    )
    e.pop("LEMMA_EXPERIMENT_ALLOW_DIRTY", None)
    e["UV_NO_SYNC"] = "1"
    return e


def load_status() -> dict:
    if STATUS.is_file():
        return json.loads(STATUS.read_text())
    return {"queries": {}}


def save_status_merge(qid: str, rec: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    with STATUS.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        fh.seek(0)
        raw = fh.read()
        st = json.loads(raw) if raw.strip() else {"queries": {}}
        st.setdefault("queries", {})[qid] = rec
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(st, indent=2) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def run_one(qid: str, sql: str) -> dict:
    log = OUT_DIR / "agent_logs" / f"{qid}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    print(f"=== {qid} start pid={os.getpid()} ===", flush=True)
    t0 = time.time()
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(
            [str(PY), "-m", "db_extension.run_optimizer", sql],
            cwd=ROOT,
            env=env_for_experiment(),
            stdout=fh,
            stderr=subprocess.STDOUT,
        )
    elapsed = time.time() - t0
    text = log.read_text(encoding="utf-8", errors="replace")
    verified = "proof_verified=True" in text
    rec = {
        "ok": verified or proc.returncode == 0,
        "returncode": proc.returncode,
        "elapsed_s": round(elapsed, 1),
        "log": str(log),
        "verified_hint": verified,
        "pid": os.getpid(),
    }
    save_status_merge(qid, rec)
    print(
        f"=== {qid} done rc={proc.returncode} {elapsed:.0f}s verified={verified} ===",
        flush=True,
    )
    return rec


def _keep(rec: dict) -> bool:
    if not rec.get("ok") and not rec.get("verified_hint"):
        return False
    if rec.get("elapsed_s", 0) < 10:
        return False
    return True


def main() -> int:
    n_workers = int(os.environ.get("LEMMA_PARALLEL", "24"))
    queries = parse_sql_file(SQL_FILE)
    st = load_status()
    kept = {k: v for k, v in st.get("queries", {}).items() if _keep(v)}
    save_path_init = {"queries": kept}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(save_path_init, indent=2) + "\n")

    todo = [(qid, sql) for qid, sql in queries if qid not in kept]
    print(
        f"parallel workers={n_workers} already_ok={len(kept)} todo={len(todo)} docker=0",
        flush=True,
    )
    if not todo:
        print("nothing to do", flush=True)
        return 0
    if not PY.is_file():
        print(f"missing venv python {PY}", file=sys.stderr)
        return 2

    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(run_one, qid, sql): qid for qid, sql in todo}
        for fut in as_completed(futs):
            qid = futs[fut]
            try:
                fut.result()
            except Exception as exc:
                print(f"=== {qid} worker_exc {exc!r} ===", flush=True)
                save_status_merge(
                    qid,
                    {
                        "ok": False,
                        "returncode": -1,
                        "elapsed_s": 0,
                        "verified_hint": False,
                        "error": repr(exc),
                    },
                )

    st = load_status()
    qs = st.get("queries", {})
    n_ok = sum(1 for v in qs.values() if v.get("ok") or v.get("verified_hint"))
    print(f"SUMMARY ok={n_ok}/{len(qs)} (want ≥49/50)", flush=True)
    return 0 if n_ok >= 49 else 1


if __name__ == "__main__":
    raise SystemExit(main())
