#!/usr/bin/env python3
"""Prove MCP measure path (measure_core.run_solution) on TPCH Q1 stand-in vs DuckDB.

Builds a temp agent workspace with context/ro SQL+schema, marked runquery_agent.rs
(verified stand-in body), and optional bench_hints for hot-path timing — then calls
the same harness entry point as MCP ``run_runquery``.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WORKSPACE = ROOT / "research_loop" / "generated" / "prove_measure_ws"
DEFAULT_TBL = ROOT / "data" / "tpch-sf1" / "lineitem.tbl"
SF1_ROWS = 6_001_215
VERUS_BIN = Path("/home/emil/tools/verus/verus")
QUERY_KEY = "Q1"
QUERY_ID = 1


def _ensure_verus_on_path() -> None:
    verus_dir = str(VERUS_BIN.parent)
    path = os.environ.get("PATH", "")
    if verus_dir not in path.split(":"):
        os.environ["PATH"] = f"{verus_dir}:{os.environ.get('HOME', '')}/.cargo/bin:{path}"
    which = shutil.which("verus")
    if which is None:
        print(
            "ERROR: verus not found on PATH.\n"
            f"  export PATH=\"{verus_dir}:$HOME/.cargo/bin:$PATH\"",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"verus: {which}")


def _projected_schema(sql: str) -> dict[str, str]:
    from verus_transpiler.column_projection import project_schema_for_query

    from research_loop.bench_standins.tpch_runqueries import lineitem_schema

    return project_schema_for_query(sql, dict(lineitem_schema))


def _build_workspace(ws: Path) -> None:
    from research_loop.bench_standins.tpch_runqueries import (
        TPCH_BENCH_EXEC,
        TPCH_BENCH_MAIN_PREFIX,
        TPCH_BENCH_POST_TIMING,
        TPCH_BENCH_TIMING_BODY,
        TPCH_HOT_PATHS,
        queries,
    )
    from research_loop.bench_standins.verified_runqueries import (
        TPCH_RUNQUERIES,
    )

    sql = queries[QUERY_KEY].strip()
    schema = _projected_schema(sql)
    standin_raw = TPCH_RUNQUERIES[QUERY_KEY].strip()

    ro = ws / "context" / "ro"
    ro.mkdir(parents=True, exist_ok=True)
    (ro / "query.sql").write_text(sql + "\n", encoding="utf-8")
    (ro / "schema.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

    bench_hints = {
        "hot_path_rs": TPCH_HOT_PATHS.get(QUERY_KEY, ""),
        "bench_exec": TPCH_BENCH_EXEC.get(QUERY_KEY, ""),
        "bench_timing_body": TPCH_BENCH_TIMING_BODY.get(QUERY_KEY, ""),
        "bench_post_timing": TPCH_BENCH_POST_TIMING.get(QUERY_KEY, ""),
        "bench_main_prefix": TPCH_BENCH_MAIN_PREFIX.get(QUERY_KEY, ""),
    }
    bench_hints = {k: v for k, v in bench_hints.items() if v}
    (ro / "bench_hints.json").write_text(json.dumps(bench_hints, indent=2) + "\n", encoding="utf-8")

    # Full proved stand-in (pub exec fn + proof) — host_standin path in measure_core.
    (ws / "runquery_agent.rs").write_text(standin_raw + "\n", encoding="utf-8")
    print(f"workspace: {ws}")


def _duckdb_median_us(sql: str, tbl: Path, limit: int, *, warmups: int = 2, runs: int = 5) -> int:
    import duckdb

    con = duckdb.connect()
    con.execute("PRAGMA threads=1")
    con.execute(
        f"""
        CREATE TABLE lineitem AS
        SELECT * FROM read_csv(
            '{tbl}',
            delim='|',
            header=true,
            auto_detect=true
        ) LIMIT {limit}
        """
    )
    for _ in range(warmups):
        con.execute(sql).fetchall()
    times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        con.execute(sql).fetchall()
        times.append((time.perf_counter() - t0) * 1e6)
    times.sort()
    return int(times[len(times) // 2])


def _lemma_measure_us(ws: Path, dataset_size: int) -> tuple[int, bool, str]:
    from db_extension.agent import measure_core as mc

    out = mc.run_solution(
        path="runquery_agent.rs",
        query_id=QUERY_ID,
        dataset_size=dataset_size,
        ws=ws,
    )
    metrics = out.get("metrics") or {}
    proof_ok = bool(metrics.get("proof_verified"))
    latency = int(out.get("latency_us") or metrics.get("latency_us") or -1)
    err = ""
    if not out.get("ok"):
        err = str(metrics.get("compiler_error") or "") or "; ".join(out.get("errors") or []) or "harness failed"
    return latency, proof_ok, err


def _print_table(rows: list[dict]) -> None:
    headers = ("rows", "lemma_us", "duck_us", "ratio", "proof_ok", "competitive")
    widths = [
        max(len(h), *(len(str(r.get(k, ""))) for r in rows))
        for k, h in zip(
            ("rows", "lemma_us", "duck_us", "ratio", "proof_ok", "competitive"),
            headers,
        )
    ]
    fmt = "  ".join(f"{{:{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for r in rows:
        print(
            fmt.format(
                r["rows"],
                r["lemma_us"] if r["lemma_us"] >= 0 else "-",
                r["duck_us"] if r["duck_us"] >= 0 else "-",
                r["ratio"],
                r["proof_ok"],
                r["competitive"],
            )
        )


def main() -> int:
    _ensure_verus_on_path()

    if not DEFAULT_TBL.is_file():
        print(f"ERROR: missing TPC-H lineitem table: {DEFAULT_TBL}", file=sys.stderr)
        return 1

    os.environ["LEMMA_BENCH_TBL"] = str(DEFAULT_TBL)

    from research_loop.bench_standins.tpch_runqueries import queries

    sql = queries[QUERY_KEY].strip()

    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)
    _build_workspace(WORKSPACE)

    sizes: list[int] = [50_000]
    if os.environ.get("PROVE_MEASURE_SKIP_SF1", "0") != "1":
        sizes.append(SF1_ROWS)

    rows: list[dict] = []
    any_proof = False
    any_competitive = False

    for n in sizes:
        print(f"\n--- measure rows={n} ---", file=sys.stderr)
        lemma_us, proof_ok, err = _lemma_measure_us(WORKSPACE, n)
        if err:
            print(f"lemma measure error: {err}", file=sys.stderr)
        duck_us = _duckdb_median_us(sql, DEFAULT_TBL, n)
        ratio = "-"
        competitive = False
        if lemma_us > 0 and duck_us > 0:
            ratio = f"{lemma_us / duck_us:.2f}x"
            competitive = lemma_us < duck_us or lemma_us <= 2 * duck_us
        rows.append(
            {
                "rows": n,
                "lemma_us": lemma_us,
                "duck_us": duck_us,
                "ratio": ratio,
                "proof_ok": proof_ok,
                "competitive": competitive,
            }
        )
        any_proof = any_proof or proof_ok
        any_competitive = any_competitive or competitive

    print()
    _print_table(rows)

    verified_rows = [r for r in rows if r["proof_ok"] and r["lemma_us"] > 0]
    if not verified_rows:
        print("\nFAIL: no verified run with finite lemma latency", file=sys.stderr)
        return 1

    if any_competitive:
        print("\nCOMPETITIVE=1")
    else:
        print("\nWARN: verified but not competitive vs DuckDB (goal: lemma < duck or within 2x)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
