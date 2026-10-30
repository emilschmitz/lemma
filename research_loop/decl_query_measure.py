"""Export the tables a query reads and time that SQL in the same database."""

from __future__ import annotations

import datetime as dt
import io
import json
import os
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
import lemma_config
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


DUCK_MEMORY_LIMIT_ENV = lemma_config.env_name("duck_memory_limit")
DUCK_THREADS_ENV = lemma_config.env_name("duck_threads")
MAX_TIE_ROWS = 200_000


def duck_settings(dest: Path) -> dict:
    """The DuckDB settings every host measure connection runs under, so the reference and our side are timed identically.

    DuckDB's default memory limit is about 80% of the machine's RAM, above the container scope's cap (a big scan could be cgroup-OOM-killed):
    ``lemma.toml`` [measure] duck_memory_limit (8GB, checked to stay below [safety] scope_memory_max; spills to ``dest/duck_tmp``) and duck_threads (8),
    recorded in expect.json."""
    return {
        "memory_limit": lemma_config.get("duck_memory_limit"),
        "threads": int(lemma_config.get("duck_threads")),
        "temp_directory": str(dest / "duck_tmp"),
    }


def open_measure_connection(db_path: Path, dest: Path, *, read_only: bool = True) -> tuple[duckdb.DuckDBPyConnection, dict]:
    """Open ``db_path`` under :func:`duck_settings`; returns the connection and the settings applied."""
    settings = duck_settings(dest)
    dest.mkdir(parents=True, exist_ok=True)  # DuckDB creates only the leaf of temp_directory
    con = duckdb.connect(str(db_path), read_only=read_only)
    con.execute(f"PRAGMA memory_limit='{settings['memory_limit']}'")
    con.execute(f"PRAGMA threads={settings['threads']}")
    con.execute(f"PRAGMA temp_directory='{settings['temp_directory']}'")
    return con, settings


def write_query_measure(**kwargs) -> dict:
    """The data export and the DuckDB reference timing: an exclusive heavy phase (see declarative_spec/heavy_phase.py)."""
    from declarative_spec.heavy_phase import heavy_phase

    with heavy_phase("prepare"):
        return _write_query_measure(**kwargs)


