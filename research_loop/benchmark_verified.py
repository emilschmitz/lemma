#!/usr/bin/env python3
"""Benchmark verified Dafny→Rust vs bare Rust vs DuckDB (hot RunQuery loop, 50k rows)."""
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from db_extension import DatabaseCatalog
from research_loop.admit_runquery import admit_runquery
from research_loop.benchmark_runqueries import RUNQUERIES
from research_loop.postprocessor import postprocess, inject_hot_loop_main
from research_loop.ssb_workload import queries
from sql_transpiler import transpile_sql_to_dafny_columnar, generate_cols_native_rs

RESEARCH = os.path.join(ROOT, "research_loop")
RUNTIME = os.path.join(RESEARCH, "working_query-rust", "runtime")
NATIVE_BRIDGE = os.path.join(RESEARCH, "native_bridge", "src")
NATIVE_OPS = os.path.join(NATIVE_BRIDGE, "native_ops.rs")
NATIVE_AGG = os.path.join(NATIVE_BRIDGE, "native_agg.rs")
TBL = os.path.join(ROOT, "ssb-dbgen", "lineorder_flat.tbl")
LIMIT = 50000
BENCH_QUERIES = sorted(RUNQUERIES.keys())


def run_cmd(cmd, cwd=None, timeout=120, env=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


def duckdb_connect():
    import duckdb
    con = duckdb.connect()
    con.execute(
        f"CREATE TABLE lineorder_flat AS "
        f"SELECT * FROM read_csv('{TBL}', delim='|', header=true, quote='\"') "
        f"LIMIT {LIMIT}"
    )
    return con


def bench_duckdb(con, sql: str) -> int:
    for _ in range(2):
        con.execute(sql).fetchall()
    t0 = time.perf_counter()
    con.execute(sql).fetchall()
    return int((time.perf_counter() - t0) * 1_000_000)


def bench_bare(query_idx: int) -> int:
    res = run_cmd(
        ["cargo", "run", "--release", "--bin", "bench_q", str(query_idx), TBL, str(LIMIT)],
        cwd=os.path.join(RESEARCH, "bench_bare"),
    )
    if res.returncode != 0:
        print(res.stdout, res.stderr)
        return -1
    m = re.search(r"QUERY_LATENCY_US:\s*(\d+)", res.stdout)
    return int(m.group(1)) if m else -1


def bench_verified(query_idx: int, runquery: str) -> tuple[int, bool]:
    catalog = DatabaseCatalog()
    schema = catalog.get_table_schema("lineorder_flat")
    spec = transpile_sql_to_dafny_columnar(queries[query_idx - 1], schema)
    main = 'method {:verify false} Main() { print "SUCCESS\\n"; }'
    src = f"{spec}\n\n{runquery}\n\n{main}\n"

    build = os.path.join(RESEARCH, "bench_build")
    shutil.rmtree(build, ignore_errors=True)
    os.makedirs(build)
    dfy = os.path.join(build, "q.dfy")
    cols_rs = os.path.join(build, "cols_native.rs")
    with open(dfy, "w") as f:
        f.write(src)
    with open(cols_rs, "w") as f:
        f.write(generate_cols_native_rs(schema))

    admission = admit_runquery(src)
    if not admission.ok:
        print("RunQuery admission failed:", "; ".join(admission.violations))
        return -1, False

    v = run_cmd(["dafny", "verify", "--allow-warnings", dfy], timeout=180)
    if v.returncode != 0:
        print(v.stdout, v.stderr)
        return -1, False

    translate_cmd = [
        "dafny", "translate", "rs", "--enforce-determinism", "--no-verify", "--allow-warnings",
        dfy, cols_rs, NATIVE_OPS, NATIVE_AGG,
    ]
    t = run_cmd(translate_cmd, cwd=build)
    if t.returncode != 0:
        print(t.stdout, t.stderr)
        return -1, False

    proj = os.path.join(build, "q-rust")
    rs = os.path.join(proj, "src", "q.rs")
    main_rs = os.path.join(proj, "src", "main.rs")
    shutil.copy(rs, main_rs)
    cargo = os.path.join(proj, "Cargo.toml")
    with open(cargo, "w") as f:
        f.write(f'[package]\nname = "bench"\nversion = "0.1.0"\nedition = "2021"\n[dependencies]\ndafny_runtime = {{ path = "{RUNTIME}" }}\n')

    postprocess(main_rs, TBL, LIMIT, allow_fast_native_agg=admission.allow_fast_native_agg)
    inject_hot_loop_main(main_rs, TBL, LIMIT)
    env = os.environ.copy()
    env["RUSTFLAGS"] = "-C target-cpu=native"
    b = run_cmd(["cargo", "build", "--release"], cwd=proj, timeout=180, env=env)
    if b.returncode != 0:
        print(b.stdout, b.stderr)
        return -1, True

    bin_path = os.path.join(proj, "target", "release", "bench")
    r = run_cmd([bin_path], cwd=ROOT, timeout=120)
    m = re.search(r"QUERY_LATENCY_US:\s*(\d+)", r.stdout)
    return (int(m.group(1)) if m else -1), True


def main():
    print(f"=== Benchmarks ({LIMIT} rows, hot loop only) ===")
    print(f"{'Q':>4} {'DuckDB us':>10} {'Bare us':>10} {'Verified us':>12} {'verified':>9}")
    print("-" * 50)

    con = duckdb_connect()
    rows = []
    for qidx in BENCH_QUERIES:
        sql = queries[qidx - 1]
        duck = bench_duckdb(con, sql)
        bare = bench_bare(qidx)
        ver, ok = bench_verified(qidx, RUNQUERIES[qidx])
        rows.append((qidx, duck, bare, ver, ok))
        print(f"{qidx:4d} {duck:10d} {bare:10d} {ver:12d} {str(ok):>9}")

    print("-" * 50)
    wins = sum(1 for _, d, _, v, ok in rows if ok and v > 0 and v < d)
    print(f"Verified beats DuckDB on {wins}/{len(rows)} queries")


if __name__ == "__main__":
    main()
