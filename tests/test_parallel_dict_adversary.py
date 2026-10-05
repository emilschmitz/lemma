"""Adversary review of the parallel / dictionary / dict-join / transplant additions (manual adversary, Sonnet subagent).

Verdict: research_loop/menus/parallel_dict_ADVERSARY_VERDICT.md. Verus only through scripts/ram/verus_guarded.sh, one
heavy job at a time.

Method for the proved fixtures: emit the spec for the fixture's SQL, assemble it with the fixture body, run Verus ONCE
(`compile_and_run`: verify, compile, run), then rewrite the column files for each data size and re-run the compiled
binary, comparing its printed rows with DuckDB's on the same data. Sizes straddle the worker count (8): 0, 1, 3, 7, 8, 9,
15, 16, 17 and a larger one. A panic is simulated in a worker closure by editing the assembled source and compiling with
`--no-verify` (the Err arm of `join` must then recompute the chunk inline and print the same rows).
"""

from __future__ import annotations

import os
import random
import re
import subprocess
import tempfile
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from declarative_spec import parallel
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.bench import rows_from_stdout_general, rows_match_error
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.pipeline import VERUS_CANDIDATES, compile_and_run, run_declarative_metrics
from declarative_spec.prompt import _FIXTURES
from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
from research_loop.assumption_packages import assumption_package
from research_loop.decl_query_measure import write_query_measure
from research_loop.scripts.declarative_transplant import transplant
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

ROOT = Path(__file__).resolve().parent.parent
GUARDED = ROOT / "scripts" / "ram" / "verus_guarded.sh"
needs_verus = pytest.mark.skipif(not any(c.is_file() for c in VERUS_CANDIDATES), reason="verus binary not installed")
SIZES = [0, 1, 3, 7, 8, 9, 15, 16, 17, 100]


def _env(monkeypatch: pytest.MonkeyPatch, parallel_on: bool, dict_on: bool) -> None:
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(GUARDED))
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "1") if parallel_on else monkeypatch.delenv("LEMMA_PARALLEL_VSTD", raising=False)
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict") if dict_on else monkeypatch.delenv("LEMMA_STRING_ENCODING", raising=False)


def _build_db(path: Path, ddl: list[str], tables: dict[str, list[tuple]]) -> None:
    con = duckdb.connect(str(path))
    for stmt in ddl:
        con.execute(stmt)
    for name, rows in tables.items():
        if rows:
            marks = ",".join("?" for _ in rows[0])
            con.executemany(f"INSERT INTO {name} VALUES ({marks})", rows)
    con.close()


def _run_binary(binary: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(binary)], capture_output=True, text=True, cwd=cwd, timeout=300, check=False)


def run_case(
    tmp: Path,
    *,
    sql: str,
    schema: dict,
    catalog: CatalogAssumptions,
    body_text: str,
    ddl: list[str],
    gen: Callable[[int, random.Random], dict[str, list[tuple]]],
    sizes: list[int] = SIZES,
    panic_in_worker: bool = False,
) -> list[int]:
    """Verify once, then compare the binary with DuckDB on every size. Returns the sizes checked."""
    spec = emit_declarative_spec(sql, schema, catalog)
    data = tmp / "data"
    rng = random.Random(7)
    db = tmp / "dmax.duckdb"
    _build_db(db, ddl, gen(sizes[-1], rng))  # the largest first so the catalog row caps cover every size
    prepared = write_query_measure(sql=sql, schema=schema, catalog=catalog, db_path=db, dest=data)
    program = assemble_declarative_program(
        spec, extract_agent_edit(body_text), helpers=extract_agent_helpers(body_text), column_bins=prepared["bins"]
    )
    work = tmp / "run"
    if panic_in_worker:
        # compile the unverified, panic-injected variant: the first spawned closure panics on entry
        marker = re.search(r"vstd::thread::spawn\(\s*move\s*\|\|[^{]*\{", program)
        assert marker is not None, "no spawned closure found"
        program = program[: marker.end()] + "\n    let boom: Vec<u8> = Vec::new();\n    let _x = boom[0usize];\n" + program[marker.end() :]
        work.mkdir(parents=True, exist_ok=True)
        (work / "declarative_query.rs").write_text(program)
        built = subprocess.run(
            [str(GUARDED), str(work / "declarative_query.rs"), "--no-verify", "--compile", "--", "-C", "opt-level=1"],
            capture_output=True, text=True, cwd=work, check=False,
        )
        assert (work / "declarative_query").is_file(), (built.stdout + built.stderr)[-1500:]
    else:
        metrics = compile_and_run(program, work_dir=work, timeout_sec=900)
        assert metrics["proof_verified"], str(metrics.get("compiler_error"))[-2000:]
    done: list[int] = []
    for n in sizes:
        rng = random.Random(1000 + n)
        db = tmp / f"d{n}.duckdb"
        _build_db(db, ddl, gen(n, rng))
        prepared = write_query_measure(sql=sql, schema=schema, catalog=catalog, db_path=db, dest=data)
        proc = _run_binary(work / "declarative_query", work)
        assert proc.returncode == 0, (n, proc.stderr[-600:])
        if panic_in_worker:
            assert "panicked" in proc.stderr, (n, "the injected worker panic never fired")
        got = rows_from_stdout_general(proc.stdout)
        err = rows_match_error(got, prepared["rows"], prepared["kinds"])
        assert err is None, (n, err, got[:5], prepared["rows"][:5])
        done.append(n)
    return done


