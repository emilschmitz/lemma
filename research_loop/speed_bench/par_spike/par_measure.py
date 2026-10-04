"""Measure the vstd-thread parallel proved bodies (par_spike/q0N_par.rs) against the
single-threaded proved bodies (proved/q0N_*.rs) and DuckDB at 8 and 1 threads.

Same method as ../measure.py: LEMMA_MAX_ROWS is set to the row count, verus --compile
checks and builds each binary, blocks of proved / parallel / DuckDB runs are interleaved,
each block starts only when the CPU is mostly idle, the reported number is the median of
all samples. Parallel binaries take SPEED_THREADS workers and own one chunk each.

Run from the repo root with the repo's python that has duckdb:
  python research_loop/speed_bench/par_spike/par_measure.py --rows 20000000 --out r20M.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from research_loop.speed_bench import measure as M  # noqa: E402
from research_loop.speed_bench.queries import QUERY_BY_ID  # noqa: E402
from research_loop.speed_bench.run import _duckdb_create  # noqa: E402
from research_loop.trust_configs import apply_trust_config  # noqa: E402

PAIRS = {"q01_par": "q01_filter_sum", "q03_par": "q03_group_sum", "q04_par": "q04_group_count"}
CACHE = HERE / ".cache"


def build_par(name: str, rows: int) -> tuple[Path, str]:
    out = CACHE / str(rows)
    out.mkdir(parents=True, exist_ok=True)
    src = out / f"{name}.rs"
    text, n = M._CAP_RE.subn(f"LEMMA_MAX_ROWS: usize = {rows};", (HERE / f"{name}.rs").read_text())
    assert n == 1
    src.write_text(text)
    proc = subprocess.run(
        [str(M.VERUS), str(src), "--triggers-mode", "silent", "--compile", "--", *M.RUSTC_FLAGS],
        capture_output=True,
        text=True,
        cwd=str(out),
        check=False,
    )
    m = M._VERIFIED_RE.search(proc.stdout + proc.stderr)
    if proc.returncode != 0 or not m or m.group(2) != "0":
        raise RuntimeError(f"{name} @ {rows}: verus failed\n{proc.stdout[-3000:]}{proc.stderr[-3000:]}")
    return out / name, f"{m.group(1)} verified, {m.group(2)} errors"


def run_bin(binary: Path, rows: int, warmup: int, runs: int, threads: int | None) -> dict:
    env = {**os.environ, "SPEED_ROWS": str(rows), "SPEED_WARMUP": str(warmup), "SPEED_RUNS": str(runs)}
    if threads is not None:
        env["SPEED_THREADS"] = str(threads)
    proc = subprocess.run([str(binary)], capture_output=True, text=True, env=env, check=True)
    result = re.search(r"^RESULT:(.+)$", proc.stdout, re.MULTILINE)
    samples = re.search(r"^SAMPLES_US:\[(.+)\]$", proc.stdout, re.MULTILINE)
    overflow = re.search(r"^OVERFLOW:(\d+)$", proc.stdout, re.MULTILINE)
    assert result and samples, proc.stdout[:500]
    assert overflow is None or overflow.group(1) == "0"
    ints = [int(x) for x in re.findall(r"\d+", result.group(1))]
    return {"ints": ints, "samples_us": [int(x) for x in samples.group(1).split(",")]}


def norm(qid: str, ints: list[int]) -> list:
    if qid.startswith("q01"):
        return ints
    return sorted(zip(ints[0::2], ints[1::2]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, required=True)
    ap.add_argument("--runs", type=int, default=15)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--interleave", type=int, default=3)
    ap.add_argument("--threads", type=int, nargs="+", default=[1, 2, 4, 8])
    ap.add_argument("--idle-min", type=float, default=0.70)
    ap.add_argument("--quiet-timeout", type=float, default=180.0)
    ap.add_argument("--query", action="append", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    assert args.runs >= 11
    per_block = max(args.runs // args.interleave, 1)
    results = []
    with apply_trust_config("adversary_imperativespec0"):
        con = duckdb.connect()
        _duckdb_create(args.rows, con)
        for pname, qid in PAIRS.items():
            if args.query and qid not in args.query:
                continue
            single_bin, single_verus = M.build(qid, args.rows)
            par_bin, par_verus = build_par(pname, args.rows)
            sql = QUERY_BY_ID[qid].sql
            samples: dict[str, list[float]] = {"single": []}
            samples.update({f"par{t}": [] for t in args.threads})
            samples.update({"duck8": [], "duck1": []})
            ints: dict[str, list] = {}
            idles: list[float] = []
            noisy = False
            for _ in range(args.interleave):
                idle, reached = M.wait_quiet(args.idle_min, args.quiet_timeout)
                idles.append(round(idle, 3))
                noisy = noisy or not reached
                r = run_bin(single_bin, args.rows, args.warmup, per_block, None)
                samples["single"] += r["samples_us"]
                ints["single"] = norm(qid, r["ints"])
                for t in args.threads:
                    r = run_bin(par_bin, args.rows, args.warmup, per_block, t)
                    samples[f"par{t}"] += r["samples_us"]
                    ints[f"par{t}"] = norm(qid, r["ints"])
                for t in (8, 1):
                    con.execute(f"PRAGMA threads={t}")
                    d = M.time_duckdb(con, sql, args.warmup, per_block)
                    samples[f"duck{t}"] += d["samples_us"]
                    ints[f"duck{t}"] = norm(qid, d["ints"])
            q = {k: M._quantiles(v) for k, v in samples.items()}
            med = {k: v["median"] for k, v in q.items()}
            entry = {
                "id": qid,
                "rows": args.rows,
                "noisy": noisy,
                "idle_before_blocks": idles,
                "verus_single": single_verus,
                "verus_par": par_verus,
                "n_samples": len(samples["single"]),
                "us": q,
                "match_duck8": {k: ints[k] == ints["duck8"] for k in ints},
                "speedup_vs_single": {k: med["single"] / med[k] for k in med if k.startswith("par")},
                "speedup_vs_duck8": {k: med["duck8"] / med[k] for k in med if k.startswith("par") or k == "single"},
                "speedup_vs_duck1": {k: med["duck1"] / med[k] for k in med if k.startswith("par") or k == "single"},
            }
            results.append(entry)
            print(json.dumps(entry), flush=True)
        con.close()
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
