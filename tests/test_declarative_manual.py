"""Path handling of the manual-prover harness, and the expect.json that run_runquery loads."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from declarative_spec.bench import load_speed_bar
from research_loop.decl_query_measure import write_query_measure
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions
from research_loop.scripts.declarative_manual import _abs


def test_relative_path_resolves_against_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "ws").mkdir()
    monkeypatch.chdir(tmp_path)
    assert _abs("ws", "--ws") == (tmp_path / "ws").resolve()


def test_missing_path_exits_with_a_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="--sql-file 'nope.sql' does not exist"):
        _abs("nope.sql", "--sql-file")


@pytest.mark.parametrize(
    ("sql", "rows"),
    [
        ("SELECT k, COUNT(*) AS c FROM t GROUP BY k", [[1, 2], [2, 1]]),
        ("SELECT k, SUM(k) AS s FROM t GROUP BY k", [[1, 2], [2, 2]]),
    ],
)
def test_measure_writes_expect_json_that_load_speed_bar_reads(tmp_path: Path, sql: str, rows: list) -> None:
    db = tmp_path / "m.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE t (k INTEGER)")
    con.execute("INSERT INTO t VALUES (1), (1), (2)")
    con.close()
    prepared = write_query_measure(
        sql=sql, schema={"t": {"k": "integer"}}, catalog=_CAT, db_path=db, dest=tmp_path / "decl_data",
    )
    loaded = load_speed_bar(tmp_path / "decl_data")
    assert loaded is not None
    bins, bar = loaded
    assert bins == prepared["bins"]
    assert bar["table_rows"] == {"t": 3}
    assert bar["duck_us"] == prepared["duck_us"]
    assert bar["duck1_us"] == prepared["duck1_us"]
    assert sorted(bar["rows"]) == rows


_CAT = CatalogAssumptions(
    tables={"t": TableAssumptions(max_rows=3, columns={"k": ColumnAssumption(max_value_exclusive=4)})}
)


def test_verus_binary_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.pipeline import _verus_binary

    monkeypatch.setenv("LEMMA_VERUS_BIN", "/x/guarded.sh")
    assert _verus_binary() == "/x/guarded.sh"
    monkeypatch.setenv("LEMMA_VERUS_BIN", "  ")
    assert _verus_binary() != "  "


def test_avg_queries_are_recorded_as_pending_not_dropped() -> None:
    from research_loop.scripts.declarative_round import _avg_refusal

    for sql in ("SELECT AVG(x) FROM t", "select k, avg ( x ) as a from t group by k"):
        rec = _avg_refusal("sec", "Q1", sql)
        assert rec is not None and "pending idealization" in rec["refusal"] and rec["qid"] == "Q1"
    assert _avg_refusal("sec", "Q2", "SELECT SUM(x), AVERAGE_X FROM t") is None


def test_null_in_a_non_nullable_column_fails_loudly(tmp_path: Path) -> None:
    import research_loop.decl_query_measure as m

    db = tmp_path / "n.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE t (k INTEGER)")
    con.execute("INSERT INTO t VALUES (1), (2), (3), (NULL)")
    con.close()
    with pytest.raises(ValueError, match="has NULLs"):
        m.write_query_measure(
            sql="SELECT k, COUNT(*) AS c FROM t GROUP BY k",
            schema={"t": {"k": "integer"}},
            catalog=_CAT,
            db_path=db,
            dest=tmp_path / "o",
        )


def test_job_env_snapshot_keeps_only_the_settings_that_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scripts.declarative_manual import _JOB_ENV_KEYS, _job_env_snapshot

    for k in _JOB_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    assert _job_env_snapshot() == {}
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "1")
    monkeypatch.setenv("UNRELATED", "x")
    assert _job_env_snapshot() == {"LEMMA_STRING_ENCODING": "dict", "LEMMA_PARALLEL_VSTD": "1"}


# ---- check regenerates the spec (the spec is the ground truth) --------------------------------------------------------------


def _workspace(tmp_path: Path, spec_on_disk: str, body_file_spec: str = "OTHER SPEC TEXT") -> Path:
    ws = tmp_path / "ws"
    (ws / "decl_data").mkdir(parents=True)
    (ws / "context" / "ro").mkdir(parents=True)
    (ws / "decl_data" / "bar.json").write_text('{"duck_us": 10, "rows": []}')
    (ws / "context" / "ro" / "spec.rs").write_text(spec_on_disk)
    (ws / "runquery_agent.rs").write_text(body_file_spec)
    return ws


def _patch_check(monkeypatch: pytest.MonkeyPatch, regenerated: str) -> list[str]:
    from research_loop.scripts import declarative_manual as m

    seen: list[str] = []
    monkeypatch.setattr(m, "regenerate_spec", lambda kind, sql: regenerated)

    def fake_metrics(**kw):
        seen.append(kw["spec_rs"])
        return {"status": "SUCCESS", "proof_verified": True, "latency_us": 1}

    monkeypatch.setattr(m, "run_declarative_metrics", fake_metrics)
    return seen


def test_check_passes_an_honest_workspace_and_builds_from_the_regenerated_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scripts import declarative_manual as m

    ws = _workspace(tmp_path, "spec line 1\nspec line 2\n")
    seen = _patch_check(monkeypatch, "spec line 1\nspec line 2\n")
    out = m.check("sec", "SELECT 1", ws)
    assert out["status"] == "SUCCESS" and seen == ["spec line 1\nspec line 2\n"]  # not the (different) text in runquery_agent.rs


def test_check_refuses_a_tampered_spec_and_names_the_first_differing_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scripts import declarative_manual as m

    ws = _workspace(tmp_path, "spec line 1\nensures true,\n")
    seen = _patch_check(monkeypatch, "spec line 1\nensures res == real,\n")
    with pytest.raises(m.SpecMismatch, match=r"first difference at line 2: regenerated 'ensures res == real,' vs workspace 'ensures true,'"):
        m.check("sec", "SELECT 1", ws)
    assert seen == []  # nothing was verified or timed


def test_a_transplant_into_a_stale_spec_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scripts import declarative_manual as m
    from research_loop.scripts.declarative_transplant import transplant

    src = "// AGENT_HELPERS_START\n// AGENT_HELPERS_END\n// AGENT_EDIT_START\nBODY\n// AGENT_EDIT_END\n"
    stale_spec = "OLD CAPS 100\n// AGENT_HELPERS_START\n// AGENT_HELPERS_END\n// AGENT_EDIT_START\n// AGENT_EDIT_END\n"
    moved = transplant(src, stale_spec)
    assert "BODY" in moved and moved.startswith("OLD CAPS 100")  # the destination's spec text is untouched by the copy
    ws = _workspace(tmp_path, stale_spec, moved)
    seen = _patch_check(monkeypatch, "NEW CAPS 200\n// AGENT_HELPERS_START\n// AGENT_HELPERS_END\n// AGENT_EDIT_START\n// AGENT_EDIT_END\n")
    with pytest.raises(m.SpecMismatch, match="line 1: regenerated 'NEW CAPS 200' vs workspace 'OLD CAPS 100'"):
        m.check("sec", "SELECT 1", ws)
    assert seen == []


def test_first_difference_handles_length_and_equality() -> None:
    from research_loop.scripts.declarative_manual import first_difference

    assert first_difference("a\nb", "a\nb\nc") == "line 3: regenerated '<end of file>' vs workspace 'c'"
    assert first_difference("a\nb\nc", "a\nb") == "line 3: regenerated 'c' vs workspace '<end of file>'"
    assert first_difference("a", "a") == "texts are identical"


def test_the_job_snapshot_carries_the_narrow_cells_flag_and_leaves_unset_flags_out(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scripts import declarative_manual as dm

    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    monkeypatch.delenv("LEMMA_PARALLEL_VSTD", raising=False)
    snap = dm._job_env_snapshot()
    assert snap["LEMMA_NARROW_CELLS"] == "1" and "LEMMA_PARALLEL_VSTD" not in snap
    monkeypatch.delenv("LEMMA_NARROW_CELLS")
    assert "LEMMA_NARROW_CELLS" not in dm._job_env_snapshot()


def test_tpch_catalog_comes_from_the_profiled_package_when_one_is_named_and_from_row_counts_otherwise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from research_loop.assumption_packages.json_io import catalog_to_dict
    from research_loop.scripts import declarative_round as rnd

    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE lineitem (q DECIMAL(15,2))")
    con.execute("INSERT INTO lineitem VALUES (1.5), (2.5)")
    con.close()
    monkeypatch.delenv("LEMMA_TPCH_PACKAGE", raising=False)
    _schema, plain = rnd.tpch_schema_and_catalog(db)
    assert plain.tables["lineitem"].max_rows == 2 and not plain.tables["lineitem"].columns
    pkg = CatalogAssumptions(max_rows=8, tables={"lineitem": TableAssumptions(max_rows=8, columns={"q": ColumnAssumption(max_value_exclusive=1024)})})
    path = tmp_path / "pkg.json"
    path.write_text(json.dumps(catalog_to_dict(pkg)))
    monkeypatch.setenv("LEMMA_TPCH_PACKAGE", str(path))
    _schema, profiled = rnd.tpch_schema_and_catalog(db)
    assert profiled.tables["lineitem"].columns["q"].max_value_exclusive == 1024


def test_sec_package_is_the_named_one_when_set_and_the_database_default_otherwise(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scripts import declarative_round as rnd

    monkeypatch.setenv("LEMMA_SEC_PACKAGE", "/p/mine.json")
    assert rnd.sec_package() == "/p/mine.json"
    monkeypatch.delenv("LEMMA_SEC_PACKAGE")
    assert rnd.sec_package() in ("sec_margin", "sec_margin_dec")