def _write_query_measure(
    *,
    sql: str,
    schema: dict,
    catalog: CatalogAssumptions | None,
    db_path: Path,
    dest: Path,
    bindings: list[dict[str, str]] | None = None,
) -> dict:
    """Write one column file per input struct and the DuckDB median for ``sql``.

    A query template (``declarative_spec/templates.py``) needs ``bindings``: the parameter values of the official rounds (round i
    binds ``bindings[i % len]`` on both sides). The prepare-time DuckDB timing, the expected rows and the in-session runs use
    ``bindings[0]``."""
    if not db_path.is_file():
        raise FileNotFoundError(f"measure database missing at {db_path}")
    from declarative_spec import templates

    template = templates.parse_template(sql)
    params0: dict | None = None
    plain_sql = sql
    if template is not None:
        if not bindings:
            raise ValueError("a query template needs parameter bindings for the measure (templates.generate_bindings)")
        for binding in bindings:
            templates.binary_args(template, binding)  # loud on a missing name or a value outside its type
        params0 = templates.python_values(template, bindings[0])
        plain_sql = templates.instantiate(template, bindings[0])
    elif bindings:
        raise ValueError("bindings given for SQL that is not a query template")
    spec = emit_declarative_spec(sql, schema, catalog)
    structs = re.findall(r"pub struct (Cols_[A-Za-z0-9_]+)\s*\{([^}]+)\}", spec)
    out_match = re.search(r"pub struct OutRow\s*\{([^}]+)\}", spec)
    map_match = re.search(r"-> \(res: (?:Option<)?HashMapWithView<(\w+), (\w+)>>?\)", spec)  # Option<..>: assumptions = false, None declines
    string_map_match = re.search(r"-> \(res: (?:Option<)?StringHashMap<(\w+)>>?\)", spec)
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
    # Plan every table's column mapping before the first export: an unmappable field must fail in milliseconds, not after a 1 GB export.
    plans = plan_tables(plain_sql, schema, catalog, spec)  # a template: the fixed-constant SQL of bindings[0]
    # Predicate pushdown (lemma.toml [run] pushdown): the export keeps only rows that can matter (declarative_spec/pushdown.py
    # states the rule and its soundness argument). The reference answer below is still DuckDB on the full original SQL.
    pushdown = None
    wheres: dict[str, str | None] = {suffix: None for suffix in plans}
    # A stream join (docs/STREAM.md): the build tables always get their own pushed conjuncts, as in the extension (in_duckdb.install_executor), and
    # the streamed table never does, whatever `pushdown` says. Unfiltered, TPC-H SF10 Q12's 60M-row build side took the binary to 9 GB (OOM).
    from declarative_spec import stream_join

    stream_builds_only = "pub fn pool_open(" in spec and stream_join.is_join(spec)
    if lemma_config.get("pushdown") or stream_builds_only:
        from declarative_spec.pushdown import plan_pushdown, scan_plan

        pushdown = plan_pushdown(sql, schema, dialect="duckdb")
        if stream_builds_only:
            from research_loop.in_duckdb import stream_builds

            builds = {plans[suffix][0].casefold() for suffix in stream_builds(spec)}
            pushdown.pushed = {table: frags for table, frags in pushdown.pushed.items() if table in builds}
        for suffix, plan in plans.items():
            # A query template: a pushed conjunct may compare with a parameter; the canonical files hold bindings[0] (the in-session
            # runs and the expected rows use it) and every binding gets its own export below (official round i: bindings[i % len]).
            wheres[suffix] = pushdown.bound_where(plan[0], sql, bindings[0] if bindings else None)
    varying = [suffix for suffix, plan in plans.items() if pushdown is not None and pushdown.params(plan[0])]
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "expect.json").unlink(missing_ok=True)  # stale until the export and timing succeed
    (dest / "scan_plan.json").unlink(missing_ok=True)
    # Agent scans (declarative_spec/agent_scan.py): column files of earlier scans describe earlier data; never reuse them.
    scans = "pub fn scan_where_" in spec
    for stale in [*dest.glob("scan_*.bin"), *dest.glob("scan_*.key"), dest / "scan_ctx.pkl", dest / "scan_cmd"]:
        stale.unlink(missing_ok=True)
    shutil.rmtree(dest / "bindings", ignore_errors=True)  # per-binding exports of an earlier prepare
    bins: dict[str, str] = {}
    table_rows: dict[str, int] = {}
    dict_sizes: dict[str, int] = {}  # `<struct suffix>.<column>` -> entries of its dictionary
    dict_entries: dict[str, dict[str, list[str]]] = {}
    try:
        con, duck_cfg = open_measure_connection(db_path, dest)
    except duckdb.Error as exc:
        raise ValueError(str(exc)) from exc
    try:
        for suffix, plan in plans.items():
            path = dest / f"cols_{suffix}.bin"
            part = path.with_suffix(".bin.part")
            with part.open("wb") as fh:
                sizes: dict[str, int] = {}
                dict_entries[suffix] = {}
                table_rows[suffix] = _export_planned_to(
                    con, plan, fh, sizes, where=wheres[suffix], dict_entries=dict_entries[suffix] if scans else None
                )
            dict_sizes.update({f"{suffix}.{col}": n for col, n in sizes.items()})
            part.replace(path)  # a refused export leaves the earlier file, not a truncated one
            bins[suffix] = str(path)
        binding_data = None
        if varying:
            binding_data = _export_bindings(con, dest, plans, varying, pushdown, sql, bindings or [], bins, scans, table_rows, dict_entries)
        if scans:
            from research_loop.scan_export import write_scan_context

            fields = {s.removeprefix("Cols_"): _FIELD.findall(body) for s, body in structs}
            write_scan_context(dest, db_path, duck_cfg, plans, fields, wheres, dict_entries)
        pushdown_info = None
        if pushdown is not None:
            pushdown_info = scan_plan(spec, pushdown, schema, sql)
            for suffix, plan in plans.items():
                entry = pushdown_info["tables"][next(t for t, e in pushdown_info["tables"].items() if e["struct"] == f"Cols_{suffix}")]
                entry["rows_full"] = _count_rows(con, _quote(plan[0]))
                entry["rows_delivered"] = table_rows[suffix]
            (dest / "scan_plan.json").write_text(json.dumps(pushdown_info, indent=1) + "\n", encoding="utf-8")
        scales_match = _OUT_SCALES.search(spec)
        scales = [int(x) for x in scales_match.group(1).split(",")] if scales_match else None
        duck_threads = int(con.execute("SELECT current_setting('threads')").fetchone()[0])
        duck_cfg["memory_limit_effective"] = str(con.execute("SELECT current_setting('memory_limit')").fetchone()[0])
        duck_us, rows, kinds = _time_query(con, sql, out_fields, scales, params0)
        tie_rows = _tie_group_rows(con, plain_sql, rows, out_fields, scales)  # a template: the fixed-constant SQL of bindings[0]
        from declarative_spec.bench import cut_applies, order_info

        order = order_info(plain_sql)
        tie_info = {"order_cols": order["order_cols"], "limited": cut_applies(order, len(rows))}  # in expect.json too: the in-session MCP check reads it
        con.execute("SET threads=1")
        duck1_us = _median_us(con, sql, params0)
    except duckdb.Error as exc:
        raise ValueError(str(exc)) from exc
    finally:
        con.close()
    if not bins:
        raise DeclarativeUnsupported("measure wrote no column files")
    template_info: dict = {}
    if template is not None:
        template_info = {
            "template_bindings": bindings,  # official round i binds bindings[i % len] on both sides
            "binding_args": templates.binary_args(template, bindings[0]),  # the binary's command line for the in-session runs (rows above)
            "row_format": {"out_fields": out_fields, "scales": scales},  # how the official rounds canonicalize DuckDB's rows per binding
        }
    # The in-session run_runquery tool loads this (declarative_spec.bench.load_speed_bar): the agent's
    # runs then use the official column files, the DuckDB bar and the expected result rows.
    expect = {
        "duck_us": duck_us,
        "duck_threads": duck_threads,
        "duck1_us": duck1_us,
        "rows": rows,
        "kinds": kinds,
        "table_rows": table_rows,
        "dict_sizes": dict_sizes,
        "tie_rows": tie_rows,
        **tie_info,
        "duck_settings": duck_cfg,
        "sql": sql,  # the official measure re-times DuckDB on this text, on this file, under duck_settings
        "db_path": str(db_path),
        **template_info,
    }
    if pushdown_info is not None:  # absent with pushdown off: expect.json stays byte-identical
        expect["scan_plan"] = pushdown_info
    if binding_data is not None:  # a template whose pushed predicate binds parameters: one export per binding (activate_binding)
        expect["binding_data"] = binding_data
        for rnd in binding_data["rounds"]:
            for key, n in rnd["dict_sizes"].items():
                dict_sizes[key] = max(dict_sizes.get(key, 0), n)  # the dense-slot budget holds for every round's data
    (dest / "expect.json").write_text(json.dumps(expect) + "\n", encoding="utf-8")
    return {
        **({"scan_plan": pushdown_info} if pushdown_info is not None else {}),
        **({"binding_data": binding_data} if binding_data is not None else {}),
        "bins": bins,
        "duck_us": duck_us,
        "duck_threads": duck_threads,
        "duck1_us": duck1_us,
        "rows": rows,
        "kinds": kinds,
        "table_rows": table_rows,
        "dict_sizes": dict_sizes,
        "tie_rows": tie_rows,
        **tie_info,
        "duck_settings": duck_cfg,
        "sql": sql,
        "db_path": str(db_path),
        **template_info,
    }


