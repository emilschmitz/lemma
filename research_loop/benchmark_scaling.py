#!/usr/bin/env python3
"""Scaling benchmark: Q1–Q5, halving row counts, equivalent hot-loop timing.

Methodology (apples-to-apples hot loop):
  - Data loaded once per (engine, row_count) before any query timing.
  - Each query timed with 3 consecutive executions; we report the 3rd (matches bench_q / harness).
  - Load time recorded separately; never included in hot_us.
  - DuckDB / PostgreSQL: two hot variants — threads=1 (fair vs single-threaded Rust) and default parallelism.
  - Bare / verified Rust: single-threaded generated loops (no parallelism today).

Results: data/benchmarks/scaling_results.json
Plot:     plots/scaling_avg_hot_q1_q5.png
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db_extension import DatabaseCatalog
from research_loop.admit_runquery import admit_runquery
from research_loop.benchmark_runqueries import RUNQUERIES
from research_loop.postprocessor import postprocess, inject_hot_loop_main
from research_loop.ssb_workload import queries, schema
from sql_transpiler import transpile_sql_to_dafny_columnar, generate_cols_native_rs

RESEARCH = ROOT / "research_loop"
TBL = ROOT / "ssb-dbgen" / "lineorder_flat.tbl"
RUNTIME = RESEARCH / "working_query-rust" / "runtime"
NATIVE_OPS = RESEARCH / "native_bridge" / "src" / "native_ops.rs"
NATIVE_AGG = RESEARCH / "native_bridge" / "src" / "native_agg.rs"
BENCH_BARE = RESEARCH / "bench_bare"
BARE_BIN = BENCH_BARE / "target" / "release" / "bench_q"
BUILD = RESEARCH / "bench_build"
DATA_DIR = ROOT / "data" / "benchmarks"
PLOTS_DIR = ROOT / "plots"
RESULTS_PATH = DATA_DIR / "scaling_results.json"
VERIFIED_CACHE = DATA_DIR / "verified_bins"

QUERIES = [1, 2, 3, 4, 5]
MAX_ROWS = 1_500_000
MIN_ROWS = 5_000
WARM_RUNS = 3  # report last run (same as bench_q time_loop)

PG_CONTAINER = "lemma-bench-pg"
PG_IMAGE = "postgres:16"
PG_PORT = 54329
PG_PASSWORD = "lemma"
PG_DSN = f"postgresql://postgres:{PG_PASSWORD}@127.0.0.1:{PG_PORT}/postgres"
PG_TBL_IN_CONTAINER = "/data/lineorder_flat.tbl"

PG_TYPE = {"int": "INTEGER", "string": "TEXT"}
PG_DDL = ",\n  ".join(f"{col} {PG_TYPE[typ]}" for col, typ in schema.items())


def default_meta() -> dict:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "description": "SSB flat table Q1–Q5 scaling benchmark (hot-loop latency).",
        "metric": "hot_us — microseconds for the 3rd consecutive timed query execution",
        "plot_metric": "Mean of Q1–Q5 hot_us converted to milliseconds",
        "data_source": str(TBL.relative_to(ROOT)),
        "methodology": (
            "Hot loop = 3rd consecutive timed execution after data is resident in the engine. "
            "DuckDB/PostgreSQL: table loaded once per (parallelism mode, row_count); "
            "Rust binaries load columns inside the process before the timed loop. "
            "Load time is recorded separately and never included in hot_us."
        ),
        "queries": QUERIES,
        "warm_runs": WARM_RUNS,
        "engines": [
            "duckdb_1t",
            "duckdb_mt",
            "postgres_1t",
            "postgres_mt",
            "bare_rust",
            "verified_rust",
        ],
        "postgres": {
            "image": PG_IMAGE,
            "port": PG_PORT,
            "load": f"COPY ... FROM PROGRAM 'head -n LIMIT+1 {PG_TBL_IN_CONTAINER}'",
            "parallelism": {
                "postgres_1t": "SET max_parallel_workers_per_gather = 0",
                "postgres_mt": "default PostgreSQL parallel query settings",
            },
        },
    }


def halving_sizes(max_rows: int, min_rows: int) -> list[int]:
    out: list[int] = []
    n = max_rows
    while n >= min_rows:
        out.append(n)
        n = n // 2
    if out[-1] != min_rows and min_rows not in out:
        out.append(min_rows)
    # common demo anchor
    if 50_000 not in out:
        out.append(50_000)
    return sorted(set(out))


def run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 300, env: dict | None = None):
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env or os.environ.copy(),
    )


def ensure_bare_binary() -> None:
    if BARE_BIN.is_file():
        return
    r = run(["cargo", "build", "--release", "--bin", "bench_q"], cwd=BENCH_BARE, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"bench_q build failed:\n{r.stderr}")


def hot_loop_third(run_fn) -> tuple[int, list[int]]:
    """Run 3 timed iterations; return (3rd_us, all_us)."""
    times: list[int] = []
    for _ in range(WARM_RUNS):
        t0 = time.perf_counter()
        run_fn()
        times.append(int((time.perf_counter() - t0) * 1_000_000))
    return times[-1], times


def duckdb_session(limit: int, threads: int | None) -> tuple[object, float]:
    import duckdb

    con = duckdb.connect(":memory:")
    if threads is not None:
        con.execute(f"PRAGMA threads={threads}")
    t0 = time.perf_counter()
    con.execute(
        f"CREATE TABLE lineorder_flat AS "
        f"SELECT * FROM read_csv('{TBL}', delim='|', header=true, quote='\"') "
        f"LIMIT {limit}"
    )
    load_s = time.perf_counter() - t0
    return con, load_s


def bench_duckdb(limit: int) -> dict:
    import duckdb

    default_threads = duckdb.connect(":memory:").execute("SELECT current_setting('threads')").fetchone()[0]
    out: dict = {"load_s": {}, "hot_us": {}, "all_runs_us": {}}
    for label, threads in [("duckdb_1t", 1), ("duckdb_mt", int(default_threads))]:
        con, load_s = duckdb_session(limit, threads)
        out["load_s"][label] = round(load_s, 4)
        out["hot_us"][label] = {}
        out["all_runs_us"][label] = {}
        for q in QUERIES:
            sql = queries[q - 1]

            def _run(s=sql):
                con.execute(s).fetchall()

            hot, all_r = hot_loop_third(_run)
            out["hot_us"][label][str(q)] = hot
            out["all_runs_us"][label][str(q)] = all_r
    out["duckdb_default_threads"] = int(default_threads)
    return out


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return run(["docker", *args], timeout=120)


@contextmanager
def postgres_container():
    import psycopg

    _docker("rm", "-f", PG_CONTAINER)
    r = _docker(
        "run", "-d", "--name", PG_CONTAINER,
        "-e", f"POSTGRES_PASSWORD={PG_PASSWORD}",
        "-p", f"{PG_PORT}:5432",
        "-v", f"{TBL.parent.resolve()}:/data:ro",
        PG_IMAGE,
    )
    if r.returncode != 0:
        raise RuntimeError(f"failed to start postgres container:\n{r.stderr}")

    deadline = time.time() + 60
    last_err = ""
    while time.time() < deadline:
        try:
            with psycopg.connect(PG_DSN, connect_timeout=2) as conn:
                conn.execute("SELECT 1")
            break
        except Exception as e:
            last_err = str(e)
            time.sleep(1)
    else:
        logs = _docker("logs", PG_CONTAINER)
        raise RuntimeError(f"postgres not ready: {last_err}\n{logs.stdout}\n{logs.stderr}")

    try:
        yield
    finally:
        _docker("rm", "-f", PG_CONTAINER)


def postgres_session(limit: int, parallel: str) -> tuple[object, float]:
    import psycopg

    conn = psycopg.connect(PG_DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        if parallel == "1t":
            cur.execute("SET max_parallel_workers_per_gather = 0")
        cur.execute("DROP TABLE IF EXISTS lineorder_flat")
        cur.execute(f"CREATE TABLE lineorder_flat (\n  {PG_DDL}\n)")
        t0 = time.perf_counter()
        cur.execute(
            f"COPY lineorder_flat FROM PROGRAM "
            f"'head -n {limit + 1} {PG_TBL_IN_CONTAINER}' "
            f"WITH (FORMAT csv, DELIMITER '|', HEADER true, QUOTE '\"')"
        )
        cur.execute("ANALYZE lineorder_flat")
        load_s = time.perf_counter() - t0
    return conn, load_s


def bench_postgres(limit: int) -> dict:
    out: dict = {"load_s": {}, "hot_us": {}, "all_runs_us": {}}
    for label, parallel in [("postgres_1t", "1t"), ("postgres_mt", "mt")]:
        conn, load_s = postgres_session(limit, parallel)
        out["load_s"][label] = round(load_s, 4)
        out["hot_us"][label] = {}
        out["all_runs_us"][label] = {}
        try:
            for q in QUERIES:
                sql = queries[q - 1].strip()

                def _run(s=sql, c=conn):
                    with c.cursor() as cur:
                        cur.execute(s)
                        cur.fetchall()

                hot, all_r = hot_loop_third(_run)
                out["hot_us"][label][str(q)] = hot
                out["all_runs_us"][label][str(q)] = all_r
        finally:
            conn.close()
    out["postgres_image"] = PG_IMAGE
    return out


def postgres_cached(block: dict) -> bool:
    pg = block.get("postgres") or {}
    if not pg.get("hot_us"):
        return False
    for label in ("postgres_1t", "postgres_mt"):
        if label not in pg.get("hot_us", {}):
            return False
        for q in QUERIES:
            if str(q) not in pg["hot_us"][label]:
                return False
    return True


def bench_bare(q: int, limit: int) -> dict:
    t0 = time.perf_counter()
    r = run([str(BARE_BIN), str(q), str(TBL), str(limit)], cwd=ROOT, timeout=300)
    wall_s = time.perf_counter() - t0
    if r.returncode != 0:
        return {"error": (r.stderr or r.stdout)[-500:], "wall_s": round(wall_s, 3)}
    m = re.search(r"QUERY_LATENCY_US:\s*(\d+)", r.stdout)
    hot = int(m.group(1)) if m else -1
    load_est = max(0.0, wall_s - hot * WARM_RUNS / 1_000_000)
    return {
        "wall_s": round(wall_s, 4),
        "load_est_s": round(load_est, 4),
        "hot_us": hot,
        "note": "hot_us is 3rd timed RunQuery; load is before timer inside process",
    }


def verified_bin_path(q: int, limit: int) -> Path:
    return VERIFIED_CACHE / f"q{q}_n{limit}"


def build_verified(q: int, limit: int) -> Path:
    dest = verified_bin_path(q, limit)
    bin_path = dest / "bench"
    if bin_path.is_file():
        return bin_path

    runquery = RUNQUERIES[q]
    catalog = DatabaseCatalog()
    schema = catalog.get_table_schema("lineorder_flat")
    spec = transpile_sql_to_dafny_columnar(queries[q - 1], schema)
    src = f'{spec}\n\n{runquery}\n\nmethod {{:verify false}} Main() {{ print "SUCCESS\\n"; }}\n'

    work = BUILD / f"q{q}_n{limit}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    dfy = work / "q.dfy"
    cols_rs = work / "cols_native.rs"
    dfy.write_text(src)
    cols_rs.write_text(generate_cols_native_rs(schema))

    admission = admit_runquery(src)
    if not admission.ok:
        raise RuntimeError(f"Q{q} admission: {'; '.join(admission.violations)}")

    v = run(["dafny", "verify", "--allow-warnings", str(dfy)], timeout=300)
    if v.returncode != 0:
        raise RuntimeError(f"Q{q} verify failed:\n{v.stdout}\n{v.stderr}")

    t = run(
        [
            "dafny", "translate", "rs", "--enforce-determinism", "--no-verify", "--allow-warnings",
            str(dfy), str(cols_rs), str(NATIVE_OPS), str(NATIVE_AGG),
        ],
        cwd=work,
        timeout=300,
    )
    if t.returncode != 0:
        raise RuntimeError(f"Q{q} translate failed:\n{t.stdout}\n{t.stderr}")

    proj = work / "q-rust"
    main_rs = proj / "src" / "main.rs"
    shutil.copy(proj / "src" / "q.rs", main_rs)
    (proj / "Cargo.toml").write_text(
        f'[package]\nname = "bench"\nversion = "0.1.0"\nedition = "2021"\n'
        f'[dependencies]\ndafny_runtime = {{ path = "{RUNTIME}" }}\n'
    )
    postprocess(str(main_rs), str(TBL), limit, allow_fast_native_agg=admission.allow_fast_native_agg)
    inject_hot_loop_main(str(main_rs), str(TBL), limit)
    env = os.environ.copy()
    env["RUSTFLAGS"] = "-C target-cpu=native"
    b = run(["cargo", "build", "--release"], cwd=proj, timeout=300, env=env)
    if b.returncode != 0:
        raise RuntimeError(f"Q{q} cargo failed:\n{b.stdout}\n{b.stderr}")

    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(proj / "target" / "release" / "bench", bin_path)
    return bin_path


def bench_verified(q: int, limit: int) -> dict:
    try:
        bin_path = build_verified(q, limit)
    except Exception as e:
        return {"error": str(e)}
    t0 = time.perf_counter()
    r = run([str(bin_path)], cwd=ROOT, timeout=300)
    wall_s = time.perf_counter() - t0
    if r.returncode != 0:
        return {"error": (r.stdout + r.stderr)[-500:], "wall_s": round(wall_s, 3)}
    m = re.search(r"QUERY_LATENCY_US:\s*(\d+)", r.stdout)
    hot = int(m.group(1)) if m else -1
    load_est = max(0.0, wall_s - hot * WARM_RUNS / 1_000_000)
    return {
        "wall_s": round(wall_s, 4),
        "load_est_s": round(load_est, 4),
        "hot_us": hot,
        "note": "hot_us is 3rd timed RunQuery; load is before timer inside process",
    }


def load_results() -> dict:
    if RESULTS_PATH.is_file():
        data = json.loads(RESULTS_PATH.read_text())
        meta = data.setdefault("meta", {})
        for key, value in default_meta().items():
            if key not in meta:
                meta[key] = value
        return data
    return {"meta": default_meta(), "sizes": {}}


def save_results(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data["meta"]["updated_at"] = datetime.now(timezone.utc).isoformat()
    RESULTS_PATH.write_text(json.dumps(data, indent=2))


def run_all() -> dict:
    ensure_bare_binary()
    data = load_results()
    sizes = halving_sizes(MAX_ROWS, MIN_ROWS)

    for limit in sizes:
        key = str(limit)
        if key in data["sizes"] and data["sizes"][key].get("complete"):
            print(f"skip {limit:,} (cached)", flush=True)
            continue

        print(f"\n=== {limit:,} rows ===", flush=True)
        entry: dict = {"rows": limit, "duckdb": None, "queries": {}}

        print("  DuckDB (1-thread + default threads)...", flush=True)
        entry["duckdb"] = bench_duckdb(limit)

        for q in QUERIES:
            print(f"  Q{q} bare...", flush=True)
            bare = bench_bare(q, limit)
            print(f"  Q{q} verified...", flush=True)
            verified = bench_verified(q, limit)
            entry["queries"][str(q)] = {"bare_rust": bare, "verified_rust": verified}
            b = bare.get("hot_us", -1)
            v = verified.get("hot_us", -1)
            d1 = entry["duckdb"]["hot_us"]["duckdb_1t"][str(q)]
            dm = entry["duckdb"]["hot_us"]["duckdb_mt"][str(q)]
            print(f"    hot_us  duck1t={d1}  duckmt={dm}  bare={b}  verified={v}", flush=True)

        entry["complete"] = True
        data["sizes"][key] = entry
        save_results(data)

    return data


def run_postgres(data: dict) -> dict:
    sizes = sorted(int(k) for k, v in data["sizes"].items() if v.get("complete"))
    if not sizes:
        raise RuntimeError("no complete benchmark sizes — run the main benchmark first")

    with postgres_container():
        for limit in sizes:
            key = str(limit)
            block = data["sizes"][key]
            if postgres_cached(block):
                print(f"skip postgres {limit:,} (cached)", flush=True)
                continue

            print(f"\n=== PostgreSQL {limit:,} rows ===", flush=True)
            block["postgres"] = bench_postgres(limit)
            for q in QUERIES:
                p1 = block["postgres"]["hot_us"]["postgres_1t"][str(q)]
                pm = block["postgres"]["hot_us"]["postgres_mt"][str(q)]
                print(f"    hot_us  pg1t={p1}  pgmt={pm}  (Q{q})", flush=True)
            save_results(data)

    data["meta"]["engines"] = default_meta()["engines"]
    save_results(data)
    return data


def plot_results(data: dict) -> Path:
    import matplotlib.pyplot as plt

    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    sizes = sorted(int(k) for k in data["sizes"] if data["sizes"][k].get("complete"))
    if not sizes:
        raise RuntimeError("no complete benchmark sizes to plot")

    series = {
        "duckdb_1t": [],
        "duckdb_mt": [],
        "postgres_1t": [],
        "postgres_mt": [],
        "bare_rust": [],
        "verified_rust": [],
    }
    points: dict[str, list[tuple[int, float]]] = {k: [] for k in series}

    for limit in sizes:
        block = data["sizes"][str(limit)]
        avgs = {k: [] for k in series}
        for q in QUERIES:
            avgs["duckdb_1t"].append(block["duckdb"]["hot_us"]["duckdb_1t"][str(q)])
            avgs["duckdb_mt"].append(block["duckdb"]["hot_us"]["duckdb_mt"][str(q)])
            if postgres_cached(block):
                avgs["postgres_1t"].append(block["postgres"]["hot_us"]["postgres_1t"][str(q)])
                avgs["postgres_mt"].append(block["postgres"]["hot_us"]["postgres_mt"][str(q)])
            avgs["bare_rust"].append(block["queries"][str(q)]["bare_rust"]["hot_us"])
            avgs["verified_rust"].append(block["queries"][str(q)]["verified_rust"]["hot_us"])
        for k in series:
            if not avgs[k]:
                continue
            points[k].append((limit, sum(avgs[k]) / len(avgs[k]) / 1000.0))

    fig, ax = plt.subplots(figsize=(10, 5.5))
    labels = {
        "duckdb_1t": "DuckDB (1 thread)",
        "duckdb_mt": "DuckDB (default threads)",
        "postgres_1t": "PostgreSQL (no parallel gather)",
        "postgres_mt": "PostgreSQL (default parallelism)",
        "bare_rust": "Bare Rust",
        "verified_rust": "Verified Rust",
    }
    markers = {
        "duckdb_1t": "o",
        "duckdb_mt": "s",
        "postgres_1t": "v",
        "postgres_mt": "P",
        "bare_rust": "^",
        "verified_rust": "D",
    }
    for key, pts in points.items():
        if not pts:
            continue
        xs, ys = zip(*pts)
        ax.plot(xs, ys, marker=markers[key], label=labels[key], linewidth=2)

    ax.set_xscale("log", base=2)
    ax.set_xlabel("Row count (SSB flat)")
    ax.set_ylabel("Avg hot-loop time Q1–Q5 (ms)")
    ax.set_title("SSB Q1–Q5: avg 3rd-run hot loop vs row count")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out = PLOTS_DIR / "scaling_avg_hot_q1_q5.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-only", action="store_true", help="Run PostgreSQL hot loops for cached sizes")
    parser.add_argument("--plot-only", action="store_true", help="Regenerate plot from scaling_results.json")
    args = parser.parse_args()

    data = load_results()
    if args.plot_only:
        plot = plot_results(data)
        print(f"Plot: {plot}")
        return

    if args.postgres_only:
        data = run_postgres(data)
    else:
        data = run_all()

    plot = plot_results(data)
    print(f"\nResults: {RESULTS_PATH}")
    print(f"Plot:    {plot}")


if __name__ == "__main__":
    main()
