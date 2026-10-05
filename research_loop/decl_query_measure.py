"""Export the tables a query reads and time that SQL in the same database."""

from __future__ import annotations

import datetime as dt
import io
import json
import re
import shutil
import statistics
import struct
import tempfile
import time
from decimal import Decimal
from pathlib import Path
from typing import BinaryIO

import duckdb
import numpy as np

from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.parse_query import parse_query
from declarative_spec.resolve import flatten_derived
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
) -> dict:
    """Write one column file per input struct and the DuckDB median for ``sql``."""
    if not db_path.is_file():
        raise FileNotFoundError(f"measure database missing at {db_path}")
    spec = emit_declarative_spec(sql, schema, catalog)
    structs = re.findall(r"pub struct (Cols_[A-Za-z0-9_]+)\s*\{([^}]+)\}", spec)
    out_match = re.search(r"pub struct OutRow\s*\{([^}]+)\}", spec)
    map_match = re.search(r"-> \(res: HashMapWithView<(\w+), (\w+)>\)", spec)
    string_map_match = re.search(r"-> \(res: StringHashMap<(\w+)>\)", spec)
    if not structs or (out_match is None and map_match is None and string_map_match is None):
        result_ty = re.search(r"pub fn run_query\([^)]*\) -> \(res: ([^)]+)\)", spec)
        raise DeclarativeUnsupported(
            "measure cannot print the result type "
            f"{result_ty.group(1) if result_ty else 'unknown'}: need OutRow, HashMapWithView or StringHashMap"
        )
    if out_match is not None:
        out_fields = _OUT.findall(out_match.group(1))
        if not out_fields:
            raise DeclarativeUnsupported("measure needs OutRow fields")
    elif string_map_match is not None:
        # String-keyed map: the binary prints one `ROW <hex key> <value>` per key, like an OutRow.
        out_fields = [("key", "String"), ("value", string_map_match.group(1))]
    else:
        # Map result: the query yields (key, aggregate); the binary prints `ROW key value`.
        out_fields = [("", map_match.group(1)), ("", map_match.group(2))]
    # A flat (projected) schema carries no table name; the SQL's FROM names it.
    # The emitter parses the exact-integer rewrite of the SQL (a ratio's `/` only parses there), so name the table from it.
    from declarative_spec.numeric_rewrite import rewrite_numeric

    integer_sql, _scales = rewrite_numeric(sql, schema, catalog)
    model = SchemaModel.from_caller(schema, flatten_derived(parse_query(integer_sql)).tables[0]).with_nullable(catalog)
    # Plan every table's column mapping before the first export: an unmappable field must fail in milliseconds, not after a 1 GB export.
    plans = {}
    for struct_name, body in structs:
        suffix = struct_name.removeprefix("Cols_")
        plans[suffix] = _plan_table(model, _table_for_suffix(model, suffix), _FIELD.findall(body))
    dest.mkdir(parents=True, exist_ok=True)
    bins: dict[str, str] = {}
    table_rows: dict[str, int] = {}
    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except duckdb.Error as exc:
        raise ValueError(str(exc)) from exc
    try:
        for suffix, plan in plans.items():
            path = dest / f"cols_{suffix}.bin"
            with path.open("wb") as fh:
                table_rows[suffix] = _export_planned_to(con, plan, fh)
            bins[suffix] = str(path)
        scales_match = _OUT_SCALES.search(spec)
        scales = [int(x) for x in scales_match.group(1).split(",")] if scales_match else None
        duck_threads = int(con.execute("SELECT current_setting('threads')").fetchone()[0])
        duck_us, rows, kinds = _time_query(con, sql, out_fields, scales)
        con.execute("SET threads=1")
        duck1_us = _median_us(con, sql)
    except duckdb.Error as exc:
        raise ValueError(str(exc)) from exc
    finally:
        con.close()
    if not bins:
        raise DeclarativeUnsupported("measure wrote no column files")
    # The in-session run_runquery tool loads this (declarative_spec.bench.load_speed_bar): the agent's
    # runs then use the official column files, the DuckDB bar and the expected result rows.
    expect = {
        "duck_us": duck_us,
        "duck_threads": duck_threads,
        "duck1_us": duck1_us,
        "rows": rows,
        "kinds": kinds,
        "table_rows": table_rows,
    }
    (dest / "expect.json").write_text(json.dumps(expect) + "\n", encoding="utf-8")
    return {
        "bins": bins,
        "duck_us": duck_us,
        "duck_threads": duck_threads,
        "duck1_us": duck1_us,
        "rows": rows,
        "kinds": kinds,
        "table_rows": table_rows,
    }


