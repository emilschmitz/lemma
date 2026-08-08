"""Workload resolution for Lemma ONE product path (SSB / holdout / TPC-H / SEC)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import duckdb

from db_extension.dataset_config import effective_dataset_size, tbl_path
from db_extension.verus_bridge import extract_tables_from_sql, looks_like_ssb_sql

ROOT = Path(__file__).resolve().parents[1]
TPCH_DATA_DIR = ROOT / "data" / "tpch-sf1"
DEFAULT_EXPERIMENT_DB_DIR = ROOT / "build" / "duckdb_experiment_session"

# Holdout benchmark tables (name → tbl filename).
_HOLDOUT_TABLE_FILES: dict[str, str] = {
    "scan_skew": "scan_skew.tbl",
    "scan_skew_1m": "scan_skew_1m.tbl",
    "zipf_left": "zipf_left.tbl",
    "zipf_right": "zipf_right.tbl",
    "str_filter": "str_filter.tbl",
    "lineitem_slice": "lineitem_slice.tbl",
    "orders_slice": "orders_slice.tbl",
    "lineitem_1m": "lineitem_1m.tbl",
    "orders_1m": "orders_1m.tbl",
    "ssb_flat_500k": "ssb_flat_500k.tbl",
}

_TPCH_TABLE_FILES: dict[str, str] = {
    "lineitem": "lineitem.tbl",
    "orders": "orders.tbl",
    "customer": "customer.tbl",
    "nation": "nation.tbl",
    "region": "region.tbl",
    "supplier": "supplier.tbl",
    "partsupp": "partsupp.tbl",
    "part": "part.tbl",
}

_VALID_WORKLOADS = frozenset({"ssb", "holdout", "tpch", "sec", "auto"})


@dataclass(frozen=True)
class WorkloadSpec:
    name: str
    db_path: str
    tables: dict[str, Path]
    schema: dict
    primary_table: str


def holdout_data_dir() -> Path:
    raw = os.environ.get("LEMMA_HOLDOUT_DATA", "").strip()
    if raw:
        return Path(raw)
    return ROOT / "research_loop" / "holdout" / "data"


def workload_env_name() -> str:
    raw = (
        os.environ.get("LEMMA_WORKLOAD", "").strip()
        or os.environ.get("LEMMA_EXPERIMENT_WORKLOAD", "").strip()
        or "auto"
    )
    return raw.lower() if raw else "auto"


def session_db_path(db_path: str | None = None) -> str:
    """Filesystem DuckDB path for persistent experiment sessions."""
    raw = db_path if db_path is not None else os.environ.get("LEMMA_DUCKDB_PATH", "").strip()
    if raw and raw not in (":memory:", ""):
        return raw
    out = DEFAULT_EXPERIMENT_DB_DIR / "session.duckdb"
    out.parent.mkdir(parents=True, exist_ok=True)
    return str(out)


def holdout_table_path(table: str) -> Path | None:
    return _holdout_tbl_path(table)


def infer_workload_from_tables(tables: list[str]) -> str:
    lowered = [t.lower() for t in tables]
    if any(t in _HOLDOUT_TABLE_FILES for t in lowered):
        return "holdout"
    if any(t == "lineorder_flat" for t in lowered):
        return "ssb"
    if any(t in _TPCH_TABLE_FILES for t in lowered):
        return "tpch"
    duck = os.environ.get("LEMMA_DUCKDB_PATH", "").strip()
    if duck and duck not in (":memory:", "") and Path(duck).is_file():
        return "sec"
    return "ssb"


def _duckdb_describe_schema(con: duckdb.DuckDBPyConnection, table: str) -> dict[str, str]:
    rows = con.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE lower(table_name) = lower(?)
        ORDER BY ordinal_position
        """,
        [table],
    ).fetchall()
    return {col.upper(): dtype.upper() for col, dtype in rows}


def schema_from_tbl(path: Path, table: str) -> dict[str, str]:
    """Infer column types from a pipe-delimited .tbl without loading the full file."""
    con = duckdb.connect()
    try:
        con.execute(
            f"CREATE TABLE {table} AS SELECT * FROM read_csv("
            f"'{path}', delim='|', header=true, quote='\"') LIMIT 0"
        )
        return _duckdb_describe_schema(con, table)
    finally:
        con.close()


def _schema_for_tables(
    tables: dict[str, Path],
    *,
    db_path: str | None = None,
    sql_tables: list[str] | None = None,
) -> dict:
    """Build flat or nested schema dict from tbl paths and/or an open DuckDB file."""
    if db_path and Path(db_path).is_file() and sql_tables:
        con = duckdb.connect(db_path, read_only=True)
        try:
            db_tables = {r[0].lower() for r in con.execute("SHOW TABLES").fetchall()}
            if all(t.lower() in db_tables for t in sql_tables):
                if len(sql_tables) == 1:
                    return _duckdb_describe_schema(con, sql_tables[0])
                return {
                    t: _duckdb_describe_schema(con, t)
                    for t in sql_tables
                }
        finally:
            con.close()

    if len(tables) == 1:
        name, path = next(iter(tables.items()))
        if path.is_file():
            return schema_from_tbl(path, name)

    if not tables:
        return {}

    multi: dict[str, dict[str, str]] = {}
    for name, path in tables.items():
        if path.is_file():
            multi[name] = schema_from_tbl(path, name)
    if len(multi) == 1:
        return next(iter(multi.values()))
    return multi


def _holdout_tbl_path(table: str) -> Path | None:
    fname = _HOLDOUT_TABLE_FILES.get(table.lower())
    if not fname:
        return None
    return holdout_data_dir() / fname


