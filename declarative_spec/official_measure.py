"""The OFFICIAL speed verdict: K interleaved rounds of DuckDB and our compiled binary, compared by their medians.

One binary run against one DuckDB number taken earlier (at prepare) put the verdict inside noise: the same proved TPC-H Q14 binary measured
1.06-1.08x in session and 0.74x in one official re-measure, and DuckDB itself varied 13.4 vs 19.95 ms between runs. Machine state (clocks, page
cache, neighbours) drifts between two measurements taken minutes apart. So the official measure takes both sides back to back, K times, and
alternates which side goes first (an order effect cancels instead of favouring one side):

- ours: one invocation of the compiled binary per round; its figure is the median of the binary's own TIMED_RUNS consecutive timed runs
  (the load of the column files is not timed).
- DuckDB: per round, ``LEMMA_OFFICIAL_DUCK_REPS`` (default 9 = TIMED_RUNS) consecutive executions on a connection that stays open and was warmed
  up, same protocol as ours; the round's figure is their median. Same settings as the bar was prepared under (``duck_settings`` recorded in
  expect.json: threads, memory limit), read-only on the same database file.

Verdict: ``median(ours) * speed_bar_mult < median(duck)``; the bar is unchanged. The in-session ``run_runquery`` keeps its single binary run against the
prepare-time DuckDB median and is labelled ``in_session_single_vs_prepare_duck``.
"""

from __future__ import annotations

import os
import shutil
import statistics
import time
from collections.abc import Callable
from pathlib import Path

ROUNDS_ENV = "LEMMA_OFFICIAL_ROUNDS"
DUCK_REPS_ENV = "LEMMA_OFFICIAL_DUCK_REPS"
DEFAULT_ROUNDS = 5
DEFAULT_DUCK_REPS = 9  # = assemble.TIMED_RUNS: both sides report a median of nine consecutive runs
MEASUREMENT_OFFICIAL = "official_interleaved_medians"
MEASUREMENT_IN_SESSION = "in_session_single_vs_prepare_duck"


def official_rounds() -> int:
    k = int(os.environ.get(ROUNDS_ENV, "").strip() or DEFAULT_ROUNDS)
    if k < 1:
        raise ValueError(f"{ROUNDS_ENV} must be at least 1, got {k}")
    return k


def duck_reps() -> int:
    n = int(os.environ.get(DUCK_REPS_ENV, "").strip() or DEFAULT_DUCK_REPS)
    if n < 1:
        raise ValueError(f"{DUCK_REPS_ENV} must be at least 1, got {n}")
    return n


def interleave(ours: Callable[[], int], duck: Callable[[], int], k: int) -> list[dict]:
    """K rounds, each timing both sides back to back; even rounds run ours first, odd rounds DuckDB first."""
    rounds: list[dict] = []
    for index in range(k):
        ours_first = index % 2 == 0
        if ours_first:
            ours_us = ours()
            duck_us = duck()
        else:
            duck_us = duck()
            ours_us = ours()
        rounds.append({"round": index, "order": "ours_first" if ours_first else "duck_first", "ours_us": ours_us, "duck_us": duck_us})
    return rounds


def summarize(rounds: list[dict]) -> dict:
    """Medians over the rounds and the speedup OF THE MEDIANS (not the median of per-round ratios)."""
    ours_med = int(statistics.median(r["ours_us"] for r in rounds))
    duck_med = int(statistics.median(r["duck_us"] for r in rounds))
    return {
        "ours_median_us": ours_med,
        "duck_median_us": duck_med,
        "speedup": duck_med / max(ours_med, 1),
        "ratio_min": min(r["duck_us"] / max(r["ours_us"], 1) for r in rounds),
        "ratio_max": max(r["duck_us"] / max(r["ours_us"], 1) for r in rounds),
        "rounds": rounds,
    }


def duck_round_timer(speed_bar: dict, work_dir: Path) -> tuple[Callable[[], int], Callable[[], None]]:
    """(time one round of DuckDB in microseconds, close). Opens the database read-only under the settings the bar was prepared with."""
    import duckdb

    missing = [key for key in ("sql", "db_path", "duck_settings") if not speed_bar.get(key)]
    if missing:
        raise ValueError(f"expect.json lacks {missing}: re-run prepare so the official measure can re-time DuckDB")
    settings = speed_bar["duck_settings"]
    tmp = work_dir / "duck_official_tmp"
    tmp.mkdir(parents=True, exist_ok=True)  # DuckDB creates only the leaf of temp_directory
    try:
        con = duckdb.connect(str(speed_bar["db_path"]), read_only=True)
        con.execute(f"PRAGMA memory_limit='{settings['memory_limit']}'")
        con.execute(f"PRAGMA threads={int(settings['threads'])}")
        con.execute(f"PRAGMA temp_directory='{tmp}'")
    except duckdb.Error as exc:
        raise ValueError(str(exc)) from exc
    sql = str(speed_bar["sql"])
    reps = duck_reps()
    for _ in range(2):  # warm: the same two warmups the prepare-time timing takes
        con.execute(sql).fetchall()

    probe: list[float] = []
    for _ in range(reps):
        t0 = time.perf_counter()
        con.execute("SELECT 1").fetchall()
        probe.append((time.perf_counter() - t0) * 1_000_000)

    def one_round() -> int:
        con.execute(sql).fetchall()  # untimed first run: ours starts each round after a load, so DuckDB gets a preamble too
        samples: list[float] = []
        for _ in range(reps):
            t0 = time.perf_counter()
            con.execute(sql).fetchall()
            samples.append((time.perf_counter() - t0) * 1_000_000)
        return int(statistics.median(samples))

    one_round.python_overhead_us = int(statistics.median(probe))  # type: ignore[attr-defined]  # recorded, NOT subtracted (conservative)

    def close() -> None:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)  # spill files of a small memory_limit can be GBs

    return one_round, close
