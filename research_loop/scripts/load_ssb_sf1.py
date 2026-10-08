"""Load ssb-dbgen .tbl files (SF1) into a NORMALIZED SSB star-schema DuckDB (lineorder, date, part, supplier, customer)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

T = "INTEGER"
V = "VARCHAR"
D = "DATE_STR"
TABLES = {
    "lineorder": ("lineorder.tbl", [
        ("lo_orderkey", T), ("lo_linenumber", T), ("lo_custkey", T), ("lo_partkey", T), ("lo_suppkey", T),
        ("lo_orderdate", D), ("lo_orderpriority", V), ("lo_shippriority", T), ("lo_quantity", T),
        ("lo_extendedprice", T), ("lo_ordtotalprice", T), ("lo_discount", T), ("lo_revenue", T),
        ("lo_supplycost", T), ("lo_tax", T), ("lo_commitdate", D), ("lo_shipmode", V)]),
    "customer": ("customer.tbl", [
        ("c_custkey", T), ("c_name", V), ("c_address", V), ("c_city", V), ("c_nation", V), ("c_region", V),
        ("c_phone", V), ("c_mktsegment", V)]),
    "supplier": ("supplier.tbl", [
        ("s_suppkey", T), ("s_name", V), ("s_address", V), ("s_city", V), ("s_nation", V), ("s_region", V),
        ("s_phone", V)]),
    "part": ("part.tbl", [
        ("p_partkey", T), ("p_name", V), ("p_mfgr", V), ("p_category", V), ("p_brand1", V), ("p_color", V),
        ("p_type", V), ("p_size", T), ("p_container", V)]),
    "date": ("date.tbl", [
        ("d_datekey", T), ("d_date", V), ("d_dayofweek", V), ("d_month", V), ("d_year", T), ("d_yearmonthnum", T),
        ("d_yearmonth", V), ("d_daynuminweek", T), ("d_daynuminmonth", T), ("d_daynuminyear", T),
        ("d_monthnuminyear", T), ("d_weeknuminyear", T), ("d_sellingseason", V), ("d_lastdayinweekfl", T),
        ("d_lastdayinmonthfl", T), ("d_holidayfl", T), ("d_weekdayfl", T)]),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tbl-dir", type=Path, required=True)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--scale", default="1")
    a = ap.parse_args()
    a.db.unlink(missing_ok=True)
    con = duckdb.connect(str(a.db))
    con.execute("SET memory_limit='2GB'")
    con.execute("SET threads TO 2")
    counts = {}
    for name, (fn, cols) in TABLES.items():
        # dbgen rows end with a trailing delimiter -> one extra empty column; read everything as text, then cast
        spec = {c: "VARCHAR" for c, _ in cols}
        spec["_trailing"] = "VARCHAR"
        con.execute(
            f"CREATE TABLE tmp AS SELECT * FROM read_csv('{a.tbl_dir / fn}', delim=',', quote='\"', "
            f"header=false, columns={spec}, auto_detect=false)"
        )
        sel = []
        for c, t in cols:
            if t == D:
                sel.append(f"CAST(replace({c}, '-', '') AS INTEGER)")
            elif t == T:
                sel.append(f"CAST({c} AS INTEGER)")
            else:
                sel.append(c)
        ddl = ", ".join(f"{c} {V if t == V else T}" for c, t in cols)
        con.execute(f'CREATE TABLE "{name}" ({ddl})')
        con.execute(f'INSERT INTO "{name}" SELECT {", ".join(sel)} FROM tmp')
        con.execute("DROP TABLE tmp")
        counts[name] = con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
        print(name, counts[name])
    ver = con.execute("select version()").fetchone()[0]
    con.close()
    a.manifest.write_text(json.dumps({
        "benchmark": "SSB",
        "scale_factor": a.scale,
        "schema": "normalized star (lineorder, date, part, supplier, customer)",
        "dbgen": "ssb-dbgen (vadimtk fork, copied from main checkout, no download) built with gcc -std=gnu89 -fcommon; "
                 "./dbgen -s 1 -f -T c|p|s|d|l; default seed",
        "dbgen_note": "fork writes lo_orderdate/lo_commitdate as 'YYYY-MM-DD'; loader converts to integer YYYYMMDD "
                      "(= d_datekey). Part brand column is the standard name p_brand1. All integer columns INTEGER.",
        "row_counts": counts,
        "duckdb_version": ver,
        "db": str(a.db),
        "tbl_dir": str(a.tbl_dir),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
