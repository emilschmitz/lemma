"""Shared helpers for Verus DuckDB experiments (no agent cache / optimizer)."""
from __future__ import annotations

import os
import re

import duckdb
import pandas as pd

from verus.db_extension.dataset_config import effective_dataset_size, tbl_path

COLOR_GREEN = "\033[92m"
COLOR_RESET = "\033[0m"


def print_result_table(df: pd.DataFrame) -> None:
    if df.empty:
        print("Empty result (0 rows)")
        return
    print(df.to_string(index=False))


def sql_result_schema(con: duckdb.DuckDBPyConnection, sql: str) -> tuple[list[str], list[str]]:
    cur = con.execute(sql)
    desc = cur.description or []
    names = [d[0] for d in desc]
    types = [str(d[1]) if len(d) > 1 else "" for d in desc]
    return names, types


def is_integer_result_type(type_str: str) -> bool:
    t = type_str.upper()
    return any(k in t for k in ("INT", "HUGEINT", "BIGINT", "SMALLINT", "TINYINT", "UBIGINT"))


def quote_sql_identifier(name: str) -> str:
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return name
    return '"' + name.replace('"', '""') + '"'


def escape_sql_string_literal(sql: str) -> str:
    return sql.replace("'", "''")


def lemma_select_line(con: duckdb.DuckDBPyConnection, sql: str) -> str:
    names, types = sql_result_schema(con, sql)
    alias = quote_sql_identifier(names[0] if len(names) == 1 else "result")
    inner = escape_sql_string_literal(sql.strip())
    call = f"lemma('{inner}')"
    if len(names) == 1 and is_integer_result_type(types[0]):
        return f"SELECT CAST({call} AS HUGEINT) AS {alias}"
    return f"SELECT {call} AS {alias}"


def setup_ssb_flat(con: duckdb.DuckDBPyConnection, *, quiet: bool = False) -> None:
    flat_path = tbl_path()
    row_limit = effective_dataset_size()

    if not flat_path.exists():
        raise FileNotFoundError(
            f"Real SSB flat table not found at {flat_path}.\n"
            "Run: ./scripts/build_ssb_flat_dataset.sh"
        )

    if quiet:
        con.execute("SET enable_progress_bar = false")

    if not quiet:
        print(f"Loading table 'lineorder_flat' from {flat_path} ({row_limit:,} rows)...")
    con.execute(
        f"CREATE OR REPLACE TABLE lineorder_flat AS "
        f"SELECT * FROM read_csv('{flat_path}', delim='|', header=True) LIMIT {row_limit}"
    )
    if not quiet:
        print(f"{COLOR_GREEN}Loaded {row_limit:,} rows into 'lineorder_flat'.{COLOR_RESET}")


def load_csv_table(
    con: duckdb.DuckDBPyConnection,
    table: str,
    path: os.PathLike[str] | str,
    *,
    quiet: bool = False,
) -> int:
    path = os.fspath(path)
    if not quiet:
        print(f"Loading '{table}' from {path}...")
    con.execute(
        f"CREATE OR REPLACE TABLE {quote_sql_identifier(table)} AS "
        f"SELECT * FROM read_csv('{path}', delim='|', header=true, quote='\"')"
    )
    n = con.execute(f"SELECT COUNT(*) FROM {quote_sql_identifier(table)}").fetchone()[0]
    if not quiet:
        print(f"{COLOR_GREEN}Loaded {n:,} rows into '{table}'.{COLOR_RESET}")
    return int(n)