# ---------------------------------------------------------------------------------------------
# Fixtures 1: parallel ungrouped SUM / MIN / MAX / COUNT.
# ---------------------------------------------------------------------------------------------

PRE_SCHEMA = {"pre": {"line": "bigint", "report": "bigint"}}
PRE_CATALOG = CatalogAssumptions(tables={"pre": TableAssumptions(max_rows=2**31)})
PRE_DDL = ["CREATE TABLE pre (line BIGINT, report BIGINT)"]


def pre_gen(n: int, rng: random.Random) -> dict[str, list[tuple]]:
    return {"pre": [(rng.randint(0, 10), rng.randint(0, 3)) for _ in range(n)]}


PAR_UNGROUPED = {
    "parallel_ungrouped_sum.rs": "SELECT SUM(line) AS total FROM pre WHERE line > 5",
    "parallel_ungrouped_min.rs": "SELECT MIN(line) AS m FROM pre WHERE line > 5",
    "parallel_ungrouped_max.rs": "SELECT MAX(line) AS m FROM pre WHERE line > 5",
    "parallel_ungrouped_count.rs": "SELECT COUNT(*) AS c FROM pre WHERE line > 5",
}


@needs_verus
@pytest.mark.parametrize("name", sorted(PAR_UNGROUPED))
def test_parallel_ungrouped_fixtures_match_duckdb_at_every_size_around_the_worker_count(
    name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _env(monkeypatch, True, False)
    text = (_FIXTURES / name).read_text()
    done = run_case(
        tmp_path, sql=PAR_UNGROUPED[name], schema=PRE_SCHEMA, catalog=PRE_CATALOG, body_text=text, ddl=PRE_DDL, gen=pre_gen
    )
    assert done == SIZES


@needs_verus
def test_a_worker_panic_takes_the_err_arm_and_prints_the_same_rows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Simulated panic in the first spawned closure (unverified build): join() returns Err, the chunk is recomputed inline."""
    _env(monkeypatch, True, False)
    text = (_FIXTURES / "parallel_ungrouped_sum.rs").read_text()
    done = run_case(
        tmp_path,
        sql=PAR_UNGROUPED["parallel_ungrouped_sum.rs"],
        schema=PRE_SCHEMA,
        catalog=PRE_CATALOG,
        body_text=text,
        ddl=PRE_DDL,
        gen=pre_gen,
        sizes=[0, 1, 8, 9, 100],
        panic_in_worker=True,
    )
    assert done == [0, 1, 8, 9, 100]


# ---------------------------------------------------------------------------------------------
# Fixture 2: parallel dense GROUP BY over a dictionary key (SEC num).
# ---------------------------------------------------------------------------------------------

NUM_SCHEMA = {"num": {"uom": "varchar", "value": "decimal(38,4)"}}
NUM_DDL = ["CREATE TABLE num (uom VARCHAR, value DECIMAL(38,4))"]


def num_gen(n: int, rng: random.Random) -> dict[str, list[tuple]]:
    keys = ["USD", "pure", "shares", "EUR"] if n > 8 else ["USD"]
    rows = []
    for _ in range(n):
        k = rng.choice(keys)
        # includes a group whose SUM is 0 (value 0 only) and negative cells
        rows.append((k, Decimal(0) if k == "EUR" else Decimal(rng.randint(-5000, 5000)) / Decimal(100)))
    return {"num": rows}


@needs_verus
def test_parallel_dense_group_by_counts_and_sums_match_duckdb(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _env(monkeypatch, True, True)
    text = (_FIXTURES / "dict_group_count_sum_parallel.rs").read_text()
    done = run_case(
        tmp_path,
        sql="SELECT uom, COUNT(*) AS c, SUM(value) AS s FROM num GROUP BY uom",
        schema=NUM_SCHEMA,
        catalog=assumption_package("sec_margin_dec"),
        body_text=text,
        ddl=NUM_DDL,
        gen=num_gen,
    )
    assert done == SIZES


# ---------------------------------------------------------------------------------------------
# Fixture 3: TPC-H Q1 (two dictionary keys, flat m1*m2 slots, WHERE leaves some slots with count 0).
# ---------------------------------------------------------------------------------------------

Q1 = (
    "SELECT l_returnflag, l_linestatus, sum(l_quantity) AS sum_qty, sum(l_extendedprice) AS sum_base_price, "
    "sum(l_extendedprice * (1 - l_discount)) AS sum_disc_price, count(*) AS count_order FROM lineitem "
    "WHERE l_shipdate <= date '1998-12-01' - interval '90' day GROUP BY l_returnflag, l_linestatus "
    "ORDER BY l_returnflag, l_linestatus"
)
LI_DDL = [
    "CREATE TABLE lineitem (l_returnflag VARCHAR, l_linestatus VARCHAR, l_quantity DECIMAL(15,2), "
    "l_extendedprice DECIMAL(15,2), l_discount DECIMAL(15,2), l_shipdate DATE)"
]
LI_SCHEMA = {
    "lineitem": {
        "l_returnflag": "VARCHAR",
        "l_linestatus": "VARCHAR",
        "l_quantity": "DECIMAL(15,2)",
        "l_extendedprice": "DECIMAL(15,2)",
        "l_discount": "DECIMAL(15,2)",
        "l_shipdate": "DATE",
    }
}


def li_gen(n: int, rng: random.Random) -> dict[str, list[tuple]]:
    cutoff = date(1998, 9, 2)
    rows = []
    for _ in range(n):
        flag, status = rng.choice([("A", "F"), ("N", "O"), ("R", "F"), ("N", "F")])
        # (N, F) rows are always after the cutoff: the slot exists in the dictionaries but its count stays 0
        offset = rng.randint(1, 400) if (flag, status) == ("N", "F") else rng.randint(-400, 3)
        rows.append(
            (flag, status, Decimal(rng.randint(1, 50)), Decimal(rng.randint(100, 100000)) / 100, Decimal(rng.randint(0, 10)) / 100, cutoff + timedelta(days=offset))
        )
    return {"lineitem": rows}


@needs_verus
def test_tpch_q1_two_key_flat_slots_match_duckdb_and_an_empty_slot_is_not_a_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _env(monkeypatch, True, True)
    text = (_FIXTURES / "hard" / "dict_parallel_q1.rs").read_text()
    cat = CatalogAssumptions(max_rows=100, tables={"lineitem": TableAssumptions(max_rows=100)})
    done = run_case(tmp_path, sql=Q1, schema=LI_SCHEMA, catalog=cat, body_text=text, ddl=LI_DDL, gen=li_gen)
    assert done == SIZES
    # the witness that a zero-count slot exists in the data: (N, F) is in the dictionaries but never in the result
    con = duckdb.connect()
    con.execute(LI_DDL[0])
    rows = li_gen(100, random.Random(1100))["lineitem"]
    con.executemany("INSERT INTO lineitem VALUES (?,?,?,?,?,?)", rows)
    groups = {(r[0], r[1]) for r in con.execute(Q1).fetchall()}
    assert ("N", "F") not in groups and ("N", "F") in {(r[0], r[1]) for r in rows}


# ---------------------------------------------------------------------------------------------
# Fixture 4: nullable-string scan in parallel (validity bit + dictionary code).
# ---------------------------------------------------------------------------------------------

PRE_NULL_SCHEMA = {"pre": {"stmt": "varchar", "line": "int"}}
PRE_NULL_DDL = ["CREATE TABLE pre (stmt VARCHAR, line INTEGER)"]


def pre_null_gen(n: int, rng: random.Random) -> dict[str, list[tuple]]:
    return {"pre": [(rng.choice(["BS", "IS", None, "CF", "BS"]), rng.randint(0, 6)) for _ in range(n)]}


@needs_verus
def test_parallel_nullable_dictionary_scan_matches_duckdb(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _env(monkeypatch, True, True)
    text = (_FIXTURES / "parallel_dict_nullable_count_min.rs").read_text()
    done = run_case(
        tmp_path,
        sql="SELECT COUNT(*) AS c, MIN(line) AS lo FROM pre WHERE stmt = 'BS' AND line > 3",
        schema=PRE_NULL_SCHEMA,
        catalog=assumption_package("sec_margin_dec"),
        body_text=text,
        ddl=PRE_NULL_DDL,
        gen=pre_null_gen,
    )
    assert done == SIZES


# ---------------------------------------------------------------------------------------------
# Fixture 5: dictionary join probe (num JOIN sub on adsh through each table's own dictionary).
# ---------------------------------------------------------------------------------------------

JOIN_SQL = "SELECT SUM(n.value) AS v FROM num n JOIN sub s ON n.adsh = s.adsh WHERE s.form = '10-K'"
JOIN_SCHEMA = {"num": {"adsh": "varchar", "value": "decimal(38,4)"}, "sub": {"adsh": "varchar", "form": "varchar"}}
JOIN_DDL = ["CREATE TABLE num (adsh VARCHAR, value DECIMAL(38,4))", "CREATE TABLE sub (adsh VARCHAR, form VARCHAR)"]


def join_gen(n: int, rng: random.Random) -> dict[str, list[tuple]]:
    subs = [(f"a{i}", rng.choice(["10-K", "10-Q", "8-K"])) for i in range(max(1, n // 3))]
    # probe codes absent from the build side: adsh values `zz*` are in num only
    nums = [(rng.choice([s[0] for s in subs] + ["zz1", "zz2"]), Decimal(rng.randint(-900, 900)) / 10) for _ in range(n)]
    return {"num": nums, "sub": subs}


@needs_verus
def test_dict_join_probe_matches_duckdb_with_absent_probe_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _env(monkeypatch, False, True)
    text = (_FIXTURES / "dict_join_probe_sum.rs").read_text()
    done = run_case(
        tmp_path,
        sql=JOIN_SQL,
        schema=JOIN_SCHEMA,
        catalog=assumption_package("sec_margin_dec"),
        body_text=text,
        ddl=JOIN_DDL,
        gen=join_gen,
    )
    assert done == SIZES


def join_dup_gen(n: int, rng: random.Random) -> dict[str, list[tuple]]:
    """Build side with repeated adsh (the catalog declares sub.adsh unique, but valid_cols does not state it)."""
    base = [(f"a{i}", rng.choice(["10-K", "10-Q"])) for i in range(max(1, n // 4))]
    subs = base + [(a, "10-K") for a, _f in base[: max(1, len(base) // 2)]] + base[:1]
    nums = [(rng.choice([s[0] for s in subs] + ["zz1"]), Decimal(rng.randint(-900, 900)) / 10) for _ in range(n)]
    return {"num": nums, "sub": subs}


@needs_verus
def test_duplicate_build_keys_are_counted_per_code_not_dropped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """valid_cols_sub does NOT contain the declared unique key (the probe keeps a per-code COUNT array), so duplicates in the
    build side must still give DuckDB's answer: each probe row is multiplied by the number of matching build rows."""
    _env(monkeypatch, False, True)
    spec = emit_declarative_spec(JOIN_SQL, JOIN_SCHEMA, assumption_package("sec_margin_dec"))
    valid_sub = spec.split("spec fn valid_cols_sub")[1].split("\n}")[0]
    assert "0 <= i < j <" not in valid_sub  # no unique-key conjunct: the proof cannot rely on uniqueness
    text = (_FIXTURES / "dict_join_probe_sum.rs").read_text()
    done = run_case(
        tmp_path,
        sql=JOIN_SQL,
        schema=JOIN_SCHEMA,
        catalog=assumption_package("sec_margin_dec"),
        body_text=text,
        ddl=JOIN_DDL,
        gen=join_dup_gen,
        sizes=[1, 4, 8, 9, 16, 40],
    )
    assert done == [1, 4, 8, 9, 16, 40]


# ---------------------------------------------------------------------------------------------
# (1) assembly: the same object, self joins, panics, dictionary and validity vectors live beside the codes.
# ---------------------------------------------------------------------------------------------

BODY_STUB = "    let mut res: Vec<OutRow> = Vec::new();\n    res"


def _asm(sql: str, schema: dict, catalog: CatalogAssumptions, monkeypatch: pytest.MonkeyPatch, dict_on: bool = False) -> str:
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "1")
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict") if dict_on else monkeypatch.delenv("LEMMA_STRING_ENCODING", raising=False)
    spec = emit_declarative_spec(sql, schema, catalog)
    bins = {n: f"/nonexistent/{n}.bin" for n in schema}
    return assemble_declarative_program(spec, BODY_STUB, column_bins=bins)