def _table_for_suffix(model: SchemaModel, suffix: str) -> str:
    hits = [orig for orig in model.original_table_names.values() if rust_ident(orig) == suffix]
    if len(hits) != 1:
        raise ValueError(f"no table matches column struct {suffix}")
    return hits[0]


def _plan_table(model: SchemaModel, table: str, fields: list[tuple[str, str]]) -> tuple:
    """Map every spec struct field to its table column and check the mapping; reads no data, so a bad field fails here, not after the export."""
    _orig, cols = model.lookup_table(table)
    # The spec struct may hold only the columns the query reads. Export exactly those, in struct order.
    by_ident = {rust_ident(col_key): col_key for col_key in cols}
    names: list[str] = []
    types: list[str] = []
    infos: list[ColumnTypeInfo] = []
    dict_of: dict[int, int] = {}  # field index of a `<col>__dict` -> field index of its codes
    code_fields: dict[str, int] = {}
    valid_fields: set[int] = set()  # field indices of a `<col>__valid` (false for a NULL cell)
    nullable: list[bool] = []
    for fname, fty in fields:
        if fname.endswith("__valid"):
            # The validity vector of a nullable column: true where the cell is not NULL.
            col_key = by_ident.get(fname[: -len("__valid")])
            if col_key is None or fty != "bool" or not model.is_nullable(table, col_key):
                raise ValueError(f"{table}.{fname}: not the validity vector of a nullable column")
            valid_fields.add(len(names))
        elif fname.endswith("__dict"):
            # The dictionary of a string column loaded as codes (``declarative_spec.string_encoding``).
            base = fname[: -len("__dict")]
            col_key = by_ident.get(base)
            if col_key is None or fty != "String" or cols[col_key].exec_rust != "String":
                raise ValueError(f"{table}.{fname}: not the dictionary of a string column")
            dict_of[len(names)] = code_fields[base]
        else:
            col_key = by_ident.get(fname)
            if col_key is not None and cols[col_key].exec_rust == "String" and fty in ("u8", "u16", "u32"):
                code_fields[fname] = len(names)
            elif col_key is None or (
                cols[col_key].exec_rust != fty
                # a narrowed integer column loaded wide (a group key of a map-result shape, LEMMA_NARROW_CELLS)
                and not (fty == "i64" and cols[col_key].exec_rust in ("i32", "i16", "i8") and not cols[col_key].is_date)
            ):
                raise ValueError(f"{table}.{fname}: {fty} is not a column of the table with that type")
        names.append(model.original_column_names[(table.casefold(), col_key)])
        types.append(fty)
        infos.append(cols[col_key])
        nullable.append(model.is_nullable(table, col_key))
    return table, names, types, infos, nullable, dict_of, valid_fields


def _export_table(
    con: duckdb.DuckDBPyConnection,
    model: SchemaModel,
    table: str,
    fields: list[tuple[str, str]],
) -> bytes:
    return _export_planned(con, _plan_table(model, table, fields))


def _export_planned(con: duckdb.DuckDBPyConnection, plan: tuple) -> bytes:
    sink = io.BytesIO()
    _export_planned_to(con, plan, sink)
    return sink.getvalue()


def _export_planned_to(con: duckdb.DuckDBPyConnection, plan: tuple, sink: BinaryIO) -> int:
    """Write the column file for ``plan`` to ``sink``; memory is bounded by ``_BATCH_ROWS`` rows (plus the dictionaries), not the table."""
    table, names, types, infos, nullable, dict_of, valid_fields = plan
    return _encode_columns(con, table, names, types, infos, nullable, dict_of, valid_fields, sink)


_BATCH_ROWS = 1_000_000  # rows per scan batch of the exporter


_INT_RANGE: dict[str, tuple[int, int]] = {
    "i8": (-(2**7), 2**7 - 1), "i16": (-(2**15), 2**15 - 1), "i32": (-(2**31), 2**31 - 1), "i64": (-(2**63), 2**63 - 1),
    "u8": (0, 2**8 - 1), "u16": (0, 2**16 - 1), "u32": (0, 2**32 - 1), "u64": (0, 2**64 - 1), "usize": (0, 2**64 - 1),
}
_SQL_TARGET = {
    "i8": "TINYINT", "i16": "SMALLINT", "i32": "INTEGER", "i64": "BIGINT",
    "u8": "UTINYINT", "u16": "USMALLINT", "u32": "UINTEGER", "u64": "UBIGINT", "usize": "UBIGINT",
}
_NP_DTYPE = {
    "i8": "<i1", "i16": "<i2", "i32": "<i4", "i64": "<i8", "u8": "<u1", "u16": "<u2", "u32": "<u4", "u64": "<u8", "usize": "<u8",
    "f64": "<f8",
}
_DECIMAL_TYPE = re.compile(r"DECIMAL\((\d+),\s*(\d+)\)")


