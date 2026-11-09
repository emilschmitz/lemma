"""Streaming executors: VARCHAR template parameters and SQL LIKE (lemma.toml [run] stream, docs/STREAM.md "String parameters and
LIKE", declarative_spec/stream.py read_params / params_block, stream_join).

A VARCHAR parameter (`=`, `<>`, IN lists: what templates.param_ranges states and lift.lift_constants lifts) is a `String` field of
Params. One table: Exec merges workers that each hold their own Params, so the spec reads the strings through params_canon(p) (a
String of the same text, chosen; proved, nothing trusted) and params_eq compares the texts. A join: one Pool holds one Params, the spec
reads `&p.x`. LIKE (`spec_like` over Seq<char>, the emitter's exact text) is a per-row predicate of agg_row, in WHERE or inside a CASE.
No trusted item is added. Verus: the host scaffold with a stub agent (invented one-table and join queries; TPC-H Q3 / Q12 / Q14 and the
lifted SEC q6 / q4 templates streaming the tables the stream_join rule picks on tpch_sf10.duckdb and sec_edgar_dec.duckdb), the two
fixtures (string parameters with = and IN; LIKE inside CASE inside SUM) and their mutants (a parameter ignored, an IN value ignored,
LIKE ignored or half checked, exec_merge without the parameter check). The compiled fixtures (binary-mode main: random chunk sizes,
several threads) against DuckDB on random tables under several bindings. The prompt's general notes.
"""

from __future__ import annotations

import json
import random
import re
import subprocess
from pathlib import Path

import duckdb
import pytest

from declarative_spec import stream, stream_join, templates
from declarative_spec.admit import admit_stream
from declarative_spec.assemble import assemble_stream_program
from declarative_spec.bench import rows_from_stdout_general, rows_match_error
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from research_loop.structural_catalog import structural_catalog

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "declarative_proofs" / "stream"
GUARD = ROOT / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")

S_SCHEMA = {"t": {"a": "integer", "g": "varchar", "s": "varchar", "m": "decimal(12,2)"}}
S_CATALOG = structural_catalog(set())
PARAMS_SQL = "-- params: x VARCHAR, y VARCHAR, z VARCHAR\nSELECT COUNT(*) AS c, SUM(m) AS sm FROM t WHERE s = $x AND g IN ($y, $z)"
LIKE_SQL = "SELECT SUM(CASE WHEN s LIKE 'ab%' THEN m ELSE 0 END) AS sp, SUM(m) AS sm, COUNT(*) AS c FROM t"
FIXTURES = {"ungrouped_string_params.rs": PARAMS_SQL, "ungrouped_like_case.rs": LIKE_SQL}
_ENV_KEYS = ("LEMMA_ASSUMPTIONS", "LEMMA_PARALLEL_VSTD", "LEMMA_STRING_ENCODING", "LEMMA_AGENT_SCAN", "LEMMA_JOIN_CHAIN", "LEMMA_STREAM", "LEMMA_EXAMPLES")

J_SCHEMA = {"t": {"a": "integer", "k": "varchar", "m": "decimal(12,2)"}, "u": {"k": "varchar", "g": "varchar", "w": "integer"}}
J_PARAMS_SQL = "-- params: x VARCHAR, y VARCHAR, lo BIGINT\nSELECT u.g, COUNT(*) AS c, SUM(t.m) AS sm FROM t JOIN u ON t.k = u.k WHERE u.g <> $x AND t.k IN ($y, 'zz') AND u.w > $lo GROUP BY u.g"
J_LIKE_SQL = "SELECT SUM(CASE WHEN u.g LIKE 'PRO%' THEN t.m ELSE 0 END) AS sp, SUM(t.m) AS sm FROM t JOIN u ON t.k = u.k WHERE t.k LIKE '%a_'"

