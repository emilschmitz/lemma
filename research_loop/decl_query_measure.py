"""Export the tables a query reads and time that SQL in the same database."""

from __future__ import annotations

import datetime as dt
import re
import statistics
import struct
import time
from decimal import Decimal
from pathlib import Path

import duckdb

from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.schema_types import ColumnTypeInfo, SchemaModel, rust_ident
from research_loop.table_assumptions import CatalogAssumptions

_FIELD = re.compile(r"pub\s+((?:r#)?[A-Za-z_][A-Za-z0-9_]*):\s+Vec<([^>]+)>")
_OUT = re.compile(r"pub\s+((?:r#)?[A-Za-z_][A-Za-z0-9_]*):\s+([^,\n]+),")
_OUT_SCALES = re.compile(r"^// OUT_SCALES: ([0-9,]+)$", re.MULTILINE)
_EPOCH = dt.date(1970, 1, 1)


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
    map_match = re.search(r"-> \(res: HashMapWithView<(\w+), (\w+)>\)", spec)
    if not structs or (out_match is None and map_match is None):
        raise DeclarativeUnsupported("measure needs an OutRow spec or a HashMapWithView result")
    if out_match is not None:
        out_fields = _OUT.findall(out_match.group(1))
        if not out_fields:
            raise DeclarativeUnsupported("measure needs OutRow fields")
    else:
        # Map result: the query yields (key, aggregate); the binary prints `ROW key value`.
        out_fields = [("", map_match.group(1)), ("", map_match.group(2))]
    model = SchemaModel.from_caller(schema, next(iter(schema)))
    dest.mkdir(parents=True, exist_ok=True)
    bins: dict[str, str] = {}
    table_rows: dict[str, int] = {}
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
            table_rows[suffix] = int.from_bytes(blob[:8], "little")
            path = dest / f"cols_{suffix}.bin"
            path.write_bytes(blob)
            bins[suffix] = str(path)
        scales_match = _OUT_SCALES.search(spec)
        scales = [int(x) for x in scales_match.group(1).split(",")] if scales_match else None
        duck_us, rows, kinds = _time_query(con, sql, out_fields, scales)
    except duckdb.Error as exc:
        raise ValueError(str(exc)) from exc
    finally:
        con.close()
    if not bins:
        raise DeclarativeUnsupported("measure wrote no column files")
    return {
        "bins": bins,
        "duck_us": duck_us,
        "rows": rows,
        "kinds": kinds,
        "table_rows": table_rows,
        "float_abs_eps": float_abs_eps,
    }


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
    # The spec struct may hold only the columns the query reads. Export exactly those, in struct order.
    by_ident = {rust_ident(col_key): col_key for col_key in cols}
    names: list[str] = []
    types: list[str] = []
    infos: list[ColumnTypeInfo] = []
    for fname, fty in fields:
        col_key = by_ident.get(fname.removeprefix("r#"))
        if col_key is None or cols[col_key].exec_rust != fty:
            raise ValueError(f"{table}.{fname}: {fty} is not a column of the table with that type")
        names.append(model.original_column_names[(table.casefold(), col_key)])
        types.append(fty)
        infos.append(cols[col_key])
    # A DATE leaves DuckDB as its day number (an exact INTEGER), a DECIMAL as the exact scaled integer.
    listed = ", ".join(
        f"({_quote(name)} - DATE '1970-01-01')" if info.is_date else _quote(name)
        for name, info in zip(names, infos, strict=True)
    )
    try:
        fetched = con.execute(f"SELECT {listed} FROM {_quote(table)}").fetchall()
    except duckdb.Error as exc:
        raise ValueError(str(exc)) from exc
    # The spec has no NULL semantics: a NULL packed as 0 or "" would silently change the answer.
    for idx, name in enumerate(names):
        if any(row[idx] is None for row in fetched):
            raise ValueError(
                f"{table}.{name} has NULLs; the declarative spec has no NULL semantics"
            )
    buf = bytearray(struct.pack("<Q", len(fetched)))
    # Column-major, the order the generated reader consumes: all of column 0, then column 1, ...
    for idx, fty in enumerate(types):
        scale = infos[idx].scale
        for row in fetched:
            value = row[idx]
            buf.extend(_pack(fty, decimal_scaled(value, scale) if isinstance(value, Decimal) else value))
    return bytes(buf)


