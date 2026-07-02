#!/usr/bin/env python3
"""Benchmark verified Q1/Q11 against DuckDB and bare Rust baselines."""
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from db_extension import DatabaseCatalog
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

# Native-optimized RunQuery: extern AddU64/MulU64U32, column locals, no `as int` in hot path.
Q1_RUNQUERY = """
method RunQuery(cols: Cols) returns (res: NativeU64)
  requires ValidCols(cols)
  ensures res == MethodSpec(cols)
{
  res := 0 as NativeU64;
  var i := cols.n();
  while i > 0
    invariant 0 <= i <= cols.n()
    invariant res as int == MethodSpecHelper(cols, i) as int
  {
    i := i - 1;
    var od := cols.GetLO_ORDERDATE(i);
    var disc := cols.GetLO_DISCOUNT(i);
    var qty := cols.GetLO_QUANTITY(i);
    if 19930101 <= od && od <= 19931231 && 1 <= disc && disc <= 3 && qty < 25 {
      var ep := cols.GetLO_EXTENDEDPRICE(i);
      res := AddU64(res, MulU64U32(ep, disc));
    }
  }
}
"""

# Group-by: NativeAggMap + ghost map (transpiler-recommended pattern; fully verified).
Q11_RUNQUERY = """
method RunQuery(cols: Cols) returns (res: map<(NativeU32, string), NativeI64>)
  requires ValidCols(cols)
  ensures res == MethodSpec(cols)
  requires forall j :: 0 <= j < cols.n() ==>
    -9223372036854775808 <= SubU64ToI64(cols.GetLO_REVENUE(j), cols.GetLO_SUPPLYCOST(j)) as int
      < 9223372036854775808
{
  var agg := new NativeAggMap();
  ghost var g: map<(NativeU32, string), NativeI64> := map[];
  var i := cols.n();
  while i > 0
    invariant 0 <= i <= cols.n()
    invariant g == MethodSpecHelper(cols, i)
    invariant agg.Snapshot() == g
    invariant forall k :: k in g ==>
      -9223372036854775808 <= g[k] as int < 9223372036854775808
  {
    i := i - 1;
    if cols.EqAtC_REGION(i, "AMERICA") && cols.EqAtS_REGION(i, "AMERICA")
       && cols.EqAtP_MFGR(i, "MFGR#1")
    {
      var yr := cols.GetD_YEAR(i);
      var nation := cols.GetC_NATION(i);
      var key := (yr, nation);
      var term := SubU64ToI64(cols.GetLO_REVENUE(i), cols.GetLO_SUPPLYCOST(i));
      agg.Add(yr, nation, term);
      ghost var prev := if key in g then g[key] else 0 as NativeI64;
      g := g[key := AddI64(prev, term)];
    }
  }
  res := agg.ToMap();
}
"""


def run_cmd(cmd, cwd=None, timeout=120, env=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


def bench_duckdb(sql: str) -> int:
    import duckdb
    con = duckdb.connect()
    con.execute(
        f"CREATE TABLE lineorder_flat AS "
        f"SELECT * FROM read_csv('{TBL}', delim='|', header=true, quote='\"') "
        f"LIMIT {LIMIT}"
    )
    for _ in range(2):
        con.execute(sql).fetchall()
    t0 = time.perf_counter()
    con.execute(sql).fetchall()
    return int((time.perf_counter() - t0) * 1_000_000)


def bench_bare(name: str) -> int:
    res = run_cmd(
        ["cargo", "run", "--release", "--bin", name, TBL, str(LIMIT)],
        cwd=os.path.join(RESEARCH, "bench_bare"),
    )
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

    postprocess(main_rs, TBL, LIMIT)
    inject_hot_loop_main(main_rs, TBL, LIMIT)
    env = os.environ.copy()
    env["RUSTFLAGS"] = "-C target-cpu=native"
    b = run_cmd(["cargo", "build", "--release"], cwd=proj, timeout=180, env=env)
    if b.returncode != 0:
        print(b.stdout, b.stderr)
        return -1, True

    bin_path = os.path.join(proj, "target", "release", "bench")
    r = run_cmd([bin_path], cwd=ROOT, timeout=60)
    m = re.search(r"QUERY_LATENCY_US:\s*(\d+)", r.stdout)
    return (int(m.group(1)) if m else -1), True


def main():
    q1_sql = queries[0]
    q11_sql = queries[10]
    print("=== Benchmarks (50k rows, hot RunQuery loop only) ===")
    print(f"DuckDB Q1:  {bench_duckdb(q1_sql)} us")
    print(f"Bare Q1:    {bench_bare('bench_q1')} us")
    v1, ok1 = bench_verified(1, Q1_RUNQUERY)
    print(f"Verified Q1: {v1} us (verified={ok1})")
    print(f"DuckDB Q11: {bench_duckdb(q11_sql)} us")
    print(f"Bare Q11:   {bench_bare('bench_q11')} us")
    v11, ok11 = bench_verified(11, Q11_RUNQUERY)
    print(f"Verified Q11: {v11} us (verified={ok11})")


if __name__ == "__main__":
    main()