def _pack_strings(values: list[str]) -> bytes:
    """Each string as a little-endian u32 byte length then its UTF-8 bytes, built with numpy rather than a Python step per string."""
    raw = [v.encode("utf-8") for v in values]
    n = len(raw)
    if n == 0:
        return b""
    lens = np.fromiter(map(len, raw), dtype=np.int64, count=n)
    if int(lens.max()) > 2**32 - 1:
        raise ValueError("string column longer than u32")
    out = np.empty(int(lens.sum()) + 4 * n, dtype=np.uint8)
    starts = np.cumsum(lens + 4) - (lens + 4)
    hdr_idx = (starts[:, None] + np.arange(4)).ravel()
    out[hdr_idx] = lens.astype("<u4").view(np.uint8)
    body = np.ones(out.shape[0], dtype=bool)
    body[hdr_idx] = False
    out[body] = np.frombuffer(b"".join(raw), dtype=np.uint8)
    return out.tobytes()


def _decimal_unscaled_sql(name: str, scale: int, src_scale: int, width: int = 38) -> str:
    """SQL for ``value * 10**scale`` as an exact HUGEINT (a DECIMAL multiply would overflow at 38 digits)."""
    if src_scale > scale:
        raise ValueError(f"{name} has more than {scale} fractional digits")
    if width + (scale - src_scale) <= 18:
        # fits a BIGINT with room for the multiply: plain 64-bit arithmetic (HUGEINT arithmetic is several times slower)
        return f"CAST({name} * {10**scale} AS BIGINT)"
    if src_scale > 18:
        # the fraction times 10**src_scale overflows DECIMAL(38) from scale 20 up: take the unscaled digits from the exact decimal text
        digits = f"CAST(replace(CAST({name} AS VARCHAR), '.', '') AS HUGEINT)"
        return f"({digits} * {10 ** (scale - src_scale)}::HUGEINT)"
    ip = f"trunc({name})"
    frac = f"CAST(({name} - {ip}) * CAST({10**src_scale} AS DECIMAL(38,0)) AS HUGEINT)"
    return f"(CAST({ip} AS HUGEINT) * {10**scale}::HUGEINT + {frac} * {10 ** (scale - src_scale)}::HUGEINT)"