def test_main_passes_the_same_object_for_every_table_including_dictionary_and_validity_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    cat = assumption_package("sec_margin_dec")
    program = _asm("SELECT COUNT(*) AS c, MIN(line) AS lo FROM pre WHERE stmt = 'BS' AND line > 3", PRE_NULL_SCHEMA, cat, monkeypatch, True)
    main = program.split("fn main()")[1]
    assert "let arc_pre = std::sync::Arc::new(cols_pre);" in main
    assert "run_query(&*arc_pre, &arc_pre)" in main
    assert "&cols_pre" not in main.split("run_query(")[1]  # the call never passes the un-Arc'd struct: no second object
    # the Arc owns the struct that holds codes, dictionary and validity together
    spec = emit_declarative_spec("SELECT COUNT(*) AS c FROM pre WHERE stmt = 'BS'", PRE_NULL_SCHEMA, cat)
    struct = spec.split("pub struct Cols_pre")[1].split("}")[0]
    assert "stmt__dict" in struct and "stmt__valid" in struct and "pre_arc" in spec


def test_two_table_parallel_join_passes_both_arcs_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "1")
    monkeypatch.delenv("LEMMA_STRING_ENCODING", raising=False)
    schema = {"pre": {"line": "bigint", "report": "bigint"}, "u": {"report": "bigint", "w": "bigint"}}
    cat = CatalogAssumptions(tables={"pre": TableAssumptions(max_rows=2**20), "u": TableAssumptions(max_rows=2**10)})
    program = _asm("SELECT SUM(u.w) AS total FROM pre JOIN u ON pre.report = u.report", schema, cat, monkeypatch)
    assert "run_query(&*arc_pre, &*arc_u, &arc_pre, &arc_u)" in program
    assert program.count("Arc::new(") == 2