def decimal_scaled(value: Decimal, scale: int) -> int:
    """``value * 10**scale`` as an exact integer, with no rounding."""
    sign, digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)
    shift = exponent + scale
    if shift < 0:
        raise ValueError(f"{value} has more than {scale} fractional digits")
    return (-1 if sign else 1) * int("".join(map(str, digits)) or "0") * 10**shift


def _time_query(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    out_fields: list[tuple[str, str]],
    scales: list[int] | None = None,
) -> tuple[int, list[list[object]], list[str] | None]:
    for _ in range(2):
        con.execute(sql).fetchall()
    samples: list[float] = []
    result: list[tuple] | None = None
    names: list[str] = []
    duck_types: list[str] = []
    for _ in range(5):
        t0 = time.perf_counter()
        cur = con.execute(sql)
        result = cur.fetchall()
        samples.append((time.perf_counter() - t0) * 1_000_000)
        names = [str(col[0]) for col in cur.description]
        duck_types = [str(col[1]) for col in cur.description]
    if result is None:
        raise RuntimeError("no timing sample")
    indexes: list[int] = []
    if all(not fname for fname, _fty in out_fields):
        if len(names) != len(out_fields):
            raise ValueError(f"map result needs {len(out_fields)} query columns, got {names}")
        indexes = list(range(len(names)))
        kinds = [_kind(fty) for _fname, fty in out_fields]
        if any(k != "int" for k in kinds):
            raise ValueError("map result keys and values must be integers")
        pairs = sorted((_canon(out_fields[0][1], r[0]), _canon(out_fields[1][1], r[1])) for r in result)
        return int(statistics.median(samples)), [[k, v] for k, v in pairs], None
    # Result columns are matched by position: the SELECT order is the OutRow order. DuckDB's own
    # column names (`sum(l_quantity)`) are not the spec's field names.
    if len(names) != len(out_fields):
        raise ValueError(f"the query returns {len(names)} columns {names}, OutRow has {len(out_fields)}")
    indexes = list(range(len(names)))
    if scales is None:
        scales = [0] * len(out_fields)
    if len(scales) != len(out_fields):
        raise ValueError(f"OUT_SCALES has {len(scales)} entries, OutRow has {len(out_fields)}")
    for position, (scale, duck_type) in enumerate(zip(scales, duck_types, strict=True)):
        duck_scale = int(m.group(1)) if (m := re.fullmatch(r"DECIMAL\(\d+,(\d+)\)", duck_type)) else 0
        if duck_scale != scale:
            raise ValueError(
                f"output column {position} has scale {scale} in the spec, DuckDB returns {duck_type}"
            )
    kinds = [_kind(fty) for _fname, fty in out_fields]
    rows: list[list[object]] = []
    for record in result:
        rows.append([_canon(out_fields[i][1], record[indexes[i]], scales[i]) for i in range(len(out_fields))])
    return int(statistics.median(samples)), rows, kinds


def _kind(exec_rust: str) -> str:
    exec_rust = exec_rust.removeprefix("Option<").removesuffix(">")
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


def _canon(exec_rust: str, value: object, scale: int = 0) -> object:
    if exec_rust.startswith("Option<"):  # SQL NULL stays NULL; the binary prints it as NULL
        return None if value is None else _canon(exec_rust[len("Option<") : -1], value, scale)
    if isinstance(value, Decimal):
        return decimal_scaled(value, scale)
    if isinstance(value, dt.date):
        return (value - _EPOCH).days
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
    if value is None:
        raise ValueError("NULL cell: the declarative spec has no NULL semantics")
    if fty == "String":
        raw = str(value).encode("utf-8")
        if len(raw) > 2**32 - 1:
            raise ValueError("string column longer than u32")
        return struct.pack("<I", len(raw)) + raw
    if fty == "bool":
        return bytes([1 if value else 0])
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
