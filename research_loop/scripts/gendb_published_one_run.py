"""One-run DuckDB + Lemma timing on GenDB-published per-query benchmarks.

Paper reference: arXiv:2603.02081 §4.2 — only queries with published GenDB ms:
  SEC-EDGAR (queries.sql): Q4, Q6
  TPC-H SF10 (queries_paper_subset.sql): Q6, Q9, Q18

DuckDB: one process per DB, PRAGMA threads=64, single timed execution → ONE_RUN_US.
Lemma: product path ``python -m db_extension.run_optimizer`` with MAX_ITERATIONS=1.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import duckdb

ROOT = Path(__file__).resolve().parents[2]
HOLDOUT_SEC = ROOT / "holdout" / "gendb_sec_edgar"
SEC_SQL = HOLDOUT_SEC / "queries.sql"
TPCH_SQL = ROOT / "holdout" / "tpch_sf10" / "queries_paper_subset.sql"
DEFAULT_SEC_DB = HOLDOUT_SEC / "duckdb" / "sec_edgar.duckdb"
DEFAULT_TPCH_DB = ROOT / "build" / "tpch_sf10" / "tpch_sf10.duckdb"
ALT_TPCH_DB = Path("/home/emil/lemma/build/tpch_sf10/tpch_sf10.duckdb")
DEFAULT_OUT = HOLDOUT_SEC / "results" / "gendb_published_one_run.json"
PY = ROOT / ".venv" / "bin" / "python"

# Published GenDB per-query ms (arXiv:2603.02081 §4.2) — do not invent others.
GENDB_PAPER_MS: dict[str, dict[str, int]] = {
    "sec": {"Q4": 106, "Q6": 88},
    "tpch": {"Q6": 17, "Q9": 38, "Q18": 74},
}

PUBLISHED_IDS: dict[str, list[str]] = {
    "sec": ["Q4", "Q6"],
    "tpch": ["Q6", "Q9", "Q18"],
}

DUCKDB_PROTOCOL = (
    "one process per DB, open once; PRAGMA threads=N; "
    "one timed execution per query → ONE_RUN_US (no session-hot median)"
)
LEMMA_PROTOCOL = (
    "python -m db_extension.run_optimizer; MAX_ITERATIONS=1; "
    "LEMMA_EXPERIMENT=1; Docker sandbox when USE_AGENT_DOCKER=1"
)


def _load_parse_queries() -> Callable[[Path], dict[str, str]]:
    path = HOLDOUT_SEC / "session_hot.py"
    spec = importlib.util.spec_from_file_location("_gendb_session_hot", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return cast(Callable[[Path], dict[str, str]], mod.parse_queries)


parse_queries = _load_parse_queries()


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def resolve_tpch_db(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    if DEFAULT_TPCH_DB.is_file():
        return DEFAULT_TPCH_DB
    if ALT_TPCH_DB.is_file():
        return ALT_TPCH_DB
    return DEFAULT_TPCH_DB


def load_published_queries(family: str) -> list[tuple[str, str, int]]:
    sql_path = SEC_SQL if family == "sec" else TPCH_SQL
    if not sql_path.is_file():
        raise FileNotFoundError(f"missing SQL file: {sql_path}")
    all_queries = parse_queries(sql_path)
    paper_ms = GENDB_PAPER_MS[family]
    specs: list[tuple[str, str, int]] = []
    for qid in PUBLISHED_IDS[family]:
        if qid not in all_queries:
            raise KeyError(f"{qid} not found in {sql_path}")
        specs.append((qid, all_queries[qid], paper_ms[qid]))
    return specs


def run_duckdb_one_run(
    db_path: Path,
    query_specs: list[tuple[str, str, int]],
    *,
    threads: int,
) -> dict[str, Any]:
    if not db_path.is_file():
        raise FileNotFoundError(f"database not found: {db_path}")

    t_open = time.perf_counter()
    con = duckdb.connect(str(db_path), read_only=True)
    con.execute(f"PRAGMA threads={int(threads)}")
    open_us = int((time.perf_counter() - t_open) * 1_000_000)

    print(f"DUCKDB db={db_path} threads={threads} OPEN_US={open_us}", flush=True)
    out: dict[str, dict[str, Any]] = {}
    for qid, sql, _paper_ms in query_specs:
        t0 = time.perf_counter()
        cur = con.execute(sql)
        rows = cur.fetchall()
        one_run_us = int((time.perf_counter() - t0) * 1_000_000)
        row_count = len(rows)
        block = {
            "ONE_RUN_US": one_run_us,
            "ONE_RUN_MS": round(one_run_us / 1000.0, 3),
            "row_count": row_count,
        }
        out[qid] = block
        print(f"  {qid}: ONE_RUN_US={one_run_us} rows={row_count}", flush=True)

    con.close()
    return {"OPEN_US": open_us, "queries": out}


def env_for_lemma(*, workload: str, duckdb_path: str) -> dict[str, str]:
    """Experiment env for run_optimizer; set defaults only when unset."""
    e = os.environ.copy()
    home = os.environ.get("HOME", "/home/emil")
    e["PATH"] = (
        f"{home}/.local/bin:{home}/src/verus/source/target-verus/release:"
        f"{home}/.cargo/bin:" + e.get("PATH", "")
    )
    e.setdefault("VERUS_Z3_PATH", f"{home}/src/verus/source/z3")
    e.setdefault("MAX_ITERATIONS", "1")
    e.setdefault("LEMMA_EXPERIMENT", "1")
    e.setdefault("MOCK_AGENT", "0")
    e.setdefault("LEMMA_ALLOW_DUCKDB_FALLBACK", "0")
    e.setdefault("USE_AGENT_DOCKER", "1")
    e.setdefault("AGENT_IMAGE", "lemma-agent:cli")
    e.setdefault("LEMMA_AGENT_BACKEND", "cli")
    e.setdefault("AGENT_TIMEOUT_SEC", "600")
    e.setdefault("LEMMA_MCP_ITERATE_ROWS", "50000")
    e.setdefault("LEMMA_KEEP_OPTIMIZING", "1")
    e.setdefault("LEMMA_RESEARCH_LOG", "1")
    e["LEMMA_WORKLOAD"] = workload
    e["LEMMA_DUCKDB_PATH"] = duckdb_path
    e.setdefault("AGENT_NETWORK", "0")
    e.setdefault("UV_NO_SYNC", "1")
    e.pop("LEMMA_EXPERIMENT_ALLOW_DIRTY", None)
    return e


def _parse_bool(s: str) -> bool | None:
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    return None


def parse_optimizer_output(text: str) -> dict[str, Any]:
    """Extract proof/latency fields from run_optimizer stdout+stderr."""
    parsed: dict[str, Any] = {}

    # Last assignment wins: an early CUSTOM_PIPELINE_FAILED / proof_verified=False
    # must not hide a later marked-submit success.
    found = list(re.finditer(r"proof_verified=(True|False)", text))
    if found:
        parsed["proof_verified"] = _parse_bool(found[-1].group(1))
    elif (
        "Using marked submit metrics" in text
        or "Official full-table measure after marked submit" in text
        or "official full-table" in text.lower()
    ):
        parsed["proof_verified"] = True

    metrics_objects: list[dict[str, Any]] = []
    for line in text.splitlines():
        if line.startswith("LEMMA_METRICS_JSON:"):
            try:
                metrics = json.loads(line[len("LEMMA_METRICS_JSON:") :].strip())
                if isinstance(metrics, dict):
                    metrics_objects.append(metrics)
            except json.JSONDecodeError:
                pass

    for metrics in metrics_objects:
        for key in (
            "SESSION_HOT_US",
            "PREP_US",
            "OPEN_US",
            "COLD_QUERY_US",
        ):
            if key in metrics:
                parsed[key] = metrics[key]

    best_m = re.search(r"best_latency_us=(\d+)", text)
    if best_m:
        parsed["latency_us"] = int(best_m.group(1))
    else:
        official_full_latencies: list[int] = []
        official_latencies: list[int] = []
        fallback_latencies: list[int] = []
        all_timed: list[int] = []
        for metrics in metrics_objects:
            if metrics.get("proof_verified") is not True:
                continue
            if metrics.get("status") != "SUCCESS":
                continue
            try:
                lat = int(metrics.get("latency_us", -1))
            except (TypeError, ValueError):
                continue
            if lat < 0:
                continue
            all_timed.append(lat)
            if metrics.get("official_measure_error"):
                fallback_latencies.append(lat)
            elif metrics.get("measure_path") == "official_full":
                official_full_latencies.append(lat)
            else:
                official_latencies.append(lat)
        if official_full_latencies:
            parsed["latency_us"] = min(official_full_latencies)
        elif official_latencies:
            parsed["latency_us"] = min(official_latencies)
        elif fallback_latencies:
            parsed["latency_us"] = min(fallback_latencies)
        elif all_timed:
            parsed["latency_us"] = min(all_timed)

    for key in ("SESSION_HOT_US", "QUERY_LATENCY_US", "QUERY_US"):
        m = re.search(rf"{key}:\s*(\d+)", text)
        if m and "SESSION_HOT_US" not in parsed:
            parsed["SESSION_HOT_US"] = int(m.group(1))
            break

    if "latency_us" not in parsed:
        for pattern in (
            r"Executed in (\d+) us",
            r"latency_us[=:\s]+(-?\d+)",
        ):
            m = re.search(pattern, text)
            if m:
                parsed["latency_us"] = int(m.group(1))
                break

    fail_m = re.search(r"CUSTOM_PIPELINE_FAILED:\s*(.+)", text)
    if fail_m:
        parsed["error"] = fail_m.group(1).strip()[:2000]
    elif "Failing loud" in text and "error" not in parsed:
        parsed["error"] = "optimization failed (see log tail)"

    return parsed


def run_lemma_one(
    qid: str,
    sql: str,
    *,
    workload: str,
    duckdb_path: str,
    log_dir: Path,
) -> dict[str, Any]:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{workload}_{qid}.log"
    env = env_for_lemma(workload=workload, duckdb_path=duckdb_path)
    python = str(PY) if PY.is_file() else sys.executable

    print(
        f"LEMMA {workload}:{qid} MAX_ITERATIONS={env.get('MAX_ITERATIONS')} start",
        flush=True,
    )
    t0 = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(
            [python, "-m", "db_extension.run_optimizer", sql],
            cwd=ROOT,
            env=env,
            stdout=fh,
            stderr=subprocess.STDOUT,
            check=False,
        )
    elapsed_s = round(time.perf_counter() - t0, 1)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    fields = parse_optimizer_output(text)
    verified = fields.get("proof_verified") is True or "proof_verified=True" in text
    lemma_ok = verified and proc.returncode == 0

    rec: dict[str, Any] = {
        "lemma_ok": lemma_ok,
        "returncode": proc.returncode,
        "elapsed_s": elapsed_s,
        "log": str(log_path),
        "max_iterations": env.get("MAX_ITERATIONS"),
        "use_agent_docker": env.get("USE_AGENT_DOCKER") == "1",
    }
    rec.update(fields)
    if not lemma_ok:
        tail = text[-4000:] if text else "(empty log)"
        rec["error"] = (
            rec.get("error") or f"lemma failed rc={proc.returncode}; log tail:\n{tail}"
        )

    print(
        f"  {qid}: lemma_ok={lemma_ok} rc={proc.returncode} "
        f"proof_verified={fields.get('proof_verified')} "
        f"latency_us={fields.get('latency_us')} "
        f"SESSION_HOT_US={fields.get('SESSION_HOT_US')}",
        flush=True,
    )
    return rec


def build_family_block(
    family: str,
    db_path: Path,
    query_specs: list[tuple[str, str, int]],
    *,
    threads: int,
    skip_duck: bool,
    skip_lemma: bool,
    log_dir: Path,
) -> dict[str, Any]:
    workload = "sec" if family == "sec" else "tpch"
    block: dict[str, Any] = {
        "sql_file": str(SEC_SQL if family == "sec" else TPCH_SQL),
        "duckdb_path": str(db_path),
        "queries": {},
    }

    duck_by_q: dict[str, dict[str, Any]] = {}
    if not skip_duck:
        duck = run_duckdb_one_run(db_path, query_specs, threads=threads)
        block["OPEN_US"] = duck["OPEN_US"]
        duck_by_q = duck["queries"]

    for qid, sql, paper_ms in query_specs:
        qrec: dict[str, Any] = {
            "id": qid,
            "family": family,
            "sql": sql,
            "gendb_paper_ms": paper_ms,
        }
        if qid in duck_by_q:
            qrec.update(duck_by_q[qid])
        if not skip_lemma:
            qrec["lemma"] = run_lemma_one(
                qid,
                sql,
                workload=workload,
                duckdb_path=str(db_path),
                log_dir=log_dir,
            )
        block["queries"][qid] = qrec

    return block


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-run DuckDB + Lemma on GenDB-published query subset"
    )
    parser.add_argument(
        "--sec-db",
        type=Path,
        default=DEFAULT_SEC_DB,
        help=f"SEC DuckDB path (default: {DEFAULT_SEC_DB})",
    )
    parser.add_argument(
        "--tpch-db",
        type=Path,
        default=None,
        help=f"TPC-H DuckDB path (default: {DEFAULT_TPCH_DB} or {ALT_TPCH_DB})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output JSON (default: {DEFAULT_OUT})",
    )
    parser.add_argument("--skip-lemma", action="store_true", help="DuckDB only")
    parser.add_argument("--skip-duck", action="store_true", help="Lemma only")
    parser.add_argument(
        "--threads",
        type=int,
        default=64,
        help="DuckDB PRAGMA threads (default: 64)",
    )
    parser.add_argument(
        "--sec-only",
        action="store_true",
        help="Run SEC-EDGAR published queries only",
    )
    parser.add_argument(
        "--tpch-only",
        action="store_true",
        help="Run TPC-H published queries only",
    )
    args = parser.parse_args()

    run_sec = not args.tpch_only
    run_tpch = not args.sec_only
    tpch_db = resolve_tpch_db(args.tpch_db)

    results: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "git_sha": git_sha(),
        "hostname": socket.gethostname(),
        "protocol": {
            "duckdb": DUCKDB_PROTOCOL,
            "lemma": LEMMA_PROTOCOL,
        },
        "duckdb_threads": args.threads,
        "gendb_paper_ref": "arXiv:2603.02081 §4.2",
    }

    log_dir = ROOT / "research_loop" / "generated" / "gendb_published_one_run"
    errors: list[str] = []

    if run_sec:
        try:
            sec_specs = load_published_queries("sec")
            results["sec"] = build_family_block(
                "sec",
                args.sec_db,
                sec_specs,
                threads=args.threads,
                skip_duck=args.skip_duck,
                skip_lemma=args.skip_lemma,
                log_dir=log_dir,
            )
        except (FileNotFoundError, KeyError) as exc:
            errors.append(f"sec: {exc}")
            results["sec_error"] = str(exc)

    if run_tpch:
        try:
            tpch_specs = load_published_queries("tpch")
            results["tpch"] = build_family_block(
                "tpch",
                tpch_db,
                tpch_specs,
                threads=args.threads,
                skip_duck=args.skip_duck,
                skip_lemma=args.skip_lemma,
                log_dir=log_dir,
            )
        except (FileNotFoundError, KeyError) as exc:
            errors.append(f"tpch: {exc}")
            results["tpch_error"] = str(exc)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, default=str) + "\n")
    print(f"Wrote {args.out}", flush=True)

    if errors and args.skip_lemma and run_sec and "sec" in results and not run_tpch:
        # Duck-only smoke may intentionally use tiny SEC while TPC-H is absent.
        return 0
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ImportError:
        print("duckdb not installed; run: uv sync --group dev", file=sys.stderr)
        raise
