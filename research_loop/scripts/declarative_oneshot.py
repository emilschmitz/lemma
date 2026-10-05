"""One-shot cost of a proved declarative query next to the kernel-only number, and the break-even repeat count.

``declarative_oneshot.py --ws WS [--duck-runs 9] [--bin-runs 3]``   (run under ``flock /tmp/lemma_timing.lock systemd-run --user --scope -p MemoryMax=8G ...``)

The workspace must hold a checked body (``check`` was run: ``declarative_build/declarative_query`` and ``decl_data/cols_*.bin`` exist). The job
environment (database, flags, package) comes from the workspace's ``manual_job.json``. Measured, in one window:

* ``pin_encode_us``: the reference engine executes ONE projection that yields exactly the loaded vectors (dates as day numbers, DECIMAL as the scaled integer,
  every cell cast to the narrow loaded width, string columns as dictionary codes via ``enum_code``) and the rows are materialized as numpy arrays.
  This is the pin plus the narrow/dictionary encoding. The dictionary itself (``SELECT DISTINCT``) is counted too.
* ``load_us``: the binary reading the column files into its vectors and checking the cell requirements (the ``LOAD_US`` line the assembled main prints).
* ``kernel_us`` (median of the binary's own 9 runs, median over ``--bin-runs`` binary starts) and ``duck_us`` (median of ``--duck-runs`` runs of the SQL,
  the reference engine scanning its own storage in place, no preparation).

``one_shot_us = pin_encode_us + load_us + kernel_us``: what a first query on freshly pinned data costs. ``break_even_queries`` is the smallest N with
``pin_encode_us + load_us + N * kernel_us < N * duck_us`` (the preparation amortized over N repeated queries), or ``never`` when the kernel is not faster.
The zero-copy lease bridge (no copy, no re-encode) is a possible later trusted proposal; it is not built, these numbers are the copying path.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402

from declarative_spec.schema_types import SchemaModel, rust_ident  # noqa: E402

_FIELD = re.compile(r"pub\s+((?:r#)?[A-Za-z_][A-Za-z0-9_]*):\s+Vec<([^>]+)>")
_NP = {"i8": "int8", "i16": "int16", "i32": "int32", "i64": "int64", "u8": "uint8", "u16": "uint16", "u32": "uint32", "bool": "bool"}
_SQL_INT = {"i8": "TINYINT", "i16": "SMALLINT", "i32": "INTEGER", "i64": "BIGINT", "u8": "UTINYINT", "u16": "USMALLINT", "u32": "UINTEGER", "i128": "HUGEINT"}


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def projections(spec: str, model: SchemaModel) -> list[tuple[str, str, list[str], list[str]]]:
    """(table, enum setup SQL list, select items) per input struct: the SQL that yields exactly the loaded vectors."""
    out = []
    for struct_name, body in re.findall(r"pub struct (Cols_[A-Za-z0-9_]+)\s*\{([^}]+)\}", spec):
        suffix = struct_name.removeprefix("Cols_")
        table = next(t for t in model.tables if rust_ident(t) == suffix or t == suffix)
        _orig, cols = model.lookup_table(table)
        by_ident = {rust_ident(c): c for c in cols}
        setup: list[str] = []
        items: list[str] = []
        for fname, fty in _FIELD.findall(body):
            base = fname.removeprefix("r#")
            if base.endswith("__dict") or base.endswith("__valid"):
                continue
            key = by_ident[base]
            info = cols[key]
            name = _quote(model.original_column_names[(table.casefold(), key)])
            if info.exec_rust == "String":
                enum = f"lemma_enum_{suffix}_{base}"
                setup.append(f"CREATE OR REPLACE TEMP TYPE {enum} AS ENUM (SELECT DISTINCT {name} FROM {_quote(table)} ORDER BY 1)")
                items.append(f"CAST(enum_code(CAST({name} AS {enum})) AS {_SQL_INT[fty]})")
            elif info.is_date:
                items.append(f"CAST({name} - DATE '1970-01-01' AS {_SQL_INT[fty]})")
            elif info.scale:
                items.append(f"CAST({name} * {10 ** info.scale} AS {_SQL_INT[fty]})")
            else:
                items.append(f"CAST({name} AS {_SQL_INT[fty]})")
        out.append((table, setup, items))
    return out


def _median(xs: list[float]) -> float:
    return statistics.median(xs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ws", required=True)
    ap.add_argument("--duck-runs", type=int, default=9)
    ap.add_argument("--bin-runs", type=int, default=3)
    ap.add_argument("--name", default="")
    ap.add_argument("--data", default="")
    a = ap.parse_args()
    ws = Path(a.ws).resolve()
    job = json.loads((ws / "manual_job.json").read_text())
    os.environ.update(job["env"])
    from research_loop.scripts import declarative_manual as dm

    sql = (ws / "context" / "ro" / "query.sql").read_text().strip()
    schema, _catalog = dm._job_env(job["kind"])
    spec = (ws / "context" / "ro" / "spec.rs").read_text()
    resolved = dm._project(sql, schema)
    first_table = re.search(r"\bFROM\s+(\w+)", sql, re.I).group(1)
    model = SchemaModel.from_caller(resolved, first_table)
    db = os.environ.get("LEMMA_DUCKDB_PATH") or os.environ["LEMMA_TPCH_DB"]
    con = duckdb.connect(db, read_only=True)

    # pin + narrow/dictionary encoding: one projection per input table, materialized as numpy.
    pin_encode: list[float] = []
    for _ in range(3):
        t0 = time.perf_counter()
        total_bytes = 0
        for _table, setup, items in projections(spec, model):
            for s in setup:
                con.execute(s)
            arrays = con.execute(f"SELECT {', '.join(items)} FROM {_quote(_table)}").fetchnumpy()
            total_bytes += sum(v.nbytes for v in arrays.values())
        pin_encode.append((time.perf_counter() - t0) * 1e6)
        del arrays

    # the same window: the reference engine and the binary alternate
    exe = ws / "declarative_build" / "declarative_query"
    duck: list[float] = []
    kernels: list[int] = []
    bests: list[int] = []
    loads: list[int] = []
    con.execute("SELECT 1")
    for _ in range(2):  # warm
        con.execute(sql).fetchall()
    for i in range(a.duck_runs):
        t0 = time.perf_counter()
        con.execute(sql).fetchall()
        duck.append((time.perf_counter() - t0) * 1e6)
        if i < a.bin_runs:
            run = subprocess.run([str(exe)], capture_output=True, text=True, check=True)
            kernels.append(int(re.search(r"QUERY_LATENCY_US:\s*(\d+)", run.stdout).group(1)))
            bests.append(int(re.search(r"QUERY_LATENCY_BEST_US:\s*(\d+)", run.stdout).group(1)))
            loads.append(int(re.search(r"LOAD_US:\s*(\d+)", run.stdout).group(1)))
    pe, ld, kern, dk = _median(pin_encode), _median(loads), _median(kernels), _median(duck)
    prep = pe + ld
    result = {
        "name": a.name or ws.name,
        "data": a.data,
        "sql": sql,
        "env": {k: v for k, v in job["env"].items() if k not in ("LEMMA_DUCKDB_PATH", "LEMMA_TPCH_DB")},
        "loaded_bytes": total_bytes,
        "pin_encode_us": round(pe),
        "load_us": round(ld),
        "kernel_us": round(kern),
        "kernel_best_us": min(bests),
        "duck_us": round(dk),
        "one_shot_us": round(prep + kern),
        "kernel_speedup": round(dk / kern, 2),
        "one_shot_speedup": round(dk / (prep + kern), 2),
        "break_even_queries": math.ceil(prep / (dk - kern)) if dk > kern else "never",
    }
    print(json.dumps(result))
    with (ROOT / "research_loop" / "generated" / "decl_oneshot.jsonl").open("a") as fh:
        fh.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
