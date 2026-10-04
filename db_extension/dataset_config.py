"""SSB flat dataset paths and row limits (real ssb-dbgen data, not synthetic)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from research_loop.experiment_stream import (
    duckdb_error_is_contention,
    emit_duckdb_contention,
)

ROOT = Path(__file__).resolve().parents[1]
SSB_DIR = ROOT / "ssb-dbgen"
DEFAULT_TBL = SSB_DIR / "lineorder_flat.tbl"
META_PATH = SSB_DIR / "dataset_meta.json"

# SSB lineorder ≈ scale × 1.5M rows → 1.333 ≈ 2M fact rows.
DEFAULT_SSB_SCALE = 1.333
DEFAULT_MCP_ITERATE_ROWS = 50_000

_NO_DATASET_SIZE_MSG = (
    "Cannot determine dataset row count: set LEMMA_DATASET_SIZE or provide "
    "a readable bench table (LEMMA_BENCH_TBL) or SSB flat tbl."
)


def ssb_dir() -> Path:
    raw = os.environ.get("LEMMA_SSB_DIR", "").strip()
    return Path(raw) if raw else SSB_DIR


def tbl_path() -> Path:
    raw = os.environ.get("LEMMA_SSB_FLAT_TBL", "").strip()
    if raw:
        return Path(raw)
    return ssb_dir() / "lineorder_flat.tbl"


def ssb_scale() -> float:
    raw = os.environ.get("LEMMA_SSB_SCALE", "").strip()
    if not raw:
        return DEFAULT_SSB_SCALE
    return float(raw)


def dataset_size_limit() -> int | None:
    raw = os.environ.get("LEMMA_DATASET_SIZE", "").strip()
    if not raw:
        return None
    return max(1, int(raw))


def _count_tbl_rows(path: Path) -> int:
    with open(path, "rb") as f:
        lines = 0
        for chunk in iter(lambda: f.read(1 << 20), b""):
            lines += chunk.count(b"\n")
    return max(0, lines - 1)


def file_row_count() -> int | None:
    meta = ssb_dir() / "dataset_meta.json"
    if meta.is_file():
        try:
            data = json.loads(meta.read_text())
            n = data.get("row_count")
            if n is not None:
                return int(n)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    path = tbl_path()
    if not path.is_file():
        return None
    return _count_tbl_rows(path)


def _safe_duckdb_table_name(table: str) -> bool:
    return bool(table) and table.replace("_", "").isalnum()


def _quote_duckdb_ident(name: str) -> str:
    """Quote a DuckDB identifier, doubling embedded quotes."""
    return '"' + name.replace('"', '""') + '"'


def _count_duckdb_primary_rows() -> int | None:
    """Row count from LEMMA_DUCKDB_PATH primary table (SEC / DuckDB workloads)."""
    db = os.environ.get("LEMMA_DUCKDB_PATH", "").strip()
    if not db or not Path(db).is_file():
        return None
    table = (os.environ.get("LEMMA_PRIMARY_TABLE") or "").strip()
    if not table:
        table = (os.environ.get("LEMMA_BENCH_TABLE") or "").strip()
    if not table:
        return None
    if not _safe_duckdb_table_name(table):
        return None
    try:
        import duckdb
    except ImportError:
        return None
    try:
        con = duckdb.connect(db, read_only=True)
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            return int(n)
        finally:
            con.close()
    except Exception as exc:
        if duckdb_error_is_contention(str(exc)):
            emit_duckdb_contention(stage="count_primary_rows", error=str(exc), db_path=db)
            raise
        return None


_U64_MAX_EXCLUSIVE = 2**64

_INTEGER_DUCKDB_TYPES = frozenset(
    {
        "integer",
        "int",
        "int4",
        "int32",
        "smallint",
        "int2",
        "int16",
        "bigint",
        "int64",
        "int8",
        "hugeint",
        "tinyint",
        "int1",
        "utinyint",
        "uint8",
        "usmallint",
        "uint16",
        "uinteger",
        "uint32",
        "ubigint",
        "uint64",
    }
)

_FLOAT_DUCKDB_TYPES = frozenset({"double", "float8", "float", "real"})


# Candidate keys from the SEC filing layout. A key is recorded only when a
# GROUP BY on the real table has max count 1. Repeated keys are omitted.
_UNIQUE_KEY_CANDIDATES: tuple[tuple[str, ...], ...] = (
    ("adsh",),
    ("tag", "version"),
)


def connect_measured_duckdb(stage: str) -> Any:
    """Read-only connection to ``LEMMA_DUCKDB_PATH``. Raises when it is unusable."""
    import duckdb

    db = os.environ.get("LEMMA_DUCKDB_PATH", "").strip()
    if not db:
        raise RuntimeError(
            "LEMMA_DUCKDB_PATH is not set: the measured catalog needs the SEC DuckDB."
        )
    if not Path(db).is_file():
        raise FileNotFoundError(f"LEMMA_DUCKDB_PATH {db!r} is not a file.")
    try:
        return duckdb.connect(db, read_only=True)
    except Exception as exc:
        if duckdb_error_is_contention(str(exc)):
            emit_duckdb_contention(stage=stage, error=str(exc), db_path=db)
        raise


def _main_columns(con: Any) -> list[tuple[str, str, str]]:
    """(table, column, lowercase base type) for every column in schema ``main``."""
    rows = con.execute(
        "SELECT table_name, column_name, data_type "
        "FROM information_schema.columns WHERE table_schema = 'main'"
    ).fetchall()
    return [
        (str(t), str(c), str(d).lower().split("(")[0])
        for t, c, d in rows
        if _safe_duckdb_table_name(str(t))
    ]


def table_unique_keys() -> dict[str, tuple[tuple[str, ...], ...]]:
    """Unique column groups measured from ``LEMMA_DUCKDB_PATH``.

    A candidate is stored only when every column exists and no group has more
    than one row. Raises when the database is missing or a query fails.
    """
    con = connect_measured_duckdb("unique_keys")
    try:
        cols_by_table: dict[str, set[str]] = {}
        for table, column, _ in _main_columns(con):
            cols_by_table.setdefault(table, set()).add(column)
        found: dict[str, tuple[tuple[str, ...], ...]] = {}
        for table_name, columns in cols_by_table.items():
            unique: list[tuple[str, ...]] = []
            for key in _UNIQUE_KEY_CANDIDATES:
                if not set(key).issubset(columns):
                    continue
                group = ", ".join(_quote_duckdb_ident(col) for col in key)
                max_count = con.execute(
                    f"SELECT MAX(c) FROM (SELECT COUNT(*) AS c "
                    f"FROM {_quote_duckdb_ident(table_name)} GROUP BY {group})"
                ).fetchone()[0]
                if max_count is not None and int(max_count) == 1:
                    unique.append(key)
            if unique:
                found[table_name] = tuple(unique)
        return found
    finally:
        con.close()


def tables_one_row_per_adsh() -> set[str]:
    """Tables whose ``adsh`` column has at most one row per value."""
    return {
        name for name, groups in table_unique_keys().items() if ("adsh",) in groups
    }


def table_column_abs_sum_caps() -> dict[str, dict[str, int]]:
    """Exclusive bound on ``sum(abs(col))``: ``sum(ceil(abs))+1`` when it fits in u64.

    A column is omitted when the sum overflows u64, a cell is NaN/inf, or the column
    is all NULL.
    Raises when the database is missing or a query fails.
    """
    con = connect_measured_duckdb("column_abs_sum_caps")
    try:
        caps: dict[str, dict[str, int]] = {}
        for table_name, column_name, base in _main_columns(con):
            if base not in _INTEGER_DUCKDB_TYPES | _FLOAT_DUCKDB_TYPES:
                continue
            col = _quote_duckdb_ident(column_name)
            total = con.execute(
                f"SELECT CASE "
                f"WHEN COUNT(*) FILTER ("
                f"WHERE {col} IS NOT NULL "
                f"AND (NOT isfinite({col}) OR ABS({col}) >= {_U64_MAX_EXCLUSIVE})"
                f") > 0 THEN NULL "
                f"ELSE SUM(CASE WHEN isfinite({col}) "
                f"AND ABS({col}) < {_U64_MAX_EXCLUSIVE} "
                f"THEN CAST(CEIL(ABS({col})) AS HUGEINT) END) "
                f"END FROM {_quote_duckdb_ident(table_name)}"
            ).fetchone()[0]
            if total is None:
                continue
            # Exclusive bound must itself fit in a u64 const (strictly below 2^64).
            exclusive = int(total) + 1
            if exclusive >= _U64_MAX_EXCLUSIVE:
                continue
            caps.setdefault(table_name, {})[column_name] = exclusive
        return caps
    finally:
        con.close()


def table_column_value_caps() -> dict[str, dict[str, int]]:
    """Per-table per-column exclusive upper bounds from ``LEMMA_DUCKDB_PATH``.

    INTEGER/BIGINT: ``max(abs(col)) + 1``. DOUBLE: same only when the column max is
    integral, finite, and fits in ``u64``. Other columns are omitted. Raises when the
    database is missing or a query fails.
    """
    con = connect_measured_duckdb("column_value_caps")
    try:
        caps: dict[str, dict[str, int]] = {}
        for table_name, column_name, base in _main_columns(con):
            if base not in _INTEGER_DUCKDB_TYPES | _FLOAT_DUCKDB_TYPES:
                continue
            col = _quote_duckdb_ident(column_name)
            table = _quote_duckdb_ident(table_name)
            if base in _FLOAT_DUCKDB_TYPES:
                # Stay in HUGEINT. float64 cannot represent integers above 2^53,
                # so a Python float round-trip can publish a cap below the real max.
                exact = con.execute(
                    f"SELECT CASE "
                    f"WHEN MAX(ABS({col})) IS NULL THEN NULL "
                    f"WHEN NOT isfinite(MAX(ABS({col}))) THEN NULL "
                    f"WHEN MAX(ABS({col})) <> TRUNC(MAX(ABS({col}))) THEN NULL "
                    f"WHEN MAX(ABS({col})) >= {_U64_MAX_EXCLUSIVE} THEN NULL "
                    f"ELSE CAST(TRUNC(MAX(ABS({col}))) AS HUGEINT) "
                    f"END FROM {table}"
                ).fetchone()[0]
            else:
                exact = con.execute(f"SELECT MAX(ABS({col})) FROM {table}").fetchone()[0]
            if exact is None:
                continue
            exclusive = int(exact) + 1
            # A u64 const cannot name 2^64. Skip the column.
            if exclusive >= _U64_MAX_EXCLUSIVE:
                continue
            caps.setdefault(table_name, {})[column_name] = exclusive
        return caps
    finally:
        con.close()


def table_row_counts() -> dict[str, int]:
    """Per-table ``COUNT(*)`` from ``LEMMA_DUCKDB_PATH``. Raises when unavailable."""
    con = connect_measured_duckdb("count_table_rows")
    try:
        names = [
            str(t)
            for (t,) in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
            ).fetchall()
            if _safe_duckdb_table_name(str(t))
        ]
        return {
            name: int(
                con.execute(
                    f"SELECT COUNT(*) FROM {_quote_duckdb_ident(name)}"
                ).fetchone()[0]
            )
            for name in names
        }
    finally:
        con.close()


def _count_duckdb_max_table_rows() -> int | None:
    """Max row count across user tables in LEMMA_DUCKDB_PATH (official pin limit)."""
    if not os.environ.get("LEMMA_DUCKDB_PATH", "").strip():
        return None
    return max(table_row_counts().values())


def effective_dataset_size() -> int:
    """Rows to load/run against: env limit if set, else all available rows."""
    limit = dataset_size_limit()
    bench = os.environ.get("LEMMA_BENCH_TBL", "").strip()
    if bench:
        p = Path(bench)
        if p.is_file():
            available = _count_tbl_rows(p)
            if limit is not None:
                return min(limit, available)
            return available

    # DuckDB before SSB meta: leftover ssb-dbgen/dataset_meta.json must not
    # pin a 6M row count onto a tiny SEC experiment. Official measure pins every
    # table with the same LIMIT, so use max table count (not primary only).
    available = _count_duckdb_max_table_rows()
    if available is None:
        available = _count_duckdb_primary_rows()
    if available is None:
        available = file_row_count()

    if limit is not None:
        if available is None:
            return limit
        return min(limit, available)

    if available is None:
        raise RuntimeError(_NO_DATASET_SIZE_MSG)
    return available


_MCP_ITERATE_UNCAPPED_VALUES = frozenset({"0", "full", "unlimited"})


def mcp_iterate_is_uncapped() -> bool:
    """True when ``LEMMA_MCP_ITERATE_ROWS`` is ``0``, ``full``, or ``unlimited`` (case-insensitive)."""
    raw = os.environ.get("LEMMA_MCP_ITERATE_ROWS", "").strip()
    return raw.lower() in _MCP_ITERATE_UNCAPPED_VALUES if raw else False


def mcp_iterate_rows_cap() -> int:
    """Row cap for MCP ``run_runquery`` when ``dataset_size`` is omitted (capped mode only)."""
    if mcp_iterate_is_uncapped():
        raise RuntimeError(
            "mcp_iterate_rows_cap() is undefined when LEMMA_MCP_ITERATE_ROWS is uncapped "
            "(0/full/unlimited); use mcp_iterate_is_uncapped() and mcp_iterate_dataset_size()."
        )
    raw = os.environ.get("LEMMA_MCP_ITERATE_ROWS", "").strip()
    if not raw:
        return DEFAULT_MCP_ITERATE_ROWS
    return max(1, int(raw))


def mcp_iterate_dataset_size() -> int:
    """MCP iterate rows: official pin when uncapped, else min(official, cap)."""
    official = effective_dataset_size()
    if mcp_iterate_is_uncapped():
        return official
    return min(official, mcp_iterate_rows_cap())


def _resolve_row_budget_sizes() -> tuple[int | None, int]:
    """Return (official pin rows or None, MCP iterate rows when dataset_size omitted)."""
    uncapped = mcp_iterate_is_uncapped()
    try:
        official = effective_dataset_size()
        iterate_max = official if uncapped else min(official, mcp_iterate_rows_cap())
        return official, iterate_max
    except RuntimeError:
        limit = dataset_size_limit()
        if limit is not None:
            official = limit
            iterate_max = official if uncapped else min(official, mcp_iterate_rows_cap())
            return official, iterate_max
        iterate_max = 0 if uncapped else mcp_iterate_rows_cap()
        return None, iterate_max


def run_runquery_iterate_tool_blurb(
    *,
    iterate_rows: int | None = None,
    official_rows: int | None = None,
) -> str:
    """Shared omit-``dataset_size`` wording for MCP tool descriptions."""
    if iterate_rows is None:
        try:
            iterate_rows = mcp_iterate_dataset_size()
        except RuntimeError:
            iterate_rows = (
                mcp_iterate_rows_cap() if not mcp_iterate_is_uncapped() else 0
            )
    if official_rows is None:
        try:
            official_rows = effective_dataset_size()
        except RuntimeError:
            official_rows = None

    if official_rows is not None and iterate_rows == official_rows:
        return (
            f"Omit dataset_size for the official pin ({iterate_rows} rows — same as submit "
            f"scoring; see Row budgets). Pass an explicit smaller dataset_size for quick probes."
        )
    return (
        f"Omit dataset_size for MCP iterate max ({iterate_rows} rows; not official pin — "
        f"see Row budgets). Pass an explicit smaller dataset_size for quick probes."
    )


def row_budget_prompt_section() -> str:
    """Markdown section with official pin X, MCP iterate max Y, and optional table counts."""
    official, iterate_max = _resolve_row_budget_sizes()
    iterate_matches_official = official is not None and iterate_max == official

    if official is not None:
        cap_note = (
            ""
            if iterate_matches_official
            else f" Optimize for **{official}**, not for the iterate cap."
        )
        official_bullet = (
            f"- **Official pin (submit is scored on this):** each table "
            f"`SELECT … LIMIT {official}`. Your `run_query` must finish on that pin.{cap_note}"
        )
        nested_note = (
            "At this pin, nested rem_join visits ~n0×n1 cells and can miss the 600s wall."
            if iterate_matches_official
            else (
                f"Fast at {iterate_max}×{iterate_max} can miss the 600s official wall at the pin."
            )
        )
    else:
        official_bullet = (
            "- **Official pin (submit is scored on this):** unknown — set "
            "`LEMMA_DATASET_SIZE` or provide a readable bench table / DuckDB file. "
            "The host loads **every table** with `SELECT … LIMIT X` where X is the max "
            "table row count (capped by env)."
        )
        nested_note = (
            f"Fast at {iterate_max}×{iterate_max} can miss the official wall at the pin."
        )

    if iterate_matches_official:
        iterate_bullet = (
            f"- **MCP iterate max:** omit `dataset_size` on `run_runquery` → "
            f"**{iterate_max}** rows (same pin submit is scored on). "
            f"Smaller `dataset_size` = probes only."
        )
    else:
        iterate_bullet = (
            f"- **MCP iterate max:** omit `dataset_size` on `run_runquery` → "
            f"**{iterate_max}** rows (the maximum you can time while iterating). "
            f"Smaller `dataset_size` = probes only. Iterate time at {iterate_max} is not official."
        )

    lines = [
        "## Row budgets (this run, host)",
        official_bullet,
        iterate_bullet,
        (
            f"- Nested-loop joins (`rem_join_*` / "
            f"`while i0 < n0 {{ while i1 < n1 }}`) visit ~n0×n1 cells. {nested_note}"
        ),
    ]

    counts = table_row_counts() if os.environ.get("LEMMA_DUCKDB_PATH", "").strip() else None
    if counts:
        table_bits = ", ".join(f"{name}={n}" for name, n in sorted(counts.items()))
        lines.append(f"- **Table row counts (DuckDB):** {table_bits}")

    return "\n".join(lines)