TPCH_SCHEMA = json.loads((ROOT / "tests" / "fixtures" / "tpch22" / "schema.json").read_text())
SEC_COLUMNS = json.loads((ROOT / "configs" / "data" / "sec_edgar_3y_dec.json").read_text())["columns"]
SEC_SCHEMA = {t: {c: ty.lower() for c, ty in cs.items()} for t, cs in SEC_COLUMNS.items()}
# the columns of sec_edgar_dec.duckdb that hold NULLs (tests/test_stream_null_distinct.py)
SEC_NULLABLE = {
    ("num", "coreg"), ("num", "footnote"), ("sub", "afs"), ("sub", "cityba"), ("sub", "countryba"), ("sub", "countryinc"), ("sub", "fp"),
    ("sub", "fy"), ("sub", "fye"), ("sub", "sic"), ("sub", "stprba"), ("tag", "crdr"), ("tag", "doc"), ("tag", "tlabel"), ("pre", "plabel"),
    ("pre", "stmt"),
}
QT = ROOT / "configs" / "query_templates"
# The stream table the stream_join rule picks at binding 0 of the seed-1 draw (2026-11-08, read-only on
# research_loop/generated/tpch_sf10.duckdb and holdout/gendb_sec_edgar/duckdb/sec_edgar_dec.duckdb; rows after each table's filters):
# Q3 lineitem 32,233,888 (orders 7,314,636, customer 300,276); Q12 orders 15,000,000 (lineitem 312,478); Q14 part 2,000,000 (lineitem
# 749,991); SEC q6 num 33,234,006 (pre 252,621, sub 7,732); SEC q4 num 33,234,006 (tag 1,070,662, pre 252,621, sub 16,559).
REAL = {
    "tpch_q03": (QT / "tpch" / "q03.sql", "lineitem", TPCH_SCHEMA, None),
    "tpch_q12": (QT / "tpch" / "q12.sql", "orders", TPCH_SCHEMA, None),
    "tpch_q14": (QT / "tpch" / "q14.sql", "part", TPCH_SCHEMA, None),
    "sec_q6": (QT / "sec_edgar" / "q6.sql", "num", SEC_SCHEMA, SEC_NULLABLE),
    "sec_q4": (QT / "sec_edgar" / "q4.sql", "num", SEC_SCHEMA, SEC_NULLABLE),
}


