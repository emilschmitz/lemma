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

Verdict: ``median(ours) * speed_bar_mult < median(duck)``; the bar is unchanged.

``measure_in_duckdb`` (lemma.toml ``in_duckdb``): the same interleaved rounds, with our side the whole in-DuckDB round trip
``SELECT * FROM lemma_query('<sql>')`` (scan with the pushed predicate + copy + runtime checks + proved run_query + rows back). With
``pushdown`` and ``agent_scan`` off it is a separate figure next to the verdict. With either on (the defaults) the binary's hot time
excludes DuckDB's filtering (it happened at export), so the binary's rounds are labelled ``hot, excludes scan/filter`` and
``measure_in_duckdb`` is the REPORTED number (:func:`timing_labels`, docs/COMPARABILITY.md). The in-session ``run_runquery`` keeps its
single binary run against the prepare-time DuckDB median and is labelled ``in_session_single_vs_prepare_duck``.

The extension keeps an input cache (``lemma_cache``, db_extension/duckdb_ext/README.md): a repeated call on unchanged data reuses the
converted input buffers. ``measure_in_duckdb`` therefore times our side twice: COLD (the cache is emptied before every timed call: the
first call's cost, scan included) and WARM (the same query and binding just ran: inputs from the cache). The top-level medians and
``speedup`` are the cold ones (what every call cost before the cache), ``cold`` / ``warm`` hold both, and ``verdict.basis`` names the
one the verdict uses (cold).
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
HOT_LABEL = "hot"
HOT_EXCLUDES_SCAN_LABEL = "hot, excludes scan/filter"


def filtering_on() -> bool:
    """lemma.toml ``pushdown`` or ``agent_scan``: DuckDB filters rows for the proved code (at export, or in a scan_where call)."""
    return bool(lemma_config.get("pushdown")) or bool(lemma_config.get("agent_scan"))


def timing_labels() -> dict:
    """What a timed number of the binary means, for every RESULT line and official record (docs/COMPARABILITY.md).

    The binary's hot time starts at ``run_query`` over column files that are already loaded. With ``pushdown`` or ``agent_scan`` on,
    DuckDB did the filtering when it exported those files (or exports them for a scan_where call), so the hot time leaves out work
    DuckDB's reference time includes: it is labelled ``hot, excludes scan/filter`` and is NOT the reported number. The reported
    number is then the in-DuckDB end-to-end measure (:func:`measure_in_duckdb`: the scan with the pushed predicate in the caller's
    snapshot, the hand-over, the checks and ``run_query``, against DuckDB on the same connection). With both off the binary's
    official rounds are the reported number, as before."""
    if filtering_on():
        return {
            "hot_label": HOT_EXCLUDES_SCAN_LABEL,
            "reported_measure": MEASUREMENT_IN_DUCKDB,
            "reported_note": "pushdown/agent_scan on: the binary's hot time excludes DuckDB's scan and filter; report measure_in_duckdb",
        }
    return {"hot_label": HOT_LABEL, "reported_measure": MEASUREMENT_OFFICIAL, "reported_note": ""}


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


# ---- the in-DuckDB path (lemma.toml [engine] in_duckdb): the proved executor called from inside DuckDB, end to end ----

MEASUREMENT_IN_DUCKDB = "in_duckdb_interleaved_medians"
COLD_LABEL = "cold: first call, the extension's input cache emptied before every timed lemma_query (scan included)"
WARM_LABEL = "warm: repeated call, the same query and binding ran just before (inputs from the input cache, no scan)"
VERDICT_BASIS = "cold"
CLEAR_CACHE_SQL = "SELECT * FROM lemma_cache_clear()"
# The extension's error text when the proved run_query returned None (lemma.toml assumptions = false) and lemma_route_unproved is off.
EXTENSION_DECLINED = "Lemma: declined:"


class InDuckdbDeclined(RuntimeError):
    """``lemma_query`` declined in a round (or its warm-up): the proved ``run_query`` returned None on the data."""


def _ours(con, sql: str):
    """``con.execute(sql)`` for OUR side: an extension decline becomes :class:`InDuckdbDeclined` (every other error propagates)."""
    import duckdb

    try:
        return con.execute(sql).fetchall()
    except duckdb.Error as exc:
        if EXTENSION_DECLINED in str(exc):
            raise InDuckdbDeclined(str(exc)) from exc
        raise


def lemma_query_sql(sql: str, binding: dict | None = None) -> str:
    """``SELECT * FROM lemma_query('<sql>')``: the round trip the in-DuckDB measure times.

    A query template takes its binding: one SQL literal per parameter, in declaration order, after the text
    (``lemma_query('<template>', 5, DATE '1995-01-01', 0.05, 'BUILDING')``); the executor checks each against its spec."""
    args = "'" + sql.replace("'", "''") + "'"
    if binding is not None:
        from declarative_spec import templates

        template = templates.parse_template(sql)
        if template is None:
            raise ValueError("a binding for SQL that is not a query template")
        templates.python_values(template, binding)  # names exactly the parameters, each of its type
        args += "".join(", " + templates.sql_literal(p, binding[p.name]) for p in template.params)
    return f"SELECT * FROM lemma_query({args})"


def _median_round(con, sql: str, reps: int, params: dict | None = None, *, ours: bool = False, cold: bool = False) -> int:
    """One round as in :func:`duck_round_timer`: an untimed run, then ``reps`` timed runs (execute + fetchall); their median.
    ``ours``: the ``lemma_query`` side, whose decline is raised as :class:`InDuckdbDeclined` (never timed, never replaced).
    ``cold``: the extension's input cache is emptied (untimed) before every timed run, so each one is a first call."""
    run = (lambda: _ours(con, sql)) if ours else (lambda: con.execute(sql, params).fetchall())
    run()
    samples: list[float] = []
    for _ in range(reps):
        if cold:
            con.execute(CLEAR_CACHE_SQL).fetchall()
        t0 = time.perf_counter()
        run()
        samples.append((time.perf_counter() - t0) * 1_000_000)
    return int(statistics.median(samples))


def in_duckdb_round_timers(
    speed_bar: dict, work_dir: Path, *, extension: Path, home: Path
) -> tuple[Callable[..., int], Callable[..., int], Callable[..., int], Callable[[], None]]:
    """(one COLD round of ``lemma_query``, one WARM round of it, one round of DuckDB, close), all on ONE read-only connection under
    the bar's settings. Cold: the extension's input cache is emptied before every timed call; warm: the round's untimed first call
    fills it and the timed calls reuse it (``lemma_cache`` on).

    ``lemma_query`` is the whole in-DuckDB path: the scan of the needed columns in the caller's snapshot, the copy into the
    executor's buffers, the runtime check of every data assumption, the proved ``run_query`` and the rows back into DuckDB
    vectors. Same rounds and repetitions as :func:`duck_round_timer`. The extension is loaded unsigned.

    A query template (``template_bindings`` in the bar): both timers take the round's binding; ``lemma_query`` gets the values
    as arguments (:func:`lemma_query_sql`), DuckDB runs the template text with them bound to ``$name``."""
    import duckdb

    if not bool(lemma_config.get("in_duckdb")):
        raise ValueError("in_duckdb is off in lemma.toml [engine]: the in-DuckDB measure is not available")
    missing = [key for key in ("sql", "db_path", "duck_settings") if not speed_bar.get(key)]
    if missing:
        raise ValueError(f"speed bar lacks {missing}")
    settings = speed_bar["duck_settings"]
    tmp = work_dir / "duck_official_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(speed_bar["db_path"]), read_only=True, config={"allow_unsigned_extensions": "true"})
    try:
        con.execute(f"PRAGMA memory_limit='{settings['memory_limit']}'")
        con.execute(f"PRAGMA threads={int(settings['threads'])}")
        con.execute(f"PRAGMA temp_directory='{tmp}'")
        con.execute(f"LOAD '{extension}'")
        con.execute(f"SET lemma_home = '{home}'")
        con.execute("SET lemma_cache = true")
    except duckdb.Error as exc:
        con.close()
        raise ValueError(str(exc)) from exc
    sql = str(speed_bar["sql"])
    bindings = speed_bar.get("template_bindings")
    reps = duck_reps()

    def close() -> None:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)

    if bindings:
        from declarative_spec import templates

        template = templates.parse_template(sql)
        if template is None:
            close()
            raise ValueError("the bar has template_bindings but its SQL is not a query template")

        def ours_t(binding: dict) -> int:
            return _median_round(con, lemma_query_sql(sql, binding), reps, ours=True)

        def ours_cold_t(binding: dict) -> int:
            return _median_round(con, lemma_query_sql(sql, binding), reps, ours=True, cold=True)

        def duck_t(binding: dict) -> int:
            return _median_round(con, sql, reps, templates.python_values(template, binding))

        try:
            for _ in range(2):  # warm both sides (and load the executor library once)
                con.execute(sql, templates.python_values(template, bindings[0])).fetchall()
                _ours(con, lemma_query_sql(sql, bindings[0]))
        except BaseException:
            close()
            raise
        return ours_cold_t, ours_t, duck_t, close
    ours_sql = lemma_query_sql(sql)
    try:
        for _ in range(2):  # warm both sides (and load the executor library once)
            con.execute(sql).fetchall()
            _ours(con, ours_sql)
    except BaseException:
        close()
        raise
    return (
        (lambda: _median_round(con, ours_sql, reps, ours=True, cold=True)),
        (lambda: _median_round(con, ours_sql, reps, ours=True)),
        (lambda: _median_round(con, sql, reps)),
        close,
    )


