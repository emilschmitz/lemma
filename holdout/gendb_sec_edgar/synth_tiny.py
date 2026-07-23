#!/usr/bin/env python3
"""Synthesize a tiny SEC-EDGAR-shaped DuckDB for RAM-safe GenDB-style smoke.

Writes holdout/gendb_sec_edgar/duckdb/sec_edgar_tiny.duckdb (~50k–100k pre rows).
Deterministic seed; no SEC download required.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = SCRIPT_DIR / "schema.sql"
DEFAULT_DB = SCRIPT_DIR / "duckdb" / "sec_edgar_tiny.duckdb"

STMTS = ["BS", "CF", "IS", "EQ", "CI", "UN", "SI"]
RFILES = ["H", "H", "H", "H", "X"]
FORMS = ["10-K", "10-Q", "8-K", "20-F"]
UOMS = ["USD", "USD", "USD", "shares", "pure"]
TAGS = [
    ("Assets", "us-gaap/2023"),
    ("Revenues", "us-gaap/2023"),
    ("NetIncomeLoss", "us-gaap/2023"),
    ("EarningsPerShareBasic", "us-gaap/2023"),
    ("StockholdersEquity", "us-gaap/2023"),
]


def strip_fk(schema_sql: str) -> str:
    schema_clean = re.sub(r"--[^\n]*", "", schema_sql)
    schema_clean = re.sub(
        r",?\s*FOREIGN KEY\s*\([^)]+\)\s*REFERENCES\s+\w+\([^)]+\)",
        "",
        schema_clean,
    )
    schema_clean = re.sub(r"\s*REFERENCES\s+\w+\([^)]+\)", "", schema_clean)
    schema_clean = re.sub(r",\s*\)", "\n)", schema_clean)
    return schema_clean


def make_adsh(rng: random.Random, i: int) -> str:
    base = 10000000 + i
    return f"{base:010d}-23-000001"


def synth_sub(rng: random.Random, n_filings: int) -> list[tuple]:
    rows: list[tuple] = []
    for i in range(n_filings):
        adsh = make_adsh(rng, i)
        cik = 1000000 + (i % 400)
        name = f"Synthetic Registrant {cik}"
        sic = rng.choice([7372, 2834, 4512, 4813, 6021])
        form = rng.choice(FORMS)
        fy = rng.choice([2022, 2023, 2024])
        fp = rng.choice(["FY", "Q1", "Q2", "Q3", "Q4"])
        rows.append(
            (
                adsh,
                cik,
                name,
                sic,
                "US",
                "CA",
                "San Francisco",
                "USA",
                form,
                fy * 10000 + 1231,
                fy,
                fp,
                fy * 10000 + rng.randint(101, 331),
                f"{fy}-03-15 16:00:00",
                0,
                1,
                "1-LAF",
                1,
                "1231",
                f"{adsh}.xml",
            )
        )
    return rows


def synth_tag() -> list[tuple]:
    return [
        (tag, version, 0, 0, "monetary", "I", "D", tag.replace("Loss", " Loss"), f"Doc for {tag}")
        for tag, version in TAGS
    ]


def synth_pre(rng: random.Random, adsh_list: list[str], n_rows: int) -> list[tuple]:
    rows: list[tuple] = []
    seen: set[tuple[str, int, int]] = set()
    tag, version = rng.choice(TAGS)
    while len(rows) < n_rows:
        adsh = rng.choice(adsh_list)
        report = rng.randint(1, 4)
        line = rng.randint(1, 60)
        key = (adsh, report, line)
        if key in seen:
            continue
        seen.add(key)
        stmt = rng.choice(STMTS)
        rows.append(
            (
                adsh,
                report,
                line,
                stmt,
                rng.randint(0, 1),
                rng.choice(RFILES),
                tag,
                version,
                f"{stmt} line {line}",
                rng.randint(0, 1),
            )
        )
    return rows


def synth_num(rng: random.Random, adsh_list: list[str], n_rows: int) -> list[tuple]:
    rows: list[tuple] = []
    for _ in range(n_rows):
        adsh = rng.choice(adsh_list)
        tag, version = rng.choice(TAGS)
        uom = rng.choice(UOMS)
        fy = rng.randint(2022, 2024)
        value = round(rng.uniform(1.0, 1_000_000.0), 2)
        rows.append(
            (
                adsh,
                tag,
                version,
                fy * 10000 + rng.randint(101, 331),
                rng.choice([0, 1, 4]),
                uom,
                None,
                value,
                None,
            )
        )
    return rows


def load_table(con: duckdb.DuckDBPyConnection, table: str, rows: list[tuple], columns: list[str]) -> None:
    con.execute(f"DELETE FROM {table}")
    if not rows:
        return
    col_sql = ", ".join(columns)
    df = pd.DataFrame({col: [row[i] for row in rows] for i, col in enumerate(columns)})
    con.register("_synth_batch", df)
    con.execute(f"INSERT INTO {table} ({col_sql}) SELECT {col_sql} FROM _synth_batch")
    con.unregister("_synth_batch")


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize tiny SEC-EDGAR DuckDB")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--pre-rows", type=int, default=75_000)
    parser.add_argument("--num-rows", type=int, default=8_000)
    parser.add_argument("--filings", type=int, default=500)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    args.db_path.parent.mkdir(parents=True, exist_ok=True)
    if args.db_path.exists():
        if not args.force:
            con = duckdb.connect(str(args.db_path), read_only=True)
            pre_count = con.execute("SELECT COUNT(*) FROM pre").fetchone()[0]
            con.close()
            if pre_count > 0:
                print(f"Database already exists: {args.db_path} ({pre_count:,} pre rows)")
                print("Use --force to rebuild.")
                return
        args.db_path.unlink(missing_ok=True)

    sub_rows = synth_sub(rng, args.filings)
    adsh_list = [row[0] for row in sub_rows]
    pre_rows = synth_pre(rng, adsh_list, args.pre_rows)
    num_rows = synth_num(rng, adsh_list, args.num_rows)
    tag_rows = synth_tag()

    con = duckdb.connect(str(args.db_path))
    for stmt in strip_fk(SCHEMA_PATH.read_text()).split(";"):
        stmt = stmt.strip()
        if stmt.upper().startswith("CREATE"):
            con.execute(stmt)

    load_table(
        con,
        "sub",
        sub_rows,
        [
            "adsh",
            "cik",
            "name",
            "sic",
            "countryba",
            "stprba",
            "cityba",
            "countryinc",
            "form",
            "period",
            "fy",
            "fp",
            "filed",
            "accepted",
            "prevrpt",
            "nciks",
            "afs",
            "wksi",
            "fye",
            "instance",
        ],
    )
    load_table(
        con,
        "pre",
        pre_rows,
        [
            "adsh",
            "report",
            "line",
            "stmt",
            "inpth",
            "rfile",
            "tag",
            "version",
            "plabel",
            "negating",
        ],
    )
    load_table(
        con,
        "num",
        num_rows,
        ["adsh", "tag", "version", "ddate", "qtrs", "uom", "coreg", "value", "footnote"],
    )
    load_table(
        con,
        "tag",
        tag_rows,
        ["tag", "version", "custom", "abstract", "datatype", "iord", "crdr", "tlabel", "doc"],
    )

    print("=== sec_edgar_tiny.duckdb ===")
    for table in ["sub", "pre", "num", "tag"]:
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count:,} rows")
    size_mb = args.db_path.stat().st_size / (1024 * 1024)
    print(f"  path: {args.db_path}")
    print(f"  size: {size_mb:.2f} MB")
    print(f"  seed: {args.seed}")
    con.close()


if __name__ == "__main__":
    try:
        main()
    except ImportError:
        print("duckdb not installed; run: uv sync --group dev", file=sys.stderr)
        raise
