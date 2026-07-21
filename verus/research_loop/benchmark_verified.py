#!/usr/bin/env python3
"""Benchmark Verus exec path for SSB / TPC-H fixtures vs bare Rust."""
from __future__ import annotations

import argparse
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
DEFAULT_SSB_TBL = os.path.join(ROOT, "ssb-dbgen", "lineorder_flat.tbl")
DEFAULT_TPCH_TBL = os.path.join(ROOT, "data", "tpch-sf1", "lineitem.tbl")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from verus.research_loop.verified_runqueries import (  # noqa: E402
    SSB_RUNQUERIES,
    TPCH_RUNQUERIES,
)
from verus.research_loop.basic_sql_fixtures import BASIC_SQL_FIXTURES  # noqa: E402
from verus.research_loop.basic_sql_join_fixtures import (  # noqa: E402
    BASIC_SQL_JOIN_FIXTURES,
)
from verus.research_loop.basic_sql_set_cte_fixtures import (  # noqa: E402
    BASIC_SQL_SET_CTE_FIXTURES,
)
from verus.research_loop.basic_sql_proj_order_fixtures import (  # noqa: E402
    BASIC_SQL_PROJ_ORDER_FIXTURES,
)
from verus.research_loop.harness import (  # noqa: E402
    ALL_BASIC_SQL_FIXTURES,
    basic_sql_tbl_path,
    run_basic_sql_extended_join_pipeline,
    run_basic_sql_join_pipeline,
    run_basic_sql_nway_pipeline,
    run_basic_sql_pipeline,
    run_ssb_pipeline,
    run_tpch_pipeline,
)

def _ratio(verus_us: int, bare_us: int) -> str:
    if verus_us < 0 or bare_us < 0:
        return "-"
    if bare_us == 0:
        return "inf"
    return f"{verus_us / bare_us:.2f}"