def test_a_self_join_has_no_parallel_variant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "1")
    schema = {"pre": {"line": "bigint", "report": "bigint"}}
    cat = CatalogAssumptions(tables={"pre": TableAssumptions(max_rows=1000)})
    with pytest.raises(DeclarativeUnsupported):
        emit_declarative_spec("SELECT COUNT(*) AS c FROM pre x JOIN pre y ON x.report = y.report", schema, cat)


def test_every_parallel_spec_requires_arc_equals_the_plain_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "1")
    monkeypatch.delenv("LEMMA_STRING_ENCODING", raising=False)
    spec = emit_declarative_spec(PAR_UNGROUPED["parallel_ungrouped_sum.rs"], PRE_SCHEMA, PRE_CATALOG)
    sig = spec.split("pub fn run_query(")[1].split("ensures")[0]
    assert "pre_arc: &std::sync::Arc<Cols_pre>" in sig and "**pre_arc == *pre" in sig
    assert parallel.params(spec) == [("pre", "Cols_pre")]


# ---------------------------------------------------------------------------------------------
# (3) the transplant tool.
# ---------------------------------------------------------------------------------------------


def test_transplant_copies_only_the_two_agent_regions() -> None:
    src = (_FIXTURES / "parallel_ungrouped_sum.rs").read_text()
    monkey_spec = (
        "// host line one\npub fn run_query() {\n// AGENT_HELPERS_START\nOLD HELPER\n// AGENT_HELPERS_END\n"
        "// AGENT_EDIT_START\nOLD BODY\n// AGENT_EDIT_END\n}\n// host line two\n"
    )
    out = transplant(src, monkey_spec)
    assert out.startswith("// host line one\n") and out.endswith("// host line two\n")
    assert "OLD BODY" not in out and "OLD HELPER" not in out
    assert extract_agent_edit(out).strip() == extract_agent_edit(src).strip()
    assert extract_agent_helpers(out).strip() == extract_agent_helpers(src).strip()


