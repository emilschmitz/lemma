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

import shutil
import statistics
import time
from collections.abc import Callable
from pathlib import Path

import lemma_config

ROUNDS_ENV = lemma_config.env_name("official_rounds")
DUCK_REPS_ENV = lemma_config.env_name("official_duck_reps")  # default 9 = assemble.TIMED_RUNS: both sides report a median of nine consecutive runs
MEASUREMENT_OFFICIAL = "official_interleaved_medians"
MEASUREMENT_IN_SESSION = "in_session_single_vs_prepare_duck"


def official_rounds() -> int:
    return int(lemma_config.get("official_rounds"))


def duck_reps() -> int:
    return int(lemma_config.get("official_duck_reps"))


def interleave(ours: Callable[..., int], duck: Callable[..., int], k: int, bindings: list[dict] | None = None) -> list[dict]:
    """K rounds, each timing both sides back to back; even rounds run ours first, odd rounds DuckDB first.

    ``bindings`` (a query template): round i passes ``bindings[i % len(bindings)]`` to BOTH sides, so each round compares the two
    engines on the same fresh parameter values; the binding is recorded in the round."""
    rounds: list[dict] = []
    for index in range(k):
        ours_first = index % 2 == 0
        args = () if bindings is None else (bindings[index % len(bindings)],)
        if ours_first:
            ours_us = ours(*args)
            duck_us = duck(*args)
        else:
            duck_us = duck(*args)
            ours_us = ours(*args)
        entry = {"round": index, "order": "ours_first" if ours_first else "duck_first", "ours_us": ours_us, "duck_us": duck_us}
        if bindings is not None:
            entry["binding"] = dict(args[0])
        rounds.append(entry)
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


def duck_round_timer(speed_bar: dict, work_dir: Path) -> tuple[Callable[..., int], Callable[[], None]]:
    """(time one round of DuckDB in microseconds, close). Opens the database read-only under the settings the bar was prepared with.

    For a query template (``template_bindings`` in expect.json) a round takes the binding: DuckDB executes the template text as a
    prepared statement with those values bound to ``$name``, and the round's result rows (canonical, as the row check compares
    them) are appended to ``one_round.rows`` (with the binding's LIMIT cut and tie group)."""
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
    template_bindings = speed_bar.get("template_bindings")
    if template_bindings:
        return _template_round_timer(con, sql, speed_bar, template_bindings, reps, tmp)
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


def _template_round_timer(con, sql: str, speed_bar: dict, bindings: list[dict], reps: int, tmp: Path) -> tuple[Callable[[dict], int], Callable[[], None]]:
    """The DuckDB side of a query template's rounds: the same protocol as fixed SQL, with the round's values bound."""
    from declarative_spec import templates
    from declarative_spec.bench import cut_applies, order_info
    from research_loop.decl_query_measure import _tie_group_rows, canonical_rows

    template = templates.parse_template(sql)
    if template is None:
        raise ValueError("expect.json has template_bindings but its SQL is not a query template")
    row_format = speed_bar.get("row_format")
    if not row_format:
        raise ValueError("expect.json lacks row_format: re-run prepare so the official measure can check each binding's rows")
    out_fields = [tuple(f) for f in row_format["out_fields"]]
    scales = row_format.get("scales")
    warm = templates.python_values(template, bindings[0])
    for _ in range(2):
        con.execute(sql, warm).fetchall()
    probe: list[float] = []
    for _ in range(reps):
        t0 = time.perf_counter()
        con.execute("SELECT 1").fetchall()
        probe.append((time.perf_counter() - t0) * 1_000_000)
    rows_log: list[list] = []

    def one_round(binding: dict) -> int:
        params = templates.python_values(template, binding)
        cur = con.execute(sql, params)  # untimed first run, as for fixed SQL; its rows are this binding's expected rows
        result = cur.fetchall()
        names = [str(col[0]) for col in cur.description]
        types = [str(col[1]) for col in cur.description]
        rows = canonical_rows(result, names, types, out_fields, scales)[0]
        plain = templates.instantiate(template, binding)  # the same query as fixed-constant SQL: its LIMIT cut and tie group
        rows_log.append({"rows": rows, "limited": cut_applies(order_info(plain), len(rows)), "tie_rows": _tie_group_rows(con, plain, rows, out_fields, scales)})
        samples: list[float] = []
        for _ in range(reps):
            t0 = time.perf_counter()
            con.execute(sql, params).fetchall()
            samples.append((time.perf_counter() - t0) * 1_000_000)
        return int(statistics.median(samples))

    one_round.python_overhead_us = int(statistics.median(probe))  # type: ignore[attr-defined]
    one_round.rows = rows_log  # type: ignore[attr-defined]

    def close() -> None:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)

    return one_round, close
