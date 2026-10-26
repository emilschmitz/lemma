"""Stateful accelerators (lemma.toml `stateful`): contract emission, admission, assembly, the host runtime, the prompt, and
end-to-end Verus + differential runs of the two fixture accelerators (tests/fixtures/declarative_proofs/stateful_*.rs).

The differential runs compile the fixtures in serve mode (one call per stdin line: `<version> <column file per table>`) and
compare every answer with DuckDB on the table as it is at that version: random small tables under inserts, deletes and
updates (each change bumps the version), and TPC-H SF1 (read-only research_loop/generated/tpch_sf1.duckdb).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import random
import re
import subprocess
from pathlib import Path

import duckdb
import pytest

import lemma_config
from declarative_spec import stateful
from declarative_spec.admit import admit_stateful
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.bench import rows_from_stdout_general
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.regions import extract_agent_build, extract_agent_edit, extract_agent_helpers, extract_agent_state
from research_loop.assumption_packages import assumption_package

ROOT = Path(__file__).resolve().parents[1]
PROOFS = ROOT / "tests" / "fixtures" / "declarative_proofs"
TPCH = ROOT / "tests" / "fixtures" / "tpch22"
SCHEMA = json.loads((TPCH / "schema.json").read_text())
OFF_GOLDEN = json.loads((ROOT / "tests" / "fixtures" / "stateful_flag_off_golden.json").read_text())
CATALOG = assumption_package("tpch_sf1")
GUARD = ROOT / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")
SF1 = Path("/home/emil/projects/lemma-db/research_loop/generated/tpch_sf1.duckdb")

GROUP_SQL = "SELECT l_returnflag, COUNT(*) AS c, SUM(l_quantity) AS s FROM lineitem GROUP BY l_returnflag"
DATE_SQL = (
    "SELECT SUM(l_extendedprice) AS rev FROM lineitem "
    "WHERE l_shipdate >= DATE '1994-01-01' AND l_shipdate < DATE '1995-01-01'"
)
FIXTURES = {"stateful_group_table.rs": GROUP_SQL, "stateful_date_prefix.rs": DATE_SQL, "stateful_degenerate_sum.rs": DATE_SQL}


_RUN_DEFAULT_KEYS = ("string_encoding", "join_chain", "parallel_vstd")


@pytest.fixture(autouse=True)
def _run_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """The container-run defaults of lemma.toml (dict strings, join chain, parallel auto), which the root conftest pins off for older tests:
    the fixtures are written against the specs a run emits."""
    for key in _RUN_DEFAULT_KEYS:
        monkeypatch.delenv(lemma_config.env_name(key), raising=False)


@contextlib.contextmanager
def _stateful_env():
    """For module-scoped setup (outside a test's monkeypatch): the run defaults with the flag on."""
    saved = {k: os.environ.get(k) for k in [lemma_config.env_name(x) for x in (*_RUN_DEFAULT_KEYS, "stateful")]}
    for key in _RUN_DEFAULT_KEYS:
        os.environ.pop(lemma_config.env_name(key), None)
    os.environ[lemma_config.env_name("stateful")] = "1"
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture
def stateful_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(lemma_config.env_name("stateful"), "1")


@pytest.fixture
def stateful_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(lemma_config.env_name("stateful"), raising=False)


def _emit(sql: str) -> str:
    return emit_declarative_spec(sql, SCHEMA, CATALOG)


def _regions(text: str) -> dict[str, str]:
    return {
        "state": extract_agent_state(text),
        "build": extract_agent_build(text),
        "execute": extract_agent_edit(text),
        "helpers": extract_agent_helpers(text),
    }


def _assemble(spec: str, text: str, **kw) -> str:
    r = _regions(text)
    return assemble_declarative_program(spec, r["execute"], helpers=r["helpers"], state=r["state"], build=r["build"], **kw)


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


def _needs_verus() -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")


# ---- emission ------------------------------------------------------------------------------------------------------------


def test_flag_is_in_lemma_toml_and_off_by_default(stateful_off: None) -> None:
    assert lemma_config.default("stateful") is False
    assert lemma_config.schema()["stateful"][0] == "run"
    assert stateful.enabled() is False


@pytest.mark.parametrize("name", sorted(OFF_GOLDEN))
def test_flag_off_emits_byte_identical_specs(name: str, stateful_off: None, exact_division_off: None) -> None:
    """sha256 of the spec (or the refusal) that the emitter of a254d17 (main before this flag) produced, for the 22 TPC-H queries
    and the two fixture queries (tests/fixtures/stateful_flag_off_golden.json). a254d17 predates exact_division = true (q01, q14)."""
    want = OFF_GOLDEN[name]
    sql = {"stateful_group": GROUP_SQL, "stateful_date": DATE_SQL}.get(name) or (TPCH / f"{name}.sql").read_text().strip()
    if "sha256" not in want:
        with pytest.raises(DeclarativeUnsupported):
            _emit(sql)
        return
    assert hashlib.sha256(_emit(sql).encode()).hexdigest() == want["sha256"]


@pytest.mark.parametrize("sql", [GROUP_SQL, DATE_SQL])
def test_flag_on_keeps_the_query_spec_and_freezes_build_execute(sql: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(lemma_config.env_name("stateful"), raising=False)
    plain = _emit(sql)
    monkeypatch.setenv(lemma_config.env_name("stateful"), "1")
    spec = _emit(sql)
    assert "pub fn run_query(" not in spec
    # Everything above the SQL comment (tables, spec folds, host lemmas, OutRow) is the same text.
    assert spec.partition("// SQL (the query")[0] == plain.partition("// SQL (the query")[0]
    # query_post is the run_query ensures, verbatim.
    ens = re.search(r"pub fn run_query\(.*?    ensures\n((?:        [^\n]*\n)*)\{", plain, re.S).group(1)
    post = re.search(r"pub open spec fn query_post\(lineitem: &Cols_lineitem, res: Vec<OutRow>\) -> bool \{\n(.*?)\n\}", spec, re.S).group(1)
    assert [ln.strip().removeprefix("&&& ") for ln in post.splitlines()] == [ln.strip().removesuffix(",") for ln in ens.splitlines()]
    assert "pub fn build(lineitem: Cols_lineitem) -> (s: QState)" in spec
    assert "        query_pre(&lineitem),\n    ensures\n        s.inv(),\n        s.db() == (QDb { lineitem: lineitem })," in spec
    assert "pub fn execute(s: &QState) -> (res: Vec<OutRow>)\n    requires\n        s.inv(),\n    ensures\n        query_post(&s.db().lineitem, res)," in spec
    assert "query_pre(&self.snap@.lineitem) && qstate_inv(self)" in spec
    for marker in ("// AGENT_STATE_START", "// AGENT_BUILD_START", "// AGENT_EDIT_START", "// AGENT_HELPERS_START"):
        assert spec.count(marker) == 1, marker


_SYNTH = """verus! {
pub struct Cols_t {
    pub n: usize,
    pub a: Vec<i64>,
}
pub open spec fn valid_cols_t(t: &Cols_t) -> bool {
    &&& t.a@.len() == t.n as int
}
pub struct OutRow {
    pub x: i128,
}
// HOST_LEMMAS_START
// HOST_LEMMAS_END
// AGENT_HELPERS_START
// AGENT_HELPERS_END
pub fn run_query(t: &Cols_t, lo: i64, t_arc: &std::sync::Arc<Cols_t>) -> (res: Vec<OutRow>)
    requires
        **t_arc == *t,
        valid_cols_t(t),
    ensures
        res@.len() == 1,
        res@[0].x as int >= lo as int,
{
// AGENT_EDIT_START
// AGENT_EDIT_END
}
}
"""


def test_runtime_parameters_go_to_execute_and_arc_parameters_are_dropped() -> None:
    spec = stateful.to_stateful(_SYNTH)
    assert "pub fn execute(s: &QState, lo: i64) -> (res: Vec<OutRow>)" in spec
    assert "query_post(&s.db().t, lo, res)" in spec
    assert "pub open spec fn query_post(t: &Cols_t, lo: i64, res: Vec<OutRow>) -> bool {\n    &&& res@.len() == 1\n    &&& res@[0].x as int >= lo as int\n}" in spec
    assert "pub open spec fn query_pre(t: &Cols_t) -> bool {\n    &&& valid_cols_t(t)\n}" in spec
    assert "t_arc" not in spec
    c = stateful.contract(spec)
    assert c.tables == [("t", "Cols_t")] and c.params == [("lo", "i64")] and c.ret == "Vec<OutRow>"
    runtime = stateful.runtime_rs(spec)
    assert "pub fn execute_at(&self, version: u64, lo: i64) -> (res: Option<Vec<OutRow>>)" in runtime
    assert "Some(execute(st, lo))" in runtime


def test_unsupported_contracts_are_refused_loudly() -> None:
    with pytest.raises(DeclarativeUnsupported, match="self join"):
        stateful.to_stateful(_SYNTH.replace("lo: i64, t_arc: &std::sync::Arc<Cols_t>", "u: &Cols_t"))
    with pytest.raises(DeclarativeUnsupported, match="requires on the runtime parameter lo"):
        stateful.to_stateful(_SYNTH.replace("        valid_cols_t(t),\n", "        valid_cols_t(t),\n        lo > 0,\n"))
    with pytest.raises(DeclarativeUnsupported, match="no run_query contract"):
        stateful.to_stateful(_SYNTH.replace("pub fn run_query", "pub fn other_query"))


# ---- admission -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", sorted(FIXTURES))
def test_admission_accepts_the_fixture_regions(fixture: str, stateful_on: None) -> None:
    spec = _emit(FIXTURES[fixture])
    r = _regions((PROOFS / fixture).read_text())
    result = admit_stateful(spec_rs=spec, **r)
    assert result.ok, result.violations


@pytest.mark.parametrize(
    ("region", "inject", "message"),
    [
        ("build", "    assume(false);\n", "build: assume("),
        ("execute", "    admit();\n", "execute: admit("),
        ("state", "#[verifier::external_body]\npub struct Hidden { pub x: u64 }\n", "external"),
        ("state", "impl QAcc { pub open spec fn f(&self) -> bool { true } }\n", "impl block"),
        ("state", "pub fn helper() -> u64 { 0 }\n", "only `struct` and `enum`"),
        ("state", "pub struct QState { pub x: u64 }\n", "redefines a host name: QState"),
        ("state", "pub struct Cols_extra { pub n: usize }\n", "`Cols_` name"),
        ("state", "#[derive(Clone)]\npub struct D { pub x: u64 }\n", "attribute not allowed"),
        ("helpers", "#[verifier::external_body]\nproof fn cheat() ensures false { }\n", "external"),
        ("helpers", "pub open spec fn query_post(x: int) -> bool { true }\n", "redefines a host name: query_post"),
        ("build", "    let p = std::fs::read(\"x\");\n", "host access"),
    ],
)
def test_admission_rejects_trusted_constructs_in_every_region(region: str, inject: str, message: str, stateful_on: None) -> None:
    spec = _emit(DATE_SQL)
    r = _regions((PROOFS / "stateful_degenerate_sum.rs").read_text())
    r[region] = inject + r[region]
    result = admit_stateful(spec_rs=spec, **r)
    assert not result.ok
    assert any(message in v for v in result.violations), result.violations


def test_admission_requires_qacc_and_qstate_inv(stateful_on: None) -> None:
    spec = _emit(DATE_SQL)
    r = _regions((PROOFS / "stateful_degenerate_sum.rs").read_text())
    no_acc = admit_stateful(spec_rs=spec, **{**r, "state": r["state"].replace("QAcc", "Other")})
    assert any("must define `pub struct QAcc`" in v for v in no_acc.violations)
    no_inv = admit_stateful(spec_rs=spec, **{**r, "helpers": r["helpers"].replace("qstate_inv", "my_inv")})
    assert any("spec fn qstate_inv" in v for v in no_inv.violations)


def test_pipeline_admits_all_four_regions(stateful_on: None) -> None:
    from declarative_spec.pipeline import _admit_and_assemble

    spec = _emit(DATE_SQL)
    text = (PROOFS / "stateful_degenerate_sum.rs").read_text()
    assembled, body, error = _admit_and_assemble(spec, text, None, None)
    assert error == "" and "pub struct QRuntime" in assembled and "QAcc { lineitem }" in assembled
    _, _, error = _admit_and_assemble(spec, text.replace("    QState { snap", "    assume(false);\n    QState { snap"), None, None)
    assert "build: assume(" in error
    _, _, error = _admit_and_assemble(spec, text.replace("// AGENT_BUILD_END\n", ""), None, None)
    assert "AGENT_BUILD" in error


# ---- assembly and the host runtime (text) --------------------------------------------------------------------------------


def test_measure_main_builds_once_then_times_execute_only(stateful_on: None) -> None:
    spec = _emit(GROUP_SQL)
    text = (PROOFS / "stateful_group_table.rs").read_text()
    program = _assemble(spec, text, column_bins={"lineitem": "/x/cols_lineitem.bin"})
    main = program[program.index("fn main()") :]
    assert main.count("rt.refresh(0, cols_lineitem);") == 1
    assert main.index("rt.refresh(0, cols_lineitem);") < main.index("let start = std::time::Instant::now();")
    assert 'let res = rt.execute_at(0).expect("the state was built at this version");' in main
    assert "STATE_BUILD_US" in main and "QUERY_LATENCY_US" in main
    verus_part = program[: program.index("fn main()")]
    assert "pub fn execute_at(&self, version: u64) -> (res: Option<Vec<OutRow>>)" in verus_part
    assert verus_part.index("pub struct QRuntime") < verus_part.rindex("}")


def test_serve_main_reads_files_only_when_the_version_changes(stateful_on: None) -> None:
    spec = _emit(DATE_SQL)
    program = _assemble(spec, (PROOFS / "stateful_date_prefix.rs").read_text(), serve=True)
    main = program[program.index("fn main()") :]
    current = main.index("if rt.is_current(version) {")
    read = main.index("std::fs::read(&path_lineitem)")
    refresh = main.index("rt.refresh(version, cols_lineitem);")
    assert current < read < refresh < main.index("rt.execute_at(version)")
    assert main.count("std::fs::read(") == 1
    with pytest.raises(ValueError, match="stateful spec"):
        assemble_declarative_program(_SYNTH, "Vec::new()", state="pub struct QAcc {}")


# ---- prompt ---------------------------------------------------------------------------------------------------------------


def test_prompt_states_the_contract_only_for_a_stateful_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.prompt import build_declarative_prompt

    monkeypatch.setenv(lemma_config.env_name("stateful"), "1")
    on = build_declarative_prompt(sql=DATE_SQL, spec_path="s", edit_path="e", lemma_index="idx", spec_text=_emit(DATE_SQL))
    monkeypatch.setenv(lemma_config.env_name("stateful"), "0")
    off = build_declarative_prompt(sql=DATE_SQL, spec_path="s", edit_path="e", lemma_index="idx", spec_text=_emit(DATE_SQL))
    assert "## Stateful contract" in on and "## Stateful contract" not in off
    for fact in ("// AGENT_STATE_START", "// AGENT_BUILD_START", "spec fn qstate_inv(s: &QState) -> bool", "`lineitem: Cols_lineitem`",
                 "built at another version", "many times per `build`", "not saved", "STATE_BUILD_US"):
        assert fact in on, fact


# ---- end to end: Verus ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", ["stateful_degenerate_sum.rs"])
def test_degenerate_state_verifies_and_a_wrong_body_does_not(fixture: str, stateful_on: None, tmp_path: Path) -> None:
    _needs_verus()
    spec = _emit(FIXTURES[fixture])
    text = (PROOFS / fixture).read_text()
    out = _verus(_assemble(spec, text), tmp_path, "degenerate")
    assert re.search(r"verification results:: \d+ verified, 0 errors", out), out[-3000:]
    bad = _verus(_assemble(spec, text.replace("d < 9131", "d < 9132")), tmp_path, "degenerate_bad")
    assert re.search(r"verification results:: \d+ verified, [1-9]\d* errors", bad), bad[-3000:]


def test_runtime_without_the_version_check_does_not_verify(stateful_on: None, tmp_path: Path) -> None:
    """`execute_at` answering from a state built at another version is a proof error, not a convention."""
    _needs_verus()
    spec = _emit(DATE_SQL)
    program = _assemble(spec, (PROOFS / "stateful_degenerate_sum.rs").read_text())
    assert program.count("if self.version == version {") == 1
    out = _verus(program.replace("if self.version == version {", "if true {"), tmp_path, "no_version_check")
    assert re.search(r"verification results:: \d+ verified, [1-9]\d* errors", out), out[-3000:]
    stale = program.replace("self.state = Some(st);\n        self.version = version;", "self.state = Some(st);")
    assert stale != program
    out = _verus(stale, tmp_path, "no_version_record")
    assert re.search(r"verification results:: \d+ verified, [1-9]\d* errors", out), out[-3000:]


# ---- end to end: compiled serve binaries, differential against DuckDB under updates ------------------------------------------


def _compile_serve(fixture: str, tmp: Path) -> Path:
    with _stateful_env():
        spec = _emit(FIXTURES[fixture])
    name = fixture.removesuffix(".rs")
    out = _verus(_assemble(spec, (PROOFS / fixture).read_text(), serve=True), tmp, name, "--compile", "--", "-C", "opt-level=3")
    assert re.search(r"verification results:: \d+ verified, 0 errors", out), out[-3000:]
    binary = tmp / name
    assert binary.is_file(), out[-2000:]
    return binary


@pytest.fixture(scope="module")
def serve_binaries(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    _needs_verus()
    tmp = tmp_path_factory.mktemp("stateful_serve")
    return {f: _compile_serve(f, tmp) for f in ("stateful_group_table.rs", "stateful_date_prefix.rs")}


class Server:
    """One serve process: a call is `<version> <column file>`; the reply is `BUILT 0|1`, the rows, `END`."""

    def __init__(self, binary: Path) -> None:
        self.proc = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert self.proc.stdout.readline().strip() == "SERVE_TABLES: lineitem"

    def call(self, version: int, path: str) -> tuple[bool, str]:
        self.proc.stdin.write(f"{version} {path}\n")
        self.proc.stdin.flush()
        lines = []
        while (line := self.proc.stdout.readline()) != "END\n":
            assert line, self.proc.stderr.read()
            lines.append(line)
        built = lines[0].strip()
        assert built in ("BUILT 0", "BUILT 1"), lines
        return built == "BUILT 1", "".join(lines)

    def close(self) -> None:
        self.proc.stdin.close()
        assert self.proc.wait(timeout=60) == 0, self.proc.stderr.read()


def _expect(sql: str, db: Path, dest: Path) -> dict:
    from research_loop.decl_query_measure import write_query_measure

    with _stateful_env():
        return write_query_measure(sql=sql, schema=SCHEMA, catalog=CATALOG, db_path=db, dest=dest)


def _check(stdout: str, prep: dict) -> None:
    from declarative_spec.bench import rows_match_error

    err = rows_match_error(
        rows_from_stdout_general(stdout), prep["rows"], prep["kinds"], prep.get("order_cols"), bool(prep.get("limited")), prep.get("tie_rows")
    )
    assert err is None, (err, stdout[-2000:], prep["rows"])


_FLAGS = ["A", "N", "R"]


def _random_rows(rng: random.Random, n: int, flags: list[str]) -> list[tuple]:
    rows = []
    for _ in range(n):
        day = rng.choice([rng.randint(8035, 10591), rng.randint(8700, 9200), rng.randint(-2000, -1), rng.randint(65536, 66000)]) if rng.random() < 0.1 else rng.randint(8035, 10591)
        rows.append((rng.choice(flags), rng.randint(0, 5000) / 100, rng.randint(0, 10_000_000) / 100, day))
    return rows


def _insert(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    con.executemany(
        "INSERT INTO lineitem VALUES (?, CAST(? AS DECIMAL(15,2)), CAST(? AS DECIMAL(15,2)), DATE '1970-01-01' + CAST(? AS INTEGER))", rows
    )


def _updates(rng: random.Random):
    """A sequence of table changes; each one is a new data version."""
    yield "insert", lambda con: _insert(con, _random_rows(rng, rng.randint(1, 40), _FLAGS))
    yield "delete some", lambda con: con.execute(f"DELETE FROM lineitem WHERE hash(rowid) % 5 = {rng.randint(0, 4)}")
    yield "update quantity", lambda con: con.execute("UPDATE lineitem SET l_quantity = l_quantity / 2 WHERE l_returnflag = 'N'")
    yield "new group", lambda con: _insert(con, [("Z", 1.25, 10.0, 9000)])
    yield "move dates", lambda con: con.execute("UPDATE lineitem SET l_shipdate = l_shipdate + 30 WHERE l_returnflag = 'R'")
    yield "empty range", lambda con: con.execute("DELETE FROM lineitem WHERE l_shipdate >= DATE '1994-01-01' AND l_shipdate < DATE '1995-01-01'")
    yield "refill range", lambda con: _insert(con, [("A", 3.0, 99.99, 8766), ("N", 4.0, 0.01, 9130), ("R", 5.0, 7.0, 9131)])
    yield "delete all", lambda con: con.execute("DELETE FROM lineitem")
    yield "insert again", lambda con: _insert(con, _random_rows(rng, 25, _FLAGS + ["F"]))


@pytest.mark.parametrize("seed", [1, 2])
def test_differential_under_updates_on_random_tables(seed: int, serve_binaries: dict[str, Path], tmp_path: Path) -> None:
    """Every change bumps the version; every answer equals DuckDB on the table at that version. A repeated call at the same
    version does not build again and gives the same answer; going back to an older version number builds again."""
    rng = random.Random(seed)
    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE lineitem (l_returnflag VARCHAR, l_quantity DECIMAL(15,2), l_extendedprice DECIMAL(15,2), l_shipdate DATE)")
    _insert(con, _random_rows(rng, 200, _FLAGS))
    con.close()
    servers = {f: Server(b) for f, b in serve_binaries.items()}
    version = 1
    builds = {f: 0 for f in servers}
    steps = [("initial", None), *_updates(rng)]
    for label, change in steps:
        if change is not None:
            con = duckdb.connect(str(db))
            change(con)
            con.close()
            version += 1
        for fixture, server in servers.items():
            prep = _expect(FIXTURES[fixture], db, tmp_path / f"v{version}_{fixture}")
            path = prep["bins"]["lineitem"]
            built, out = server.call(version, path)
            assert built, (label, fixture)
            builds[fixture] += 1
            _check(out, prep)
            again, out2 = server.call(version, path)
            assert not again and rows_from_stdout_general(out2) == rows_from_stdout_general(out), (label, fixture)
    for fixture, server in servers.items():
        # Back to the first data: a version number the state was not built at, so it builds again (one state is kept).
        prep = _expect(FIXTURES[fixture], db, tmp_path / f"back_{fixture}")
        built, out = server.call(1, prep["bins"]["lineitem"])
        assert built
        _check(out, prep)
        server.close()
    assert all(n == len(steps) for n in builds.values())


def test_same_version_is_trusted_not_rechecked(serve_binaries: dict[str, Path], tmp_path: Path) -> None:
    """The version number is the caller's word (the trusted part): new data under an unchanged version is not read."""
    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE lineitem (l_returnflag VARCHAR, l_quantity DECIMAL(15,2), l_extendedprice DECIMAL(15,2), l_shipdate DATE)")
    _insert(con, [("A", 1.0, 10.0, 9000)])
    con.close()
    first = _expect(DATE_SQL, db, tmp_path / "a")
    con = duckdb.connect(str(db))
    _insert(con, [("A", 1.0, 5.0, 9001)])
    con.close()
    second = _expect(DATE_SQL, db, tmp_path / "b")
    server = Server(serve_binaries["stateful_date_prefix.rs"])
    built, out = server.call(7, first["bins"]["lineitem"])
    assert built
    _check(out, first)
    built, out = server.call(7, second["bins"]["lineitem"])
    assert not built
    _check(out, first)  # the old answer: the files of the new data were not read
    with pytest.raises(AssertionError):
        _check(out, second)
    built, out = server.call(8, second["bins"]["lineitem"])
    assert built
    _check(out, second)
    server.close()


def test_differential_on_tpch_sf1(serve_binaries: dict[str, Path], tmp_path: Path) -> None:
    if not SF1.is_file():
        pytest.skip("research_loop/generated/tpch_sf1.duckdb not present")
    for fixture, binary in serve_binaries.items():
        prep = _expect(FIXTURES[fixture], SF1, tmp_path / fixture)
        server = Server(binary)
        built, out = server.call(1, prep["bins"]["lineitem"])
        assert built
        _check(out, prep)
        assert prep["rows"] and prep["rows"][0][-1] is not None
        build_us = int(re.search(r"STATE_BUILD_US: (\d+)", out).group(1))
        for _ in range(3):
            built, out = server.call(1, prep["bins"]["lineitem"])
            assert not built
            _check(out, prep)
        exec_us = int(re.search(r"EXEC_US: (\d+)", out).group(1))
        print(f"{fixture}: SF1 build {build_us} us, execute {exec_us} us, DuckDB {prep['duck_us']} us")
        server.close()


def test_measure_path_proves_builds_once_and_checks_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The in-session measure (`run_runquery`): admission of the four regions, Verus, compile, one build, timed executes, row check."""
    _needs_verus()
    from declarative_spec.pipeline import run_declarative_metrics

    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE lineitem (l_returnflag VARCHAR, l_quantity DECIMAL(15,2), l_extendedprice DECIMAL(15,2), l_shipdate DATE)")
    _insert(con, _random_rows(random.Random(5), 300, _FLAGS))
    con.close()
    prep = _expect(GROUP_SQL, db, tmp_path / "prep")
    monkeypatch.setenv(lemma_config.env_name("stateful"), "1")
    spec = _emit(GROUP_SQL)
    text = (PROOFS / "stateful_group_table.rs").read_text()
    metrics = run_declarative_metrics(spec_rs=spec, agent_source=text, work_dir=tmp_path / "run", column_bins=prep["bins"], speed_bar=prep)
    assert metrics.get("proof_verified"), metrics.get("compiler_error")
    assert "rows differ" not in str(metrics.get("compiler_error", "")) and "result row" not in str(metrics.get("compiler_error", ""))
    assert metrics["stdout"].count("STATE_BUILD_US:") == 1 and "QUERY_LATENCY_US:" in metrics["stdout"]
    wrong = text.replace("sums.set(code, sb + v as i128);", "sums.set(code, sb + v as i128 + 0);").replace(
        "res.push(OutRow { l_returnflag: s.acc.dict[c].clone(), c: cnt, s: sv });", "res.push(OutRow { l_returnflag: s.acc.dict[c].clone(), c: cnt, s: sv + 1 });"
    )
    bad = run_declarative_metrics(spec_rs=spec, agent_source=wrong, work_dir=tmp_path / "bad", column_bins=prep["bins"], speed_bar=prep)
    assert not bad.get("proof_verified")


# ---------------------------------------------------------------- assumptions = false (the default): execute may decline


def _off_spec(monkeypatch: pytest.MonkeyPatch, sql: str = DATE_SQL) -> str:
    monkeypatch.delenv("LEMMA_ASSUMPTIONS", raising=False)  # lemma.toml's default: no data assumptions, no catalog caps
    return emit_declarative_spec(sql, SCHEMA, None)


def test_assumptions_off_execute_returns_option_and_query_post_stays_on_the_value(stateful_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec import decline

    spec = _off_spec(monkeypatch)
    assert decline.is_decline_spec(spec) and "pub fn run_query(" not in spec and "run_query_ok" not in spec
    assert "pub fn execute(s: &QState) -> (res: Option<Vec<OutRow>>)" in spec
    assert "res matches Some(res) ==> query_post(&s.db().lineitem, res)," in spec
    assert "pub open spec fn query_post(lineitem: &Cols_lineitem, res: Vec<OutRow>) -> bool" in spec
    assert "pub fn build(lineitem: Cols_lineitem) -> (s: QState)" in spec  # build cannot decline
    c = stateful.contract(spec)
    assert c.declines and c.ret == "Option<Vec<OutRow>>" and c.value == "Vec<OutRow>"
    unwrapped = decline.unwrap_option(spec)
    assert stateful.wrap_decline(unwrapped) == spec and not decline.is_decline_spec(unwrapped)
    assert stateful.contract(unwrapped).ret == "Vec<OutRow>" and not stateful.contract(unwrapped).declines
    runtime = stateful.runtime_rs(spec)
    assert "-> (res: Option<Option<Vec<OutRow>>>)" in runtime and "(Some(Some(r)), Some(st)) => query_post(&st.db().lineitem, r)," in runtime
    with pytest.raises(ValueError, match="already declines"):
        stateful.wrap_decline(spec)


def test_assumptions_off_mains_report_a_decline(stateful_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _off_spec(monkeypatch)
    body = "    None\n"
    regions = _regions((PROOFS / "stateful_degenerate_sum.rs").read_text())
    measure = assemble_declarative_program(spec, body, helpers=regions["helpers"], state=regions["state"], build=regions["build"])
    assert "const LEMMA_DECLINE_EXIT_CODE: i32 = 3;" in measure
    assert 'match rt.execute_at(0).expect("the state was built at this version") { Some(v) => v, None => { println!("LEMMA_DECLINED"); std::process::exit(LEMMA_DECLINE_EXIT_CODE); } }' in measure
    serve = assemble_declarative_program(spec, body, helpers=regions["helpers"], state=regions["state"], build=regions["build"], serve=True)
    tail = serve[serve.index("fn main()") :]
    assert "match answered {" in tail and 'println!("LEMMA_DECLINED");' in tail and "std::process::exit" not in tail  # the server keeps serving


def test_assumptions_off_prompt_explains_the_execute_decline(stateful_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.prompt import _features, build_declarative_prompt

    spec = _off_spec(monkeypatch)
    text = build_declarative_prompt(sql=DATE_SQL, spec_path="s.rs", edit_path="e.rs", lemma_index="", spec_text=spec)
    assert "`execute` returns `Option<..>`: `Some(res)` must satisfy `query_post(.., res)`" in text and "`build` cannot decline" in text
    assert "## Stateful contract" in text and _features(spec)["ty"] == "Vec<OutRow>"
