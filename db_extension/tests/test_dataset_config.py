"""Tests for dataset row limit resolution (no silent default cap)."""
from __future__ import annotations

from pathlib import Path

import pytest

from db_extension.agent import measure_core as mc
from db_extension.agent.mcp_tool_specs import openai_host_tool_definitions
from db_extension.dataset_config import (
    dataset_size_limit,
    effective_dataset_size,
    mcp_iterate_dataset_size,
    mcp_iterate_is_uncapped,
    row_budget_prompt_section,
    run_runquery_iterate_tool_blurb,
    table_column_abs_sum_caps,
    table_column_value_caps,
    table_row_counts,
    tables_one_row_per_adsh,
)
from db_extension_paths.dataset_config import (
    effective_dataset_size as paths_effective_dataset_size,
)


def _write_tbl(path: Path, data_rows: int) -> None:
    lines = ["id|amount"]
    for i in range(data_rows):
        lines.append(f"{i}|{i}")
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture
def isolated_ssb(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point SSB paths at an empty tmp dir so file_row_count finds nothing."""
    monkeypatch.setenv("LEMMA_SSB_DIR", str(tmp_path))
    return tmp_path


def test_dataset_size_limit_unset_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_DATASET_SIZE", raising=False)
    assert dataset_size_limit() is None


def test_dataset_size_limit_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_DATASET_SIZE", "3")
    assert dataset_size_limit() == 3


def test_effective_size_all_rows_from_bench_tbl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_ssb: Path,
) -> None:
    tbl = tmp_path / "bench.tbl"
    _write_tbl(tbl, 7)
    monkeypatch.delenv("LEMMA_DATASET_SIZE", raising=False)
    monkeypatch.setenv("LEMMA_BENCH_TBL", str(tbl))
    assert effective_dataset_size() == 7
    assert paths_effective_dataset_size() == 7


def test_effective_size_env_cap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_ssb: Path,
) -> None:
    tbl = tmp_path / "bench.tbl"
    _write_tbl(tbl, 10)
    monkeypatch.setenv("LEMMA_DATASET_SIZE", "3")
    monkeypatch.setenv("LEMMA_BENCH_TBL", str(tbl))
    assert effective_dataset_size() == 3
    assert paths_effective_dataset_size() == 3


def test_effective_size_raises_without_tbl_or_env(
    monkeypatch: pytest.MonkeyPatch,
    isolated_ssb: Path,
) -> None:
    monkeypatch.delenv("LEMMA_DATASET_SIZE", raising=False)
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.delenv("LEMMA_DUCKDB_PATH", raising=False)
    monkeypatch.delenv("LEMMA_PRIMARY_TABLE", raising=False)
    with pytest.raises(RuntimeError, match="LEMMA_DATASET_SIZE"):
        effective_dataset_size()
    with pytest.raises(RuntimeError, match="LEMMA_DATASET_SIZE"):
        paths_effective_dataset_size()


def test_sec_duckdb_count_beats_ssb_meta(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Tiny SEC DuckDB must not inherit leftover ssb-dbgen dataset_meta.json (6M)."""
    duckdb = pytest.importorskip("duckdb")
    ssb = tmp_path / "ssb"
    ssb.mkdir()
    (ssb / "dataset_meta.json").write_text('{"row_count": 6001215}\n')
    db = tmp_path / "tiny.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE pre AS SELECT * FROM range(7) t(x)")
    con.close()
    monkeypatch.delenv("LEMMA_DATASET_SIZE", raising=False)
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.setenv("LEMMA_SSB_DIR", str(ssb))
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(db))
    monkeypatch.setenv("LEMMA_PRIMARY_TABLE", "pre")
    assert effective_dataset_size() == 7


def test_effective_size_uses_max_table_not_primary_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_ssb: Path,
) -> None:
    duckdb = pytest.importorskip("duckdb")
    db = tmp_path / "two_tables.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE a AS SELECT * FROM range(10) t(x)")
    con.execute("CREATE TABLE b AS SELECT * FROM range(100) t(x)")
    con.close()
    monkeypatch.delenv("LEMMA_DATASET_SIZE", raising=False)
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(db))
    monkeypatch.setenv("LEMMA_PRIMARY_TABLE", "a")
    assert effective_dataset_size() == 100


def test_effective_size_from_duckdb_primary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_ssb: Path,
) -> None:
    duckdb = pytest.importorskip("duckdb")
    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE pre AS SELECT * FROM range(5) t(x)")
    con.close()
    monkeypatch.delenv("LEMMA_DATASET_SIZE", raising=False)
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(db))
    monkeypatch.setenv("LEMMA_PRIMARY_TABLE", "pre")
    assert effective_dataset_size() == 5


