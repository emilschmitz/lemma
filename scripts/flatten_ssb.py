#!/usr/bin/env python3
"""Join normalized SSB .tbl files into denormalized lineorder_flat.tbl (real data)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb


def flatten(root: Path) -> int:
    db_path = root / "ssb-dbgen"
    print("--- Flattening SSB tables via DuckDB ---")
    print(f"    Source dir: {db_path}")

    con = duckdb.connect(database=":memory:")
    con.execute("SET memory_limit='3GB'")
    con.execute("SET threads TO 2")

    part_cols = {
        "P_PARTKEY": "BIGINT", "P_NAME": "VARCHAR", "P_MFGR": "VARCHAR", "P_CATEGORY": "VARCHAR", "P_BRAND": "VARCHAR",
        "P_COLOR": "VARCHAR", "P_TYPE": "VARCHAR", "P_SIZE": "BIGINT", "P_CONTAINER": "VARCHAR",
    }
    con.execute(f"""
        CREATE TABLE part AS SELECT * FROM read_csv('{db_path}/part.tbl',
        delim=',', header=False, columns={part_cols}, auto_detect=False)
    """)

    supp_cols = {
        "S_SUPPKEY": "BIGINT", "S_NAME": "VARCHAR", "S_ADDRESS": "VARCHAR", "S_CITY": "VARCHAR",
        "S_NATION": "VARCHAR", "S_REGION": "VARCHAR", "S_PHONE": "VARCHAR",
    }
    con.execute(f"""
        CREATE TABLE supplier AS SELECT * FROM read_csv('{db_path}/supplier.tbl',
        delim=',', header=False, columns={supp_cols}, auto_detect=False)
    """)

    cust_cols = {
        "C_CUSTKEY": "BIGINT", "C_NAME": "VARCHAR", "C_ADDRESS": "VARCHAR", "C_CITY": "VARCHAR",
        "C_NATION": "VARCHAR", "C_REGION": "VARCHAR", "C_PHONE": "VARCHAR", "C_MKTSEGMENT": "VARCHAR",
    }
    con.execute(f"""
        CREATE TABLE customer AS SELECT * FROM read_csv('{db_path}/customer.tbl',
        delim=',', header=False, columns={cust_cols}, auto_detect=False)
    """)

    date_cols = {
        "D_DATEKEY": "BIGINT", "D_DATE": "VARCHAR", "D_DAYOFWEEK": "VARCHAR", "D_MONTH": "VARCHAR",
        "D_YEAR": "BIGINT", "D_YEARMONTHNUM": "BIGINT", "D_YEARMONTH": "VARCHAR", "D_DAYNUMINWEEK": "BIGINT",
        "D_DAYNUMINMONTH": "BIGINT", "D_DAYNUMINYEAR": "BIGINT", "D_MONTHNUMINYEAR": "BIGINT",
        "D_WEEKNUMINYEAR": "BIGINT", "D_SELLINGSEASON": "VARCHAR", "D_LASTDAYINWEEKFL": "BIGINT",
        "D_LASTDAYINMONTHFL": "BIGINT", "D_HOLIDAYFL": "BIGINT", "D_WEEKDAYFL": "BIGINT",
    }
    con.execute(f"""
        CREATE TABLE date_dim AS SELECT * FROM read_csv('{db_path}/date.tbl',
        delim=',', header=False, columns={date_cols}, auto_detect=False)
    """)

    lo_cols = {
        "LO_ORDERKEY": "BIGINT", "LO_LINENUMBER": "BIGINT", "LO_CUSTKEY": "BIGINT", "LO_PARTKEY": "BIGINT",
        "LO_SUPPKEY": "BIGINT", "LO_ORDERDATE": "VARCHAR", "LO_ORDERPRIORITY": "VARCHAR", "LO_SHIPPRIORITY": "BIGINT",
        "LO_QUANTITY": "BIGINT", "LO_EXTENDEDPRICE": "BIGINT", "LO_ORDTOTALPRICE": "BIGINT", "LO_DISCOUNT": "BIGINT",
        "LO_REVENUE": "BIGINT", "LO_SUPPLYCOST": "BIGINT", "LO_TAX": "BIGINT", "LO_COMMITDATE": "VARCHAR",
        "LO_SHIPMODE": "VARCHAR",
    }
    con.execute(f"""
        CREATE TABLE lineorder AS SELECT * FROM read_csv('{db_path}/lineorder.tbl',
        delim=',', header=False, columns={lo_cols}, auto_detect=False)
    """)

    print("Joining tables...")
    con.execute("""
        CREATE TABLE lineorder_flat AS
        SELECT
            LO_ORDERKEY, LO_LINENUMBER, LO_CUSTKEY, LO_PARTKEY, LO_SUPPKEY,
            CAST(replace(LO_ORDERDATE, '-', '') AS BIGINT) AS LO_ORDERDATE,
            LO_ORDERPRIORITY, LO_SHIPPRIORITY, LO_QUANTITY,
            LO_EXTENDEDPRICE, LO_ORDTOTALPRICE, LO_DISCOUNT, LO_REVENUE,
            LO_SUPPLYCOST, LO_TAX,
            CAST(replace(LO_COMMITDATE, '-', '') AS BIGINT) AS LO_COMMITDATE,
            LO_SHIPMODE,
            C_NAME, C_ADDRESS, C_CITY, C_NATION, C_REGION, C_PHONE, C_MKTSEGMENT,
            S_NAME, S_ADDRESS, S_CITY, S_NATION, S_REGION, S_PHONE,
            P_NAME, P_MFGR, P_CATEGORY, P_BRAND, P_COLOR, P_TYPE, P_SIZE, P_CONTAINER,
            D_YEAR, D_YEARMONTHNUM, D_WEEKNUMINYEAR
        FROM lineorder
        JOIN customer ON LO_CUSTKEY = C_CUSTKEY
        JOIN supplier ON LO_SUPPKEY = S_SUPPKEY
        JOIN part ON LO_PARTKEY = P_PARTKEY
        JOIN date_dim ON CAST(replace(LO_ORDERDATE, '-', '') AS BIGINT) = D_DATEKEY
    """)

    output_file = db_path / "lineorder_flat.tbl"
    print(f"Exporting denormalized table to {output_file}...")
    con.execute(f"""
        COPY lineorder_flat TO '{output_file}' (HEADER TRUE, DELIMITER '|');
    """)

    count = con.execute("SELECT COUNT(*) FROM lineorder_flat").fetchone()[0]
    scale = float(os.environ.get("LEMMA_SSB_SCALE", "1.333"))
    meta = {
        "row_count": int(count),
        "ssb_scale": scale,
        "source": "ssb-dbgen + scripts/flatten_ssb.py",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "tbl_path": str(output_file),
    }
    (db_path / "dataset_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Done! lineorder_flat has {count:,} rows.")
    return int(count)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    flatten(args.root)


if __name__ == "__main__":
    main()