def _tpch_tbl_path(table: str) -> Path | None:
    fname = _TPCH_TABLE_FILES.get(table.lower())
    if not fname:
        return None
    p = TPCH_DATA_DIR / fname
    return p if p.is_file() else None


def _build_ssb_spec(sql_tables: list[str]) -> WorkloadSpec:
    flat = tbl_path()
    primary = "lineorder_flat"
    tables = {primary: flat}
    schema = _schema_for_tables(tables, sql_tables=[primary])
    if not schema and flat.is_file():
        from research_loop.ssb_workload import schema as ssb_schema, fallback_dtypes

        schema = {
            col: (fallback_dtypes.get(col, "INTEGER") if t == "int" else "VARCHAR")
            for col, t in ssb_schema.items()
        }
    return WorkloadSpec(
        name="ssb",
        db_path=session_db_path(),
        tables=tables,
        schema=schema,
        primary_table=primary,
    )


def _build_holdout_spec(sql_tables: list[str]) -> WorkloadSpec:
    tables: dict[str, Path] = {}
    for t in sql_tables:
        p = _holdout_tbl_path(t)
        if p is not None:
            tables[t] = p
    if not tables and sql_tables:
        for t in sql_tables:
            p = _holdout_tbl_path(t)
            if p is not None:
                tables[t] = p
    if not tables:
        # Default primary for holdout smoke queries
        p = _holdout_tbl_path("scan_skew")
        if p is not None:
            tables["scan_skew"] = p
    primary = sql_tables[0] if sql_tables else (next(iter(tables)) if tables else "scan_skew")
    if primary not in tables and tables:
        primary = next(iter(tables))
    schema = _schema_for_tables(tables, sql_tables=sql_tables or list(tables))
    return WorkloadSpec(
        name="holdout",
        db_path=session_db_path(),
        tables=tables,
        schema=schema,
        primary_table=primary,
    )


def _build_tpch_spec(sql_tables: list[str]) -> WorkloadSpec:
    tables: dict[str, Path] = {}
    for t in sql_tables:
        p = _tpch_tbl_path(t)
        if p is not None:
            tables[t] = p
    primary = sql_tables[0] if sql_tables else "lineitem"
    if primary not in tables:
        p = _tpch_tbl_path(primary)
        if p is not None:
            tables[primary] = p
    schema = _schema_for_tables(tables, sql_tables=sql_tables or list(tables))
    if not schema and len(sql_tables) == 1 and sql_tables[0].lower() == "lineitem":
        from research_loop.bench_standins.tpch_runqueries import lineitem_schema

        schema = dict(lineitem_schema)
    return WorkloadSpec(
        name="tpch",
        db_path=session_db_path(),
        tables=tables,
        schema=schema,
        primary_table=primary,
    )


def _build_sec_spec(sql_tables: list[str]) -> WorkloadSpec:
    db = session_db_path()
    if not Path(db).is_file():
        raise FileNotFoundError(
            f"SEC workload requires an existing DuckDB at LEMMA_DUCKDB_PATH ({db})"
        )
    primary = sql_tables[0] if sql_tables else ""
    schema = _schema_for_tables({}, db_path=db, sql_tables=sql_tables)
    return WorkloadSpec(
        name="sec",
        db_path=db,
        tables={},
        schema=schema,
        primary_table=primary,
    )


def _validate_spec_files(spec: WorkloadSpec) -> None:
    """Fail loud when tbl-backed workloads reference missing files."""
    missing = [f"{name}: {path}" for name, path in spec.tables.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"Workload {spec.name!r} missing required table files:\n  "
            + "\n  ".join(missing)
        )
    if spec.name == "sec" and not Path(spec.db_path).is_file():
        raise FileNotFoundError(f"SEC DuckDB not found at {spec.db_path}")


def resolve_workload(sql: str, *, workload: str | None = None) -> WorkloadSpec:
    """Resolve tables, schema, and DuckDB session path for SQL."""
    from research_loop.lemma_flags import lemma_experiment

    name = (workload or workload_env_name()).lower()
    if name not in _VALID_WORKLOADS:
        raise ValueError(f"Unknown workload {name!r}; expected one of {sorted(_VALID_WORKLOADS)}")

    sql_tables = extract_tables_from_sql(sql)
    if name == "auto":
        if sql_tables:
            name = infer_workload_from_tables(sql_tables)
        elif looks_like_ssb_sql(sql):
            name = "ssb"
        else:
            name = "ssb"

    if name == "ssb":
        spec = _build_ssb_spec(sql_tables or ["lineorder_flat"])
    elif name == "holdout":
        spec = _build_holdout_spec(sql_tables)
    elif name == "tpch":
        spec = _build_tpch_spec(sql_tables or ["lineitem"])
    elif name == "sec":
        spec = _build_sec_spec(sql_tables)
    else:
        raise ValueError(f"Unhandled workload {name!r}")

    if lemma_experiment() or os.environ.get("LEMMA_EXPERIMENT", "0") == "1":
        _validate_spec_files(spec)
        if not spec.schema:
            raise ValueError(
                f"Workload {spec.name!r}: could not resolve schema for tables {sql_tables!r}"
            )
        primary_tbl = spec.tables.get(spec.primary_table)
        if spec.name != "sec" and primary_tbl is not None and not primary_tbl.is_file():
            raise FileNotFoundError(f"Primary bench tbl missing: {primary_tbl}")

    return spec


def primary_bench_tbl(spec: WorkloadSpec) -> str:
    """Best tbl path for harness benchmark (primary table)."""
    env = os.environ.get("LEMMA_BENCH_TBL", "").strip()
    if env:
        return env
    path = spec.tables.get(spec.primary_table)
    return str(path) if path is not None else ""