@pytest.fixture
def stream_on(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LEMMA_STREAM", "1")
    monkeypatch.setenv("LEMMA_TEMPLATES", "1")
    monkeypatch.setenv("LEMMA_PUSHDOWN", "0")


def _emit(sql: str) -> str:
    return emit_declarative_spec(sql, S_SCHEMA, S_CATALOG)


def _emit_join(sql: str) -> str:
    return emit_declarative_spec(stream_join.with_header(sql, "t"), J_SCHEMA, structural_catalog(set()))


def _real(case: str) -> str:
    path, table, schema, nullable = REAL[case]
    return emit_declarative_spec(stream_join.with_header(path.read_text(), table), schema, None if nullable is None else structural_catalog(nullable))


def _verus(program: str, tmp: Path, name: str, *extra: str) -> str:
    rs = tmp / f"{name}.rs"
    rs.write_text(program)
    proc = subprocess.run(
        [str(GUARD), str(rs), "--triggers-mode", "silent", "--rlimit", "16", *extra],
        capture_output=True,
        text=True,
        cwd=tmp,
        timeout=3600,
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


def _trusted(spec: str) -> list[str]:
    return [re.search(r"pub fn (\w+)", spec[m.start():]).group(1) for m in re.finditer(r"#\[verifier::external_body\]", spec)]


def _fixture_program(name: str, *, mutate=None, column_bins: dict[str, str] | None = None) -> str:
    regions = stream.extract_regions((FIX / name).read_text())
    if mutate is not None:
        regions = mutate(dict(regions))
    return assemble_stream_program(_emit(FIXTURES[name]), regions, column_bins=column_bins)


# ---- the contract text and the gate ---------------------------------------------------------------------------------------------------


def test_one_table_string_parameters_are_string_fields_read_through_params_canon(stream_on: None) -> None:
    spec = _emit(PARAMS_SQL)
    assert "#[derive(Clone)]\n#[verifier::allow(autoderive_clone_without_spec)]\npub struct Params {\n    pub x: String,\n    pub y: String,\n    pub z: String,\n}" in spec
    # params_eq compares the texts (vstd's String ==); params_canon depends on the texts only
    assert "        r == (a.x@ == b.x@ && a.y@ == b.y@ && a.z@ == b.z@),\n{\n    a.x == b.x && a.y == b.y && a.z == b.z\n}" in spec
    assert "pub open spec fn params_canon(p: &Params) -> Params {\n    Params { x: param_str(p.x@), y: param_str(p.y@), z: param_str(p.z@) }\n}" in spec
    assert "        choose|s: String| s@ == v\n" in spec and "broadcast use params_text::lemma_param_text;" in spec
    assert "row_hit(t, i0, &params_canon(p).x, &params_canon(p).y, &params_canon(p).z)" in spec  # agg_row
    assert "res matches Some(r) ==> run_query_ok(&t@, &params_canon(p).x, &params_canon(p).y, &params_canon(p).z, r)," in spec
    assert "assert(seg_agg(sh.id, k, p_b) =~= seg_agg(sh.id, k, p));" in spec  # exec_merge: b's fold is a's when the texts agree
    assert _trusted(spec) == ["chunk_t", "str_ent", "stream_end_t"]
    for word in ("assume(", "admit(", "arbitrary(", "axiom fn", "external_body]\npub open spec", "#[verifier::external]\npub"):
        assert word not in spec.split("// ---- the stream: ghost table")[0].split("// ---- the query's aggregate")[1], word
    # the integer parameters of a template keep phase 1's Copy form
    ints = _emit("-- params: lo BIGINT\nSELECT COUNT(*) AS c FROM t WHERE a > $lo")
    assert "#[derive(Clone, Copy)]\npub struct Params {\n    pub lo: i64,\n}" in ints and "params_canon" not in ints


def test_join_string_parameters_are_read_from_the_one_pool_params(stream_on: None) -> None:
    spec = _emit_join(J_PARAMS_SQL)
    assert stream_join.is_join(spec)
    assert "pub struct Params {\n    pub x: String,\n    pub y: String,\n    pub lo: i64,\n}" in spec
    assert "params_canon" not in spec and "param_str" not in spec
    assert "&p.x, &p.y, p.lo" in spec
    assert _trusted(spec) == ["chunk_t", "str_ent", "stream_end_t"]


@pytest.mark.parametrize(
    "sql",
    [
        LIKE_SQL,
        "SELECT COUNT(*) AS c, SUM(m) AS sm FROM t WHERE g LIKE '%x_'",
        "SELECT g, COUNT(*) AS c FROM t WHERE s LIKE 'a%b' GROUP BY g",
        "-- params: x VARCHAR\nSELECT SUM(CASE WHEN s LIKE '_b%' THEN m ELSE 0 END) AS sp FROM t WHERE g = $x",
    ],
)
def test_like_in_where_and_in_case_is_accepted(sql: str, stream_on: None) -> None:
    spec = _emit(sql)
    assert stream.is_stream(spec) and "pub open spec fn spec_like(" in spec
    assert _trusted(spec) == ["chunk_t", "str_ent", "stream_end_t"]


def test_like_over_a_join_is_accepted(stream_on: None) -> None:
    spec = _emit_join(J_LIKE_SQL)
    assert stream_join.is_join(spec) and "spec_like(" in spec


def test_a_spec_like_of_another_text_is_still_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the emitter's own spec_like (emit_like.SPEC_LIKE_FN) is a per-row predicate; any other recursive spec fn is not a fold."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LEMMA_TEMPLATES", "1")
    monkeypatch.setenv("LEMMA_PUSHDOWN", "0")
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "off")
    monkeypatch.setenv("LEMMA_AGENT_SCAN", "0")
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "plain")
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "0")
    spec = _emit("SELECT COUNT(*) AS c FROM t WHERE g LIKE '%x_'")
    monkeypatch.setenv("LEMMA_STREAM", "1")
    assert stream.is_stream(stream.to_stream(spec))
    changed = spec.replace("    } else if p[0] == '_' || p[0] == s[0] {", "    } else if p[0] == s[0] {")
    assert changed != spec
    with pytest.raises(DeclarativeUnsupported, match="spec fn spec_like is not a recognized fold"):
        stream.to_stream(changed)


