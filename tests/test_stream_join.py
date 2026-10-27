"""Streaming executors, phase 2a: inner equi-joins of one streamed table with materialized build tables (lemma.toml [run] stream,
docs/STREAM.md "Joins", declarative_spec/stream_join.py).

Phase 1 unchanged: the single-table stream specs and prompts are byte-identical to the tree before the join work
(tests/fixtures/stream_phase1_flag_on_golden.json; the flag-off goldens are tests/test_stream.py's). The stream table: the
`-- stream: <table>` line, the rule (rows after the table's own filters, a tie to the first in FROM) on a database, the reorder (the
stream table outermost whatever the FROM order). The gate's refusals. Verus: the host scaffold with a stub agent (TPC-H Q12 in both
orientations, SEC q3 without its HAVING subquery, the invented join), the join fixture and its mutants (a probe that misses a match, a
duplicate build key counted once, a build that drops duplicates), mutants of the Pool runtime. Admission of the seven regions. The
compiled fixture (binary-mode main: random chunk sizes, several threads) against DuckDB on random tables with duplicate build keys,
NULL keys and stream rows that match nothing.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import subprocess
from pathlib import Path

import duckdb
import pytest

from declarative_spec import stream, stream_join
from declarative_spec.admit import admit_stream
from declarative_spec.assemble import assemble_stream_program
from declarative_spec.bench import rows_from_stdout_general, rows_match_error
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from research_loop.structural_catalog import structural_catalog

ROOT = Path(__file__).resolve().parents[1]
TPCH_SCHEMA = json.loads((ROOT / "tests" / "fixtures" / "tpch22" / "schema.json").read_text())
TEMPLATES = ROOT / "configs" / "query_templates" / "tpch"
Q12 = (ROOT / "configs" / "queries" / "tpch" / "tpch_q12.sql").read_text()
SEC_COLUMNS = json.loads((ROOT / "configs" / "data" / "sec_edgar_3y_dec.json").read_text())["columns"]
SEC_SCHEMA = {t: {c: ty.lower() for c, ty in cs.items()} for t, cs in SEC_COLUMNS.items()}
# SEC q3 (configs/queries/sec_edgar/q3.sql) without its HAVING subquery (a subquery is refused in phase 2a)
SEC_Q3 = """SELECT s.name, s.cik, SUM(n.value) AS total_value
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD' AND s.fy = 2022 AND n.value IS NOT NULL
GROUP BY s.name, s.cik
ORDER BY total_value DESC
LIMIT 100"""
SEC_CATALOG = structural_catalog({("sub", "fy")})  # measured on sec_edgar_dec.duckdb: sub.fy has NULLs, num.adsh/uom/value and sub.adsh/name/cik none
FIX = ROOT / "tests" / "fixtures" / "declarative_proofs" / "stream"
PHASE1 = json.loads((ROOT / "tests" / "fixtures" / "stream_phase1_flag_on_golden.json").read_text())
GUARD = ROOT / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")

J_SCHEMA = {"t": {"a": "integer", "k": "varchar", "m": "decimal(12,2)"}, "u": {"k": "varchar", "g": "varchar", "w": "integer"}}
J_CATALOG = structural_catalog({("u", "k")})  # the build side's join key may be NULL
J_SQL = "-- stream: t\nSELECT u.g, COUNT(*) AS c, SUM(t.m) AS sm FROM t JOIN u ON t.k = u.k WHERE u.k IS NOT NULL GROUP BY u.g"
J_FIXTURE = "join_group_build_key.rs"
_ENV_KEYS = ("LEMMA_ASSUMPTIONS", "LEMMA_PARALLEL_VSTD", "LEMMA_STRING_ENCODING", "LEMMA_AGENT_SCAN", "LEMMA_JOIN_CHAIN", "LEMMA_STREAM", "LEMMA_EXAMPLES")


@pytest.fixture
def stream_on(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LEMMA_STREAM", "1")
    monkeypatch.setenv("LEMMA_TEMPLATES", "1")
    monkeypatch.setenv("LEMMA_PUSHDOWN", "0")


def _emit_j(sql: str = J_SQL) -> str:
    return emit_declarative_spec(sql, J_SCHEMA, J_CATALOG)


def _verus(program: str, tmp: Path, name: str, *extra: str) -> str:
    rs = tmp / f"{name}.rs"
    rs.write_text(program)
    proc = subprocess.run(
        [str(GUARD), str(rs), "--triggers-mode", "silent", "--rlimit", "16", *extra],
        capture_output=True,
        text=True,
        cwd=tmp,
        timeout=1800,
        check=False,
    )
    return proc.stdout + proc.stderr


def _verified(out: str) -> bool:
    return re.search(r"verification results:: \d+ verified, 0 errors", out) is not None


def _fails(out: str) -> bool:
    return re.search(r"verification results:: \d+ verified, [1-9]\d* errors", out) is not None


def _needs_verus() -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")


def _fixture_program(*, mutate=None, column_bins: dict[str, str] | None = None) -> str:
    regions = stream.extract_regions((FIX / J_FIXTURE).read_text())
    if mutate is not None:
        regions = mutate(dict(regions))
    return assemble_stream_program(_emit_j(), regions, column_bins=column_bins)


# ---- phase 1 unchanged --------------------------------------------------------------------------------------------------------------

_T_SCHEMA = {"t": {"a": "integer", "b": "bigint", "d": "date", "s": "varchar", "m": "decimal(12,2)"}}
_T_SQL = [
    "SELECT SUM(b) AS sb FROM t WHERE a > 3 AND d < DATE '2000-01-01'",
    "SELECT s, COUNT(*) AS c, SUM(m) AS sm FROM t GROUP BY s",
    "SELECT MIN(b) AS mn, MAX(d) AS mx, SUM(b) AS sb, AVG(b) AS ab, COUNT(*) AS c, COUNT(b) AS cb FROM t WHERE d < DATE '2000-01-01' AND s <> 'zz'",
    "SELECT s, MIN(a) AS mn, MAX(d) AS mx, SUM(a) AS sx, AVG(a) AS av, COUNT(*) AS c FROM t WHERE a > 3 GROUP BY s HAVING COUNT(*) > 1 ORDER BY s LIMIT 5",
]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_phase1_specs_and_prompts_are_byte_identical(stream_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.stream_prompt import build_stream_prompt

    for name in ("q01", "q06"):
        assert _sha(emit_declarative_spec((TEMPLATES / f"{name}.sql").read_text(), TPCH_SCHEMA, None)) == PHASE1[name], name
    cat = structural_catalog({("t", "b")})
    for i, sql in enumerate(_T_SQL):
        spec = emit_declarative_spec(sql, _T_SCHEMA, cat)
        assert _sha(spec) == PHASE1[f"t{i}"], sql
        assert not stream_join.is_join(spec) and stream_join.BUILD_START not in spec
        for ex in ("none", "full"):
            monkeypatch.setenv("LEMMA_EXAMPLES", ex)
            text = build_stream_prompt(sql=sql, spec_path="s.rs", edit_path="e.rs", lemma_index="IDX", last_error="", in_docker=True, spec_text=spec, restart_note="")
            assert _sha(text) == PHASE1[f"t{i}_prompt_{ex}"], (sql, ex)
        monkeypatch.delenv("LEMMA_EXAMPLES")


# ---- the contract text --------------------------------------------------------------------------------------------------------------


def test_join_contract_adds_no_trusted_item(stream_on: None) -> None:
    spec = _emit_j()
    assert stream.is_stream(spec) and stream_join.is_join(spec)
    assert "// LEMMA_STREAM_JOIN: t is streamed (outermost); u is a build table" in spec
    bodies = [m.start() for m in re.finditer(r"#\[verifier::external_body\]", spec)]
    assert [re.search(r"pub fn (\w+)", spec[i:]).group(1) for i in bodies] == ["chunk_t", "str_ent", "stream_end_t"]
    assert spec.count("TRUSTED S1") == 2 and spec.count("TRUSTED S2") == 1
    assert "assume(" not in spec and "admit(" not in spec and "arbitrary(" not in spec
    assert re.findall(r"#\[verifier::external\]\nfn (\w+)", spec) == ["lemma_stream_slice", "lemma_stream_str_bytes", "lemma_stream_strings_ok"]
    for mark in ("AGENT_STATE_START", "AGENT_HELPERS_START", stream_join.BUILD_START, *(m for pair in stream.BODY_REGIONS.values() for m in pair)):
        assert spec.count(mark) == 1, mark
    assert "pub uninterp spec fn stream_table_t(id: u64) -> Cols_t;" in spec and "stream_table_u" not in spec and "Chunk_u" not in spec
    assert "pub struct Agg {\n    pub count_c: int,\n    pub sum_sm: int,\n    pub hits: int,\n}" in spec
    assert "pub fn q_build(b_u: &Cols_u, p: &Params) -> (r: Option<QBuild>)" in spec
    assert "pub fn q_step(s: &mut QAcc, c: &Chunk_t, bld: &QBuild, b_u: &Cols_u, p: &Params) -> (ok: bool)" in spec
    assert "count_c: count_c_d1(t, b_u, i0, 0, k)," in spec  # agg_row is the spec's own inner fold at the stream row
    assert "res matches Some(r) ==> run_query_ok(&t@, b_u, r)," in spec
    assert "r matches StreamOut::Rows(res) ==> run_query_ok(&stream_table_t(pl.sid()), &pl.build_u(), res)," in spec
    assert "pub struct Pool {" in spec and "vstd::rwlock::RwLock<Slot, SlotPred>" in spec and "#[verifier::type_invariant]" in spec
    assert "pub fn exec_new" not in spec  # the per-worker Exec of phase 1 is replaced by the Pool


def test_the_stream_table_is_outermost_whatever_the_from_order(stream_on: None) -> None:
    flipped = "-- stream: t\nSELECT u.g, COUNT(*) AS c, SUM(t.m) AS sm FROM u JOIN t ON u.k = t.k WHERE u.k IS NOT NULL GROUP BY u.g"
    spec = _emit_j(flipped)
    assert "pub uninterp spec fn stream_table_t(id: u64) -> Cols_t;" in spec
    assert "pub open spec fn count_c(t: &Cols_t, u: &Cols_u, i0: int, k: Seq<char>) -> int" in spec  # the spec's outer fold is over t
    for table, build in (("orders", "lineitem"), ("lineitem", "orders")):
        spec = emit_declarative_spec(stream_join.with_header(Q12, table), TPCH_SCHEMA, None)
        assert f"pub uninterp spec fn stream_table_{table}(id: u64) -> Cols_{table};" in spec
        assert f"pub fn q_build(b_{build}: &Cols_{build}, p: &Params)" in spec
        assert f"// SQL (the query this spec states):\n//     -- stream: {table}\n" in spec  # the choice is recorded in the spec


@pytest.mark.parametrize(
    "sql, why",
    [
        ("SELECT u.g, COUNT(*) AS c FROM t LEFT JOIN u ON t.k = u.k GROUP BY u.g", "LEFT JOIN"),
        ("SELECT u.g, COUNT(*) AS c FROM t RIGHT JOIN u ON t.k = u.k GROUP BY u.g", "RIGHT JOIN"),
        ("SELECT u.g, COUNT(*) AS c FROM t FULL OUTER JOIN u ON t.k = u.k GROUP BY u.g", "FULL"),
        ("SELECT u.g, COUNT(*) AS c FROM t SEMI JOIN u ON t.k = u.k GROUP BY u.g", "SEMI"),
        ("SELECT u.g, COUNT(*) AS c FROM t ANTI JOIN u ON t.k = u.k GROUP BY u.g", "ANTI"),
        ("SELECT u.g, COUNT(*) AS c FROM t CROSS JOIN u GROUP BY u.g", "CROSS"),
        ("SELECT u.g, COUNT(*) AS c FROM t JOIN u USING (k) GROUP BY u.g", "USING"),
        ("SELECT u.g, COUNT(*) AS c FROM t JOIN u ON t.k = u.k WHERE EXISTS (SELECT 1 FROM u AS v WHERE v.k = t.k) GROUP BY u.g", "subquery"),
        ("SELECT u.g, COUNT(*) AS c FROM t JOIN u ON t.k = u.k WHERE t.a IN (SELECT w FROM u) GROUP BY u.g", "subquery"),
        ("SELECT u.g, COUNT(*) AS c FROM t JOIN u ON t.k = u.k WHERE NOT EXISTS (SELECT 1 FROM u AS v WHERE v.g = u.g) GROUP BY u.g", "subquery"),
        ("WITH x AS (SELECT k FROM u) SELECT COUNT(*) AS c FROM t JOIN x ON t.k = x.k", "WITH"),
        ("SELECT t.k, COUNT(*) AS c FROM t JOIN t AS t2 ON t.a = t2.a GROUP BY t.k", "self join"),
    ],
)
def test_the_join_gate_refuses_loudly(sql: str, why: str, stream_on: None) -> None:
    with pytest.raises(DeclarativeUnsupported, match=why):
        _emit_j("-- stream: t\n" + sql)


def test_a_join_without_its_stream_table_is_refused(stream_on: None) -> None:
    with pytest.raises(DeclarativeUnsupported, match="needs its stream table"):
        _emit_j(J_SQL.removeprefix("-- stream: t\n"))
    with pytest.raises(DeclarativeUnsupported, match="names no table"):
        _emit_j(J_SQL.replace("-- stream: t", "-- stream: lineitem"))
    with pytest.raises(DeclarativeUnsupported, match="more than one"):
        _emit_j("-- stream: u\n" + J_SQL)
    with pytest.raises(DeclarativeUnsupported, match="names no table"):  # a one-table query names its own table or none
        emit_declarative_spec("-- stream: u\nSELECT COUNT(*) AS c FROM t", J_SCHEMA, J_CATALOG)


def test_min_max_over_a_join_is_refused(stream_on: None) -> None:
    with pytest.raises(DeclarativeUnsupported, match="MIN / MAX over a join"):
        _emit_j("-- stream: t\nSELECT u.g, MIN(t.a) AS mn FROM t JOIN u ON t.k = u.k WHERE u.k IS NOT NULL GROUP BY u.g")


# ---- the rule: the table with the most rows after its own filters -----------------------------------------------------------------


def _small_db(path: Path, n_t: int, n_u: int) -> None:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (a INTEGER NOT NULL, k VARCHAR NOT NULL, m DECIMAL(12,2) NOT NULL)")
    con.execute("CREATE TABLE u (k VARCHAR, g VARCHAR NOT NULL, w INTEGER NOT NULL)")
    con.executemany("INSERT INTO t VALUES (?, ?, ?)", [(i % 10, f"k{i % 7}", i) for i in range(n_t)])
    con.executemany("INSERT INTO u VALUES (?, ?, ?)", [(f"k{i % 7}", f"g{i % 3}", i) for i in range(n_u)])
    con.close()


def test_choose_stream_table_counts_rows_after_each_tables_own_filters(stream_on: None, tmp_path: Path) -> None:
    db = tmp_path / "j.duckdb"
    _small_db(db, 100, 40)
    sql = "SELECT u.g, COUNT(*) AS c FROM t JOIN u ON t.k = u.k GROUP BY u.g"
    assert stream_join.choose_stream_table(sql, J_SCHEMA, db)["table"] == "t"
    # t's own filter keeps 10 of its 100 rows; u keeps 40: u is streamed (the join equality is not a filter of either table)
    choice = stream_join.choose_stream_table(sql.replace("GROUP BY", "WHERE t.a = 3 GROUP BY"), J_SCHEMA, db)
    assert choice == {"table": "u", "rows_after_filters": {"t": 10, "u": 40}, "rule": stream_join.RULE}
    # an ON conjunct of one table counts as its filter too; a tie goes to the table first in FROM
    tie = "SELECT u.g, COUNT(*) AS c FROM u JOIN t ON t.k = u.k AND t.a < 4 GROUP BY u.g"
    assert stream_join.choose_stream_table(tie, J_SCHEMA, db) == {"table": "u", "rows_after_filters": {"u": 40, "t": 40}, "rule": stream_join.RULE}
    out = stream_join.ensure_header(sql, J_SCHEMA, db, tmp_path / "run")
    assert out == "-- stream: t\n" + sql
    assert json.loads((tmp_path / "run" / "stream_choice.json").read_text())["rows_after_filters"] == {"t": 100, "u": 40}
    assert stream_join.ensure_header(out, J_SCHEMA, db, None) == out  # a named table stays
    assert stream_join.ensure_header("SELECT COUNT(*) AS c FROM t", J_SCHEMA, None, None) == "SELECT COUNT(*) AS c FROM t"
    with pytest.raises(DeclarativeUnsupported, match="LEMMA_MEASURE_DB"):
        stream_join.ensure_header(sql, J_SCHEMA, None, None)


# ---- admission ------------------------------------------------------------------------------------------------------------------------


def test_admission_accepts_the_join_fixture(stream_on: None) -> None:
    regions = stream.extract_regions((FIX / J_FIXTURE).read_text())
    assert sorted(regions) == ["build", "finish", "helpers", "init", "merge", "state", "step"]
    res = admit_stream(**regions, spec_rs=_emit_j())
    assert res.ok, res.violations


@pytest.mark.parametrize(
    "region, text, why",
    [
        ("step", "    let r = pool_step(&x, 0, &y);\n    true", "stream internals: pool_step"),
        ("finish", "    let pl: Pool = x;\n    None", "stream internals: Pool"),
        ("build", "    let ok = cols_ok_u(b_u);\n    None", "stream internals: cols_ok_u"),
        ("state", "pub struct QAcc {\n    pub z: u8,\n}", "QBuild"),
        ("helpers", "pub open spec fn qacc_inv(s: &QAcc, bld: &QBuild) -> bool { true }\npub open spec fn st_val(s: &QAcc, bld: &QBuild, k: Key) -> Agg { agg_zero() }", "qbuild_inv"),
        ("build", "    assume(false);\n    None", "assume"),
        ("state", "pub struct QAcc {\n    pub z: u8,\n}\npub struct QBuild {\n    pub z: u8,\n}\npub struct Slot {\n    pub z: u8,\n}", "Slot"),
    ],
)
def test_admission_rejects_in_a_join(region: str, text: str, why: str, stream_on: None) -> None:
    regions = stream.extract_regions((FIX / J_FIXTURE).read_text())
    regions[region] = text
    res = admit_stream(**regions, spec_rs=_emit_j())
    assert not res.ok and any(why in v for v in res.violations), res.violations


def test_admission_wants_the_build_region_exactly_for_a_join(stream_on: None) -> None:
    regions = stream.extract_regions((FIX / J_FIXTURE).read_text())
    build = regions.pop("build")
    assert any("AGENT_BUILD" in v for v in admit_stream(**regions, spec_rs=_emit_j()).violations)
    one = emit_declarative_spec("SELECT k, COUNT(*) AS c FROM t GROUP BY k", J_SCHEMA, J_CATALOG)
    p1 = stream.extract_regions((FIX / "group_string_count_sum.rs").read_text())
    assert any("join stream spec only" in v for v in admit_stream(**p1, build=build, spec_rs=one).violations)


# ---- the prompt -------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("examples", ["full", "none"])
def test_join_prompt_states_the_build_contract(examples: str, stream_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.stream_prompt import build_stream_prompt

    monkeypatch.setenv("LEMMA_EXAMPLES", examples)
    spec = _emit_j()
    text = build_stream_prompt(sql=J_SQL, spec_path="s.rs", edit_path="e.rs", lemma_index="IDX", last_error="", in_docker=True, spec_text=spec, restart_note="")
    assert "pub fn q_build(b_u: &Cols_u, p: &Params) -> (r: Option<QBuild>)" in text
    assert "`spec fn qbuild_inv(bld: &QBuild, b_u: &Cols_u, p: &Params) -> bool`" in text
    assert "Seven regions are kept" in text and "`// AGENT_BUILD_START`" in text and "uniqueness assumption: handle duplicates" in text
    assert ("## Probe structures (a join)" in text) == (examples == "full")  # technique advice is a RECIPE: left out with examples = none
    assert ("join_group_build_key" in text or "a join: a GROUP BY a build-side" in text) == (examples == "full")
    for name in ("Q12", "lineitem", "orders", "TPC"):
        assert name not in text, name


# ---- Verus: host scaffold with a stub agent ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    ["invented", "invented_two_builds", "tpch_q12_stream_orders", "tpch_q12_stream_lineitem", "sec_q3_without_having"],
)
def test_join_host_scaffold_verifies_with_a_stub_agent(case: str, stream_on: None, tmp_path: Path) -> None:
    """AGENTS.md "Host scaffold": every host item (agg lemmas, chunk view, Pool runtime) is proved with q_build None, q_step false,
    q_merge / q_finish None. Q12: the rule streams orders on SF10 (15,000,000 rows vs 310,803 lineitem rows after its filters); SEC
    q3: num (33,234,006 rows after its filters vs 27,333 of sub)."""
    _needs_verus()
    spec = {
        "invented": lambda: _emit_j(),
        # two build tables: the inner fold nests (stream_hits_d1 over u, stream_hits_d2 over v)
        "invented_two_builds": lambda: emit_declarative_spec(
            "-- stream: t\nSELECT v.h, COUNT(*) AS c, SUM(t.m) AS sm FROM t JOIN u ON t.k = u.k JOIN v ON u.g = v.g GROUP BY v.h",
            {**J_SCHEMA, "v": {"g": "varchar", "h": "integer"}},
            structural_catalog(set()),
        ),
        "tpch_q12_stream_orders": lambda: emit_declarative_spec(stream_join.with_header(Q12, "orders"), TPCH_SCHEMA, None),
        "tpch_q12_stream_lineitem": lambda: emit_declarative_spec(stream_join.with_header(Q12, "lineitem"), TPCH_SCHEMA, None),
        "sec_q3_without_having": lambda: emit_declarative_spec(stream_join.with_header(SEC_Q3, "num"), SEC_SCHEMA, SEC_CATALOG),
    }[case]()
    out = _verus(assemble_stream_program(spec, stream_join.stub(spec)), tmp_path, f"stub_{case}")
    assert _verified(out), out[-4000:]


# ---- Verus: the join fixture, its mutants, runtime mutants ---------------------------------------------------------------------------


def test_join_fixture_verifies(stream_on: None, tmp_path: Path) -> None:
    _needs_verus()
    out = _verus(_fixture_program(), tmp_path, "join_fixture")
    assert _verified(out), out[-4000:]


def _sub(region: str, old: str, new: str):
    def mutate(regions: dict[str, str]) -> dict[str, str]:
        assert regions[region].count(old) == 1, (region, old)
        regions[region] = regions[region].replace(old, new, 1)
        return regions

    return mutate


FIXTURE_MUTANTS = {
    # the probe starts at the second build row of the key's chain: the head match is missed
    "probe_misses_the_first_match": _sub("step", "Some(h) => *h,", "Some(h) => bld.nxt[*h],"),
    # the probe stops after the first match: a duplicate build key is counted once
    "duplicate_build_key_counted_once": _sub("step", "            a = nj;\n", "            a = b_u.n;\n"),
    # the build keeps one row per key (every chain ends at once): duplicates are dropped
    "build_drops_duplicate_keys": _sub("build", "                Some(h) => *h,\n                None => n,", "                Some(h) => n,\n                None => n,"),
    "merge_drops_b": _sub("merge", "m.cnt.set(j, c);", "m.cnt.set(j, m.cnt[j]);"),
}


@pytest.mark.parametrize("mutant", sorted(FIXTURE_MUTANTS))
def test_join_fixture_mutants_do_not_verify(mutant: str, stream_on: None, tmp_path: Path) -> None:
    _needs_verus()
    out = _verus(_fixture_program(mutate=FIXTURE_MUTANTS[mutant]), tmp_path, mutant)
    assert _fails(out), out[-3000:]


RUNTIME_MUTANTS = {
    "segment_records_wrong_offset": ("let s = Seg { j: raw.j as usize, off: c.off, len: c.len };", "let s = Seg { j: raw.j as usize, off: c.off + 1, len: c.len };"),
    "merge_drops_slot_segments": ("segs.append(&mut segs_b);", "segs_b.clear();"),
    "no_end_check": ("    if o != n {\n        return StreamOut::Error;\n    }\n", ""),
    "chunk_recorded_twice": ("                        segs.push(s);\n", "                        segs.push(s);\n                        segs.push(s);\n"),
}


@pytest.mark.parametrize("mutant", sorted(RUNTIME_MUTANTS))
def test_pool_runtime_mutants_do_not_verify(mutant: str, stream_on: None, tmp_path: Path) -> None:
    """The scheduling glue is not trusted in a join either: a Pool that could answer from a lost, misplaced or unstepped chunk does not
    verify."""
    _needs_verus()
    old, new = RUNTIME_MUTANTS[mutant]
    program = _fixture_program()
    assert program.count(old) == 1, mutant
    out = _verus(program.replace(old, new), tmp_path, mutant)
    assert _fails(out), out[-3000:]


# ---- differential: the compiled fixture (binary-mode main) against DuckDB --------------------------------------------------------------


def _random_tables(con: duckdb.DuckDBPyConnection, rng: random.Random, n_t: int, n_u: int, keys: int) -> None:
    con.execute("CREATE OR REPLACE TABLE t (a INTEGER NOT NULL, k VARCHAR NOT NULL, m DECIMAL(12,2) NOT NULL)")
    con.execute("CREATE OR REPLACE TABLE u (k VARCHAR, g VARCHAR NOT NULL, w INTEGER NOT NULL)")
    names = ["", "x", "a string longer than twelve", "ünïcödé", *(f"k{i}" for i in range(keys))]
    groups = ["", "G", "group longer than twelve", "ä"]
    t_rows = [(rng.randint(-5, 5), rng.choice(names + ["nomatch", "zz"]), rng.randint(-(10**11), 10**11) / 100) for _ in range(n_t)]
    # duplicate build keys (few names for many rows), NULL keys, and names no stream row carries
    u_rows = [(None if rng.random() < 0.2 else rng.choice(names + ["only_u"]), rng.choice(groups), rng.randint(0, 9)) for _ in range(n_u)]
    if t_rows:
        con.executemany("INSERT INTO t VALUES (?, ?, CAST(? AS DECIMAL(12,2)))", t_rows)
    if u_rows:
        con.executemany("INSERT INTO u VALUES (?, ?, ?)", u_rows)


@pytest.fixture(scope="module")
def join_binary(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    _needs_verus()
    tmp = tmp_path_factory.mktemp("stream_join_bin")
    mp = pytest.MonkeyPatch()
    for key in _ENV_KEYS:
        mp.delenv(key, raising=False)
    mp.setenv("LEMMA_STREAM", "1")
    mp.setenv("LEMMA_TEMPLATES", "1")
    mp.setenv("LEMMA_PUSHDOWN", "0")
    try:
        cols_t, cols_u = tmp / "cols_t.bin", tmp / "cols_u.bin"
        program = _fixture_program(column_bins={"t": str(cols_t), "u": str(cols_u)})
        log = _verus(program, tmp, "join_fixture", "--compile", "--", "-C", "opt-level=3")
        assert _verified(log), log[-3000:]
        assert (tmp / "join_fixture").is_file(), log[-2000:]
    finally:
        mp.undo()
    return tmp / "join_fixture", cols_t, cols_u


@pytest.mark.parametrize(
    "seed, n_t, n_u, keys",
    [(1, 0, 5, 3), (2, 7, 0, 3), (3, 1, 1, 1), (4, 50, 12, 2), (5, 3000, 400, 6), (6, 2500, 60, 40), (7, 300, 30, 0)],
    ids=["empty_stream", "empty_build", "one_each", "heavy_duplicates", "large", "many_keys", "special_keys_only"],
)
def test_join_differential_against_duckdb(seed: int, n_t: int, n_u: int, keys: int, stream_on: None, join_binary, tmp_path: Path) -> None:
    from research_loop.decl_query_measure import write_query_measure

    binary, cols_t, cols_u = join_binary
    db = tmp_path / "j.duckdb"
    con = duckdb.connect(str(db))
    _random_tables(con, random.Random(seed), n_t, n_u, keys)
    con.close()
    prep = write_query_measure(sql=J_SQL, schema=J_SCHEMA, catalog=J_CATALOG, db_path=db, dest=tmp_path / "prep")
    cols_t.write_bytes(Path(prep["bins"]["t"]).read_bytes())
    cols_u.write_bytes(Path(prep["bins"]["u"]).read_bytes())
    for chunk_max in (1, 7, 2048):
        for threads in (1, 3, 8):
            proc = subprocess.run([str(binary), str(chunk_max), str(threads), str(seed)], capture_output=True, text=True, timeout=120, check=False)
            assert proc.returncode == 0, (chunk_max, threads, proc.stdout[-1000:], proc.stderr[-2000:])
            assert f"STREAM_THREADS: {threads}" in proc.stdout and "STREAM_BUILD_US: " in proc.stdout
            err = rows_match_error(rows_from_stdout_general(proc.stdout), prep["rows"], prep["kinds"], prep.get("order_cols"), bool(prep.get("limited")), prep.get("tie_rows"))
            assert err is None, (chunk_max, threads, err, proc.stdout[-2000:], prep["rows"])
