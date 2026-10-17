"""Cold end-to-end of a proved query as a DuckDB aggregate (LEMMA_COLD_STREAM): build, verify, time against DuckDB answering in place.

  cold_stream_oneshot.py build   --shape NAME --out DIR
  cold_stream_oneshot.py measure --shape NAME --out DIR [--starts 9]       (under `flock /tmp/lemma_timing.lock systemd-run --user --scope -p MemoryMax=6G ...`)

The binary opens the database, registers the proved fold as an aggregate, and times ``SELECT f(cols) FROM t`` (``QUERY_LATENCY_US``: median of its own 9 runs;
``COLD_FIRST_US``: the first execution) next to the ORIGINAL SQL answered by DuckDB itself in the same process and connection (``REFERENCE_INPLACE_US``, median of 9).
``measure`` starts the binary ``--starts`` times and reports the median of each field, the ratio, and the load/other-process CPU of the window (windows with other
processes busy are discarded and rerun, see ``zero_copy_oneshot.timed_window``). Prototype link: the python wheel's DuckDB 1.5.4 C API.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_loop.scripts import zero_copy_oneshot as zo  # noqa: E402

os.environ.setdefault("LEMMA_TPCH_DB", zo.TPCH_DB)  # declarative_round reads the database paths at import time
os.environ.setdefault("LEMMA_DUCKDB_PATH", zo.SEC_DB)
FIX = ROOT / "tests" / "fixtures" / "declarative_proofs"

SHAPES = {
    "sec_sum_decimal38": dict(kind="sec", sql="SELECT SUM(value) AS total FROM num WHERE value > 5000", fixture="cold_sum_filter.rs", narrow=False),
    "sec_count_int": dict(kind="sec", sql="SELECT COUNT(*) AS n FROM num WHERE qtrs = 3", fixture="cold_count_int.rs", narrow=True),
    "tpch_sum_two_cols": dict(kind="tpch", sql="SELECT SUM(l_extendedprice) AS s FROM lineitem WHERE l_quantity < 24", fixture="cold_sum_two_cols.rs", narrow=False),
}


def _env(shape: dict) -> None:
    import lemma_config
    lemma_config.set_cli("cold_stream", True, "this script")
    os.environ["LEMMA_NARROW_CELLS"] = "1" if shape["narrow"] else "0"
    os.environ.pop("LEMMA_PARALLEL_VSTD", None)
    if shape["kind"] == "sec":
        os.environ["LEMMA_DUCKDB_PATH"] = zo.SEC_DB
    else:
        os.environ["LEMMA_TPCH_DB"] = zo.TPCH_DB


def build(name: str, out: Path) -> Path:
    shape = SHAPES[name]
    _env(shape)
    from research_loop import cold_stream
    from research_loop.scripts import declarative_manual as dm
    from research_loop.trust_configs import apply_trust_config

    sql = shape["sql"]
    with apply_trust_config("adversary_declarative0"):
        spec = dm.regenerate_spec(shape["kind"], sql)
    sm = zo.Shape(shape["kind"], sql, "", "", narrow=shape["narrow"])
    model, stored = zo.schema_and_stored(sm)
    prog = cold_stream.assemble_cold_program(
        spec, (FIX / shape["fixture"]).read_text(), db_path=sm.db, schema=model, stored_types=stored, reference_sql=sql
    )
    out.mkdir(parents=True, exist_ok=True)
    return zo._compile(prog, out, "cold", link=True)


def _run(exe: Path) -> dict:
    r = subprocess.run([str(exe)], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{exe} aborted: {r.stderr[-800:]}")
    d = {k: int(v) for k, v in re.findall(r"^(\w+_US|QUERY_LATENCY_BEST_US): (\d+)", r.stdout, re.M)}
    d["settings"] = (re.findall(r"^DUCKDB_SETTINGS: (.*)$", r.stdout, re.M) or [""])[0]
    d["row"] = re.findall(r"^ROW\x1f.*$", r.stdout, re.M)[0]
    d["reference_row"] = re.findall(r"^REFERENCE_ROW\x1f(.*)$", r.stdout, re.M)[0]
    return d


def measure(name: str, out: Path, starts: int) -> dict:
    return zo.timed_window(lambda: _measure(name, out, starts))


def _measure(name: str, out: Path, starts: int) -> dict:
    runs = [_run(out / "cold") for _ in range(starts)]
    med = lambda k: round(statistics.median(r[k] for r in runs))  # noqa: E731
    cold, ref = med("QUERY_LATENCY_US"), med("REFERENCE_INPLACE_US")
    return {
        "shape": name, "sql": SHAPES[name]["sql"], "starts": starts, "cold_median_us": cold, "cold_first_us": med("COLD_FIRST_US"),
        "reference_inplace_us": ref, "ratio_cold_over_inplace": round(cold / ref, 2), "row": runs[0]["row"],
        "rows_agree": len({r["row"] for r in runs}) == 1, "duckdb_settings": runs[0].get("settings", ""), "database": zo.TPCH_DB if SHAPES[name]["kind"] == "tpch" else zo.SEC_DB, "mode": os.environ.get("LEMMA_COLD_STREAM_MODE", "aggregate"),
        # our result against DuckDB's own answer to the original SQL: a DECIMAL result prints with a point, ours is the scaled integer
        "matches_duckdb": all(r["row"].split("\x1f", 1)[1] == r["reference_row"].replace(".", "") for r in runs),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["build", "measure", "all"])
    ap.add_argument("--shape", default="")
    ap.add_argument("--out", default="/home/emil/projects/lemma-db/research_loop/generated/pin_work")
    ap.add_argument("--tag", default="cold")
    ap.add_argument("--only", default="", help="comma-separated shape names (default: all)")
    ap.add_argument("--starts", type=int, default=9)
    a = ap.parse_args()
    if a.cmd == "all":
        # every shape: build (verify + compile), then measure in a recorded quiet window; one JSON line per shape in <out>/<tag>_<shape>.json
        names = [n for n in SHAPES if not a.only or n in a.only.split(",")]
        for name in names:
            build(name, Path(a.out) / f"{a.tag}_{name}_bin")
        for name in names:
            res = measure(name, Path(a.out) / f"{a.tag}_{name}_bin", a.starts)
            (Path(a.out) / f"{a.tag}_{name}.json").write_text(json.dumps(res) + "\n")
            print(json.dumps(res), flush=True)
    elif a.cmd == "build":
        build(a.shape, Path(a.out))
    else:
        print(json.dumps(measure(a.shape, Path(a.out), a.starts)))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("LEMMA_VERUS_BIN", str(ROOT / "scripts" / "ram" / "verus_guarded.sh"))
    raise SystemExit(main())