def measure_in_duckdb(
    speed_bar: dict, work_dir: Path, *, extension: Path, home: Path, k: int | None = None, timers: Callable | None = None
) -> dict:
    """K interleaved rounds (alternating which side goes first) of the in-DuckDB path against DuckDB, summarized like the verdict;
    twice: COLD (input cache emptied before every timed call) then WARM (repeated call, inputs from the cache).

    The top-level fields (``ours_median_us``, ``duck_median_us``, ``speedup``, ``ratio_*``, ``rounds``) are the COLD rounds, the
    meaning they had before the cache; ``cold`` and ``warm`` hold both summaries with their labels, and ``verdict`` says which one
    the verdict is (``basis: cold``).

    A query template binds round i to ``template_bindings[i % len]`` on both sides, as the official measure does.
    ``timers`` stands in for :func:`in_duckdb_round_timers` (tests).

    A decline (lemma.toml ``assumptions = false``: the proved ``run_query`` returned None) in ANY round or in the warm-up makes the
    whole result ``status: DECLINED`` with no medians: not a success, not a proof failure, and DuckDB's time is not put in its place."""
    from declarative_spec.decline import STATUS_DECLINED

    def declined(exc: InDuckdbDeclined) -> dict:
        return {"measurement": MEASUREMENT_IN_DUCKDB, "duck_reps": duck_reps(), "status": STATUS_DECLINED, "declined": True, "error": str(exc)}

    try:
        ours_cold, ours_warm, duck, close = (timers or in_duckdb_round_timers)(speed_bar, work_dir, extension=extension, home=home)
    except InDuckdbDeclined as exc:
        return declined(exc)
    rounds_k = official_rounds() if k is None else k
    bindings = speed_bar.get("template_bindings") or None
    try:
        cold = summarize(interleave(ours_cold, duck, rounds_k, bindings))
        warm = summarize(interleave(ours_warm, duck, rounds_k, bindings))
    except InDuckdbDeclined as exc:
        return declined(exc)
    finally:
        close()
    # The scan (with the transpiler's pushed predicate applied inside it) is in our cold time: with pushdown/agent_scan on this is
    # the reported number (timing_labels). The warm time reuses the inputs a previous call converted (same snapshot data).
    return {
        "measurement": MEASUREMENT_IN_DUCKDB,
        "duck_reps": duck_reps(),
        "includes_scan": True,
        "reported": filtering_on(),
        **cold,
        "cold": {"label": COLD_LABEL, **cold},
        "warm": {"label": WARM_LABEL, **warm},
        "verdict": {"basis": VERDICT_BASIS, "label": COLD_LABEL, "speedup": cold["speedup"], "warm_speedup": warm["speedup"]},
    }