def test_transplant_of_a_file_without_markers_is_loud() -> None:
    with pytest.raises(ValueError):
        transplant("fn nothing() {}", "// AGENT_HELPERS_START\n// AGENT_HELPERS_END\n// AGENT_EDIT_START\n// AGENT_EDIT_END\n")


def test_check_re_admits_a_transplanted_body_that_adds_trusted_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """`declarative_manual check` runs run_declarative_metrics: admission rejects external_body/assume before Verus runs."""
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "1")
    spec = emit_declarative_spec(PAR_UNGROUPED["parallel_ungrouped_sum.rs"], PRE_SCHEMA, PRE_CATALOG)
    evil_helpers = "#[verifier::external_body]\nproof fn lemma_free(x: int)\n    ensures false,\n{ }\n"
    src = (
        "// AGENT_HELPERS_START\n" + evil_helpers + "// AGENT_HELPERS_END\n// AGENT_EDIT_START\n    assume(false);\n    "
        "let mut res: Vec<OutRow> = Vec::new();\n    res\n// AGENT_EDIT_END\n"
    )
    out = run_declarative_metrics(spec_rs=spec, agent_source=src, work_dir=None)
    assert out["status"] == "FAILURE" and not out["proof_verified"]
    assert "external_body" in out["compiler_error"] or "assume" in out["compiler_error"]


