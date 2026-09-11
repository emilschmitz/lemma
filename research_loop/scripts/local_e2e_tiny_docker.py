#!/usr/bin/env python3
"""Local SEC tiny DuckDB product-path driver (Docker agent required)."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SQL_FILE = ROOT / "research_loop/scripts/local_e2e_tiny_queries.sql"
DEFAULT_TINY_DB = ROOT / "holdout/gendb_sec_edgar/duckdb/sec_edgar_tiny.duckdb"
LOG_DIR = ROOT / "research_loop/generated/local_e2e_tiny_docker"
LIBDUCKDB = ROOT / "build/libduckdb/libduckdb.so"
AGENT_IMAGE = "lemma-agent:cli"

_ALL_QIDS = ("Q1", "Q2", "Q3")
# Observed live slot: docker agent ~260Mi + host run_optimizer ~180Mi.
# Verus verify/measure spikes higher; leave headroom on a 15Gi box already in swap.
_OBS_SLOT_MIB = 1100
_JOBS_CAP = 6


def repo_root() -> Path:
    return ROOT


def mem_available_kb() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1])
    except OSError:
        return 0
    return 0


def observed_e2e_jobs() -> int:
    """Parallelism from LEMMA_E2E_JOBS, else min(nproc, MemAvailable / observed slot)."""
    override = os.environ.get("LEMMA_E2E_JOBS", "").strip()
    if override.isdigit():
        return max(1, int(override))
    nproc = os.cpu_count() or 2
    avail_kb = mem_available_kb()
    from_ram = max(1, avail_kb // (_OBS_SLOT_MIB * 1024)) if avail_kb else 2
    return max(1, min(nproc, from_ram, _JOBS_CAP))


def _qid_sort(qid: str) -> tuple[int, str]:
    m = re.match(r"Q(\d+)$", qid)
    return (int(m.group(1)), qid) if m else (10**9, qid)


def load_queries(sql_file: Path = SQL_FILE) -> dict[str, str]:
    from research_loop.scripts.sqlsmith_trusted_coverage import parse_sql_file

    pairs = parse_sql_file(sql_file)
    return {qid: sql for qid, sql in pairs}


def load_tiny_queries() -> dict[str, str]:
    return load_queries(SQL_FILE)


def resolve_tiny_db() -> Path:
    override = os.environ.get("LEMMA_DUCKDB_PATH", "").strip()
    if override:
        path = Path(override)
        holdout = ROOT / "holdout"
        try:
            path.resolve().relative_to(holdout.resolve())
        except ValueError:
            return DEFAULT_TINY_DB
        if path.is_file():
            return path
    return DEFAULT_TINY_DB


def verus_paths() -> list[str]:
    home = Path(os.environ.get("HOME", "/home/emil"))
    return [
        str(home / "tools/verus"),
        str(home / "src/verus/source/target-verus/release"),
        str(home / ".cargo/bin"),
        str(home / ".local/bin"),
    ]


def augmented_path(base_path: str | None = None) -> str:
    extra = ":".join(verus_paths())
    current = base_path if base_path is not None else os.environ.get("PATH", "")
    parts = [extra, current] if extra else [current]
    return ":".join(p for p in parts if p)


def maybe_reexec_with_docker_group(argv: list[str]) -> None:
    """Activate supplementary group docker (Cursor login sessions often miss it)."""
    if os.environ.get("LEMMA_DOCKER_NEWGRP") == "1":
        return
    if shutil.which("docker") is None:
        return
    proc = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if proc.returncode == 0:
        return
    err = (proc.stderr or proc.stdout or "")
    if "permission denied" not in err.lower():
        return
    import grp
    import pwd
    import shlex

    try:
        g = grp.getgrnam("docker")
    except KeyError:
        return
    user = pwd.getpwuid(os.getuid()).pw_name
    if user not in g.gr_mem:
        return
    newgrp = Path("/usr/bin/newgrp")
    if not newgrp.is_file():
        return
    inner = [sys.executable, str(Path(__file__).resolve()), *argv]
    script = (
        "export LEMMA_DOCKER_NEWGRP=1\nexec "
        + " ".join(shlex.quote(a) for a in inner)
        + "\n"
    )
    print("re-exec via newgrp docker (session missing docker group)", flush=True)
    completed = subprocess.run(
        [str(newgrp), "docker"],
        input=script,
        text=True,
        check=False,
    )
    raise SystemExit(completed.returncode)


def docker_on_path(path_env: str | None = None) -> bool:
    path = path_env if path_env is not None else os.environ.get("PATH", "")
    return shutil.which("docker", path=path) is not None


def docker_preflight_error(path_env: str | None = None) -> str | None:
    path = path_env if path_env is not None else os.environ.get("PATH", "")
    docker_bin = shutil.which("docker", path=path)
    if docker_bin is None:
        return (
            "ERROR: USE_AGENT_DOCKER=1 requires docker on PATH "
            f"(install docker and build {AGENT_IMAGE})"
        )
    try:
        proc = subprocess.run(
            [docker_bin, "info"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except OSError as exc:
        return f"ERROR: docker info failed: {exc}"
    if proc.returncode == 0:
        return None
    err = (proc.stderr or proc.stdout or "").strip()
    if "permission denied" in err.lower():
        return (
            "ERROR: docker daemon permission denied (this session is not in group docker). "
            "Relogin, or: newgrp docker"
        )
    return f"ERROR: docker info failed: {err[:400]}"


def verus_available(path_env: str | None = None) -> bool:
    path = augmented_path(path_env)
    return shutil.which("verus", path=path) is not None


def tiny_db_missing_message() -> str:
    return (
        f"tiny SEC duckdb missing: {DEFAULT_TINY_DB}\n"
        "Run: uv run python holdout/gendb_sec_edgar/synth_tiny.py"
    )


def preflight_errors(
    *,
    path_env: str | None = None,
    require_docker: bool = True,
    require_verus: bool = True,
    require_libduckdb: bool = True,
    require_tiny_db: bool = True,
) -> list[str]:
    errors: list[str] = []
    if require_docker:
        msg = docker_preflight_error(path_env)
        if msg:
            errors.append(msg)
    if require_verus and not verus_available(path_env):
        errors.append("verus not on PATH (expected under ~/tools/verus or ~/src/verus/.../release)")
    if require_libduckdb and not LIBDUCKDB.is_file():
        errors.append(f"missing libduckdb: {LIBDUCKDB}")
    tiny = resolve_tiny_db()
    if require_tiny_db and not tiny.is_file():
        errors.append(tiny_db_missing_message())
    return errors


def select_query_ids(
    argv: list[str],
    *,
    available: tuple[str, ...] | None = None,
    default_all: bool = False,
) -> list[str]:
    catalog = available if available is not None else _ALL_QIDS
    if not argv:
        return list(catalog) if default_all else ["Q1"]
    if len(argv) == 1 and argv[0].lower() in {"q1", "1"} and available is None:
        return ["Q1"]
    if len(argv) == 1 and argv[0].lower() == "all":
        return list(catalog)
    out: list[str] = []
    for arg in argv:
        qid = arg.upper()
        if not qid.startswith("Q"):
            qid = f"Q{qid}"
        if qid not in catalog:
            raise ValueError(f"unknown query {arg!r}; expected one of {list(catalog)} or all")
        if qid not in out:
            out.append(qid)
    return out or (list(catalog) if default_all else ["Q1"])


def apply_product_env(*, duckdb_path: Path) -> None:
    os.environ["PATH"] = augmented_path()
    os.environ["LEMMA_AGENT_BACKEND"] = "cli"
    os.environ["USE_AGENT_DOCKER"] = "1"
    os.environ["AGENT_IMAGE"] = AGENT_IMAGE
    os.environ["MOCK_AGENT"] = "0"
    os.environ["LEMMA_ALLOW_DUCKDB_FALLBACK"] = "0"
    os.environ["LEMMA_EXPERIMENT"] = "1"
    os.environ["LEMMA_EXPERIMENT_ALLOW_DIRTY"] = "1"
    os.environ["LEMMA_RESEARCH_LOG"] = "1"
    os.environ["LEMMA_WORKLOAD"] = "sec"
    os.environ["LEMMA_DUCKDB_PATH"] = str(duckdb_path)
    os.environ["LEMMA_DUCKDB_LIB_DIR"] = str(ROOT / "build/libduckdb")
    os.environ["LEMMA_STOP_ON_TIMED_SUCCESS"] = "1"
    os.environ["LEMMA_KEEP_OPTIMIZING"] = "0"
    os.environ.setdefault("MAX_ITERATIONS", "1")
    os.environ.setdefault("AGENT_TIMEOUT_SEC", "600")
    os.environ["AGENT_NETWORK"] = "0"
    os.environ["AGENT_WEB_SEARCH"] = "0"
    os.environ["AGENT_EGRESS_PROFILE"] = "cursor"
    home = os.environ.get("HOME", "/home/emil")
    os.environ["AGENT_CREDENTIALS_DIR"] = str(Path(home) / ".cursor")
    os.environ["AGENT_AUTH_DIR"] = str(Path(home) / ".config/cursor")
    os.environ["AGENT_CMD"] = (
        "agent -p --force --trust --approve-mcps --model cursor-grok-4.6-high "
        "--output-format stream-json --stream-partial-output < PROMPT.txt"
    )
    os.environ.pop("LEMMA_DATASET_SIZE", None)


def ensure_agent_image() -> None:
    proc = subprocess.run(
        ["docker", "image", "inspect", AGENT_IMAGE],
        capture_output=True,
        check=False,
    )
    if proc.returncode == 0:
        return
    print(f"rebuild {AGENT_IMAGE}...", flush=True)
    subprocess.run(
        [
            "docker",
            "build",
            "-t",
            AGENT_IMAGE,
            "--build-arg",
            "INSTALL_AGENT_CLI=1",
            "-f",
            "docker/agent/Dockerfile",
            ".",
        ],
        cwd=ROOT,
        check=True,
    )


def parse_optimizer_log(text: str) -> dict[str, Any]:
    from research_loop.scripts.gendb_published_one_run import parse_optimizer_output

    return parse_optimizer_output(text)


def lemma_job_ok(rec: dict[str, Any]) -> bool:
    from research_loop.scripts.overnight_lemma import lemma_job_ok as _ok

    return _ok(rec)


def check_runquery_agent_quality(text: str) -> list[str]:
    violations: list[str] = []
    if "AGENT_EDIT" not in text and "AGENT_EDIT_START" not in text:
        violations.append("missing AGENT_EDIT markers")
    if "arbitrary()" in text:
        violations.append("contains arbitrary()")
    if "unimplemented!" in text:
        violations.append("contains unimplemented!")
    return violations


def parse_run_dir(text: str) -> Path | None:
    m = re.search(r"run_dir='([^']+)'", text)
    if not m:
        return None
    path = Path(m.group(1))
    return path if path.is_dir() else None


def find_latest_runquery_agent() -> Path | None:
    candidates: list[Path] = []
    runs = ROOT / "research_loop/runs"
    if runs.is_dir():
        for run_dir in runs.iterdir():
            candidate = run_dir / "workspace" / "runquery_agent.rs"
            if candidate.is_file():
                candidates.append(candidate)
    generated = ROOT / "research_loop/generated"
    if generated.is_dir():
        for path in generated.rglob("runquery_agent.rs"):
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def copy_run_dir(log_dir: Path, run_dir: Path) -> Path | None:
    src = run_dir / "result.json"
    if not src.is_file():
        return None
    dest = log_dir / f"run_{run_dir.name}"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(run_dir, dest)
    return dest / "result.json"


def copy_latest_result_json(log_dir: Path) -> Path | None:
    runs = ROOT / "research_loop/runs"
    if not runs.is_dir():
        return None
    result_dirs = sorted(
        (p for p in runs.glob("*/result.json") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not result_dirs:
        return None
    return copy_run_dir(log_dir, result_dirs[0].parent)


def resume_ok_qids(log_dir: Path, query_ids: list[str]) -> set[str]:
    ok: set[str] = set()
    results_path = log_dir / "results.json"
    if results_path.is_file():
        try:
            data = json.loads(results_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        for rec in data.get("results") or []:
            qid = rec.get("qid")
            if rec.get("lemma_ok") and isinstance(qid, str):
                ok.add(qid)
    for qid in query_ids:
        if qid in ok:
            continue
        log_path = log_dir / f"{qid.lower()}.log"
        if not log_path.is_file():
            continue
        fields = parse_optimizer_log(log_path.read_text(encoding="utf-8", errors="replace"))
        rec = {**fields, "qid": qid, "returncode": 0}
        if lemma_job_ok(rec):
            ok.add(qid)
    return ok


def run_one_query(qid: str, sql: str, *, log_dir: Path) -> dict[str, Any]:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{qid.lower()}.log"
    print(f"=== local e2e {qid} ===", flush=True)
    t0 = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(
            [sys.executable, "-m", "db_extension.run_optimizer", sql],
            cwd=ROOT,
            env=os.environ.copy(),
            stdout=fh,
            stderr=subprocess.STDOUT,
            check=False,
        )
    elapsed_s = round(time.perf_counter() - t0, 1)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    fields = parse_optimizer_log(text)
    rec: dict[str, Any] = {
        "qid": qid,
        "returncode": proc.returncode,
        "elapsed_s": elapsed_s,
        "log": str(log_path),
        **fields,
    }
    rec["lemma_ok"] = lemma_job_ok({**rec, "returncode": proc.returncode})

    run_dir = parse_run_dir(text)
    agent_path = None
    if run_dir is not None:
        candidate = run_dir / "workspace" / "runquery_agent.rs"
        if candidate.is_file():
            agent_path = candidate
    if agent_path is None:
        agent_path = find_latest_runquery_agent()
    if agent_path is not None:
        agent_text = agent_path.read_text(encoding="utf-8", errors="replace")
        rec["runquery_agent"] = str(agent_path)
        quality = check_runquery_agent_quality(agent_text)
        if quality:
            rec["agent_quality_violations"] = quality
            rec["lemma_ok"] = False

    result_json = copy_run_dir(log_dir, run_dir) if run_dir is not None else None
    if result_json is None:
        result_json = copy_latest_result_json(log_dir)
        if result_json is not None:
            run_dir = result_json.parent
    if result_json is not None:
        rec["result_json"] = str(result_json)

    from research_loop.scripts.classify_product_failures import (
        classify_optimizer_log,
        classify_run_dir,
    )

    product = classify_run_dir(run_dir) if run_dir is not None else None
    if product is None:
        product = classify_optimizer_log(text)
    rec["product_step"] = product["step"]
    rec["product_class"] = product["class"]
    if product.get("detail"):
        rec["product_detail"] = product["detail"]

    print(
        f"{qid}: proof={rec.get('proof_verified')} lat={rec.get('latency_us')} "
        f"lemma_ok={rec.get('lemma_ok')} "
        f"step={rec.get('product_step')} {rec.get('product_class')} "
        f"{rec.get('product_detail', '')}".rstrip(),
        flush=True,
    )
    return rec


def _write_e2e_progress(log_dir: Path, results: list[dict[str, Any]], *, round_i: int) -> None:
    dest = log_dir / "results.json"
    payload = {
        "round": round_i,
        "n": len(results),
        "ok": sum(1 for r in results if r.get("lemma_ok")),
        "failed": [r["qid"] for r in results if not r.get("lemma_ok")],
        "results": results,
    }
    dest.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def run_local_e2e(
    query_ids: list[str],
    *,
    path_env: str | None = None,
    skip_docker_build: bool = False,
    sql_file: Path | None = None,
    log_dir: Path | None = None,
    retry_rounds: int = 1,
) -> tuple[list[dict[str, Any]], int]:
    saved_path = os.environ.get("PATH")
    if path_env is not None:
        os.environ["PATH"] = path_env
    try:
        return _run_local_e2e_impl(
            query_ids,
            path_env=path_env,
            skip_docker_build=skip_docker_build,
            sql_file=sql_file,
            log_dir=log_dir,
            retry_rounds=retry_rounds,
        )
    finally:
        if saved_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = saved_path


def _run_local_e2e_impl(
    query_ids: list[str],
    *,
    path_env: str | None = None,
    skip_docker_build: bool = False,
    sql_file: Path | None = None,
    log_dir: Path | None = None,
    retry_rounds: int = 1,
) -> tuple[list[dict[str, Any]], int]:
    errors = preflight_errors(path_env=path_env)
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return [], 1

    if not skip_docker_build:
        ensure_agent_image()

    duckdb_path = resolve_tiny_db()
    apply_product_env(duckdb_path=duckdb_path)
    source = sql_file if sql_file is not None else SQL_FILE
    queries = load_queries(source)
    missing = [qid for qid in query_ids if qid not in queries]
    if missing:
        print(f"queries missing from {source}: {missing}", file=sys.stderr)
        return [], 1

    dest = log_dir if log_dir is not None else LOG_DIR
    dest.mkdir(parents=True, exist_ok=True)
    latest: dict[str, dict[str, Any]] = {}
    pending = list(query_ids)
    if os.environ.get("LEMMA_E2E_FORCE_ALL", "").strip() != "1":
        already = resume_ok_qids(dest, query_ids)
        if already:
            print(f"resume skip ok: {sorted(already, key=_qid_sort)}", flush=True)
            pending = [qid for qid in pending if qid not in already]
            for qid in already:
                latest[qid] = {
                    "qid": qid,
                    "lemma_ok": True,
                    "resumed": True,
                }
    jobs = observed_e2e_jobs()
    avail_gi = mem_available_kb() / (1024 * 1024)
    print(
        f"e2e jobs={jobs} (nproc={os.cpu_count()} "
        f"MemAvailable={avail_gi:.1f}Gi slot={_OBS_SLOT_MIB}Mi cap={_JOBS_CAP})",
        flush=True,
    )
    progress_lock = threading.Lock()
    rounds = max(1, int(retry_rounds))
    for round_i in range(1, rounds + 1):
        if not pending:
            break
        print(
            f"=== e2e round {round_i}/{rounds} pending={len(pending)} jobs={jobs} ===",
            flush=True,
        )

        def _one(qid: str) -> dict[str, Any]:
            rec = run_one_query(qid, queries[qid], log_dir=dest)
            rec["round"] = round_i
            with progress_lock:
                latest[qid] = rec
                _write_e2e_progress(
                    dest,
                    [latest[qid2] for qid2 in query_ids if qid2 in latest],
                    round_i=round_i,
                )
            return rec

        if jobs <= 1 or len(pending) <= 1:
            round_recs = [_one(qid) for qid in pending]
        else:
            round_recs = []
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                futs = {pool.submit(_one, qid): qid for qid in pending}
                for fut in as_completed(futs):
                    round_recs.append(fut.result())
        still = [rec["qid"] for rec in round_recs if not rec.get("lemma_ok")]
        pending = still
        if pending and round_i < rounds:
            print(f"retrying failed: {pending}", flush=True)

    results = [latest[qid] for qid in query_ids if qid in latest]
    exit_code = 0 if results and all(r.get("lemma_ok") for r in results) else 1
    return results, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local SEC tiny Docker e2e product path")
    parser.add_argument(
        "--sql-file",
        type=Path,
        default=None,
        help="Labeled -- Qn: SQL file (default: smoke Q1–Q3)",
    )
    parser.add_argument(
        "queries",
        nargs="*",
        help="Q1 (default), all, gendb (T1–T30 + failed historical), or explicit ids",
    )
    args = parser.parse_args(argv)
    reexec_argv = list(sys.argv[1:] if argv is None else argv)

    sql_file = args.sql_file
    log_dir = LOG_DIR
    query_args = list(args.queries)
    default_all = False
    retry_rounds = 1
    if query_args and query_args[0].lower() == "gendb":
        from research_loop.scripts.local_e2e_gendb_suite import (
            OUT_DIR as GENDB_LOG,
            write_suite_sql,
        )

        os.environ.setdefault("MAX_ITERATIONS", "4")
        retry_rounds = 1
        sql_file = write_suite_sql()
        log_dir = GENDB_LOG
        query_args = query_args[1:]
        default_all = True
    elif sql_file is not None:
        default_all = True
        log_dir = sql_file.resolve().parent

    queries = load_queries(sql_file if sql_file is not None else SQL_FILE)
    try:
        query_ids = select_query_ids(
            query_args,
            available=tuple(queries),
            default_all=default_all,
        )
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    os.chdir(ROOT)
    maybe_reexec_with_docker_group(reexec_argv)
    _, code = run_local_e2e(
        query_ids,
        sql_file=sql_file,
        log_dir=log_dir,
        retry_rounds=retry_rounds,
    )
    if code == 0:
        print(f"logs under {log_dir}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