def test_mcp_iterate_cap_default(
    monkeypatch: pytest.MonkeyPatch,
    isolated_ssb: Path,
) -> None:
    monkeypatch.delenv("LEMMA_DATASET_SIZE", raising=False)
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.delenv("LEMMA_MCP_ITERATE_ROWS", raising=False)
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", "/unused/sec_edgar.duckdb")
    monkeypatch.setenv("LEMMA_PRIMARY_TABLE", "pre")
    monkeypatch.setattr(
        "db_extension.dataset_config._count_duckdb_primary_rows",
        lambda: 6_001_215,
    )
    assert effective_dataset_size() == 6_001_215
    assert mcp_iterate_dataset_size() == 50_000


def test_mcp_iterate_respects_dataset_size_env(
    monkeypatch: pytest.MonkeyPatch,
    isolated_ssb: Path,
) -> None:
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.delenv("LEMMA_MCP_ITERATE_ROWS", raising=False)
    monkeypatch.setenv("LEMMA_DATASET_SIZE", "500")
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", "/unused/sec_edgar.duckdb")
    monkeypatch.setenv("LEMMA_PRIMARY_TABLE", "pre")
    monkeypatch.setattr(
        "db_extension.dataset_config._count_duckdb_primary_rows",
        lambda: 6_001_215,
    )
    assert effective_dataset_size() == 500
    assert mcp_iterate_dataset_size() == 500


def test_mcp_iterate_custom_env_cap(
    monkeypatch: pytest.MonkeyPatch,
    isolated_ssb: Path,
) -> None:
    monkeypatch.delenv("LEMMA_DATASET_SIZE", raising=False)
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", "1000")
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", "/unused/sec_edgar.duckdb")
    monkeypatch.setenv("LEMMA_PRIMARY_TABLE", "pre")
    monkeypatch.setattr(
        "db_extension.dataset_config._count_duckdb_primary_rows",
        lambda: 6_001_215,
    )
    assert effective_dataset_size() == 6_001_215
    assert mcp_iterate_dataset_size() == 1000


def test_optimizer_path_unchanged_when_only_iterate_cap_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_ssb: Path,
) -> None:
    tbl = tmp_path / "bench.tbl"
    _write_tbl(tbl, 6_001_215)
    monkeypatch.delenv("LEMMA_DATASET_SIZE", raising=False)
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", "50000")
    monkeypatch.setattr(
        "db_extension.dataset_config._count_duckdb_primary_rows",
        lambda: 6_001_215,
    )
    monkeypatch.setenv("LEMMA_BENCH_TBL", str(tbl))
    assert effective_dataset_size() == 6_001_215
    assert mcp_iterate_dataset_size() == 50_000


def test_row_budget_prompt_section_from_env(
    monkeypatch: pytest.MonkeyPatch,
    isolated_ssb: Path,
) -> None:
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.delenv("LEMMA_DUCKDB_PATH", raising=False)
    monkeypatch.setenv("LEMMA_DATASET_SIZE", "12345")
    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", "1000")
    section = row_budget_prompt_section()
    assert "12345" in section
    assert "1000" in section
    assert "Row budgets" in section
    assert "not official" in section.lower()
    assert "not full table" not in section.lower()
    assert "Official pin" in section
    assert "MCP iterate max" in section
    assert "rem_join" in section


@pytest.mark.parametrize("uncapped_value", ["0", "full", "FULL", "unlimited"])
def test_mcp_iterate_uncapped_matches_official(
    monkeypatch: pytest.MonkeyPatch,
    isolated_ssb: Path,
    uncapped_value: str,
) -> None:
    monkeypatch.delenv("LEMMA_DATASET_SIZE", raising=False)
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", uncapped_value)
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", "/unused/sec_edgar.duckdb")
    monkeypatch.setenv("LEMMA_PRIMARY_TABLE", "pre")
    monkeypatch.setattr(
        "db_extension.dataset_config._count_duckdb_primary_rows",
        lambda: 6_001_215,
    )
    assert mcp_iterate_is_uncapped()
    assert effective_dataset_size() == 6_001_215
    assert mcp_iterate_dataset_size() == 6_001_215


def test_row_budget_uncapped_without_dataset_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
    isolated_ssb: Path,
) -> None:
    monkeypatch.delenv("LEMMA_DATASET_SIZE", raising=False)
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.delenv("LEMMA_DUCKDB_PATH", raising=False)
    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", "0")
    section = row_budget_prompt_section()
    assert "Row budgets" in section
    blurb = run_runquery_iterate_tool_blurb()
    assert "dataset_size" in blurb.lower()


def test_row_budget_prompt_when_iterate_equals_official(
    monkeypatch: pytest.MonkeyPatch,
    isolated_ssb: Path,
) -> None:
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.delenv("LEMMA_DUCKDB_PATH", raising=False)
    monkeypatch.setenv("LEMMA_DATASET_SIZE", "12345")
    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", "full")
    section = row_budget_prompt_section()
    assert "12345" in section
    assert "same pin submit is scored on" in section
    assert "not official" not in section.lower()
    assert "not full table" not in section.lower()