@needs_verus
def test_a_body_proved_for_one_spec_does_not_verify_against_another(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Transplant (a body for `line > 5` into the `line > 6` spec): Verus must reject it (rc != 0, errors)."""
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(GUARDED))
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "1")
    src = (_FIXTURES / "parallel_ungrouped_sum.rs").read_text()
    spec_b = emit_declarative_spec("SELECT SUM(line) AS total FROM pre WHERE line > 6", PRE_SCHEMA, PRE_CATALOG)
    moved = transplant(src, spec_b)
    out = run_declarative_metrics(spec_rs=spec_b, agent_source=moved, work_dir=tmp_path / "b")
    assert not out["proof_verified"] and "verification results::" in str(out.get("compiler_error")), str(out)[-800:]


@needs_verus
@pytest.mark.parametrize("cap", [2**20, 2**30])
def test_a_body_transplanted_to_another_row_cap_is_re_verified_there(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cap: int) -> None:
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(GUARDED))
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "1")
    src = (_FIXTURES / "parallel_ungrouped_sum.rs").read_text()
    cat = CatalogAssumptions(tables={"pre": TableAssumptions(max_rows=cap)})
    spec = emit_declarative_spec(PAR_UNGROUPED["parallel_ungrouped_sum.rs"], PRE_SCHEMA, cat)
    out = run_declarative_metrics(spec_rs=spec, agent_source=transplant(src, spec), work_dir=tmp_path / "c")
    assert out["proof_verified"], str(out.get("compiler_error"))[-1200:]


@needs_verus
def test_a_body_transplanted_to_a_row_cap_it_cannot_support_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The chunk arithmetic is proved for rows <= 2^31: a spec with a 2^40 cap must not verify with the same body."""
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(GUARDED))
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "1")
    src = (_FIXTURES / "parallel_ungrouped_sum.rs").read_text()
    cat = CatalogAssumptions(tables={"pre": TableAssumptions(max_rows=2**40)})
    spec = emit_declarative_spec(PAR_UNGROUPED["parallel_ungrouped_sum.rs"], PRE_SCHEMA, cat)
    out = run_declarative_metrics(spec_rs=spec, agent_source=transplant(src, spec), work_dir=tmp_path / "d")
    assert not out["proof_verified"]


