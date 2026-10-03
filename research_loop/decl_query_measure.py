"""Export the tables a query reads and time that SQL in the same database."""

from __future__ import annotations

import re
import statistics
import struct
import time
from pathlib import Path

import duckdb

from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.schema_types import SchemaModel, rust_ident
from research_loop.table_assumptions import CatalogAssumptions

_FIELD = re.compile(r"pub\s+((?:r#)?[A-Za-z_][A-Za-z0-9_]*):\s+Vec<([^>]+)>")
_OUT = re.compile(r"pub\s+((?:r#)?[A-Za-z_][A-Za-z0-9_]*):\s+([^,\n]+),")


def write_query_measure(
    *,
    sql: str,
    schema: dict,
    catalog: CatalogAssumptions | None,
    db_path: Path,
    dest: Path,
    float_abs_eps: str | None,
) -> dict:
    """Write one column file per input struct and the DuckDB median for ``sql``."""
    if not db_path.is_file():
        raise FileNotFoundError(f"measure database missing at {db_path}")
    spec = emit_declarative_spec(sql, schema, catalog, float_abs_eps=float_abs_eps)
    structs = re.findall(r"pub struct (Cols_[A-Za-z0-9_]+)\s*\{([^}]+)\}", spec)
    out_match = re.search(r"pub struct OutRow\s*\{([^}]+)\}", spec)
    if not structs or out_match is None:
        raise DeclarativeUnsupported("measure needs one OutRow spec")
    out_fields = _OUT.findall(out_match.group(1))
    if not out_fields:
        raise DeclarativeUnsupported("measure needs OutRow fields")
    model = SchemaModel.from_caller(schema, next(iter(schema)))
    dest.mkdir(parents=True, exist_ok=True)
    bins: dict[str, str] = {}
    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except duckdb.Error as exc:
        raise ValueError(str(exc)) from exc
    try:
        for struct_name, body in structs:
            suffix = struct_name.removeprefix("Cols_")
            fields = _FIELD.findall(body)
            table = _table_for_suffix(model, suffix)
            blob = _export_table(con, model, table, fields)
            path = dest / f"cols_{suffix}.bin"
            path.write_bytes(blob)
            bins[suffix] = str(path)
        duck_us, rows, kinds = _time_query(con, sql, out_fields)
    except duckdb.Error as exc:
        raise ValueError(str(exc)) from exc
    finally:
        con.close()
    if not bins:
        raise DeclarativeUnsupported("measure wrote no column files")
    return {"bins": bins, "duck_us": duck_us, "rows": rows, "kinds": kinds}


def _table_for_suffix(model: SchemaModel, suffix: str) -> str:
    hits = [orig for orig in model.original_table_names.values() if rust_ident(orig) == suffix]
    if len(hits) != 1:
        raise ValueError(f"no table matches column struct {suffix}")
    return hits[0]


def _export_table(
    con: duckdb.DuckDBPyConnection,
    model: SchemaModel,
    table: str,
    fields: list[tuple[str, str]],
) -> bytes:
    _orig, cols = model.lookup_table(table)
    ordered = sorted(cols)
    if len(ordered) != len(fields):
        raise ValueError(f"{table} column count does not match the spec")
    names: list[str] = []
    types: list[str] = []
    for col_key, (fname, fty) in zip(ordered, fields, strict=True):
        if rust_ident(col_key) != fname or cols[col_key].exec_rust != fty:
            raise ValueError(f"{table}.{col_key} does not match spec field {fname}: {fty}")
        names.append(model.original_column_names[(table.casefold(), col_key)])
        types.append(fty)
    listed = ", ".join(_quote(name) for name in names)
    try:
        fetched = con.execute(f"SELECT {listed} FROM {_quote(table)}").fetchall()
    except duckdb.Error as exc:
        raise ValueError(str(exc)) from exc
    buf = bytearray(struct.pack("<Q", len(fetched)))
    for row in fetched:
        for fty, value in zip(types, row, strict=True):
            buf.extend(_pack(fty, value))
    return bytes(buf)


def _time_query(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    out_fields: list[tuple[str, str]],
) -> tuple[int, list[list[object]], list[str]]:
    for _ in range(2):
        con.execute(sql).fetchall()
    samples: list[float] = []
    result: list[tuple] | None = None
    names: list[str] = []
    for _ in range(5):
        t0 = time.perf_counter()
        cur = con.execute(sql)
        result = cur.fetchall()
        samples.append((time.perf_counter() - t0) * 1_000_000)
        names = [str(col[0]) for col in cur.description]
    if result is None:
        raise RuntimeError("no timing sample")
    indexes: list[int] = []
    for fname, _fty in out_fields:
        bare = fname.removeprefix("r#").casefold()
        hits = [i for i, name in enumerate(names) if name.casefold() == bare]
        if len(hits) != 1:
            raise ValueError(f"output column {fname} is not in the query result {names}")
        indexes.append(hits[0])
    kinds = [_kind(fty) for _fname, fty in out_fields]
    rows: list[list[object]] = []
    for record in result:
        rows.append([_canon(out_fields[i][1], record[indexes[i]]) for i in range(len(out_fields))])
    return int(statistics.median(samples)), rows, kinds


def _kind(exec_rust: str) -> str:
    if exec_rust == "String":
        return "str"
    if exec_rust == "f64":
        return "float"
    return "int"


def _as_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"not a float: {value!r}")  # noqa: TRY004
    return float(value)


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(value)
    raise ValueError(f"not an int: {value!r}")


def _canon(exec_rust: str, value: object) -> object:
    if exec_rust == "String":
        return "" if value is None else str(value)
    if exec_rust == "f64":
        if value is None:
            raise ValueError("null float in a measured result")
        return _as_float(value)
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"non-integer result {value} for {exec_rust}")
    if value is None:
        return 0
    return _as_int(value)


def _pack(fty: str, value: object) -> bytes:
    if fty == "String":
        raw = b"" if value is None else str(value).encode("utf-8")
        if len(raw) > 2**32 - 1:
            raise ValueError("string column longer than u32")
        return struct.pack("<I", len(raw)) + raw
    if fty == "bool":
        return bytes([0 if value in (None, False) else 1])
    if value is None:
        value = 0
    try:
        if fty == "f64":
            return struct.pack("<d", _as_float(value))
        if fty == "i64":
            return struct.pack("<q", _as_int(value))
        if fty == "u64":
            return struct.pack("<Q", _as_int(value))
        if fty == "i32":
            return struct.pack("<i", _as_int(value))
        if fty == "u32":
            return struct.pack("<I", _as_int(value))
        if fty == "usize":
            return struct.pack("<Q", _as_int(value))
        if fty == "i128":
            return _as_int(value).to_bytes(16, "little", signed=True)
    except (struct.error, OverflowError, ValueError) as exc:
        raise ValueError(f"cannot pack {value!r} as {fty}") from exc
    raise ValueError(f"cannot pack column type {fty}")


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