def _export_bindings(
    con, dest: Path, plans: dict, varying: list[str], pushdown, sql: str, bindings: list[dict], bins: dict, scans: bool,
    canonical_rows: dict[str, int], canonical_dicts: dict[str, dict[str, list[str]]],
) -> dict:
    """A query template whose pushed predicate binds parameters: the tables in ``varying`` exported once per binding, under
    ``dest/bindings/b<k>/`` (binding 0 is the canonical file, linked there too so it can be restored). Official round i runs on
    binding ``i % len``'s files (:func:`activate_binding` puts them in place before the round; the binary reads fixed paths).
    The row counts differ per binding, so the generated ``main`` does not pin them (``rows_vary``)."""
    rounds: list[dict] = []
    for k, binding in enumerate(bindings):
        out_dir = dest / "bindings" / f"b{k}"
        out_dir.mkdir(parents=True, exist_ok=True)
        rnd: dict = {"bins": {}, "wheres": {}, "table_rows": {}, "dict_sizes": {}, "dict_entries": {}}
        for suffix in varying:
            plan = plans[suffix]
            where = pushdown.bound_where(plan[0], sql, binding)
            path = out_dir / f"cols_{suffix}.bin"
            entries: dict[str, list[str]] = {}
            if k == 0:  # the canonical export (bindings[0]): its rows and dictionaries
                os.link(bins[suffix], path)
                n = canonical_rows[suffix]
                entries = canonical_dicts.get(suffix) or {}
            else:
                sizes: dict[str, int] = {}
                with path.open("wb") as fh:
                    n = _export_planned_to(con, plan, fh, sizes, where=where, dict_entries=entries if scans else None)
                rnd["dict_sizes"].update({f"{suffix}.{col}": m for col, m in sizes.items()})
            rnd["bins"][suffix] = str(path)
            rnd["wheres"][suffix] = where
            rnd["table_rows"][suffix] = n
            rnd["dict_entries"][suffix] = entries
        rounds.append(rnd)
    return {"canonical": {suffix: bins[suffix] for suffix in varying}, "scan_dir": str(dest) if scans else None, "rounds": rounds}


