#!/usr/bin/env python3
"""Export all TPC-H tables to pipe-delimited .tbl files with integer-friendly columns.

Uses DuckDB tpch extension (CALL dbgen). Normalization is workload ETL, not engine code:
  - dates → YYYYMMDD integers
  - money / prices → ROUND(x * 100) as BIGINT (or INTEGER where small)
  - lineitem quantity / discount / tax as in export_tpch_lineitem.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

TPCH_TABLES = (
    "region",
    "nation",
    "part",
    "supplier",
    "partsupp",
    "customer",
    "orders",
    "lineitem",
)

# Per-table COPY SELECT (column names match DuckDB dbgen output).
_EXPORT_SQL: dict[str, str] = {
    "region": """
        SELECT r_regionkey, r_name, r_comment FROM region
    """,
    "nation": """
        SELECT n_nationkey, n_name, n_regionkey, n_comment FROM nation
    """,
    "part": """
        SELECT
            p_partkey,
            p_name,
            p_mfgr,
            p_brand,
            p_type,
            p_size,
            p_container,
            CAST(ROUND(p_retailprice * 100) AS BIGINT) AS p_retailprice,
            p_comment
        FROM part
    """,
    "supplier": """
        SELECT
            s_suppkey,
            s_name,
            s_address,
            s_nationkey,
            s_phone,
            CAST(ROUND(s_acctbal * 100) AS BIGINT) AS s_acctbal,
            s_comment
        FROM supplier
    """,
    "partsupp": """
        SELECT
            ps_partkey,
            ps_suppkey,
            ps_availqty,
            CAST(ROUND(ps_supplycost * 100) AS BIGINT) AS ps_supplycost,
            ps_comment
        FROM partsupp
    """,
    "customer": """
        SELECT
            c_custkey,
            c_name,
            c_address,
            c_nationkey,
            c_phone,
            CAST(ROUND(c_acctbal * 100) AS BIGINT) AS c_acctbal,
            c_mktsegment,
            c_comment
        FROM customer
    """,
    "orders": """
        SELECT
            o_orderkey,
            o_custkey,
            o_orderstatus,
            CAST(ROUND(o_totalprice * 100) AS BIGINT) AS o_totalprice,
            CAST(strftime(o_orderdate, '%Y%m%d') AS INTEGER) AS o_orderdate,
            o_orderpriority,
            o_clerk,
            o_shippriority,
            o_comment
        FROM orders
    """,
    "lineitem": """
        SELECT
            l_orderkey,
            l_partkey,
            l_suppkey,
            l_linenumber,
            CAST(l_quantity AS INTEGER) AS l_quantity,
            CAST(ROUND(l_extendedprice * 100) AS BIGINT) AS l_extendedprice,
            CAST(ROUND(l_discount * 100) AS INTEGER) AS l_discount,
            CAST(ROUND(l_tax * 100) AS INTEGER) AS l_tax,
            l_returnflag,
            l_linestatus,
            CAST(strftime(l_shipdate, '%Y%m%d') AS INTEGER) AS l_shipdate,
            CAST(strftime(l_commitdate, '%Y%m%d') AS INTEGER) AS l_commitdate,
            CAST(strftime(l_receiptdate, '%Y%m%d') AS INTEGER) AS l_receiptdate,
            l_shipinstruct,
            l_shipmode,
            l_comment
        FROM lineitem
    """,
}


def default_out_dir(sf: float, root: Path = ROOT) -> Path:
    if sf == 1.0:
        return root / "data" / "tpch-sf1"
    sf_label = str(sf).rstrip("0").rstrip(".") if "." in str(sf) else str(sf)
    return root / "data" / f"tpch-sf{sf_label}"


def export_tpch(sf: float, out_dir: Path, tables: tuple[str, ...] = TPCH_TABLES) -> dict[str, Any]:
    import duckdb

    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("INSTALL tpch; LOAD tpch;")
    con.execute(f"CALL dbgen(sf={sf});")

    table_meta: dict[str, dict[str, Any]] = {}
    for table in tables:
        out_path = out_dir / f"{table}.tbl"
        select_sql = _EXPORT_SQL[table].strip()
        con.execute(
            f"""
            COPY ({select_sql}) TO '{out_path.as_posix()}' (
                FORMAT CSV, DELIMITER '|', HEADER true, QUOTE '"'
            )
            """
        )
        rows = int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        table_meta[table] = {
            "row_count": rows,
            "path": str(out_path),
        }

    meta = {
        "scale_factor": sf,
        "out_dir": str(out_dir),
        "tables": table_meta,
    }
    meta_path = out_dir / "dataset_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sf", type=float, default=1.0, help="TPC-H scale factor (default 1)")
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default data/tpch-sf1 for sf=1, else data/tpch-sf{sf})",
    )
    args = p.parse_args()
    out_dir = args.out_dir if args.out_dir is not None else default_out_dir(args.sf)
    meta = export_tpch(args.sf, out_dir)
    print(f"Exported TPC-H SF={args.sf} → {out_dir}")
    for table, info in meta["tables"].items():
        path = Path(info["path"])
        size_mb = path.stat().st_size / 1e6
        print(f"  {table}: {info['row_count']:,} rows ({size_mb:.0f} MB) → {path.name}")


if __name__ == "__main__":
    main()
