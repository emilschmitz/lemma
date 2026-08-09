#!/usr/bin/env python3
"""SEC holdout feasibility timing — TRUSTED ``run_query`` only (not agent-verified).

This script measures end-to-end transpile → assemble → ``verus --compile`` → timed exec
for SEC holdout queries that already have a **real** MethodSpec from the transpiler.

**Measurement intent (not product greenwash):**
- ``run_query`` is hand-written ``#[verifier::external_body]`` with a body that **actually
  executes** the query (HashMap / Vec), and ``ensures`` matching the Trusted view /
  ``method_spec`` contract.
- Verus **proof is disabled** (`ENABLE_VERUS_VERIFY=0`). Numbers are feasibility /
  exec-path timing, **not** agent-verified pipeline success.
- Do **not** cite these results as verified Lemma query support.

Protocol (GenDB-comparable session hot, one process):
  load once → cold ``run_query`` → ``COLD_QUERY_US``;
  2 untimed warmups; median of 5 timed runs → ``SESSION_HOT_US`` (= ``QUERY_US``).

Usage::

    uv run python research_loop/scripts/sec_feasibility_timed.py --queries 1
    uv run python research_loop/scripts/sec_feasibility_timed.py --queries 1,6

Data (first match):
  ``LEMMA_BENCH_TBL`` — pipe-delimited ``.tbl`` for ``pre`` columns
  ``holdout/gendb_sec_edgar/duckdb/sec_edgar.duckdb`` (full SEC load)
  ``holdout/gendb_sec_edgar/duckdb/sec_edgar_tiny.duckdb`` (synthetic smoke)
"""

from __future__ import annotations

import argparse
import os
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QUERIES_REPO = ROOT / "holdout" / "gendb_sec_edgar" / "queries.sql"
QUERIES_HOLDOUT = Path("/home/emil/experiment_data/holdout_parts")
DUCKDB_FULL = ROOT / "holdout" / "gendb_sec_edgar" / "duckdb" / "sec_edgar.duckdb"
DUCKDB_TINY = ROOT / "holdout" / "gendb_sec_edgar" / "duckdb" / "sec_edgar_tiny.duckdb"
GENERATED = ROOT / "research_loop" / "generated"
EXPORT_TBL = GENERATED / "sec_feasibility_pre.tbl"

SEC_REAL_SPEC = frozenset({"1", "2", "4", "6", "24"})
SEC_UNSUPPORTED = frozenset({"3"})
# Q2 decorrelated JOIN may transpile; bodies not implemented here yet.
IMPLEMENTED_RUNQUERY = frozenset({"1"})

PRE_EXPORT_COLS = "stmt, rfile, adsh, line"

SESSION_HOT_LINE = 'println!("QUERY_LATENCY_US: {}", times[times.len() / 2]);'
SESSION_HOT_PATCH = (
    "let session_hot_us = times[times.len() / 2];\n"
    "    println!(\"SESSION_HOT_US: {}\", session_hot_us);\n"
    "    println!(\"QUERY_US: {}\", session_hot_us);\n"
    "    println!(\"QUERY_LATENCY_US: {}\", session_hot_us);"
)

BENCH_MAIN_PREFIX = """
    let t0 = std::time::Instant::now();
    let _cold = run_query(&cols);
    std::hint::black_box(_cold.len());
    let cold_us = t0.elapsed().as_micros();
    println!("COLD_QUERY_US: {}", cold_us);
    for _ in 0..2 {
        let _w = run_query(&cols);
        std::hint::black_box(_w.len());
    }
"""


@dataclass(frozen=True)
class QueryOutcome:
    qnum: str
    status: str
    message: str = ""
    session_hot_us: int | None = None
    cold_query_us: int | None = None
    duck_session_hot_us: int | None = None
    tbl_path: str = ""
    binary: str = ""


def _load_sec_schema() -> dict[str, dict[str, str]]:
    from tests.test_sec_holdout_parse import SEC_SCHEMA

    return SEC_SCHEMA