def activate_binding(binding_data: dict, k: int) -> None:
    """Put binding ``k``'s column files (``_export_bindings``) at the canonical paths the binary reads (a hard link renamed over the
    path: atomic, no copy), and point the agent-scan context at that binding's pushed predicate and dictionaries, dropping the scan
    files of the previous binding (they hold other rows). Outside any timed region."""
    import pickle

    rnd = binding_data["rounds"][k]
    for suffix, canonical in binding_data["canonical"].items():
        tmp = Path(canonical + ".swap")
        tmp.unlink(missing_ok=True)
        os.link(rnd["bins"][suffix], tmp)
        os.replace(tmp, canonical)
    if binding_data.get("scan_dir"):
        scan_dir = Path(binding_data["scan_dir"])
        ctx_path = scan_dir / "scan_ctx.pkl"
        ctx = pickle.loads(ctx_path.read_bytes())
        ctx["wheres"].update(rnd["wheres"])
        ctx["dict_entries"].update(rnd["dict_entries"])
        ctx_path.write_bytes(pickle.dumps(ctx))
        for stale in [*scan_dir.glob("scan_*.bin"), *scan_dir.glob("scan_*.key")]:
            stale.unlink()


def plan_tables(sql: str, schema: dict, catalog: CatalogAssumptions | None, spec: str) -> dict[str, tuple]:
    """Column struct suffix -> its export plan (``_plan_table``): which table column each spec field reads, at which type."""
    # A flat (projected) schema carries no table name; the SQL's FROM names it.
    # The emitter parses the exact-integer rewrite of the SQL (a ratio's `/` only parses there), so name the table from it.
    from declarative_spec.numeric_rewrite import rewrite_numeric

    integer_sql, _scales = rewrite_numeric(sql, schema, catalog)
    model = SchemaModel.from_caller(schema, flatten_derived(parse_query(integer_sql)).tables[0]).with_nullable(catalog)
    plans = {}
    for struct_name, body in re.findall(r"pub struct (Cols_[A-Za-z0-9_]+)\s*\{([^}]+)\}", spec):
        suffix = struct_name.removeprefix("Cols_")
        plans[suffix] = _plan_table(model, _table_for_suffix(model, suffix), _FIELD.findall(body))
    return plans


def _tie_group_rows(con, sql: str, rows: list, out_fields: list[tuple[str, str]], scales: list[int] | None) -> list | None:
    """Every row of ``sql`` WITHOUT its LIMIT whose ORDER BY keys equal those of the last kept row; None when the cut cannot fall in a tie group.

    Only for ``ORDER BY <output columns> LIMIT n`` with exactly n rows kept (see ``declarative_spec.bench.order_info``). The row check uses it to accept
    any valid choice among tied rows at the cut, and only those."""
    import sqlglot

    from declarative_spec.bench import order_info

    info = order_info(sql)
    if not (info["limited"] and info["order_cols"] and info.get("limit") == len(rows)) or all(not f for f, _t in out_fields):
        return None
    tree = sqlglot.parse_one(sql)
    tree.set("order", None)
    tree.set("limit", None)
    raw_last = con.execute(sql).fetchall()[-1]
    n = len(out_fields)
    names = ", ".join(f"c{i}" for i in range(n))
    cond = " AND ".join(f"c{i} IS NOT DISTINCT FROM ?" for i in info["order_cols"])
    count_sql = f"SELECT count(*) FROM ({tree.sql(dialect='duckdb')}) AS q({names}) WHERE {cond}"
    params = [raw_last[i] for i in info["order_cols"]]
    size = con.execute(count_sql, params).fetchone()[0]
    if size > MAX_TIE_ROWS:  # a huge tie group would sit in Python memory (the DuckDB cap does not cover it): no tie rows means the strict check
        return None
    got = con.execute(f"SELECT * FROM ({tree.sql(dialect='duckdb')}) AS q({names}) WHERE {cond}", params).fetchall()
    sc = scales if scales is not None else [0] * n
    return [[_canon(out_fields[i][1], record[i], sc[i]) for i in range(n)] for record in got]


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


