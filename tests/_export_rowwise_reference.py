"""The per-row Python exporter research_loop.decl_query_measure shipped before the bulk (numpy) one: the differential-test oracle.

Kept verbatim (renamed ``_export_table_rowwise``); the bulk exporter must emit the same bytes for every input this one accepts and refuse what it refuses.
"""

from __future__ import annotations

import struct
from decimal import Decimal

import duckdb

from declarative_spec.schema_types import ColumnTypeInfo, SchemaModel, rust_ident
from research_loop.decl_query_measure import _pack, _quote, decimal_scaled

_CHUNK_ROWS = 500_000
_DEFAULT_CELL: dict[str, object] = {
    "String": "", "bool": False, "f64": 0.0, "i64": 0, "i16": 0, "i8": 0, "u64": 0, "i32": 0, "u32": 0, "u16": 0, "u8": 0, "usize": 0, "i128": 0,
}


def _export_table_rowwise(
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
    # A DATE leaves DuckDB as its day number (an exact INTEGER), a DECIMAL as the exact scaled integer.
    listed = ", ".join(
        f"({_quote(name)} - DATE '1970-01-01')" if info.is_date else _quote(name)
        for name, info in zip(names, infos, strict=True)
    )
    # Stream in chunks and pack each column as it arrives: a Python tuple per row for a 6M-row table
    # is gigabytes, the packed columns are tens of megabytes.
    try:
        cur = con.execute(f"SELECT {listed} FROM {_quote(table)}")
    except duckdb.Error as exc:
        raise ValueError(str(exc)) from exc
    col_bufs = [bytearray() for _ in types]
    dictionaries: dict[int, dict[str, int]] = {idx: {} for idx in set(dict_of.values())}
    null_codes: set[int] = set()  # dictionary code fields that hold a NULL cell
    total = 0
    while True:
        chunk = cur.fetchmany(_CHUNK_ROWS)
        if not chunk:
            break
        total += len(chunk)
        for idx, fty in enumerate(types):
            if idx in dict_of:
                continue
            scale = infos[idx].scale
            buf = col_bufs[idx]
            for row in chunk:
                value = row[idx]
                if idx in valid_fields:
                    buf.extend(_pack("bool", value is not None))
                    continue
                if value is None:
                    # A column the catalog does not declare nullable has no NULL: a NULL packed as 0 or "" would
                    # silently change the answer. A nullable column's value cell is arbitrary where the validity
                    # vector says NULL, so the default is written.
                    if not nullable[idx]:
                        raise ValueError(
                            f"{table}.{names[idx]} has NULLs; the catalog does not declare the column nullable"
                        )
                    if idx in dictionaries:
                        # A NULL cell's code is arbitrary (the validity bit says NULL) but must index the dictionary:
                        # code 0 takes no entry of its own (see the all-NULL case below).
                        null_codes.add(idx)
                        buf.extend(_pack(fty, 0))
                        continue
                    value = _DEFAULT_CELL[fty]
                if idx in dictionaries:
                    codes = dictionaries[idx]
                    buf.extend(_pack(fty, codes.setdefault(str(value), len(codes))))
                    continue
                buf.extend(_pack(fty, decimal_scaled(value, scale) if isinstance(value, Decimal) else value))
    for source in null_codes:
        if not dictionaries[source]:
            dictionaries[source][""] = 0  # every cell is NULL: code 0 still has to index an entry
    for idx, source in dict_of.items():
        entries = sorted(dictionaries[source].items(), key=lambda kv: kv[1])
        col_bufs[idx].extend(struct.pack("<Q", len(entries)))
        for text, _code in entries:
            col_bufs[idx].extend(_pack("String", text))
    # Column-major, the order the generated reader consumes: all of column 0, then column 1, ...
    return struct.pack("<Q", total) + b"".join(col_bufs)