def _load_query_sql(qnum: str) -> str:
    holdout_file = QUERIES_HOLDOUT / f"q{qnum}.sql"
    if holdout_file.is_file():
        return holdout_file.read_text(encoding="utf-8").strip().rstrip(";") + ";"

    text = QUERIES_REPO.read_text(encoding="utf-8")
    m = re.search(
        rf"-- Q{qnum}:.*?\n(SELECT.*?;)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        raise FileNotFoundError(f"Q{qnum} not found in {QUERIES_REPO}")
    return m.group(1).strip()


def _catalog_for_query(qnum: str, sec_schema: dict[str, dict[str, str]]) -> dict:
    if qnum == "1":
        return {"pre": sec_schema["pre"]}
    if qnum in {"2", "3"}:
        return {"num": sec_schema["num"], "sub": sec_schema["sub"]}
    if qnum == "4":
        return {t: sec_schema[t] for t in ("num", "sub", "tag", "pre")}
    if qnum == "6":
        return {t: sec_schema[t] for t in ("num", "sub", "pre")}
    if qnum == "24":
        return {"num": sec_schema["num"], "pre": sec_schema["pre"]}
    return dict(sec_schema)


def _trusted_runquery_body(spec_rs: str) -> str:
    from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
    from research_loop.trusted_ret_bridge import get_bridge

    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    bridge = get_bridge(ret_type)
    if bridge is None:
        raise RuntimeError(f"missing bridge for {ret_type}")
    rust_ret = bridge.rust_ret
    ensures = bridge.ensures.rstrip(",")

    if ret_type == "map_str_str__u64_u64_u64":
        return f"""#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: {rust_ret})
    requires valid_cols(cols),
    ensures {ensures}
{{
    use std::collections::{{HashMap, HashSet}};
    struct Acc {{
        cnt: u64,
        distinct: HashSet<String>,
        line_sum: u64,
        line_cnt: u64,
    }}
    let mut groups: HashMap<(String, String), Acc> = HashMap::new();
    let mut i: usize = 0;
    while i < cols.n {{
        let stmt = cols.get_stmt_exec(i);
        if stmt != "" {{
            let rfile = cols.get_rfile_exec(i);
            let key = (stmt, rfile);
            let adsh = cols.get_adsh_exec(i);
            let line = cols.get_line_exec(i) as u64;
            let acc = groups.entry(key).or_insert_with(|| Acc {{
                cnt: 0,
                distinct: HashSet::new(),
                line_sum: 0,
                line_cnt: 0,
            }});
            acc.cnt = acc.cnt.wrapping_add(1);
            acc.distinct.insert(adsh);
            acc.line_sum = acc.line_sum.wrapping_add(line);
            acc.line_cnt = acc.line_cnt.wrapping_add(1);
        }}
        i = i + 1;
    }}
    let mut res = HashMap::new();
    for (key, acc) in groups {{
        let distinct_cnt = acc.distinct.len() as u64;
        let avg_line = if acc.line_cnt == 0 {{ 0u64 }} else {{ acc.line_sum / acc.line_cnt }};
        res.insert(key, (acc.cnt, distinct_cnt, avg_line));
    }}
    res
}}"""

    raise RuntimeError(f"no TRUSTED feasibility run_query template for ret_type={ret_type}")


def _runquery_body_for(qnum: str, spec_rs: str) -> str | None:
    if qnum in IMPLEMENTED_RUNQUERY:
        return _trusted_runquery_body(spec_rs)
    return None


def _ensure_verus_path() -> None:
    from research_loop.harness import resolve_verus_bin

    verus = resolve_verus_bin()
    if verus is None:
        raise RuntimeError(
            "verus not found on PATH.\n"
            "  export PATH=\"$HOME/tools/verus:$HOME/.cargo/bin:$PATH\""
        )
    verus_dir = str(Path(verus).parent)
    path = os.environ.get("PATH", "")
    if verus_dir not in path.split(":"):
        os.environ["PATH"] = f"{verus_dir}:{path}"


def _export_pre_tbl(duckdb_path: Path, out_path: Path) -> int:
    import duckdb

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    con = duckdb.connect(str(duckdb_path), read_only=True)
    row_count = con.execute("SELECT COUNT(*) FROM pre").fetchone()[0]
    con.execute(
        f"""
        COPY (SELECT {PRE_EXPORT_COLS} FROM pre)
        TO '{out_path}' (FORMAT CSV, DELIM '|', HEADER true)
        """
    )
    con.close()
    return int(row_count)


def _resolve_tbl_and_duckdb() -> tuple[Path, Path | None, int]:
    bench = os.environ.get("LEMMA_BENCH_TBL", "").strip()
    if bench:
        tbl = Path(bench)
        if not tbl.is_file():
            raise FileNotFoundError(
                f"LEMMA_BENCH_TBL is set but not a readable file: {tbl}"
            )
        return tbl, None, 0

    for db in (DUCKDB_FULL, DUCKDB_TINY):
        if db.is_file():
            rows = _export_pre_tbl(db, EXPORT_TBL)
            return EXPORT_TBL, db, rows

    raise FileNotFoundError(
        "No SEC bench data found. Expected one of:\n"
        f"  LEMMA_BENCH_TBL=<path-to-pre.tbl>\n"
        f"  {DUCKDB_FULL}\n"
        f"  {DUCKDB_TINY}\n"
        "For full SEC: cd holdout/gendb_sec_edgar && uv run python load_data.py"
    )


def _patch_session_hot_main(program: str) -> str:
    if SESSION_HOT_LINE not in program:
        raise RuntimeError("assembled main missing median QUERY_LATENCY_US print")
    return program.replace(SESSION_HOT_LINE, SESSION_HOT_PATCH, 1)


def _parse_metric(stdout: str, key: str) -> int | None:
    m = re.search(rf"{key}:\s*(\d+)", stdout)
    return int(m.group(1)) if m else None


def _run_binary_once(binary: str, tbl: str, limit: int) -> tuple[int, int, str]:
    res = subprocess.run(
        [binary, tbl, str(limit)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    out = (res.stdout or "") + (res.stderr or "")
    if res.returncode != 0:
        raise RuntimeError(f"binary failed (exit {res.returncode}):\n{out[-4000:]}")
    session_hot = _parse_metric(out, "SESSION_HOT_US")
    cold = _parse_metric(out, "COLD_QUERY_US")
    if session_hot is None:
        session_hot = _parse_metric(out, "QUERY_LATENCY_US")
    if session_hot is None:
        raise RuntimeError(f"no SESSION_HOT_US / QUERY_LATENCY_US in:\n{out[-2000:]}")
    return session_hot, cold or -1, out


def _duckdb_session_hot(con, sql: str) -> tuple[int, int]:
    def timed() -> int:
        t0 = time.perf_counter()
        con.execute(sql).fetchall()
        return int((time.perf_counter() - t0) * 1_000_000)

    cold = timed()
    for _ in range(2):
        timed()
    samples = [timed() for _ in range(5)]
    return int(statistics.median(samples)), cold


def _try_transpile(sql: str, catalog: dict) -> tuple[str | None, str | None]:
    from verus_transpiler import transpile_sql_to_verus
    from verus_transpiler.parse_sql import UnsupportedContractError

    try:
        spec = transpile_sql_to_verus(sql, catalog)
        return spec, None
    except UnsupportedContractError as exc:
        return None, f"UnsupportedContractError: {exc}"
    except Exception as exc:
        return None, str(exc)


def _measure_query(
    qnum: str,
    *,
    tbl_path: Path,
    duckdb_path: Path | None,
    row_limit: int,
    skip_duckdb: bool,
) -> QueryOutcome:
    sec_schema = _load_sec_schema()
    sql = _load_query_sql(qnum)
    catalog = _catalog_for_query(qnum, sec_schema)

    if qnum in SEC_UNSUPPORTED:
        return QueryOutcome(qnum, "SKIP", "known UnsupportedContractError (JOIN+HAVING subquery)")

    if qnum not in SEC_REAL_SPEC:
        return QueryOutcome(qnum, "SKIP", "not classified as real MethodSpec holdout")

    if qnum not in IMPLEMENTED_RUNQUERY:
        spec, err = _try_transpile(sql, catalog)
        if spec is None:
            if qnum in {"2", "3"}:
                return QueryOutcome(qnum, "SKIP", f"JOIN/subquery transpile: {err}")
            return QueryOutcome(qnum, "SKIP", f"transpile failed: {err}")
        return QueryOutcome(
            qnum,
            "SKIP",
            "transpile OK but no TRUSTED feasibility run_query body for this query",
        )

    spec, transpile_err = _try_transpile(sql, catalog)
    if spec is None:
        if qnum in {"2", "3"}:
            return QueryOutcome(qnum, "SKIP", f"JOIN/subquery transpile: {transpile_err}")
        return QueryOutcome(qnum, "FAIL", f"transpile: {transpile_err}")

    try:
        body = _runquery_body_for(qnum, spec)
    except RuntimeError as exc:
        return QueryOutcome(qnum, "SKIP", str(exc))
    if body is None:
        return QueryOutcome(
            qnum,
            "SKIP",
            "transpile OK but no TRUSTED feasibility run_query body for this query",
        )

    os.environ["ENABLE_VERUS_VERIFY"] = "0"
    os.environ["REQUIRE_PROOF"] = "0"

    from research_loop.harness import load_env, run_custom_sql_pipeline, run_verus_compile

    cfg = load_env(str(ROOT / "research_loop" / "config.env"))
    for k, v in cfg.items():
        os.environ.setdefault(k, v)

    limit = row_limit if row_limit > 0 else max(50_000, 10_000_000)

    res = run_custom_sql_pipeline(
        sql,
        catalog,
        run_query_body=body,
        tbl=str(tbl_path),
        limit=limit,
        skip_bench=True,
        bench_main_prefix=BENCH_MAIN_PREFIX,
    )

    stage = res.get("stage") or res.get("status")
    if res.get("status") not in {"SUCCESS", "SUCCESS_UNVERIFIED"}:
        err = res.get("error") or stage or "pipeline failed"
        if qnum in {"4", "6", "24"} and stage in {"assemble", "compile", "verify"}:
            return QueryOutcome(qnum, "SKIP", f"host/assemble blocker: {err}")
        return QueryOutcome(qnum, "FAIL", err)

    rs_path = res.get("rs_path")
    if not rs_path:
        return QueryOutcome(qnum, "FAIL", "missing rs_path after assemble")

    program = Path(rs_path).read_text(encoding="utf-8")
    program = _patch_session_hot_main(program)
    Path(rs_path).write_text(program, encoding="utf-8")

    compile_timeout = int(os.environ.get("COMPILE_TIMEOUT_SEC", "180"))
    ok, compile_msg, binary = run_verus_compile(rs_path, compile_timeout)
    if not ok or not binary:
        tail = compile_msg[-4000:] if compile_msg else ""
        if qnum in {"4", "6", "24"}:
            return QueryOutcome(qnum, "SKIP", f"compile/typecheck blocker:\n{tail}")
        return QueryOutcome(qnum, "FAIL", f"verus --compile failed:\n{tail}")

    session_hot, cold, _ = _run_binary_once(binary, str(tbl_path), limit)

    duck_hot: int | None = None
    if not skip_duckdb and duckdb_path is not None:
        import duckdb

        con = duckdb.connect(str(duckdb_path), read_only=True)
        duck_hot, _ = _duckdb_session_hot(con, sql)
        con.close()

    return QueryOutcome(
        qnum,
        "OK",
        tbl_path=str(tbl_path),
        binary=binary,
        session_hot_us=session_hot,
        cold_query_us=cold if cold >= 0 else None,
        duck_session_hot_us=duck_hot,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="SEC holdout TRUSTED feasibility timing")
    parser.add_argument(
        "--queries",
        type=str,
        default="1",
        help="Comma-separated query numbers (default: 1)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Row limit for tbl loader (0 = use full exported table)",
    )
    parser.add_argument(
        "--skip-duckdb",
        action="store_true",
        help="Skip DuckDB SESSION_HOT comparison",
    )
    args = parser.parse_args()

    qnums = [q.strip() for q in args.queries.split(",") if q.strip()]
    if not qnums:
        print("error: no queries selected", file=sys.stderr)
        return 1

    try:
        from research_loop.harness import resolve_verus_bin

        verus_bin = resolve_verus_bin()
        _ensure_verus_path()
        tbl_path, duckdb_path, row_count = _resolve_tbl_and_duckdb()
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("SEC feasibility timed (TRUSTED run_query — NOT agent-verified)")
    print(f"  tbl: {tbl_path}")
    if duckdb_path is not None:
        print(f"  duckdb: {duckdb_path} (pre rows: {row_count:,})")
    if verus_bin:
        print(f"  verus: {verus_bin}")
    print()

    outcomes: list[QueryOutcome] = []
    for qnum in qnums:
        print(f"--- Q{qnum} ---", flush=True)
        outcome = _measure_query(
            qnum,
            tbl_path=tbl_path,
            duckdb_path=duckdb_path,
            row_limit=args.limit,
            skip_duckdb=args.skip_duckdb,
        )
        outcomes.append(outcome)
        if outcome.status == "OK":
            line = f"Q{qnum}: SESSION_HOT_US={outcome.session_hot_us}"
            if outcome.cold_query_us is not None:
                line += f" COLD_QUERY_US={outcome.cold_query_us}"
            if outcome.duck_session_hot_us is not None:
                ratio = outcome.session_hot_us / outcome.duck_session_hot_us
                line += f" duckdb_SESSION_HOT_US={outcome.duck_session_hot_us} ratio={ratio:.2f}x"
            print(line)
        else:
            print(f"Q{qnum}: {outcome.status} — {outcome.message}")

    print()
    print("Summary:")
    for o in outcomes:
        if o.status == "OK" and o.session_hot_us is not None:
            print(f"  Q{o.qnum}: SESSION_HOT_US={o.session_hot_us}")
        else:
            print(f"  Q{o.qnum}: {o.status} ({o.message})")

    failed = [o for o in outcomes if o.status == "FAIL"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