def _export_planned_to(
    con: duckdb.DuckDBPyConnection,
    plan: tuple,
    sink: BinaryIO,
    dict_sizes: dict[str, int] | None = None,
    *,
    where: str | None = None,
    fixed_dicts: dict[str, list[str]] | None = None,
    dict_entries: dict[str, list[str]] | None = None,
) -> int:
    """Write the column file for ``plan`` to ``sink``; memory is bounded by ``_BATCH_ROWS`` rows (plus the dictionaries), not the table.

    ``dict_sizes``, when given, receives the entry count of every dictionary written (column name -> len), the numbers the host `main` sees.
    ``where`` (pushdown): only the rows on which this predicate is TRUE are delivered, in table order; dictionaries, value checks and the
    row count are those of the delivered rows. ``None`` is the full scan, byte-identical to the export without pushdown."""
    table, names, types, infos, nullable, dict_of, valid_fields = plan
    # The per-column spool files sit beside the destination: /tmp is often RAM (tmpfs), which would put the table back in memory.
    name = getattr(sink, "name", None)
    spool_dir = str(Path(name).parent) if isinstance(name, str) else None
    return _encode_columns(
        con, table, names, types, infos, nullable, dict_of, valid_fields, sink, spool_dir, dict_sizes,
        where=where, fixed_dicts=fixed_dicts, dict_entries=dict_entries,
    )


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


def int_cell_sql(q: str, fty: str, info: ColumnTypeInfo, base: str) -> str:
    """SQL for the integer a cell is loaded as (date: days since 1970-01-01; DECIMAL: the scaled integer); ``q`` is the quoted column.

    The agent-scan translation (research_loop/scan_export.py) compares exactly this expression, so a scan predicate tests the value
    the proved code sees."""
    m = _DECIMAL_TYPE.fullmatch(base)
    if info.is_date:
        return f"CAST({q} - DATE '1970-01-01' AS BIGINT)"
    if m:
        return _decimal_unscaled_sql(q, info.scale, int(m.group(2)), int(m.group(1)))
    if fty == "i128" or base in ("HUGEINT", "UHUGEINT", "UBIGINT"):
        return f"CAST({q} AS HUGEINT)"
    return f"CAST({q} AS BIGINT)"


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
    spool_dir: str | None = None,
    dict_sizes: dict[str, int] | None = None,
    *,
    where: str | None = None,
    fixed_dicts: dict[str, list[str]] | None = None,
    dict_entries: dict[str, list[str]] | None = None,
) -> int:
    """Bulk export to ``sink`` (returns the row count): DuckDB projects every cell at its loaded width, in row batches, as numpy arrays.

    The bytes are those of a per-cell loop over the rows: dictionary codes number the distinct values in order of first
    appearance, a NULL cell of a nullable column is the default cell (code 0 for a dictionary), a NULL in a column the
    catalog does not declare nullable is refused, and so is a value outside its loaded type.
    """
    t = _quote(table)
    # Pushdown: every read of the rows below (dictionaries, value checks, count, batches) sees only the delivered rows.
    and_pushed = f" AND ({where})" if where else ""
    where_pushed = f" WHERE ({where})" if where else ""
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
            if fixed_dicts is not None and names[idx] in fixed_dicts:
                # An agent scan: the codes index the full table's dictionary (scan_where ensures the dictionary is the full table's).
                entries = list(fixed_dicts[names[idx]])
            else:
                # Distinct non-NULL cells in order of first appearance (physical row order), which is the code order.
                rows = con.execute(
                    f"SELECT s FROM (SELECT CAST({q} AS VARCHAR) AS s, min(rowid) AS m FROM {t} WHERE {q} IS NOT NULL{and_pushed} GROUP BY 1) ORDER BY m"
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
                plan[idx], kinds[idx] = int_cell_sql(q, fty, infos[idx], base), "int"
        # A value outside its loaded type is refused before the narrowing cast (which would raise without naming the cell).
        ints = [i for i, k in kinds.items() if k == "int" and types[i] != "i128"]
        if ints:
            bounds = con.execute(f"SELECT {', '.join(f'min({plan[i]}), max({plan[i]})' for i in ints)} FROM {t}{where_pushed}").fetchone()
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
        total = _count_rows(con, t + where_pushed)
        bounds_rowid = con.execute(f"SELECT min(rowid), max(rowid) FROM {t}").fetchone()
        # Column-major layout (all of column 0, then column 1, ...) from a row-batch scan: each column's bytes go to its own
        # temporary file, so memory is bounded by the batch, not the table. The batches are rowid ranges (row-group pruned).
        spools.extend(tempfile.TemporaryFile(dir=spool_dir) for _ in types)  # noqa: SIM115
        seen = 0
        lo = bounds_rowid[0]
        while select and lo is not None and lo <= bounds_rowid[1]:
            hi = lo + _BATCH_ROWS
            arrays = con.execute(f"SELECT {', '.join(select)} FROM {t} WHERE rowid >= {lo} AND rowid < {hi}{and_pushed}").fetchnumpy()
            lo = hi
            n = len(next(iter(arrays.values())))
            seen += n
            for idx, fty in enumerate(types):
                if n and idx not in dict_of:
                    spools[idx].write(_encode_batch(arrays, idx, fty, kinds[idx], nullable[idx], f"{table}.{names[idx]}", null_codes, n))
            del arrays
        if select and seen != total:
            raise ValueError(f"{table}: scanned {seen} rows of {total}")
        _finish(spools, dictionaries, dict_of, null_codes, total, sink)
        if dict_sizes is not None:
            for source in set(dict_of.values()):
                dict_sizes[names[source]] = len(dictionaries[source])
        if dict_entries is not None:
            for source in set(dict_of.values()):
                dict_entries[names[source]] = list(dictionaries[source])
    except duckdb.Error as exc:
        raise ValueError(str(exc)) from exc
    finally:
        for enum in enum_names:
            con.execute(f"DROP TYPE IF EXISTS {enum}")
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
    params: dict | None = None,
) -> tuple[int, list[list[object]], list[str] | None]:
    """``params``: the values bound to a query template's ``$name`` placeholders (None for fixed-constant SQL)."""

    def run():
        return con.execute(sql) if params is None else con.execute(sql, params)

    for _ in range(2):
        run().fetchall()
    samples: list[float] = []
    result: list[tuple] | None = None
    names: list[str] = []
    duck_types: list[str] = []
    for _ in range(5):
        t0 = time.perf_counter()
        cur = run()
        result = cur.fetchall()
        samples.append((time.perf_counter() - t0) * 1_000_000)
        names = [str(col[0]) for col in cur.description]
        duck_types = [str(col[1]) for col in cur.description]
    if result is None:
        raise RuntimeError("no timing sample")
    rows, kinds = canonical_rows(result, names, duck_types, out_fields, scales)
    return int(statistics.median(samples)), rows, kinds