# ---- Verus: host scaffold with a stub agent --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    ["one_table_params_grouped", "one_table_like_where", "join_params", "join_like", *sorted(REAL)],
)
def test_host_scaffold_verifies_with_a_stub_agent(case: str, stream_on: None, tmp_path: Path) -> None:
    """AGENTS.md "Host scaffold": params_canon / param_str / lemma_param_text, the agg lemmas over canonical parameters, the exec_merge
    text check, the Pool with a String Params: `N verified, 0 errors` with a stub agent. The real templates stream the table the
    stream_join rule picks on the real database (REAL)."""
    _needs_verus()
    spec = {
        "one_table_params_grouped": lambda: _emit("-- params: x VARCHAR, y VARCHAR, z VARCHAR, lo BIGINT\nSELECT g, COUNT(*) AS c, SUM(m) AS sm, MIN(a) AS mn FROM t WHERE s <> $x AND g IN ($y, $z) AND a > $lo GROUP BY g"),
        "one_table_like_where": lambda: _emit("SELECT g, SUM(CASE WHEN s LIKE 'ab%' THEN m ELSE 0 END) AS sp, COUNT(*) AS c FROM t WHERE g LIKE '%x_' GROUP BY g"),
        "join_params": lambda: _emit_join(J_PARAMS_SQL),
        "join_like": lambda: _emit_join(J_LIKE_SQL),
    }.get(case, lambda: _real(case))()
    regions = stream_join.stub(spec) if stream_join.is_join(spec) else stream.STUB
    out = _verus(assemble_stream_program(spec, regions), tmp_path, f"stub_{case}")
    assert _verified(out), out[-4000:]


# ---- Verus: the fixtures and their mutants ------------------------------------------------------------------------------------------


def test_admission_accepts_the_fixtures(stream_on: None) -> None:
    for name, sql in FIXTURES.items():
        res = admit_stream(**stream.extract_regions((FIX / name).read_text()), spec_rs=_emit(sql))
        assert res.ok, (name, res.violations)


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_fixture_verifies(name: str, stream_on: None, tmp_path: Path) -> None:
    _needs_verus()
    out = _verus(_fixture_program(name), tmp_path, name.removesuffix(".rs"))
    assert _verified(out), out[-4000:]


def _sub(region: str, old: str, new: str):
    def mutate(regions: dict[str, str]) -> dict[str, str]:
        assert regions[region].count(old) == 1, (region, old)
        regions[region] = regions[region].replace(old, new, 1)
        return regions

    return mutate


