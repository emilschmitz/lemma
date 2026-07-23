"""DuckDB-hosted buffers for Lemma experiments.

Default path (`LEMMA_LOAD_FROM_DUCKDB=1`): **pin/lease** so **Lemma** can execute on
DuckDB `SELECT` result vector memory (zero-copy; see `duckdb_pin.rs`). DuckDB is the
memory host, not the query engine for that timed path.

Legacy copy export (numpy → `.lemma_cols` sidecars) is opt-in via
`LEMMA_DUCKDB_SIDECAR_EXPORT=1`.
"""
from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

MAGIC = b"LEMMA1\0\0"
HEADER_SIZE = 32

# dtype byte in file header
DTYPE_U32 = 0
DTYPE_U64 = 1
DTYPE_I64 = 2
DTYPE_F64 = 3
DTYPE_BOOL = 4
DTYPE_STR = 5

_DTYPE_TO_BYTE = {
    "u32": DTYPE_U32,
    "u64": DTYPE_U64,
    "i64": DTYPE_I64,
    "f64": DTYPE_F64,
    "bool": DTYPE_BOOL,
    "str": DTYPE_STR,
}


def duckdb_type_to_lemma(dtype: str) -> str:
    t = dtype.upper()
    if any(k in t for k in ("TINYINT", "SMALLINT", "INTEGER", "INT", "UINTEGER", "UTINYINT", "USMALLINT")):
        return "u32"
    if any(k in t for k in ("BIGINT", "UBIGINT", "HUGEINT", "UHUGEINT")):
        return "u64"
    if "DOUBLE" in t or "FLOAT" in t or "DECIMAL" in t or "NUMERIC" in t:
        return "f64"
    if "BOOL" in t:
        return "bool"
    if "VARCHAR" in t or "TEXT" in t or "CHAR" in t or "BLOB" in t:
        return "str"
    return "str"


def _write_header(f, dtype_byte: int, row_count: int) -> None:
    f.write(MAGIC)
    f.write(struct.pack("<B", dtype_byte))
    f.write(b"\x00" * 7)
    f.write(struct.pack("<QQ", row_count, HEADER_SIZE))


def export_column_array(path: Path, arr: np.ndarray, lemma_dtype: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    dtype_byte = _DTYPE_TO_BYTE[lemma_dtype]
    row_count = int(arr.shape[0])

    with open(path, "wb") as f:
        _write_header(f, dtype_byte, row_count)
        if lemma_dtype == "u32":
            f.write(arr.astype(np.uint32, copy=False).tobytes(order="C"))
        elif lemma_dtype == "u64":
            f.write(arr.astype(np.uint64, copy=False).tobytes(order="C"))
        elif lemma_dtype == "i64":
            f.write(arr.astype(np.int64, copy=False).tobytes(order="C"))
        elif lemma_dtype == "f64":
            f.write(arr.astype(np.float64, copy=False).tobytes(order="C"))
        elif lemma_dtype == "bool":
            f.write(arr.astype(np.bool_, copy=False).tobytes(order="C"))
        elif lemma_dtype == "str":
            blob = b""
            offsets = [0]
            for s in arr:
                b = str(s).encode("utf-8")
                blob += b
                offsets.append(len(blob))
            f.write(struct.pack(f"<{len(offsets)}Q", *offsets))
            f.write(blob)
        else:
            raise ValueError(f"unsupported lemma dtype: {lemma_dtype}")

    return {
        "dtype": lemma_dtype,
        "path": str(path),
        "length": row_count,
        "copy_export": True,
    }


def session_db_path(db_path: str | None = None) -> str:
    """Return a filesystem DuckDB path shared with Rust pin probes."""
    raw = db_path if db_path is not None else os.environ.get("LEMMA_DUCKDB_PATH", ":memory:")
    if raw not in (":memory:", ""):
        return raw
    out = default_export_dir(raw) / "session.duckdb"
    out.parent.mkdir(parents=True, exist_ok=True)
    return str(out)


def maybe_clear_export_cache(export_dir: Path) -> None:
    from verus.research_loop.lemma_flags import lemma_force_regenerate

    if not lemma_force_regenerate():
        return
    import shutil

    if export_dir.is_dir():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)


