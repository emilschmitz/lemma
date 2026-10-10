"""The official speed verdict: K interleaved rounds, medians, the bar unchanged, the row check first."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from declarative_spec import official_measure as om
from declarative_spec import pipeline


@pytest.fixture(autouse=True)
def _no_heavy_lock(monkeypatch):
    monkeypatch.setenv("LEMMA_HEAVY_LOCK_HELD", "1")  # heavy_phase does nothing; the tests never take the machine-wide lock
    monkeypatch.delenv("LEMMA_OFFICIAL_ROUNDS", raising=False)
    monkeypatch.delenv("LEMMA_SPEED_BAR_MULT", raising=False)


def test_interleave_alternates_which_side_goes_first() -> None:
    log: list[str] = []
    rounds = om.interleave(lambda: (log.append("ours"), 1)[1], lambda: (log.append("duck"), 2)[1], 4)
    assert log == ["ours", "duck", "duck", "ours", "ours", "duck", "duck", "ours"]
    assert [r["order"] for r in rounds] == ["ours_first", "duck_first", "ours_first", "duck_first"]


def test_interleave_odd_k_and_values_per_round() -> None:
    ours, duck = iter([10, 20, 30]), iter([100, 200, 300])
    rounds = om.interleave(lambda: next(ours), lambda: next(duck), 3)
    assert [(r["ours_us"], r["duck_us"]) for r in rounds] == [(10, 100), (20, 200), (30, 300)]
    assert [r["round"] for r in rounds] == [0, 1, 2]


def test_summarize_takes_medians_and_the_speedup_of_the_medians() -> None:
    rounds = [{"ours_us": o, "duck_us": d} for o, d in [(10, 15), (10, 15), (10, 15), (10, 15), (1000, 15)]]
    s = om.summarize(rounds)
    assert (s["ours_median_us"], s["duck_median_us"]) == (10, 15)
    assert s["speedup"] == 1.5  # an outlier round moves neither median


def test_summarize_even_count_and_ratio_of_medians_is_not_median_of_ratios() -> None:
    rounds = [{"ours_us": 10, "duck_us": 10}, {"ours_us": 20, "duck_us": 100}, {"ours_us": 40, "duck_us": 100}, {"ours_us": 50, "duck_us": 100}]
    s = om.summarize(rounds)
    assert s["ours_median_us"] == 30 and s["duck_median_us"] == 100
    assert s["speedup"] == pytest.approx(100 / 30)


def test_rounds_come_from_the_environment(monkeypatch) -> None:
    assert om.official_rounds() == 5
    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "3")
    assert om.official_rounds() == 3
    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "0")
    with pytest.raises(ValueError):
        om.official_rounds()


# ---- the verdict through _apply_speed_bar, with the two timers replaced by scripted numbers -------------------------------------------

_BAR = {"duck_us": 1000, "rows": [[1, 5]], "table_rows": {"t": 1}, "sql": "SELECT 1", "db_path": "x.duckdb", "duck_settings": {"memory_limit": "1GB", "threads": 2}}


def _metrics(tmp_path: Path, stdout: str = "ROW 1 5\n") -> dict:
    binary = tmp_path / "bin"
    binary.write_text("")
    return {
        "status": "SUCCESS", "proof_verified": True, "latency_us": 7, "latency_best_us": 6, "stdout": stdout,
        "binary_path": str(binary), "run_dir": str(tmp_path), "binary_owned": True,
    }


def _script(monkeypatch, ours: list[int], duck: list[int]):
    ours_it, duck_it = iter(ours), iter(duck)
    calls: list[str] = []
    monkeypatch.setattr(pipeline, "run_binary_timed", lambda b, d: (calls.append("ours"), (next(ours_it), 1))[1])
    monkeypatch.setattr(om, "duck_round_timer", lambda bar, wd: (lambda: (calls.append("duck"), next(duck_it))[1], lambda: None))
    return calls


def test_verdict_uses_the_medians_not_the_first_run_or_the_prepare_duck(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "5")
    # the check run (7 us) and the prepare-time DuckDB (1000 us) would pass; the rounds say 200 us vs 150 us: below the bar
    _script(monkeypatch, [200, 200, 200, 200, 5], [150, 150, 150, 150, 150])
    out = pipeline._apply_speed_bar(_metrics(tmp_path), _BAR, official=True)
    assert out["status"] == "FAILURE"
    assert (out["latency_us"], out["duck_us"]) == (200, 150)
    assert "proved but below the speed bar: query 200 us, DuckDB 150 us (0.75x" in out["compiler_error"]
    # and the other direction: one slow outlier round does not fail a fast binary
    _script(monkeypatch, [100, 100, 100, 100, 9000], [150] * 5)
    ok = pipeline._apply_speed_bar(_metrics(tmp_path), _BAR, official=True)
    assert ok["status"] == "SUCCESS" and ok["latency_us"] == 100 and ok["speedup"] == pytest.approx(1.5)


def test_the_bar_multiplier_is_unchanged(tmp_path, monkeypatch) -> None:
    _script(monkeypatch, [100] * 5, [150] * 5)
    assert pipeline._apply_speed_bar(_metrics(tmp_path), _BAR, official=True)["status"] == "SUCCESS"
    monkeypatch.setenv("LEMMA_SPEED_BAR_MULT", "2")
    _script(monkeypatch, [100] * 5, [150] * 5)
    out = pipeline._apply_speed_bar(_metrics(tmp_path), _BAR, official=True)
    assert out["status"] == "FAILURE" and out["speed_bar_mult"] == 2.0
    _script(monkeypatch, [100] * 5, [250] * 5)
    assert pipeline._apply_speed_bar(_metrics(tmp_path), _BAR, official=True)["status"] == "SUCCESS"


def test_every_round_is_recorded_with_its_order(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "3")
    calls = _script(monkeypatch, [11, 12, 13], [21, 22, 23])
    out = pipeline._apply_speed_bar(_metrics(tmp_path), _BAR, official=True)
    assert out["measurement"] == om.MEASUREMENT_OFFICIAL and out["official_k"] == 3
    assert [(r["round"], r["order"], r["ours_us"], r["duck_us"]) for r in out["official_rounds"]] == [
        (0, "ours_first", 11, 21), (1, "duck_first", 12, 22), (2, "ours_first", 13, 23)]
    assert calls == ["ours", "duck", "duck", "ours", "ours", "duck"]
    assert (out["ours_median_us"], out["duck_median_us"]) == (12, 22)
    assert out["check_run_latency_us"] == 7 and out["prepare_duck_us"] == 1000
    assert not Path(out.get("binary_path", "nope")).exists() and "binary_path" not in out  # the kept binary is released


def test_k_rounds_run_k_binary_runs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "7")
    calls = _script(monkeypatch, [10] * 7, [20] * 7)
    out = pipeline._apply_speed_bar(_metrics(tmp_path), _BAR, official=True)
    assert calls.count("ours") == 7 and calls.count("duck") == 7 and len(out["official_rounds"]) == 7


def test_the_row_check_still_runs_first_and_nothing_is_timed_when_it_fails(tmp_path, monkeypatch) -> None:
    calls = _script(monkeypatch, [1] * 5, [100] * 5)
    out = pipeline._apply_speed_bar(_metrics(tmp_path, stdout="ROW 1 6\n"), _BAR, official=True)
    assert out["status"] == "FAILURE" and "result rows differ" in out["compiler_error"]
    assert calls == []
    assert not (tmp_path / "bin").exists()


def test_a_crashing_round_fails_loudly(tmp_path, monkeypatch) -> None:
    def boom(binary, directory):
        raise RuntimeError("segfault in round")

    monkeypatch.setattr(pipeline, "run_binary_timed", boom)
    monkeypatch.setattr(om, "duck_round_timer", lambda bar, wd: (lambda: 1, lambda: None))
    out = pipeline._apply_speed_bar(_metrics(tmp_path), _BAR, official=True)
    assert out["status"] == "FAILURE" and "segfault in round" in out["compiler_error"] and out["latency_us"] == -1


def test_in_session_measure_is_unchanged_and_labelled(tmp_path, monkeypatch) -> None:
    calls = _script(monkeypatch, [], [])
    out = pipeline._apply_speed_bar(_metrics(tmp_path), _BAR)
    assert calls == [] and out["status"] == "SUCCESS"
    assert out["measurement"] == om.MEASUREMENT_IN_SESSION
    assert out["latency_us"] == 7 and out["duck_us"] == 1000 and out["speedup"] == pytest.approx(1000 / 7)
    assert "official_rounds" not in out


def test_the_synthetic_dev_bar_is_measured_the_in_session_way(tmp_path, monkeypatch) -> None:
    calls = _script(monkeypatch, [], [])
    out = pipeline._apply_speed_bar(_metrics(tmp_path), {**_BAR, "synthetic": True}, official=True)
    assert calls == [] and out["measurement"] == om.MEASUREMENT_IN_SESSION


# ---- the DuckDB side on a real (tiny) database --------------------------------------------------------------------------------------------

def test_duck_timer_reruns_the_sql_on_the_prepared_file_under_the_prepared_settings(tmp_path, monkeypatch) -> None:
    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE t AS SELECT range AS k FROM range(1000)")
    con.close()
    monkeypatch.setenv("LEMMA_OFFICIAL_DUCK_REPS", "3")
    bar = {"sql": "SELECT count(*) FROM t", "db_path": str(db), "duck_settings": {"memory_limit": "1GB", "threads": 2}}
    one_round, close = om.duck_round_timer(bar, tmp_path)
    first, second = one_round(), one_round()
    close()
    assert first >= 0 and second >= 0 and isinstance(first, int)


def test_duck_timer_refuses_a_bar_that_cannot_be_retimed(tmp_path) -> None:
    with pytest.raises(ValueError, match="re-run prepare"):
        om.duck_round_timer({"duck_us": 5}, tmp_path)
    with pytest.raises(ValueError, match="re-run prepare"):
        om.duck_round_timer({"sql": "SELECT 1", "db_path": "x"}, tmp_path)


# ---- what reaches the result record and the bar --------------------------------------------------------------------------------------------

def test_official_record_carries_rounds_and_is_absent_for_in_session_runs(tmp_path, monkeypatch) -> None:
    from declarative_spec.drive import official_record

    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "2")
    _script(monkeypatch, [10, 11], [30, 31])
    rec = official_record(pipeline._apply_speed_bar(_metrics(tmp_path), _BAR, official=True))
    assert rec["measurement"] == om.MEASUREMENT_OFFICIAL and len(rec["official_rounds"]) == 2 and rec["speedup"] == pytest.approx(3.0)  # medians 10 and 30
    assert official_record(pipeline._apply_speed_bar(_metrics(tmp_path), _BAR)) is None


def test_the_prepared_bar_names_the_sql_database_and_settings_for_both_result_shapes(tmp_path, monkeypatch) -> None:
    from declarative_spec import drive
    import research_loop.decl_query_measure as dqm

    for kinds in (["int"], None):
        prepared = {
            "bins": {"t": "b"}, "duck_us": 5, "duck_threads": 4, "duck1_us": 9, "rows": [], "kinds": kinds, "table_rows": {"t": 1},
            "dict_sizes": {}, "duck_settings": {"memory_limit": "3GB", "threads": 4}, "sql": "SELECT 1", "db_path": "d.duckdb",
        }
        monkeypatch.setenv("LEMMA_MEASURE_DB", "d.duckdb")
        monkeypatch.setattr(dqm, "write_query_measure", lambda **kw: prepared)
        _, bar = drive._maybe_large_table(sql_query="SELECT 1", catalog=None, workspace=tmp_path, schema={})
        assert (bar["sql"], bar["db_path"], bar["duck_settings"]) == ("SELECT 1", "d.duckdb", {"memory_limit": "3GB", "threads": 4})