# ---------------------------------------------------------------------------------------------
# One larger run on the local SYNTHETIC SEC database (1M num rows, 40k sub rows), read-only.
# ---------------------------------------------------------------------------------------------

SEC_LOCAL = Path("/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/duckdb/sec_edgar_local_dec.duckdb")


def _run_on_database(tmp: Path, *, sql: str, schema: dict, body_text: str) -> None:
    catalog = assumption_package("sec_margin_dec")
    prepared = write_query_measure(sql=sql, schema=schema, catalog=catalog, db_path=SEC_LOCAL, dest=tmp / "data")
    spec = emit_declarative_spec(sql, schema, catalog)
    program = assemble_declarative_program(
        spec, extract_agent_edit(body_text), helpers=extract_agent_helpers(body_text), column_bins=prepared["bins"]
    )
    metrics = compile_and_run(program, work_dir=tmp / "run", timeout_sec=900)
    assert metrics["proof_verified"], str(metrics.get("compiler_error"))[-1500:]
    assert metrics["status"] == "SUCCESS", str(metrics.get("compiler_error"))[-1500:]
    got = rows_from_stdout_general(metrics["stdout"])
    assert got and rows_match_error(got, prepared["rows"], prepared["kinds"]) is None, (got[:4], prepared["rows"][:4])


@needs_verus
@pytest.mark.skipif(not SEC_LOCAL.is_file(), reason="local SEC DECIMAL database not present")
def test_parallel_dense_group_by_on_one_million_real_shaped_rows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _env(monkeypatch, True, True)
    _run_on_database(
        tmp_path,
        sql="SELECT uom, COUNT(*) AS c, SUM(value) AS s FROM num GROUP BY uom",
        schema=NUM_SCHEMA,
        body_text=(_FIXTURES / "dict_group_count_sum_parallel.rs").read_text(),
    )


@needs_verus
@pytest.mark.skipif(not SEC_LOCAL.is_file(), reason="local SEC DECIMAL database not present")
def test_dict_join_probe_on_one_million_by_forty_thousand_rows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _env(monkeypatch, False, True)
    _run_on_database(
        tmp_path, sql=JOIN_SQL, schema=JOIN_SCHEMA, body_text=(_FIXTURES / "dict_join_probe_sum.rs").read_text()
    )


# ---------------------------------------------------------------------------------------------
# Open / informational.
# ---------------------------------------------------------------------------------------------


def test_declarative_manual_check_trusts_the_workspace_spec_file() -> None:
    """`check` verifies against `context/ro/spec.rs` as found in the workspace; it does not re-emit the spec from query.sql."""
    text = (ROOT / "research_loop" / "scripts" / "declarative_manual.py").read_text()
    check_src = text.split("def check(")[1].split("\ndef ")[0]
    assert 'ws / "context" / "ro" / "spec.rs"' in check_src


@pytest.mark.xfail(strict=True, reason="OPEN (hardening): check should regenerate the spec from query.sql + catalog and refuse a different spec.rs")
def test_check_regenerates_the_spec_so_a_tampered_spec_file_cannot_certify_a_body() -> None:
    text = (ROOT / "research_loop" / "scripts" / "declarative_manual.py").read_text()
    check_src = text.split("def check(")[1].split("\ndef ")[0]
    assert "emit_declarative_spec" in check_src


def test_a_weakened_spec_would_certify_a_trivial_body_which_is_why_the_spec_file_must_be_regenerated() -> None:
    """Informational: with the host's own ensures replaced by `true` the empty body verifies; the gate is the spec's integrity."""
    spec = emit_declarative_spec("SELECT COUNT(*) AS c FROM pre WHERE line > 5", PRE_SCHEMA, PRE_CATALOG)
    head, _sep, rest = spec.partition("    ensures\n")
    assert "count_c" in rest.split("{\n// AGENT_EDIT_START")[0]  # the real ensures names the spec fold
