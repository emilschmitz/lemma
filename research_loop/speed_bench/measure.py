"""Rigorous proved-body vs DuckDB measurement for the speed bench.

For each query and row count: copy ``proved/<id>.rs`` with ``LEMMA_MAX_ROWS`` set to the
row count (the cap is a ``requires`` assumption), run ``verus --compile`` (so Verus checks
the body at that cap), run the compiled binary (it generates the same data as the DuckDB
generator in ``run.py``), and time DuckDB hot with the session open on the same data.

Method: both sides get ``--warmup`` untimed runs and then ``--runs`` timed runs; the
reported number is the median, with min and interquartile range kept in the JSON.
DuckDB is reported at ``--duck-threads`` (default: all cores and 1 thread). Results are
compared by flattening all integers of the result rows.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_loop.speed_bench.queries import QUERIES
from research_loop.speed_bench.run import _duckdb_create
from research_loop.trust_configs import apply_trust_config

PROVED = ROOT / "research_loop/speed_bench/proved"
CACHE = ROOT / "research_loop/speed_bench/.cache/build"
VERUS = Path.home() / "tools/verus/verus"
RUSTC_FLAGS = [
    "-C",
    "opt-level=3",
    "-C",
    "target-cpu=native",
    "-C",
    "panic=abort",
    "-C",
    "codegen-units=1",
]
_CAP_RE = re.compile(r"LEMMA_MAX_ROWS: usize = [0-9_]+;")
_VERIFIED_RE = re.compile(r"verification results:: (\d+) verified, (\d+) errors")


def build(qid: str, rows: int) -> tuple[Path, str]:
    """Verify and compile ``proved/<qid>.rs`` at ``rows``. Returns (binary, verus line)."""
    out = CACHE / str(rows)
    out.mkdir(parents=True, exist_ok=True)
    (orig,) = PROVED.glob(f"{qid.split('_')[0]}_*.rs")
    src = out / orig.name
    text = orig.read_text()
    text, n = _CAP_RE.subn(f"LEMMA_MAX_ROWS: usize = {rows};", text)
    assert n == 1, qid
    src.write_text(text)
    proc = subprocess.run(
        [str(VERUS), str(src), "--compile", "--", *RUSTC_FLAGS],
        capture_output=True,
        text=True,
        cwd=str(out),
        check=False,
    )
    m = _VERIFIED_RE.search(proc.stdout + proc.stderr)
    if proc.returncode != 0 or not m or m.group(2) != "0":
        raise RuntimeError(f"{qid} @ {rows}: verus failed\n{proc.stdout[-3000:]}{proc.stderr[-3000:]}")
    return out / orig.stem, f"{m.group(1)} verified, {m.group(2)} errors"


def _cpu_idle_fraction(window: float = 0.5) -> float:
    def read() -> tuple[int, int]:
        f = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        return f[3] + f[4], sum(f)

    i0, t0 = read()
    time.sleep(window)
    i1, t1 = read()
    return (i1 - i0) / (t1 - t0)


def wait_quiet(idle_min: float, timeout: float) -> tuple[float, bool]:
    """Block until the machine is mostly idle. Returns (idle fraction, reached)."""
    deadline = time.time() + timeout
    while True:
        idle = _cpu_idle_fraction()
        if idle >= idle_min:
            return idle, True
        if time.time() > deadline:
            return idle, False


def _quantiles(samples: list[float]) -> dict[str, float]:
    s = sorted(samples)
    q = statistics.quantiles(s, n=4) if len(s) >= 4 else [s[0], s[len(s) // 2], s[-1]]
    return {"median": statistics.median(s), "min": s[0], "p25": q[0], "p75": q[2]}


def run_binary(binary: Path, rows: int, warmup: int, runs: int) -> dict:
    env = {**os.environ, "SPEED_ROWS": str(rows), "SPEED_WARMUP": str(warmup), "SPEED_RUNS": str(runs)}
    proc = subprocess.run([str(binary)], capture_output=True, text=True, env=env, check=True)
    result = re.search(r"^RESULT:(.+)$", proc.stdout, re.MULTILINE)
    samples = re.search(r"^SAMPLES_US:\[(.+)\]$", proc.stdout, re.MULTILINE)
    overflow = re.search(r"^OVERFLOW:(\d+)$", proc.stdout, re.MULTILINE)
    assert result and samples, proc.stdout[:500]
    assert overflow is None or overflow.group(1) == "0", "overflow slots used"
    ints = [int(x) for x in re.findall(r"\d+", result.group(1))]
    return {"ints": ints, "samples_us": [int(x) for x in samples.group(1).split(",")]}


def time_duckdb(con: duckdb.DuckDBPyConnection, sql: str, warmup: int, runs: int) -> dict:
    for _ in range(warmup):
        con.execute(sql).fetchall()
    samples: list[float] = []
    rows: list[tuple] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        rows = con.execute(sql).fetchall()
        samples.append((time.perf_counter() - t0) * 1e6)
    return {"ints": [int(x) for r in rows for x in r], "samples_us": samples}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=2_000_000)
    ap.add_argument("--runs", type=int, default=21)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--query", action="append", default=None)
    ap.add_argument("--duck-threads", type=int, nargs="+", default=[os.cpu_count() or 1, 1])
    ap.add_argument("--config", default="adversary_imperativespec0")
    ap.add_argument("--interleave", type=int, default=3, help="alternating proved/DuckDB blocks")
    ap.add_argument("--idle-min", type=float, default=0.85, help="start each block only when CPU idle >= this")
    ap.add_argument("--quiet-timeout", type=float, default=120.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    assert args.runs >= 11
    queries = [q for q in QUERIES if args.query is None or q.id in args.query]

    results = []
    with apply_trust_config(args.config):
        con = duckdb.connect()
        _duckdb_create(args.rows, con)
        for q in queries:
            binary, verus_line = build(q.id, args.rows)
            load0 = os.getloadavg()[0]
            # Alternate proved and DuckDB blocks so drift/thermal state hits both sides.
            per_block = max(args.runs // args.interleave, 1)
            proved_samples: list[float] = []
            duck: dict[int, list[float]] = {t: [] for t in args.duck_threads}
            proved_ints: list[int] = []
            duck_ints: dict[int, list[int]] = {}
            idles: list[float] = []
            noisy = False
            for _ in range(args.interleave):
                idle, reached = wait_quiet(args.idle_min, args.quiet_timeout)
                idles.append(round(idle, 3))
                noisy = noisy or not reached
                r = run_binary(binary, args.rows, args.warmup, per_block)
                proved_samples += r["samples_us"]
                proved_ints = r["ints"]
                for t in args.duck_threads:
                    con.execute(f"PRAGMA threads={t}")
                    d = time_duckdb(con, q.sql, args.warmup, per_block)
                    duck[t] += d["samples_us"]
                    duck_ints[t] = d["ints"]
            entry = {
                "id": q.id,
                "noisy": noisy,
                "idle_before_blocks": idles,
                "loadavg_1m_start_end": [load0, os.getloadavg()[0]],
                "rows": args.rows,
                "verus": verus_line,
                "n_samples": len(proved_samples),
                "proved_us": _quantiles(proved_samples),
                "duckdb_us": {str(t): _quantiles(v) for t, v in duck.items()},
                "match": {str(t): proved_ints == duck_ints[t] for t in args.duck_threads},
            }
            entry["speedup_median"] = {
                str(t): entry["duckdb_us"][str(t)]["median"] / entry["proved_us"]["median"]
                for t in args.duck_threads
            }
            results.append(entry)
            print(json.dumps(entry), flush=True)
        con.close()
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