MUTANTS = {
    # the parameter $x is ignored: every s passes
    ("ungrouped_string_params.rs", "x_ignored"): _sub("step", "let hit = hs[js] && hg[jg];", "let hit = hg[jg];"),
    # s is compared with $y instead of $x
    ("ungrouped_string_params.rs", "x_read_as_y"): _sub("step", "memo_eq(&c.s, ms, p.x.as_str(), p.x.as_str())", "memo_eq(&c.s, ms, p.y.as_str(), p.y.as_str())"),
    # the IN list loses its second value $z
    ("ungrouped_string_params.rs", "in_value_ignored"): _sub("step", "memo_eq(&c.g, mg, p.y.as_str(), p.z.as_str())", "memo_eq(&c.g, mg, p.y.as_str(), p.y.as_str())"),
    # the memo says "equal" for every entry
    ("ungrouped_string_params.rs", "memo_all_true"): _sub("helpers", "        let hit = eq_text(e, x) || eq_text(e, y);\n", "        let hit = true;\n"),
    # LIKE ignored: the CASE sums every row
    ("ungrouped_like_case.rs", "like_ignored"): _sub("step", "let v: i64 = if hl[j] { m } else { 0 };", "let v: i64 = m;"),
    # LIKE 'ab%' checked as "starts with a"
    ("ungrouped_like_case.rs", "like_half_checked"): _sub("helpers", "e.get_char(0) == 'a' && e.get_char(1) == 'b'", "e.get_char(0) == 'a'"),
    # the CASE's branches swapped
    ("ungrouped_like_case.rs", "like_negated"): _sub("step", "if hl[j] { m } else { 0 }", "if hl[j] { 0 } else { m }"),
}


@pytest.mark.parametrize("case", sorted(MUTANTS), ids=lambda c: f"{c[0].removesuffix('.rs')}:{c[1]}")
def test_fixture_mutants_do_not_verify(case: tuple[str, str], stream_on: None, tmp_path: Path) -> None:
    _needs_verus()
    out = _verus(_fixture_program(case[0], mutate=MUTANTS[case]), tmp_path, case[1])
    assert _fails(out), out[-3000:]


def test_exec_merge_without_the_parameter_check_does_not_verify(stream_on: None, tmp_path: Path) -> None:
    """The host runtime: merging two workers' states needs equal parameter texts (a's fold and b's fold are then one fold)."""
    _needs_verus()
    program = _fixture_program("ungrouped_string_params.rs")
    check = "    if sh.id != sh_b.id || !params_eq(&p, &p_b) {\n"
    assert program.count(check) == 1
    out = _verus(program.replace(check, "    if sh.id != sh_b.id {\n"), tmp_path, "merge_unchecked")
    assert _fails(out), out[-3000:]


# ---- differential: the compiled fixtures (binary-mode main) against DuckDB, several bindings ----------------------------------------

VALS = ["", "x", "ab", "abc", "a", "b", "xab", "AB", "äb", "ünïcödé", "a string longer than twelve", "ab" + "z" * 30]
BINDINGS = [
    {"x": "x", "y": "ab", "z": "abc"},
    {"x": "", "y": "", "z": "zz"},
    {"x": "ünïcödé", "y": "x", "z": "x"},
    {"x": "nomatch", "y": "a", "z": "b"},
    {"x": "a string longer than twelve", "y": "ab" + "z" * 30, "z": "äb"},
]


def _random_table(con: duckdb.DuckDBPyConnection, rng: random.Random, n: int) -> None:
    con.execute("CREATE OR REPLACE TABLE t (a INTEGER NOT NULL, g VARCHAR NOT NULL, s VARCHAR NOT NULL, m DECIMAL(12,2) NOT NULL)")
    rows = [(rng.randint(-5, 5), rng.choice(VALS), rng.choice(VALS), rng.randint(-(10**11), 10**11) / 100) for _ in range(n)]
    if rows:
        con.executemany("INSERT INTO t VALUES (?, ?, ?, CAST(? AS DECIMAL(12,2)))", rows)


@pytest.fixture(scope="module")
def binaries(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[Path, Path]]:
    _needs_verus()
    tmp = tmp_path_factory.mktemp("stream_strings_bin")
    mp = pytest.MonkeyPatch()
    for key in _ENV_KEYS:
        mp.delenv(key, raising=False)
    mp.setenv("LEMMA_STREAM", "1")
    mp.setenv("LEMMA_TEMPLATES", "1")
    mp.setenv("LEMMA_PUSHDOWN", "0")
    out: dict[str, tuple[Path, Path]] = {}
    try:
        for name in FIXTURES:
            cols = tmp / f"{name}.cols.bin"
            stem = name.removesuffix(".rs")
            log = _verus(_fixture_program(name, column_bins={"t": str(cols)}), tmp, stem, "--compile", "--", "-C", "opt-level=3")
            assert _verified(log), log[-3000:]
            assert (tmp / stem).is_file(), log[-2000:]
            out[name] = (tmp / stem, cols)
    finally:
        mp.undo()
    return out


