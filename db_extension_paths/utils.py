"""Shared helpers for Verus DuckDB experiments (no agent cache / optimizer)."""
from __future__ import annotations

from db_extension.utils import (
    escape_sql_string_literal,
    is_integer_result_type,
    lemma_select_line,
    load_csv_table,
    print_result_table,
    quote_sql_identifier,
    setup_workload,
    sql_result_schema,
)
from db_extension.dataset_config import effective_dataset_size, tbl_path

__all__ = [
    "effective_dataset_size",
    "escape_sql_string_literal",
    "is_integer_result_type",
    "lemma_select_line",
    "load_csv_table",
    "print_result_table",
    "quote_sql_identifier",
    "setup_ssb_flat",
    "setup_workload",
    "sql_result_schema",
    "tbl_path",
]


def setup_ssb_flat(con, *, quiet: bool = False) -> None:
    flat_path = tbl_path()
    row_limit = effective_dataset_size()

    if not flat_path.exists():
        raise FileNotFoundError(
            f"Real SSB flat table not found at {flat_path}.\n"
            "Run: ./scripts/build_ssb_flat_dataset.sh"
        )

    load_csv_table(con, "lineorder_flat", flat_path, quiet=quiet, row_limit=row_limit)
