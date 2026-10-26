"""Differential runs of predicate pushdown: proved fixture bodies on pushed-down data vs full data vs DuckDB.

For each query with a verified reference body: export the full tables (pushdown off) and the pushed-down tables (pushdown on),
verify + compile the body ONCE (Verus, memory-guarded), run the binary on the full column files, swap in the pushed files and run
it again. Both runs must print the same rows, equal to DuckDB's answer to the full original SQL (which is the same under both
flags). TPC-H Q1 / l_shipmode and SSB Q3.1 / Q4.1 / Q4.2 run on the generated SF1 databases; TPC-H Q3 / Q14 on the
deterministic SF 0.01 slice their bodies are written for (tests/tpch_mini.py). The delivered row counts are printed (-s).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.bench import rows_from_stdout_general, rows_match_error
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.pipeline import compile_and_run
from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
from research_loop.decl_query_measure import write_query_measure
from tests.test_declarative_hard_fixtures import SSB_Q31, SSB_Q41, SSB_Q42, TPCH
from tests.test_declarative_string_dict import TPCH_SQL
from tests.test_declarative_tpch_q3_q14_q19 import Q3, Q14

ROOT = Path(__file__).resolve().parents[1]
PROOFS = ROOT / "tests" / "fixtures" / "declarative_proofs"
VERUS = Path("/home/emil/tools/verus/verus")
# The fixture bodies are the real-form AVG / ratio and f64 idealization (lemma.toml [sql] exact_division = false), as in the modules they come from.
pytestmark = pytest.mark.usefixtures("exact_division_off")
MAIN = Path("/home/emil/projects/lemma-db")  # the generated databases are gitignored; a worktree reads the main checkout's (read-only)


def _db(name: str) -> Path | None:
    for base in (ROOT, MAIN):
        p = base / "research_loop" / "generated" / name
        if p.is_file():
            return p
    return None


_SSB_ENV = {"LEMMA_STRING_ENCODING": "dict", "LEMMA_JOIN_CHAIN": "1", "LEMMA_PARALLEL_VSTD": "on"}
Q1 = TPCH["group_decimal_sums_string_keys_sorted.rs"]
# name -> (sql, fixture, database, env)
CASES = {
    "tpch_sf1_shipmode_plain": (TPCH_SQL, "tpch_shipmode_min_count_plain.rs", "tpch", {"LEMMA_STRING_ENCODING": "plain"}),
    "tpch_sf1_shipmode_dict": (TPCH_SQL, "dict_shipmode_min_count.rs", "tpch", {"LEMMA_STRING_ENCODING": "dict"}),
    "tpch_sf1_q1": (Q1, "hard/group_decimal_sums_string_keys_sorted.rs", "tpch", {}),
    "ssb_sf1_q41": (SSB_Q41, "hard/dict_star_join_group_sum_sorted.rs", "ssb", _SSB_ENV),
    "ssb_sf1_q31": (SSB_Q31, "hard/dict_parallel_star_join_two_keys_revenue_order.rs", "ssb", _SSB_ENV),
    "ssb_sf1_q42": (SSB_Q42, "hard/dict_parallel_star_join_two_keys_string_order.rs", "ssb", _SSB_ENV),
    "tpch_mini_q14": (Q14, "tpch_q14_promo_ratio.rs", "mini_part", {}),
    # TPC-H Q19 is not here: at a254d17 the emitter refuses it ("comma join: no column equality connects table 'part'"), before pushdown.
    "tpch_mini_q3": (Q3, "tpch_q3_join_group_topk.rs", "mini_customer", {}),
}


def _schema_catalog(kind: str, tmp: Path):
    from research_loop.scripts.declarative_round import tpch_schema_and_catalog

    if kind == "tpch":
        db = _db("tpch_sf1.duckdb")
        if db is None:
            pytest.skip("TPC-H SF1 database not generated")
        return (db, *tpch_schema_and_catalog(db))
    if kind == "ssb":
        from research_loop.assumption_packages import assumption_package

        db = _db("ssb_sf1.duckdb")
        if db is None:
            pytest.skip("SSB SF1 database not generated")
        con = duckdb.connect(str(db), read_only=True)
        schema = {t: {r[0]: r[1].lower() for r in con.execute(f"describe {t}").fetchall()} for (t,) in con.execute("show tables").fetchall()}
        con.close()
        return db, schema, assumption_package("ssb_sf1")
    from tests.tpch_mini import build_mini_tpch

    db = build_mini_tpch(tmp / f"{kind}.duckdb", kind.removeprefix("mini_"))
    if db is None:
        pytest.skip("duckdb tpch extension unavailable")
    return (db, *tpch_schema_and_catalog(db))


def _rows(stdout: str) -> list[list[str]]:
    return rows_from_stdout_general(stdout)


@pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")
@pytest.mark.parametrize("name", sorted(CASES))
def test_proved_body_gives_the_same_rows_on_pushed_down_and_full_data(name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    sql, fixture, kind, env = CASES[name]
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(ROOT / "scripts" / "ram" / "verus_guarded.sh"))
    monkeypatch.setenv("LEMMA_RUN_TIMEOUT_SEC", "600")
    db, schema, catalog = _schema_catalog(kind, tmp_path)
    monkeypatch.setenv("LEMMA_PUSHDOWN", "0")
    full = write_query_measure(sql=sql, schema=schema, catalog=catalog, db_path=db, dest=tmp_path / "full")
    spec_off = emit_declarative_spec(sql, schema, catalog)
    monkeypatch.setenv("LEMMA_PUSHDOWN", "1")
    pushed = write_query_measure(sql=sql, schema=schema, catalog=catalog, db_path=db, dest=tmp_path / "pushed")
    spec = emit_declarative_spec(sql, schema, catalog)
    assert spec == spec_off  # the spec does not depend on the flag
    assert pushed["rows"] == full["rows"]  # the oracle is DuckDB on the full original SQL either way
    assert any(pushed["table_rows"][t] < full["table_rows"][t] for t in full["table_rows"]), (full["table_rows"], pushed["table_rows"])
    run_data = tmp_path / "run_data"
    run_data.mkdir()
    bins = {s: str(run_data / Path(p).name) for s, p in full["bins"].items()}
    for s, p in full["bins"].items():
        shutil.copyfile(p, bins[s])
    text = (PROOFS / fixture).read_text()
    program = assemble_declarative_program(spec, extract_agent_edit(text), helpers=extract_agent_helpers(text), column_bins=bins)
    # The Verus wait on this shared machine counts toward the limit: allow a long queue (the proof itself is the fixture's usual one).
    metrics = compile_and_run(program, work_dir=tmp_path / "run", timeout_sec=3600)
    assert metrics["proof_verified"] and metrics["status"] == "SUCCESS", str(metrics.get("compiler_error"))[-2000:]
    on_full = _rows(metrics["stdout"])
    for s, p in pushed["bins"].items():
        shutil.copyfile(p, bins[s])
    rerun = subprocess.run([str(tmp_path / "run" / "declarative_query")], capture_output=True, text=True, timeout=600, check=False, cwd=tmp_path / "run")
    assert rerun.returncode == 0, rerun.stderr[-2000:]
    on_pushed = _rows(rerun.stdout)
    assert on_pushed == on_full and on_full
    err = rows_match_error(on_pushed, full["rows"], full["kinds"], full.get("order_cols"), full.get("limited", False), full.get("tie_rows"))
    assert err is None, err
    with capsys.disabled():
        print(f"\nPUSHDOWN {name}: full {full['table_rows']} delivered {pushed['table_rows']} result rows {len(on_full)}")