def _encode_columns(
    con: duckdb.DuckDBPyConnection,
    table: str,
    names: list[str],
    types: list[str],
    infos: list[ColumnTypeInfo],
    nullable: list[bool],
    dict_of: dict[int, int],
    valid_fields: set[int],
    sink: BinaryIO,
) -> int:
    """Bulk export to ``sink`` (returns the row count): DuckDB projects every cell at its loaded width, in row batches, as numpy arrays.

    The bytes are those of a per-cell loop over the rows: dictionary codes number the distinct values in order of first
    appearance, a NULL cell of a nullable column is the default cell (code 0 for a dictionary), a NULL in a column the
    catalog does not declare nullable is refused, and so is a value outside its loaded type.
    """
    t = _quote(table)
    uniq = list(dict.fromkeys(names))
    try:
        desc = con.execute(f"SELECT {', '.join(_quote(n) for n in uniq)} FROM {t} LIMIT 0").description
        all_names = [d[0].casefold() for d in con.execute(f"SELECT * FROM {t} LIMIT 0").description]
    except duckdb.Error as exc:
        raise ValueError(str(exc)) from exc
    base_types = {n: str(d[1]) for n, d in zip(uniq, desc, strict=True)}
    for idx, fty in enumerate(types):
        base = base_types[names[idx]]
        if (
            (fty == "String" and (base in ("BOOLEAN", "FLOAT", "BLOB") or base.startswith("DECIMAL")))
            or (fty in _INT_RANGE and base in ("DOUBLE", "FLOAT"))
            or (fty == "bool" and base == "VARCHAR" and idx not in valid_fields)
        ):
            raise ValueError(f"{table}.{names[idx]}: DuckDB type {base} is not loadable as {fty}")
    if "rowid" in all_names:
        raise ValueError(f"{table} has a column named rowid; the row batches and the dictionary order need the row id pseudo-column")
    dictionaries: dict[int, list[str]] = {}
    plan: dict[int, str] = {}  # field index -> select expression
    kinds: dict[int, str] = {}  # field index -> int | value | valid | code | string
    enum_names: list[str] = []
    spools: list = []
    null_codes: set[int] = set()
    try:
        for idx in sorted(set(dict_of.values())):
            q = _quote(names[idx])
            # Distinct non-NULL cells in order of first appearance (physical row order), which is the code order.
            rows = con.execute(
                f"SELECT s FROM (SELECT CAST({q} AS VARCHAR) AS s, min(rowid) AS m FROM {t} WHERE {q} IS NOT NULL GROUP BY 1) ORDER BY m"
            ).fetchall()
            entries = [r[0] for r in rows]
            if any("\x00" in e for e in entries):
                raise ValueError(f"{table}.{names[idx]}: a NUL byte in a dictionary string")
            dictionaries[idx] = entries
            if len(entries) > 2 ** {"u8": 8, "u16": 16, "u32": 32}[types[idx]]:
                raise ValueError(f"cannot pack code {len(entries) - 1} as {types[idx]}")
            if entries:
                enum = f"lemma_exp_enum_{idx}"
                literals = ", ".join("'" + e.replace("'", "''") + "'" for e in entries)
                con.execute(f"CREATE OR REPLACE TEMP TYPE {enum} AS ENUM ({literals})")
                enum_names.append(enum)
                plan[idx] = f"CAST(enum_code(CAST(CAST({q} AS VARCHAR) AS {enum})) AS {_SQL_TARGET[types[idx]]})"
            else:
                plan[idx] = f"CAST(NULL AS {_SQL_TARGET[types[idx]]})"
            kinds[idx] = "code"
        for idx, fty in enumerate(types):
            if idx in dict_of or idx in kinds:
                continue
            q = _quote(names[idx])
            base = base_types[names[idx]]
            m = _DECIMAL_TYPE.fullmatch(base)
            if idx in valid_fields:
                plan[idx], kinds[idx] = f"({q} IS NOT NULL)", "valid"
            elif fty == "String":
                plan[idx], kinds[idx] = f"CAST({q} AS VARCHAR)", "string"
            elif fty == "bool":
                plan[idx], kinds[idx] = f"CAST({q} AS BOOLEAN)", "value"
            elif fty == "f64":
                scaled = _decimal_unscaled_sql(q, infos[idx].scale, int(m.group(2)), int(m.group(1))) if m else q
                plan[idx], kinds[idx] = f"CAST({scaled} AS DOUBLE)", "value"
            else:
                if infos[idx].is_date:
                    plan[idx] = f"CAST({q} - DATE '1970-01-01' AS BIGINT)"
                elif m:
                    plan[idx] = _decimal_unscaled_sql(q, infos[idx].scale, int(m.group(2)), int(m.group(1)))
                elif fty == "i128" or base in ("HUGEINT", "UHUGEINT", "UBIGINT"):
                    plan[idx] = f"CAST({q} AS HUGEINT)"
                else:
                    plan[idx] = f"CAST({q} AS BIGINT)"
                kinds[idx] = "int"
        # A value outside its loaded type is refused before the narrowing cast (which would raise without naming the cell).
        ints = [i for i, k in kinds.items() if k == "int" and types[i] != "i128"]
        if ints:
            bounds = con.execute(f"SELECT {', '.join(f'min({plan[i]}), max({plan[i]})' for i in ints)} FROM {t}").fetchone()
            for pos, i in enumerate(ints):
                lo, hi = _INT_RANGE[types[i]]
                for v in (bounds[2 * pos], bounds[2 * pos + 1]):
                    if v is not None and not lo <= v <= hi:
                        raise ValueError(f"cannot pack {v!r} as {types[i]}")
        select: list[str] = []
        for i in sorted(plan):
            expr = plan[i]
            if kinds[i] == "int":
                if types[i] == "i128":
                    select += [f"CAST(CAST({expr} AS HUGEINT) >> 64 AS BIGINT) AS h{i}", f"CAST(CAST({expr} AS HUGEINT) & 18446744073709551615 AS UBIGINT) AS l{i}"]
                    continue
                expr = f"CAST({expr} AS {_SQL_TARGET[types[i]]})"
            select.append(f"{expr} AS c{i}")
        total = _count_rows(con, t)
        bounds_rowid = con.execute(f"SELECT min(rowid), max(rowid) FROM {t}").fetchone()
        # Column-major layout (all of column 0, then column 1, ...) from a row-batch scan: each column's bytes go to its own
        # temporary file, so memory is bounded by the batch, not the table. The batches are rowid ranges (row-group pruned).
        spools.extend(tempfile.TemporaryFile() for _ in types)  # noqa: SIM115
        seen = 0
        lo = bounds_rowid[0]
        while select and lo is not None and lo <= bounds_rowid[1]:
            hi = lo + _BATCH_ROWS
            arrays = con.execute(f"SELECT {', '.join(select)} FROM {t} WHERE rowid >= {lo} AND rowid < {hi}").fetchnumpy()
            lo = hi
            n = len(next(iter(arrays.values())))
            seen += n
            for idx, fty in enumerate(types):
                if n and idx not in dict_of:
                    spools[idx].write(_encode_batch(arrays, idx, fty, kinds[idx], nullable[idx], f"{table}.{names[idx]}", null_codes, n))
            del arrays
        if select and seen != total:
            raise ValueError(f"{table}: scanned {seen} rows of {total}")
    except duckdb.Error as exc:
        raise ValueError(str(exc)) from exc
    finally:
        for enum in enum_names:
            con.execute(f"DROP TYPE IF EXISTS {enum}")
    try:
        _finish(spools, dictionaries, dict_of, null_codes, total, sink)
    finally:
        for spool in spools:
            spool.close()
    return total


