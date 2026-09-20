"""SSB flat dataset paths and row limits (real ssb-dbgen data, not synthetic)."""
from __future__ import annotations

import json
import os
from pathlib import Path

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


def table_row_counts() -> dict[str, int] | None:
    """Per-table ``COUNT(*)`` from ``LEMMA_DUCKDB_PATH``, or None if unavailable."""
    db = os.environ.get("LEMMA_DUCKDB_PATH", "").strip()
    if not db or not Path(db).is_file():
        return None
    try:
        import duckdb
    except ImportError:
        return None
    try:
        con = duckdb.connect(db, read_only=True)
        try:
            rows = con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
            ).fetchall()
            counts: dict[str, int] = {}
            for (table,) in rows:
                name = str(table)
                if not _safe_duckdb_table_name(name):
                    continue
                n = int(con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                counts[name] = n
            return counts or None
        finally:
            con.close()
    except Exception as exc:
        if duckdb_error_is_contention(str(exc)):
            emit_duckdb_contention(stage="count_table_rows", error=str(exc), db_path=db)
            raise
        return None


def _count_duckdb_max_table_rows() -> int | None:
    """Max row count across user tables in LEMMA_DUCKDB_PATH (official pin limit)."""
    counts = table_row_counts()
    if not counts:
        return None
    return max(counts.values())


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


def mcp_iterate_rows_cap() -> int:
    """Row cap for MCP ``run_runquery`` when ``dataset_size`` is omitted (not official latency)."""
    raw = os.environ.get("LEMMA_MCP_ITERATE_ROWS", "").strip()
    if not raw:
        return DEFAULT_MCP_ITERATE_ROWS
    return max(1, int(raw))


def mcp_iterate_dataset_size() -> int:
    """MCP iterate rows: min(full effective size, ``LEMMA_MCP_ITERATE_ROWS`` cap)."""
    return min(effective_dataset_size(), mcp_iterate_rows_cap())


def row_budget_prompt_section() -> str:
    """Markdown section with official pin X, MCP iterate max Y, and optional table counts."""
    iterate_cap = mcp_iterate_rows_cap()
    official: int | None
    iterate_max: int
    try:
        official = effective_dataset_size()
        iterate_max = min(official, iterate_cap)
    except RuntimeError:
        limit = dataset_size_limit()
        if limit is not None:
            official = limit
            iterate_max = min(official, iterate_cap)
        else:
            official = None
            iterate_max = iterate_cap

    if official is not None:
        official_bullet = (
            f"- **Official pin (submit is scored on this):** each table "
            f"`SELECT … LIMIT {official}`. Your `run_query` must finish on that pin. "
            f"Optimize for **{official}**, not for the iterate cap."
        )
        nested_note = (
            f"Fast at {iterate_max}×{iterate_max} can miss the 600s official wall at the pin."
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

    lines = [
        "## Row budgets (this run, host)",
        official_bullet,
        (
            f"- **MCP iterate max:** omit `dataset_size` on `run_runquery` → "
            f"**{iterate_max}** rows (the maximum you can time while iterating). "
            f"Smaller `dataset_size` = probes only. Iterate time at {iterate_max} is not official."
        ),
        (
            f"- Nested-loop joins (`rem_join_*` / "
            f"`while i0 < n0 {{ while i1 < n1 }}`) visit ~n0×n1 cells. {nested_note}"
        ),
    ]

    counts = table_row_counts()
    if counts:
        table_bits = ", ".join(f"{name}={n}" for name, n in sorted(counts.items()))
        lines.append(f"- **Table row counts (DuckDB):** {table_bits}")

    return "\n".join(lines)