def export_table(
    con: duckdb.DuckDBPyConnection,
    table: str,
    export_dir: Path,
    *,
    columns: list[str] | None = None,
) -> dict[str, Any]:
    """Materialize one DuckDB table to `.lemma_cols` files under export_dir/table/."""
    safe = table.replace('"', "")
    info = con.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE lower(table_name) = lower(?)
        ORDER BY ordinal_position
        """,
        [safe],
    ).fetchall()
    if not info:
        raise ValueError(f"table not found or has no columns: {table}")

    row_count = con.execute(f'SELECT COUNT(*) FROM "{safe}"').fetchone()[0]
    table_dir = export_dir / safe
    table_dir.mkdir(parents=True, exist_ok=True)

    df = con.execute(f'SELECT * FROM "{safe}"').df()
    col_meta: dict[str, Any] = {}
    for col_name in df.columns:
        if columns is not None and col_name.upper() not in {c.upper() for c in columns}:
            continue
        duck_type = next((dt for cn, dt in info if cn == col_name), "VARCHAR")
        lemma_dtype = duckdb_type_to_lemma(duck_type)
        rel = table_dir / f"{col_name}.lemma_cols"
        col_meta[col_name.upper()] = export_column_array(rel, df[col_name].to_numpy(), lemma_dtype)

    return {
        "row_count": int(row_count),
        "columns": col_meta,
    }


@dataclass
class ExportManifest:
    version: int
    db_path: str
    export_dir: str
    tables: dict[str, dict[str, Any]]

    def write(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "version": self.version,
                    "db_path": self.db_path,
                    "export_dir": self.export_dir,
                    "copy_export": True,
                    "tables": self.tables,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> ExportManifest:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            version=int(data.get("version", 1)),
            db_path=str(data.get("db_path", "")),
            export_dir=str(data.get("export_dir", "")),
            tables=dict(data.get("tables", {})),
        )


def default_export_dir(db_path: str | None = None) -> Path:
    if db_path and db_path not in (":memory:", ""):
        return Path(db_path).with_suffix(".lemma_export")
    return Path(os.environ.get("LEMMA_DUCKDB_EXPORT_DIR", "build/duckdb_memory_export"))


def export_tables(
    con: duckdb.DuckDBPyConnection,
    tables: list[str],
    *,
    export_dir: Path | None = None,
    db_path: str = ":memory:",
    manifest_path: Path | None = None,
) -> ExportManifest:
    out = export_dir or default_export_dir(db_path)
    out.mkdir(parents=True, exist_ok=True)
    table_meta: dict[str, dict[str, Any]] = {}
    for t in tables:
        table_meta[t] = export_table(con, t, out)
    manifest = ExportManifest(
        version=1,
        db_path=db_path,
        export_dir=str(out.resolve()),
        tables=table_meta,
    )
    mpath = manifest_path or (out / "manifest.json")
    manifest.write(mpath)
    return manifest


_HOLDOUT_TABLE_SPECS: list[tuple[str, str]] = [
    ("scan_skew", "scan_skew.tbl"),
    ("scan_skew_1m", "scan_skew_1m.tbl"),
    ("zipf_left", "zipf_left.tbl"),
    ("zipf_right", "zipf_right.tbl"),
    ("str_filter", "str_filter.tbl"),
    ("lineitem_slice", "lineitem_slice.tbl"),
    ("orders_slice", "orders_slice.tbl"),
    ("lineitem_1m", "lineitem_1m.tbl"),
    ("orders_1m", "orders_1m.tbl"),
    ("ssb_flat_500k", "ssb_flat_500k.tbl"),
]


def holdout_table_path(data_dir: Path, table: str) -> Path | None:
    for name, fname in _HOLDOUT_TABLE_SPECS:
        if name == table:
            p = data_dir / fname
            return p if p.is_file() else None
    return None


def duckdb_table_names(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [row[0] for row in con.execute("SHOW TABLES").fetchall()]


def load_holdout_table(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    table: str,
    *,
    quiet: bool = False,
) -> bool:
    """Load one holdout `.tbl` into DuckDB. Returns True if loaded."""
    from verus.db_extension.utils import load_csv_table

    path = holdout_table_path(data_dir, table)
    if path is None:
        return False
    load_csv_table(con, table, path, quiet=quiet)
    return True


def ensure_holdout_tables(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    tables: list[str],
    *,
    quiet: bool = False,
) -> list[str]:
    """Ensure named holdout tables exist; load missing ones only."""
    if quiet:
        con.execute("SET enable_progress_bar = false")
    present = set(duckdb_table_names(con))
    for name in tables:
        if name in present:
            continue
        if load_holdout_table(con, data_dir, name, quiet=quiet):
            present.add(name)
    return [t for t in tables if t in present]


def load_holdout_tables(con: duckdb.DuckDBPyConnection, data_dir: Path, *, quiet: bool = False) -> list[str]:
    """Load all holdout benchmark CSVs into DuckDB once."""
    names = [name for name, _ in _HOLDOUT_TABLE_SPECS]
    return ensure_holdout_tables(con, data_dir, names, quiet=quiet)