def _finish(spools: list, dictionaries: dict[int, list[str]], dict_of: dict[int, int], null_codes: set[int], total: int, sink: BinaryIO) -> None:
    for source in null_codes:
        if not dictionaries[source]:
            dictionaries[source] = [""]  # every cell is NULL: code 0 still has to index an entry
    for idx, source in dict_of.items():
        entries = dictionaries[source]
        spools[idx].write(struct.pack("<Q", len(entries)) + _pack_strings(entries))
    sink.write(struct.pack("<Q", total))
    for spool in spools:
        spool.seek(0)
        shutil.copyfileobj(spool, sink, 1 << 16)


def _encode_batch(arrays: dict, idx: int, fty: str, kind: str, nullable: bool, label: str, null_codes: set[int], n: int) -> bytes:
    """The bytes of one column for one row batch (the cell encoding of the per-row loop)."""
    if kind == "valid":
        return np.ma.filled(arrays[f"c{idx}"], False).astype("u1").tobytes()
    probe = arrays[f"h{idx}"] if kind == "int" and fty == "i128" else arrays[f"c{idx}"]
    has_null = bool(np.ma.getmaskarray(probe).any())
    if has_null and not nullable:
        raise ValueError(f"{label} has NULLs; the catalog does not declare the column nullable")
    if kind == "int" and fty == "i128":
        pair = np.empty((n, 2), dtype="<u8")
        pair[:, 0] = np.ma.filled(arrays[f"l{idx}"], 0).astype("<u8")
        pair[:, 1] = np.ma.filled(probe, 0).astype("<i8").view("<u8")
        return pair.tobytes()
    if kind == "code":
        if has_null:
            null_codes.add(idx)
        return np.ma.filled(probe, 0).astype(_NP_DTYPE[fty]).tobytes()
    if kind == "string":
        return _pack_strings((np.ma.filled(probe, "") if has_null else probe).tolist())
    if fty == "bool":
        return np.ma.filled(probe, False).astype("u1").tobytes()
    return np.ma.filled(probe, 0).astype(_NP_DTYPE[fty]).tobytes()


def _count_rows(con: duckdb.DuckDBPyConnection, quoted_table: str) -> int:
    return int(con.execute(f"SELECT count(*) FROM {quoted_table}").fetchone()[0])


_DEFAULT_CELL: dict[str, object] = {
    "String": "", "bool": False, "f64": 0.0, "i64": 0, "i16": 0, "i8": 0, "u64": 0, "i32": 0, "u32": 0, "u16": 0, "u8": 0, "usize": 0, "i128": 0,
}


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


def _median_us(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    """Median of five timed runs after two warmups, in the connection's current thread setting."""
    for _ in range(2):
        con.execute(sql).fetchall()
    samples: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        con.execute(sql).fetchall()
        samples.append((time.perf_counter() - t0) * 1_000_000)
    return int(statistics.median(samples))


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
        if fty == "i16":
            return struct.pack("<h", _as_int(value))
        if fty == "i8":
            return struct.pack("<b", _as_int(value))
        if fty == "i32":
            return struct.pack("<i", _as_int(value))
        if fty == "u32":
            return struct.pack("<I", _as_int(value))
        if fty == "u16":
            return struct.pack("<H", _as_int(value))
        if fty == "u8":
            return struct.pack("<B", _as_int(value))
        if fty == "usize":
            return struct.pack("<Q", _as_int(value))
        if fty == "i128":
            return _as_int(value).to_bytes(16, "little", signed=True)
    except (struct.error, OverflowError, ValueError) as exc:
        raise ValueError(f"cannot pack {value!r} as {fty}") from exc
    raise ValueError(f"cannot pack column type {fty}")


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