def canonical_rows(
    result: list[tuple],
    names: list[str],
    duck_types: list[str],
    out_fields: list[tuple[str, str]],
    scales: list[int] | None = None,
) -> tuple[list[list[object]], list[str] | None]:
    """DuckDB's result as the row check compares it with the binary's printed rows: ``(rows, kinds)``; kinds None for a map result."""
    indexes: list[int] = []
    if all(not fname for fname, _fty in out_fields):
        if len(names) != len(out_fields):
            raise ValueError(f"map result needs {len(out_fields)} query columns, got {names}")
        indexes = list(range(len(names)))
        kinds = [_kind(fty) for _fname, fty in out_fields]
        if any(k != "int" for k in kinds):
            raise ValueError("map result keys and values must be integers")
        pairs = sorted((_canon(out_fields[0][1], r[0]), _canon(out_fields[1][1], r[1])) for r in result)
        return [[k, v] for k, v in pairs], None
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
    return rows, kinds


def _median_us(con: duckdb.DuckDBPyConnection, sql: str, params: dict | None = None) -> int:
    """Median of five timed runs after two warmups, in the connection's current thread setting."""

    def run():
        return con.execute(sql) if params is None else con.execute(sql, params)

    for _ in range(2):
        run().fetchall()
    samples: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        run().fetchall()
        samples.append((time.perf_counter() - t0) * 1_000_000)
    return int(statistics.median(samples))


def _kind(exec_rust: str) -> str:
    exec_rust = exec_rust.removeprefix("Option<").removesuffix(">")
    if exec_rust == "String":
        return "str"
    if exec_rust in ("f64", "Rat"):  # Rat: an exact rational the binary prints as a double (lemma.toml [sql] exact_division)
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
    if exec_rust in ("f64", "Rat"):
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
