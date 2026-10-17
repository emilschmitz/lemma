"""Zero-copy workspace for ONE query: prepare it for a (manual) prover, check a body, time it. LEMMA_ZERO_COPY is opt-in; nothing here picks a path silently.

  zero_copy_prove.py prepare --sql-file F --ws DIR [--kind sec|tpch]   classify (refuse loudly if unsupported), write the spec and the prover brief
  zero_copy_prove.py check   --ws DIR [--flat FILE]                    admit, assemble, verify, compile, run once; result rows vs the reference engine
  zero_copy_prove.py measure --ws DIR [--flat FILE] [--runs 9]         (under `flock /tmp/lemma_timing.lock`) alternate zero-copy / copy binaries, reference median

The workspace holds ``context/ro/query.sql``, ``context/ro/spec.rs`` (the spec the prover sees: columns are ``PinnedCol``), ``context/ro/PIN_GUIDE.md``,
``context/ro/examples/`` (verified worked bodies) and ``runquery_agent.rs`` (the file the prover edits: ``AGENT_HELPERS`` / ``AGENT_EDIT`` regions).
``--flat FILE`` is a body over the UNCHANGED spec (``Vec`` columns, the manual track's body for the same query): it is assembled in ``copy`` mode
(native C-API loader) as the control, so the comparison is on identical machinery. The prototype links the python wheel's DuckDB 1.5.x C API.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIX = ROOT / "tests" / "fixtures" / "declarative_proofs"
SEC_DB = "/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/duckdb/sec_edgar_dec.duckdb"
TPCH_DB = os.environ.get("LEMMA_TPCH_DB", str(ROOT / "research_loop" / "generated" / "tpch_sf1.duckdb"))
EXAMPLES = [
    "zero_copy_sum_filter.rs", "zero_copy_sum_filter.spec.rs", "zero_copy_sum_filter_parallel.rs", "zero_copy_sum_two_cols.rs", "zero_copy_count_int.rs",
    "zero_copy_sum_filter_flat.rs",
]

GUIDE = """# Zero-copy bodies (LEMMA_ZERO_COPY): `run_query` over borrowed DuckDB chunks

The spec in `spec.rs` is the ordinary declarative spec EXCEPT that every input column is a `PinnedCol<T>` (a column that is a list of slices, the pinned
DuckDB result chunks) instead of a `Vec<T>`. Every spec statement (`t.c@[i]`, `t.c@.len()`) is unchanged, because `t.c@` is the concatenation of the chunks.
Your job is the same as always: fill `AGENT_EDIT` (and `AGENT_HELPERS`) so that Verus proves `run_query` equals the spec. Differences:

* You cannot index a column. Use the chunk fields: `t.c.chunks: Vec<&'static [T]>` (each chunk is a NON-EMPTY slice), `t.c.offs: Vec<usize>` (`offs[k]` is the first
  row of chunk `k`, `offs[m] == n`). Spec-side helper: `t.c.off(k)` (the same as an int). Walk chunk by chunk, row by row (the worked examples do):
  `let c: &[T] = t.col.chunks[k]; let base = t.col.offs[k]; ... c[j] ...` with global row `g = base + j`.
* The ONE proof fact you need is the host lemma `lemma_cell(&t.col, k as int, j as int)`: it ensures `t.col@[t.col.off(k) + j] == t.col.chunks@[k]@[j]`.
  Also host lemmas `lemma_offs_mono(&t.col, a, b)` (off is monotone), `lemma_chunk_count(&t.col, k)` (`off(k) >= k`, so at most one chunk per row).
* Random access `t.col.get(i)` (exec, O(log chunks), `ensures r == t.col@[i]`) exists for probing by row index; scans should walk chunks.
* With several columns of one table the chunks line up: `valid_cols` carries `t.b.offs@ == t.a.offs@`, so chunk `k` of every column has the same length.
* Use `num.value.off(k as int)`-style field paths directly in invariants (an alias `let col = &num.value;` loses the connection to `valid_cols` inside loops).
* Not available: strings, dictionaries, nullable columns, floats, joins (the prover refuses those queries before you start). The parallel shape (spec has `*_arc`
  parameters) splits CHUNK ranges over threads: see `examples/zero_copy_sum_filter_parallel.rs` (the pin is leaked, the slices are `'static`).
* The sequential loop shape that verifies in one pass: descending over chunks `k`, descending over rows `j`, invariant `acc as int == <fold>(num, base + j)`
  and `any <==> exists ...` bounds, exactly as `examples/zero_copy_sum_filter.rs`. Mirror it, then adapt the predicate and the aggregate.