def test_row_budget_prompt_when_iterate_below_official(
    monkeypatch: pytest.MonkeyPatch,
    isolated_ssb: Path,
) -> None:
    monkeypatch.delenv("LEMMA_DATASET_SIZE", raising=False)
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", "50000")
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", "/unused/sec_edgar.duckdb")
    monkeypatch.setenv("LEMMA_PRIMARY_TABLE", "pre")
    monkeypatch.setattr(
        "db_extension.dataset_config._count_duckdb_primary_rows",
        lambda: 6_001_215,
    )
    section = row_budget_prompt_section()
    assert "50000" in section
    assert "6001215" in section.replace("_", "").replace(",", "")
    assert "not official" in section.lower()


def test_run_runquery_iterate_tool_blurb_matches_mode(
    monkeypatch: pytest.MonkeyPatch,
    isolated_ssb: Path,
) -> None:
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.delenv("LEMMA_DUCKDB_PATH", raising=False)
    monkeypatch.setenv("LEMMA_DATASET_SIZE", "12345")
    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", "full")
    blurb = run_runquery_iterate_tool_blurb()
    assert "official pin" in blurb.lower()
    assert "not official" not in blurb.lower()

    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", "1000")
    blurb_capped = run_runquery_iterate_tool_blurb()
    assert "not official pin" in blurb_capped.lower()

    defs = openai_host_tool_definitions(include_aliases=False)
    run_def = next(d for d in defs if d["function"]["name"] == "run_runquery")
    assert blurb_capped.split(".")[0] in run_def["function"]["description"]


def test_table_row_counts_returns_none_without_duckdb(
    monkeypatch: pytest.MonkeyPatch,
    isolated_ssb: Path,
) -> None:
    monkeypatch.delenv("LEMMA_DUCKDB_PATH", raising=False)
    assert table_row_counts() is None


def test_table_row_counts_per_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_ssb: Path,
) -> None:
    duckdb = pytest.importorskip("duckdb")
    db = tmp_path / "counts.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE pre AS SELECT * FROM range(7) t(x)")
    con.execute("CREATE TABLE num AS SELECT * FROM range(100) t(x)")
    con.close()
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(db))
    counts = table_row_counts()
    assert counts == {"num": 100, "pre": 7}


def test_table_column_value_caps_integer_and_double(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_ssb: Path,
) -> None:
    duckdb = pytest.importorskip("duckdb")
    db = tmp_path / "caps.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE pre (line INTEGER, tag DOUBLE)")
    con.execute("INSERT INTO pre VALUES (-482, 10.0), (100, 20.0)")
    con.execute("CREATE TABLE messy (value DOUBLE)")
    con.execute("INSERT INTO messy VALUES (1.5)")
    con.execute("CREATE TABLE huge (value DOUBLE)")
    con.execute("INSERT INTO huge VALUES (18446744073709551616)")
    con.execute("CREATE TABLE num (value DOUBLE)")
    # Above 2^53. The DOUBLE column stores the nearest float64, not this literal.
    con.execute("INSERT INTO num VALUES (188446126794000001)")
    stored = con.execute("SELECT CAST(MAX(ABS(value)) AS HUGEINT) FROM num").fetchone()[0]
    con.close()
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(db))
    caps = table_column_value_caps()
    assert caps is not None
    assert caps["pre"]["line"] == 483
    assert caps["pre"]["tag"] == 21
    assert int(stored) > 2**53
    assert caps["num"]["value"] == int(stored) + 1
    assert "messy" not in caps or "value" not in caps.get("messy", {})
    sums = table_column_abs_sum_caps()
    assert sums is not None
    assert sums["pre"]["line"] == 582 + 1
    assert sums["messy"]["value"] == 2 + 1
    assert "huge" not in sums or "value" not in sums.get("huge", {})


def test_tables_one_row_per_adsh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_ssb: Path,
) -> None:
    duckdb = pytest.importorskip("duckdb")
    db = tmp_path / "adsh.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE sub (adsh VARCHAR)")
    con.execute("INSERT INTO sub VALUES ('a'), ('b')")
    con.execute("CREATE TABLE num (adsh VARCHAR)")
    con.execute("INSERT INTO num VALUES ('a'), ('a')")
    con.close()
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(db))
    unique = tables_one_row_per_adsh()
    assert unique == {"sub"}


def test_run_solution_default_passes_iterate_dataset_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rq = tmp_path / "runquery_agent.rs"
    rq.write_text("stub")

    seen: list[int] = []

    def fake_harness(*, query_id: int, dataset_size: int, ws: Path, sql=None, schema=None):
        seen.append(dataset_size)
        return (
            {
                "status": "SUCCESS",
                "proof_verified": True,
                "latency_us": 12,
                "compiler_error": "",
            },
            0,
        )

    monkeypatch.setattr(
        mc,
        "validate_solution",
        lambda **kwargs: {"ok": True, "runquery_path": str(rq)},
    )
    monkeypatch.setattr(mc, "_invoke_harness", fake_harness)
    monkeypatch.setattr(mc, "mcp_iterate_dataset_size", lambda: 50_000)
    out = mc.run_solution(path="runquery_agent.rs", query_id=1, ws=tmp_path)
    assert out["ok"] is True
    assert seen == [50_000]
    assert out["dataset_size"] == 50_000
