"""Zero-copy lease: build, verify and time proved queries on three load paths, one shape at a time (LEMMA_ZERO_COPY is opt-in).

  zero_copy_oneshot.py build   --shape NAME --out DIR
  zero_copy_oneshot.py measure --shape NAME --out DIR [--runs 9] [--export-runs 3]     (run under `flock /tmp/lemma_timing.lock systemd-run --user --scope -p MemoryMax=6G ...`)
  zero_copy_oneshot.py shapes

Three programs per shape, each a Verus-proved `run_query` for the SAME SQL, linked and timed in one window:

* ``shipped``:   the harness path as it is on main: the streaming bulk exporter (`decl_query_measure._export_planned_to`) writes the column file, the
  binary reads and checks it (``LOAD_US``), then the kernel.
* ``copy``:      the native loader: the binary pins the SELECT through the DuckDB C API (``PIN_US``) and copies the chunks into one ``Vec`` per column
  (``WRAP_US``), checks (``CHECK_US``), kernel. No Python, no file, no new trust beyond the pin statement's `main` code.
* ``zero_copy``: the same pin, borrowed slices instead of a copy (``WRAP_US`` is only building the slice list), checks, kernel. Trusted statement ZC-1.

``one_shot_us`` = what a first query costs: shipped = export + LOAD_US + kernel; copy/zero_copy = PIN + WRAP + CHECK + kernel. ``kernel_us`` is the binary's own
median of 9 runs; the reference engine (python duckdb 1.5.x, in place, no preparation) is the median of ``--runs`` runs. ``break_even`` is the smallest number of
repeated queries N with ``prep + N * kernel < N * reference`` (``never`` if the kernel is not faster).

PROTOTYPE LINK: the binaries link the C API exported by the python `duckdb` wheel (1.5.x, the reference engine's own library) plus libpython, see
``python_wheel_link``; the repo's `build/libduckdb` is 1.2.x and cannot open the 1.5.x databases.
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
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIX = ROOT / "tests" / "fixtures" / "declarative_proofs"
SEC_DB = "/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/duckdb/sec_edgar_dec.duckdb"
TPCH_DB = os.environ.get("LEMMA_TPCH_DB", str(ROOT / "research_loop" / "generated" / "tpch_sf1.duckdb"))


@dataclass(frozen=True)
class Shape:
    kind: str  # sec | tpch
    sql: str
    zero_body: str
    flat_body: str
    narrow: bool = False
    parallel: bool = False

    @property
    def db(self) -> str:
        return SEC_DB if self.kind == "sec" else TPCH_DB


SHAPES: dict[str, Shape] = {
    "sec_sum_decimal38": Shape("sec", "SELECT SUM(value) AS total FROM num WHERE value > 5000", "zero_copy_sum_filter.rs", "zero_copy_sum_filter_flat.rs"),
    "sec_sum_decimal38_parallel": Shape(
        "sec", "SELECT SUM(value) AS total FROM num WHERE value > 5000", "zero_copy_sum_filter_parallel.rs", "zero_copy_sum_filter_parallel_flat.rs", parallel=True
    ),
    "sec_count_int": Shape("sec", "SELECT COUNT(*) AS n FROM num WHERE qtrs = 3", "zero_copy_count_int.rs", "zero_copy_count_int_flat.rs", narrow=True),
    "tpch_sum_two_cols": Shape(
        "tpch", "SELECT SUM(l_extendedprice) AS s FROM lineitem WHERE l_quantity < 24", "zero_copy_sum_two_cols.rs", "zero_copy_sum_two_cols_flat.rs"
    ),
}


def python_wheel_link(workdir: Path) -> tuple[Path, list[str]]:
    """PROTOTYPE ONLY: link the C API of the python `duckdb` wheel (the reference engine's own DuckDB, 1.5.x), which exports it, instead of the
    repo's libduckdb (1.2.x). Needs the interpreter's libpython (the wheel's undefined Python symbols). A real build links a libduckdb 1.5.x release."""
    import sysconfig

    import _duckdb

    lib = workdir / "lib154"
    lib.mkdir(parents=True, exist_ok=True)
    link = lib / "libduckdb.so"
    link.unlink(missing_ok=True)
    link.symlink_to(Path(_duckdb.__file__).resolve())
    libdir = Path(sysconfig.get_config_var("LIBDIR"))
    libpython = libdir / sysconfig.get_config_var("LDLIBRARY")
    return lib, ["-C", "link-arg=-Wl,--no-as-needed", "-C", f"link-arg={libpython}", "-C", f"link-arg=-Wl,-rpath,{libdir}", "-C", "link-arg=-Wl,--allow-shlib-undefined"]


def _env(shape: Shape) -> None:
    os.environ["LEMMA_NARROW_CELLS"] = "1" if shape.narrow else "0"
    if shape.parallel:
        os.environ["LEMMA_PARALLEL_VSTD"] = "1"
    else:
        os.environ.pop("LEMMA_PARALLEL_VSTD", None)
    import lemma_config
    lemma_config.set_cli("zero_copy", True, "this script")
    if shape.kind == "sec":
        os.environ["LEMMA_DUCKDB_PATH"] = SEC_DB
    else:
        os.environ["LEMMA_TPCH_DB"] = TPCH_DB


def schema_and_stored(shape: Shape):
    """The declared schema model of the job and the stored types of the database (DESCRIBE), for the zero-copy assembler."""
    import duckdb

    from declarative_spec.schema_types import SchemaModel
    from research_loop.scripts import declarative_manual as dm

    schema, catalog = dm._job_env(shape.kind)
    resolved = dm._project(shape.sql, schema)
    first_table = re.search(r"\bFROM\s+(\w+)", shape.sql, re.I).group(1)
    model = SchemaModel.from_caller(resolved, first_table).with_nullable(catalog)
    con = duckdb.connect(shape.db, read_only=True)
    stored = {r[0]: r[1] for r in con.execute(f"DESCRIBE {first_table}").fetchall()}
    return model, stored


def _compile(program: str, out: Path, name: str, link: bool) -> Path:
    from declarative_spec.pipeline import target_cpu_rustc_args  # LEMMA_TARGET_CPU, default x86-64-v3 (AVX2), like the shipped pipeline

    rs = out / f"{name}.rs"
    rs.write_text(program)
    cmd = [str(ROOT / "scripts" / "ram" / "verus_guarded.sh"), str(rs), "--triggers-mode", "silent", "--rlimit", "3", "--compile", "--", "-C", "opt-level=3", "-C", "codegen-units=1", *target_cpu_rustc_args()]
    if link:
        lib, extra = python_wheel_link(out)
        cmd += ["-L", str(lib), "-C", f"link-arg=-Wl,-rpath,{lib}", *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=out, timeout=1800)
    txt = proc.stdout + proc.stderr
    (out / f"{name}.build.log").write_text(txt)
    verified = re.search(r"verification results:: (\d+) verified, (\d+) errors", txt)
    print(name, verified.group(0) if verified else txt[-2000:])
    if proc.returncode != 0 or not verified or verified.group(2) != "0":
        print(txt[-3000:])
        raise SystemExit(1)
    return out / name


def build(shape_name: str, out: Path) -> None:
    shape = SHAPES[shape_name]
    _env(shape)  # before the imports: declarative_round reads the database paths at import time
    from declarative_spec import assemble as asm
    from research_loop import zero_copy
    from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
    from research_loop.scripts import declarative_manual as dm
    from research_loop.trust_configs import apply_trust_config

    out.mkdir(parents=True, exist_ok=True)
    with apply_trust_config("adversary_declarative0"):
        spec = dm.regenerate_spec(shape.kind, shape.sql)
        model, stored = schema_and_stored(shape)
    zbody, fbody = (FIX / shape.zero_body).read_text(), (FIX / shape.flat_body).read_text()
    for mode, body, name in (("zero_copy", zbody, "zero"), ("copy", fbody, "copy")):
        prog = zero_copy.assemble_zero_copy_program(
            spec, extract_agent_edit(body), helpers=extract_agent_helpers(body), db_path=shape.db, schema=model, stored_types=stored, mode=mode
        )
        _compile(prog, out, name, link=True)
    suffix, _fields = zero_copy._single_table(spec)
    shipped = asm.assemble_declarative_program(
        spec, extract_agent_edit(fbody), helpers=extract_agent_helpers(fbody), column_bins={suffix: str(out / f"cols_{suffix}.bin")}
    )
    _compile(shipped, out, "shipped", link=False)


def _run(exe: Path) -> dict:
    r = subprocess.run([str(exe)], capture_output=True, text=True, check=True)
    nums = {k: int(v) for k, v in re.findall(r"^(\w+_US|QUERY_LATENCY_BEST_US): (\d+)", r.stdout, re.M)}
    nums["rows"] = re.findall(r"^ROW.*$", r.stdout, re.M)
    return nums


def _export_us(shape: Shape, out: Path, runs: int) -> list[float]:
    """The shipped exporter (streaming bulk), timed end to end including the file write."""
    import duckdb

    from research_loop import zero_copy
    from declarative_spec.schema_types import SchemaModel
    from research_loop import decl_query_measure as dqm
    from research_loop.scripts import declarative_manual as dm
    from research_loop.trust_configs import apply_trust_config

    with apply_trust_config("adversary_declarative0"):
        spec = dm.regenerate_spec(shape.kind, shape.sql)
        schema, catalog = dm._job_env(shape.kind)
        resolved = dm._project(shape.sql, schema)
    first_table = re.search(r"\bFROM\s+(\w+)", shape.sql, re.I).group(1)
    model = SchemaModel.from_caller(resolved, first_table).with_nullable(catalog)
    suffix, fields = zero_copy._single_table(spec)
    plan = dqm._plan_table(model, dqm._table_for_suffix(model, suffix), fields)
    times = []
    for _ in range(runs):
        con = duckdb.connect(shape.db, read_only=True)
        t0 = time.perf_counter()
        path = out / f"cols_{suffix}.bin"
        part = path.with_suffix(".bin.part")
        with part.open("wb") as fh:
            dqm._export_planned_to(con, plan, fh)
        part.replace(path)
        times.append((time.perf_counter() - t0) * 1e6)
        con.close()
    return times


MAX_LOAD = float(os.environ.get("LEMMA_ZC_MAX_LOAD", "3"))


def wait_quiet(max_wait_s: int = 3600) -> float:
    """Block until the 1-minute load average is below MAX_LOAD (the box is shared; a DuckDB all-core timing under load is invalid)."""
    t0 = time.time()
    while os.getloadavg()[0] >= MAX_LOAD:
        if time.time() - t0 > max_wait_s:
            raise SystemExit(f"load average stayed above {MAX_LOAD} for {max_wait_s}s: no valid timing window")
        time.sleep(20)
    return os.getloadavg()[0]


def _busy_seconds() -> float:
    """CPU seconds busy (not idle, not iowait) summed over all cores since boot, from /proc/stat."""
    f = open("/proc/stat").readline().split()[1:]
    vals = [int(x) for x in f]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    return (sum(vals[:8]) - idle) / os.sysconf("SC_CLK_TCK")


def _own_cpu_seconds() -> float:
    t = os.times()
    return t.user + t.system + t.children_user + t.children_system


MAX_OTHERS = float(os.environ.get("LEMMA_ZC_MAX_OTHERS_CORES", "1.5"))


def timed_window(fn, attempts: int = 3) -> dict:
    """Run ``fn`` in a quiet window. Quiet = the 1-minute load average is below MAX_LOAD BEFORE the window and the CPU the OTHER processes of the
    box used DURING it (all-core busy time minus this job's own CPU time, over the wall time) is below MAX_OTHERS cores; else the result is discarded and
    rerun. Both numbers are recorded in the result (the load average alone would count this job's own 8-thread phases as foreign load)."""
    for _ in range(attempts):
        before = wait_quiet()
        b0, o0, t0 = _busy_seconds(), _own_cpu_seconds(), time.time()
        out = fn()
        wall = time.time() - t0
        others = ((_busy_seconds() - b0) - (_own_cpu_seconds() - o0)) / wall
        if others < MAX_OTHERS:
            out["load_1min_before"], out["others_cpu_cores_during"] = round(before, 2), round(others, 2)
            return out
        print(f"discarding a measurement: other processes used {others:.1f} cores during the window", file=sys.stderr)
    raise SystemExit("no valid timing window in the attempts")


def measure(shape_name: str, out: Path, runs: int, export_runs: int) -> dict:
    return timed_window(lambda: _measure(shape_name, out, runs, export_runs))


def _measure(shape_name: str, out: Path, runs: int, export_runs: int) -> dict:
    import duckdb

    shape = SHAPES[shape_name]
    _env(shape)
    export = _export_us(shape, out, export_runs)
    res: dict[str, list[dict]] = {"shipped": [], "copy": [], "zero_copy": []}
    for _ in range(runs):
        res["shipped"].append(_run(out / "shipped"))
        res["copy"].append(_run(out / "copy"))
        res["zero_copy"].append(_run(out / "zero"))
    con = duckdb.connect(shape.db, read_only=True)
    con.execute(shape.sql).fetchall()
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter()
        con.execute(shape.sql).fetchall()
        samples.append((time.perf_counter() - t0) * 1e6)
    ref = statistics.median(samples)

    def med(rows: list[dict], key: str) -> int:
        return round(statistics.median(r[key] for r in rows))

    out_json: dict = {"shape": shape_name, "sql": shape.sql, "runs": runs, "export_runs": export_runs, "reference_us": round(ref)}
    out_json["rows_agree"] = res["shipped"][0]["rows"] == res["copy"][0]["rows"] == res["zero_copy"][0]["rows"]
    out_json["rows"] = res["zero_copy"][0]["rows"]
    ship = {"export_us": round(statistics.median(export)), "LOAD_US": med(res["shipped"], "LOAD_US"), "kernel_us": med(res["shipped"], "QUERY_LATENCY_US")}
    ship["prep_us"] = ship["export_us"] + ship["LOAD_US"]
    out_json["shipped"] = ship
    for name in ("copy", "zero_copy"):
        d = {k: med(res[name], k) for k in ("PIN_US", "WRAP_US", "CHECK_US", "QUERY_LATENCY_US")}
        d["kernel_us"] = d.pop("QUERY_LATENCY_US")
        d["prep_us"] = d["PIN_US"] + d["WRAP_US"] + d["CHECK_US"]
        out_json[name] = d
    for name in ("shipped", "copy", "zero_copy"):
        d = out_json[name]
        d["one_shot_us"] = d["prep_us"] + d["kernel_us"]
        d["break_even"] = math.ceil(d["prep_us"] / (ref - d["kernel_us"])) if ref > d["kernel_us"] else "never"
    return out_json


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["build", "measure", "shapes"])
    ap.add_argument("--shape")
    ap.add_argument("--out")
    ap.add_argument("--runs", type=int, default=9)
    ap.add_argument("--export-runs", type=int, default=3)
    a = ap.parse_args()
    if a.cmd == "shapes":
        print(json.dumps({k: v.sql for k, v in SHAPES.items()}, indent=1))
    elif a.cmd == "build":
        build(a.shape, Path(a.out))
    else:
        print(json.dumps(measure(a.shape, Path(a.out), a.runs, a.export_runs)))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("LEMMA_VERUS_BIN", str(ROOT / "scripts" / "ram" / "verus_guarded.sh"))
    raise SystemExit(main())