@pytest.mark.parametrize("name", sorted(FIXTURES))
@pytest.mark.parametrize("seed, n", [(1, 0), (2, 1), (3, 40), (4, 3000)], ids=["empty", "one_row", "small", "large"])
def test_differential_against_duckdb(name: str, seed: int, n: int, stream_on: None, binaries, tmp_path: Path) -> None:
    from research_loop.decl_query_measure import write_query_measure

    binary, cols = binaries[name]
    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    _random_table(con, random.Random(seed), n)
    con.close()
    sql = FIXTURES[name]
    template = templates.parse_template(sql)
    for b, binding in enumerate(BINDINGS if template is not None else [None]):
        prep = write_query_measure(sql=sql, schema=S_SCHEMA, catalog=S_CATALOG, db_path=db, dest=tmp_path / f"prep{b}",
                                   bindings=None if binding is None else [binding])
        cols.write_bytes(Path(prep["bins"]["t"]).read_bytes())
        args = [] if binding is None else templates.binary_args(template, binding)
        for chunk_max in (1, 7, 2048):
            for threads in (1, 3, 8):
                proc = subprocess.run([str(binary), *args, str(chunk_max), str(threads), str(seed)], capture_output=True, text=True, timeout=120, check=False)
                assert proc.returncode == 0, (binding, chunk_max, threads, proc.stdout[-1000:], proc.stderr[-2000:])
                err = rows_match_error(rows_from_stdout_general(proc.stdout), prep["rows"], prep["kinds"], prep.get("order_cols"), bool(prep.get("limited")), prep.get("tie_rows"))
                assert err is None, (binding, chunk_max, threads, err, proc.stdout[-2000:], prep["rows"])


# ---- the prompt ------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("examples", ["full", "none"])
def test_prompt_notes_for_string_parameters_and_like(examples: str, stream_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.stream_prompt import build_stream_prompt

    monkeypatch.setenv("LEMMA_EXAMPLES", examples)

    def prompt(sql: str, spec: str) -> str:
        return build_stream_prompt(sql=sql, spec_path="s.rs", edit_path="e.rs", lemma_index="IDX", last_error="", in_docker=True, spec_text=spec, restart_note="")

    par = prompt(PARAMS_SQL, _emit(PARAMS_SQL))
    assert "## String parameters and LIKE" in par and "`p.x`, `p.y`, `p.z`" in par and "`params_canon(p).x@ == p.x@`" in par
    assert "`spec_like(text, pattern)`" not in par
    like = prompt(LIKE_SQL, _emit(LIKE_SQL))
    assert "`spec_like(text, pattern)`" in like and "A VARCHAR parameter is" not in like
    join = prompt(J_PARAMS_SQL, _emit_join(J_PARAMS_SQL))
    assert "The spec reads it as `&p.x`" in join and "params_canon" not in join
    for text in (par, like):
        assert ("## String parameters and LIKE fast" in text) == (examples == "full")  # technique advice is a RECIPE
    plain = prompt("SELECT s, COUNT(*) AS c FROM t GROUP BY s", _emit("SELECT s, COUNT(*) AS c FROM t GROUP BY s"))
    assert "## String parameters and LIKE" not in plain
    for word in ("PROMO", "BUILDING", "MAIL", "USD", "l_shipmode", "p_type"):  # general notes, nothing of a benchmark query
        assert word not in par.split("## String parameters and LIKE")[1].split("\n## ")[0], word