* `check` verifies and runs on the real database through the DuckDB C API. A body that is not `N verified, 0 errors` is not an answer.
"""


def _env(kind: str, narrow: bool = True, parallel: bool = False) -> None:
    os.environ["LEMMA_NARROW_CELLS"] = "1" if narrow else "0"
    if parallel:
        os.environ["LEMMA_PARALLEL_VSTD"] = "1"
    else:
        os.environ.pop("LEMMA_PARALLEL_VSTD", None)
    import lemma_config
    lemma_config.set_cli("zero_copy", True, "this script")
    if kind == "sec":
        os.environ["LEMMA_DUCKDB_PATH"] = SEC_DB
    else:
        os.environ["LEMMA_TPCH_DB"] = TPCH_DB


def _job(ws: Path) -> dict:
    return json.loads((ws / "pin_job.json").read_text())


def _model(sql: str, kind: str):
    import duckdb

    from declarative_spec.schema_types import SchemaModel
    from research_loop.scripts import declarative_manual as dm

    schema, catalog = dm._job_env(kind)
    resolved = dm._project(sql, schema)
    first = re.search(r"\bFROM\s+(\w+)", sql, re.I).group(1)
    model = SchemaModel.from_caller(resolved, first).with_nullable(catalog)
    db = SEC_DB if kind == "sec" else TPCH_DB
    con = duckdb.connect(db, read_only=True)
    tbl = next(t for t in model.original_table_names.values() if t.casefold() == first.casefold())
    stored = {r[0]: r[1] for r in con.execute(f'DESCRIBE "{tbl}"').fetchall()}
    return model, stored, con


def prepare(sql_file: Path, ws: Path, kind: str, parallel: bool) -> None:
    _env(kind, parallel=parallel)
    from research_loop import zero_copy
    from research_loop.scripts import declarative_manual as dm
    from research_loop.trust_configs import apply_trust_config

    sql = sql_file.read_text().strip().rstrip(";")
    with apply_trust_config("adversary_declarative0"):
        spec = dm.regenerate_spec(kind, sql)
    model, stored, con = _model(sql, kind)
    res = zero_copy.resolve(spec, model, stored)  # raises ZeroCopyUnsupported with the exact reason
    rewritten = zero_copy.rewrite_spec(spec)[0]
    ro = ws / "context" / "ro"
    (ro / "examples").mkdir(parents=True, exist_ok=True)
    (ro / "query.sql").write_text(sql + "\n")
    (ro / "spec.rs").write_text(rewritten)
    (ro / "PIN_GUIDE.md").write_text(GUIDE)
    for name in EXAMPLES:
        shutil.copy(FIX / name, ro / "examples" / name)
    skeleton = rewritten  # the markers are in the spec: the prover edits between them
    (ws / "runquery_agent.rs").write_text(skeleton)
    (ws / "pin_job.json").write_text(json.dumps({"kind": kind, "parallel": parallel, "table": res.table, "columns": res.columns}))
    print(f"prepared {ws}: table {res.table} columns {res.columns} parallel={parallel}")


def _expected(sql: str, kind: str, spec: str):
    """(reference median us, expected rows, kinds) exactly as the shipped harness computes them."""
    from research_loop import decl_query_measure as dqm

    model, stored, con = _model(sql, kind)
    out = re.search(r"pub struct OutRow\s*\{([^}]+)\}", spec)
    if out is None:
        raise SystemExit("the zero-copy harness prints OutRow results only")
    out_fields = dqm._OUT.findall(out.group(1))
    sc = dqm._OUT_SCALES.search(spec)
    scales = [int(x) for x in sc.group(1).split(",")] if sc else None
    duck_us, rows, kinds = dqm._time_query(con, sql, out_fields, scales)
    return duck_us, rows, kinds


def _build(ws: Path, name: str, body_file: Path, mode: str, link: bool = True) -> Path:
    from research_loop import zero_copy
    from declarative_spec.admit import admit_declarative_body, admit_helpers
    from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
    from research_loop.scripts import declarative_manual as dm
    from research_loop.scripts import zero_copy_oneshot as zo
    from research_loop.trust_configs import apply_trust_config

    job = _job(ws)
    _env(job["kind"], parallel=job["parallel"])
    sql = (ws / "context" / "ro" / "query.sql").read_text().strip()
    with apply_trust_config("adversary_declarative0"):
        spec = dm.regenerate_spec(job["kind"], sql)
    text = body_file.read_text()
    body, helpers = extract_agent_edit(text), extract_agent_helpers(text)
    shown = zero_copy.rewrite_spec(spec)[0] if mode == "zero_copy" else spec
    bad = list(admit_declarative_body(body).violations) + (list(admit_helpers(helpers, shown).violations) if helpers else [])
    if bad:
        raise SystemExit("ADMISSION: " + "; ".join(bad))
    model, stored, _con = _model(sql, job["kind"])
    db = SEC_DB if job["kind"] == "sec" else TPCH_DB
    prog = zero_copy.assemble_zero_copy_program(spec, body, helpers=helpers, db_path=db, schema=model, stored_types=stored, mode=mode)
    out = ws / "build"
    out.mkdir(exist_ok=True)
    return zo._compile(prog, out, name, link=link)


def _run(exe: Path) -> dict:
    r = subprocess.run([str(exe)], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{exe.name} aborted: {r.stderr[-600:]}")
    nums = {k: int(v) for k, v in re.findall(r"^(\w+_US|QUERY_LATENCY_BEST_US): (\d+)", r.stdout, re.M)}
    nums["stdout"] = r.stdout
    return nums


def _rows_error(stdout: str, expect_rows, kinds) -> str | None:
    from declarative_spec.bench import rows_from_stdout_general, rows_match_error

    return rows_match_error(rows_from_stdout_general(stdout), expect_rows, kinds)


def check(ws: Path, flat: Path | None) -> dict:
    job = _job(ws)
    sql = (ws / "context" / "ro" / "query.sql").read_text().strip()
    exe = _build(ws, "zero", ws / "runquery_agent.rs", "zero_copy")
    from declarative_spec.verus_limits import verus_limit_args  # noqa: F401
    from research_loop.scripts import declarative_manual as dm
    from research_loop.trust_configs import apply_trust_config

    _env(job["kind"], parallel=job["parallel"])
    with apply_trust_config("adversary_declarative0"):
        spec = dm.regenerate_spec(job["kind"], sql)
    duck_us, rows, kinds = _expected(sql, job["kind"], spec)
    z = _run(exe)
    result = {"proved": True, "reference_us": duck_us, "zero_copy": {k: v for k, v in z.items() if k != "stdout"}, "rows_error": _rows_error(z["stdout"], rows, kinds)}
    if flat is not None:
        cexe = _build(ws, "copy", flat, "copy")
        c = _run(cexe)
        result["copy"] = {k: v for k, v in c.items() if k != "stdout"}
        result["copy_rows_error"] = _rows_error(c["stdout"], rows, kinds)
    (ws / "last_check.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result))
    if result["rows_error"] or result.get("copy_rows_error"):
        raise SystemExit("RESULT ROWS DIFFER from the reference engine: " + str(result["rows_error"] or result["copy_rows_error"]))
    return result


def measure(ws: Path, runs: int, with_copy: bool) -> dict:
    from research_loop.scripts import zero_copy_oneshot as zo

    return zo.timed_window(lambda: _measure(ws, runs, with_copy))


def _measure(ws: Path, runs: int, with_copy: bool) -> dict:
    zero, copy = ws / "build" / "zero", ws / "build" / "copy"
    zs, cs = [], []
    for _ in range(runs):
        zs.append(_run(zero))
        if with_copy:
            cs.append(_run(copy))
    job = _job(ws)
    sql = (ws / "context" / "ro" / "query.sql").read_text().strip()
    _env(job["kind"], parallel=job["parallel"])
    from research_loop.scripts import declarative_manual as dm
    from research_loop.trust_configs import apply_trust_config

    with apply_trust_config("adversary_declarative0"):
        spec = dm.regenerate_spec(job["kind"], sql)
    _model_, _stored, con = _model(sql, job["kind"])
    con.execute(sql).fetchall()
    ts = []
    for _ in range(runs):
        t0 = time.perf_counter()
        con.execute(sql).fetchall()
        ts.append((time.perf_counter() - t0) * 1e6)
    ref = round(statistics.median(ts))

    def med(rows, key):
        return round(statistics.median(r[key] for r in rows))

    out = {"reference_us": ref}
    for name, rows in (("zero_copy", zs), ("copy", cs)):
        if not rows:
            continue
        d = {k: med(rows, k) for k in ("PIN_US", "WRAP_US", "CHECK_US", "QUERY_LATENCY_US")}
        d["kernel_us"] = d.pop("QUERY_LATENCY_US")
        d["one_shot_us"] = d["PIN_US"] + d["WRAP_US"] + d["CHECK_US"] + d["kernel_us"]
        out[name] = d
    (ws / "measure.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["prepare", "check", "measure"])
    ap.add_argument("--sql-file")
    ap.add_argument("--ws", required=True)
    ap.add_argument("--kind", default="sec")
    ap.add_argument("--parallel", action="store_true")
    ap.add_argument("--flat")
    ap.add_argument("--runs", type=int, default=9)
    a = ap.parse_args()
    ws = Path(a.ws).resolve()
    if a.cmd == "prepare":
        prepare(Path(a.sql_file), ws, a.kind, a.parallel)
    elif a.cmd == "check":
        check(ws, Path(a.flat) if a.flat else None)
    else:
        measure(ws, a.runs, (ws / "build" / "copy").exists())
    return 0


if __name__ == "__main__":
    os.environ.setdefault("LEMMA_VERUS_BIN", str(ROOT / "scripts" / "ram" / "verus_guarded.sh"))
    raise SystemExit(main())