def _print_table(rows: list[dict]) -> None:
    headers = ("Query", "verus_us", "bare_us", "ratio", "proof_ok", "status")
    widths = [max(len(h), *(len(str(r.get(k, ""))) for r in rows)) for k, h in zip(
        ("query_label", "verus_us", "bare_us", "ratio", "proof_ok", "status"),
        headers,
    )]
    fmt = "  ".join(f"{{:{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for r in rows:
        verus = r.get("latency_us", -1)
        bare = r.get("bare_us", -1)
        print(
            fmt.format(
                r.get("query_label", "?"),
                verus if verus >= 0 else "-",
                bare if bare >= 0 else "-",
                r.get("ratio", _ratio(verus, bare)),
                r.get("proof_verified", False),
                r.get("status", "?"),
            )
        )


def bench_ssb(query_keys: list[int], limit: int, tbl: str) -> list[dict]:
    rows: list[dict] = []
    for qidx in query_keys:
        print(f"--- SSB Q{qidx} ---", file=sys.stderr)
        if not os.path.exists(tbl):
            rows.append(
                {
                    "query_label": f"SSB Q{qidx}",
                    "status": "SKIP",
                    "latency_us": -1,
                    "bare_us": -1,
                    "ratio": "-",
                    "proof_verified": False,
                    "bench_msg": f"tbl missing: {tbl}",
                }
            )
            continue

        res = run_ssb_pipeline(qidx, limit=limit, tbl=tbl)
        verus = res.get("latency_us", -1)
        bare = res.get("bare_us", -1)
        row = {
            "query_label": f"SSB Q{qidx}",
            "status": res.get("status", "FAILURE"),
            "latency_us": verus,
            "bare_us": bare,
            "ratio": _ratio(verus, bare),
            "proof_verified": res.get("proof_verified", False),
        }
        if res.get("status") != "SUCCESS":
            row["error"] = res.get("error", "unknown")
        rows.append(row)
    return rows


def bench_tpch(query_keys: list[str], limit: int, tbl: str) -> list[dict]:
    rows: list[dict] = []
    for qkey in query_keys:
        print(f"--- TPC-H {qkey} ---", file=sys.stderr)
        if not os.path.exists(tbl):
            rows.append(
                {
                    "query_label": f"TPC-H {qkey}",
                    "status": "SKIP",
                    "latency_us": -1,
                    "bare_us": -1,
                    "ratio": "-",
                    "proof_verified": False,
                    "bench_msg": f"tbl missing: {tbl}",
                }
            )
            continue

        res = run_tpch_pipeline(qkey, limit=limit, tbl=tbl)
        verus = res.get("latency_us", -1)
        bare = res.get("bare_us", -1)
        row = {
            "query_label": f"TPC-H {qkey}",
            "status": res.get("status", "FAILURE"),
            "latency_us": verus,
            "bare_us": bare,
            "ratio": _ratio(verus, bare),
            "proof_verified": res.get("proof_verified", False),
        }
        if res.get("status") != "SUCCESS":
            row["error"] = res.get("error", "unknown")
        rows.append(row)
    return rows


def bench_basic_sql(query_keys: list[str], limit: int) -> list[dict]:
    rows: list[dict] = []
    for key in query_keys:
        if key in BASIC_SQL_JOIN_FIXTURES:
            print(f"--- basic_sql_join:{key} ---", file=sys.stderr)
            fx = BASIC_SQL_JOIN_FIXTURES[key]
            bench_limit = limit if limit != 50_000 else fx.bench_limit
            res = run_basic_sql_join_pipeline(key, limit=bench_limit)
            verus = res.get("latency_us", -1)
            bare = res.get("bare_us", -1)
            row = {
                "query_label": f"basic_sql_join:{key}",
                "status": res.get("status", "FAILURE"),
                "latency_us": verus,
                "bare_us": bare,
                "ratio": _ratio(verus, bare),
                "proof_verified": res.get("proof_verified", False),
            }
            if res.get("status") != "SUCCESS":
                row["error"] = res.get("error", "unknown")
            if res.get("bench_skipped"):
                row["status"] = "SKIP"
                row["bench_msg"] = res.get("bench_msg", "")
            rows.append(row)
            continue

        if key in BASIC_SQL_EXTENDED_FIXTURES:
            fx_ext = BASIC_SQL_EXTENDED_FIXTURES[key]
            if fx_ext.is_nway_join:
                print(f"--- basic_sql:{key} (nway) ---", file=sys.stderr)
                res = run_basic_sql_nway_pipeline(key, limit=limit)
                verus = res.get("latency_us", -1)
                row = {
                    "query_label": f"basic_sql:{key}",
                    "status": res.get("status", "FAILURE"),
                    "latency_us": verus,
                    "bare_us": -1,
                    "ratio": "-",
                    "proof_verified": res.get("proof_verified", False),
                }
                if res.get("status") != "SUCCESS":
                    row["error"] = res.get("error", "unknown")
                if res.get("bench_skipped"):
                    row["status"] = "SKIP"
                    row["bench_msg"] = res.get("bench_msg", "")
                rows.append(row)
                continue
            if fx_ext.is_join:
                print(f"--- basic_sql:{key} (join) ---", file=sys.stderr)
                res = run_basic_sql_extended_join_pipeline(key, limit=limit)
                verus = res.get("latency_us", -1)
                row = {
                    "query_label": f"basic_sql:{key}",
                    "status": res.get("status", "FAILURE"),
                    "latency_us": verus,
                    "bare_us": -1,
                    "ratio": "-",
                    "proof_verified": res.get("proof_verified", False),
                }
                if res.get("status") != "SUCCESS":
                    row["error"] = res.get("error", "unknown")
                if res.get("bench_skipped"):
                    row["status"] = "SKIP"
                    row["bench_msg"] = res.get("bench_msg", "")
                rows.append(row)
                continue

        print(f"--- basic_sql:{key} ---", file=sys.stderr)
        tbl = basic_sql_tbl_path(key)
        if not os.path.exists(tbl):
            rows.append(
                {
                    "query_label": f"basic_sql:{key}",
                    "status": "SKIP",
                    "latency_us": -1,
                    "bare_us": -1,
                    "ratio": "-",
                    "proof_verified": False,
                    "bench_msg": f"tbl missing: {tbl}",
                }
            )
            continue

        res = run_basic_sql_pipeline(key, limit=limit, tbl=tbl)
        verus = res.get("latency_us", -1)
        row = {
            "query_label": f"basic_sql:{key}",
            "status": res.get("status", "FAILURE"),
            "latency_us": verus,
            "bare_us": -1,
            "ratio": "-",
            "proof_verified": res.get("proof_verified", False),
        }
        if res.get("status") != "SUCCESS":
            row["error"] = res.get("error", "unknown")
        rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Verus research loop multi-query bench")
    parser.add_argument(
        "-q",
        "--query",
        type=str,
        default="all",
        help="SSB query index, TPC-H Q name, or 'all' (default all)",
    )
    parser.add_argument("--tpch", action="store_true", help="Benchmark TPC-H Q1/Q6")
    parser.add_argument(
        "--basic-sql",
        action="store_true",
        help="Benchmark basic SQL batch-1 fixtures",
    )
    parser.add_argument("--limit", type=int, default=50_000, help="Row limit")
    parser.add_argument("--tbl", type=str, default=None, help="Override tbl path")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="assemble+admit only (no tbl required)",
    )
    args = parser.parse_args()

    if args.smoke:
        _smoke_assemble_admit()
        print("smoke: assemble+admit OK")
        return

    if args.basic_sql:
        keys = (
            sorted(ALL_BASIC_SQL_FIXTURES.keys())
            + sorted(BASIC_SQL_JOIN_FIXTURES.keys())
        )
        print(f"=== Verus basic SQL bench ({args.limit} rows) ===")
        rows = bench_basic_sql(keys, args.limit)
    elif args.tpch:
        tbl = args.tbl or DEFAULT_TPCH_TBL
        if args.query.lower() == "all":
            keys = sorted(TPCH_RUNQUERIES.keys())
        else:
            keys = [args.query.upper()]
        print(f"=== Verus TPC-H bench ({args.limit} rows, tbl={tbl}) ===")
        rows = bench_tpch(keys, args.limit, tbl)
    else:
        tbl = args.tbl or DEFAULT_SSB_TBL
        if args.query.lower() == "all":
            keys = sorted(SSB_RUNQUERIES.keys())
        else:
            keys = [int(args.query)]
        print(f"=== Verus SSB bench ({args.limit} rows, tbl={tbl}) ===")
        rows = bench_ssb(keys, args.limit, tbl)

    _print_table(rows)

    failures = [r for r in rows if r.get("status") == "FAILURE"]
    if failures:
        for r in failures:
            print(f"FAILED {r['query_label']}: {r.get('error', '')}", file=sys.stderr)
        sys.exit(1)

    skipped = [r for r in rows if r.get("status") == "SKIP"]
    if skipped and len(skipped) == len(rows):
        print("All queries skipped (missing tbl).", file=sys.stderr)
        sys.exit(0)


def _smoke_assemble_admit() -> None:
    from verus.research_loop.assemble_verified_program import assemble_verified_program
    from verus.research_loop.ssb_queries import load_schema, queries as ssb_queries
    from verus.research_loop._transpiler import project_schema_for_query, transpile_sql_to_verus
    from verus.research_loop.verified_runqueries import SSB_RETURN_TYPES, SSB_RUNQUERIES

    sql = ssb_queries[0]
    schema = project_schema_for_query(sql, load_schema())
    spec = transpile_sql_to_verus(sql, schema, enable_templates=False)
    program = assemble_verified_program(
        spec_rs=spec,
        run_query_body=SSB_RUNQUERIES[1],
        schema_dict=schema,
        ret_type=SSB_RETURN_TYPES[1],
        default_tbl="ssb-dbgen/lineorder_flat.tbl",
    )
    assert "pub exec fn run_query" in program
    assert "load_cols" in program
    assert "QUERY_LATENCY_US" in program


if __name__ == "__main__":
    main()
