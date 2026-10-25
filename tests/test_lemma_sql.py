"""Lemma from SQL: ``lemma('<sql>')`` (and its older name ``lemma_query``), generation of a missing executor, template matching,
``lemma_list`` / ``lemma_remove`` / ``lemma_jobs``, and constant lifting (declarative_spec/lift.py).

Unit tests (lifting, the template index key) run everywhere. The extension tests need the build (db_extension/duckdb_ext/build.sh) and
Verus: they install two proved fixtures (assumptions = false) into a store once, then copy that store into each test's LEMMA_HOME:

    SQL       SELECT SUM(cost) AS total FROM pre WHERE line > 5                           decline/usum_checked.rs
    TEMPLATE  -- params: lo BIGINT / SELECT SUM(cost) AS total FROM pre WHERE line > $lo   decline/template_usum_checked.rs

Generation runs a FAKE generator (tests/fixtures/lemma_fake_generator.py: the `lemma generate` command line, but it installs a fixture
from the store instead of running the pipeline). The real generator with the mock model is the slow smoke at the end.
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from declarative_spec import templates
from declarative_spec.lift import lift_constants
from research_loop import in_duckdb
from research_loop.structural_catalog import structural_catalog_from_db
from tests.test_in_duckdb import EXTENSION, PROOFS, ROOT, VERUS

FIX = PROOFS / "decline"
SCHEMA = {"pre": {"line": "bigint", "cost": "decimal(38,2)"}}
SQL = "SELECT SUM(cost) AS total FROM pre WHERE line > 5"
TEMPLATE = "-- params: lo BIGINT\nSELECT SUM(cost) AS total FROM pre WHERE line > $lo"
FAKE = ROOT / "tests" / "fixtures" / "lemma_fake_generator.py"
GUARD = ROOT / "scripts" / "ram" / "verus_guarded.sh"
needs_ext = pytest.mark.skipif(
    not EXTENSION.is_file() or not VERUS.is_file(), reason="build the extension first (db_extension/duckdb_ext/build.sh) and install Verus"
)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_ASSUMPTIONS", raising=False)
    monkeypatch.setenv("LEMMA_IN_DUCKDB", "true")
    monkeypatch.setenv("LEMMA_TEMPLATES", "1")


# ---------------------------------------------------------------- constant lifting (no extension)

LIFT_SCHEMA = {
    "pre": {"line": "bigint", "cost": "decimal(38,2)", "report": "bigint", "d": "date", "s": "varchar", "f": "double"},
    "sub": {"adsh": "varchar", "fy": "integer"},
}


@pytest.mark.parametrize(
    ("sql", "lifted"),
    [
        (SQL, {"p1": "5"}),
        ("SELECT COUNT(*) AS c FROM pre WHERE d >= DATE '1995-01-01' AND d < date '1996-01-01'", {"p1": "DATE '1995-01-01'", "p2": "date '1996-01-01'"}),
        ("SELECT COUNT(*) AS c FROM pre WHERE s IN ('a','b''c') AND cost BETWEEN 1.5 AND 10", {"p1": "'a'", "p2": "'b''c'", "p3": "1.5", "p4": "10"}),
        ("SELECT report, COUNT(*) AS c FROM pre WHERE (line) = (7) GROUP BY report HAVING report > 2 ORDER BY 1 LIMIT 3", {"p1": "7", "p2": "2"}),
        ("SELECT COUNT(*) AS c FROM pre WHERE report IN (SELECT fy FROM sub WHERE fy = 2020)", {"p1": "2020"}),
    ],
)
def test_lifting_lifts_where_and_having_comparisons_of_a_column_with_a_literal(sql: str, lifted: dict) -> None:
    got = lift_constants(sql, LIFT_SCHEMA, None)
    assert got is not None and got.literals == lifted
    template = templates.parse_template(got.template)
    assert [p.name for p in template.params] == list(lifted)
    # the template's text with the query's own literals in place of $name IS the query (normalized)
    assert _substitute(in_duckdb.normalize_sql(template.body, keep_dollar=True), got.literals) == in_duckdb.normalize_sql(sql)
    assert in_duckdb.template_index_key(got.template) == in_duckdb.template_index_key(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(cost) AS total FROM pre WHERE line > -5",  # a negated number
        "SELECT SUM(cost) AS total FROM pre WHERE line > 5.5",  # a fraction against an integer column
        "SELECT SUM(cost) AS total FROM pre WHERE cost > 1.234",  # more fractional digits than DECIMAL(38,2)
        "SELECT SUM(cost) AS total FROM pre WHERE f > 2",  # a DOUBLE column
        "SELECT SUM(cost) AS total FROM pre WHERE d >= '1995-01-01'",  # a date without DATE
        "SELECT SUM(cost) AS total FROM pre WHERE s > 'a'",  # a string under <
        "SELECT SUM(cost) AS total FROM pre WHERE line + 1 > 5",  # not a plain column
        "SELECT SUM(cost) AS total FROM pre WHERE line > 99999999999999999999",  # beyond BIGINT
        "SELECT CASE WHEN line > 5 THEN 1 ELSE 0 END AS x FROM pre",  # a SELECT-list constant
        "SELECT report, SUM(cost) AS s FROM pre GROUP BY report HAVING SUM(cost) > 5 ORDER BY 2 LIMIT 5",  # an aggregate, ORDER BY, LIMIT
        "SELECT COUNT(*) AS c FROM pre JOIN sub ON pre.s = sub.adsh AND sub.fy > 2000",  # JOIN ... ON
        "SELECT COUNT(*) AS c FROM pre WHERE CAST('5' AS BIGINT) = line",  # a CAST
        "SELECT COUNT(*) AS c FROM pre WHERE line > $x",  # already a placeholder
    ],
)
def test_lifting_leaves_everything_else_as_written(sql: str) -> None:
    assert lift_constants(sql, LIFT_SCHEMA, None) is None


def test_lifting_keeps_the_literals_it_cannot_lift_in_the_template_text() -> None:
    got = lift_constants("SELECT SUM(cost) AS total FROM pre WHERE line > 5 AND f < 2.5 LIMIT 10", LIFT_SCHEMA, None)
    assert got is not None and got.template == "-- params: p1 BIGINT\nSELECT SUM(cost) AS total FROM pre WHERE line > $p1 AND f < 2.5 LIMIT 10"


def test_a_lifted_template_emits_a_parameterized_spec() -> None:
    from declarative_spec.emit import emit_declarative_spec

    got = lift_constants(SQL, SCHEMA, None)
    assert got is not None
    spec = emit_declarative_spec(got.template, SCHEMA, None)
    assert "param_p1" in spec and "// PARAM p1 i64" in spec


def _substitute(body: str, literals: dict[str, str]) -> str:
    return re.sub(r"\$([A-Za-z_]\w*)", lambda m: literals[m.group(1)], body)


# ---------------------------------------------------------------- the extension

def _fill(con: duckdb.DuckDBPyConnection, n: int = 60, seed: int = 0) -> None:
    rng = random.Random(seed)
    con.execute("CREATE OR REPLACE TABLE pre (line BIGINT, cost DECIMAL(38,2))")
    con.executemany("INSERT INTO pre VALUES (?, ?)", [(rng.randint(-3, 12), Decimal(rng.randint(-500, 5000)).scaleb(-2)) for _ in range(n)])


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not EXTENSION.is_file() or not VERUS.is_file():
        pytest.skip("build the extension first (db_extension/duckdb_ext/build.sh) and install Verus")
    root = tmp_path_factory.mktemp("lemma_sql_store")
    db = root / "schema.duckdb"
    con = duckdb.connect(str(db))
    _fill(con, 5)
    con.close()
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("LEMMA_ASSUMPTIONS", raising=False)
        mp.setenv("LEMMA_IN_DUCKDB", "true")
        mp.setenv("LEMMA_TEMPLATES", "1")
        mp.setenv("LEMMA_VERUS_BIN", str(GUARD))
        mp.setenv("LEMMA_PARALLEL_VSTD", "off")
        mp.setenv("LEMMA_STRING_ENCODING", "plain")
        mp.setenv("LEMMA_JOIN_CHAIN", "0")
        for sql, body in ((SQL, "usum_checked.rs"), (TEMPLATE, "template_usum_checked.rs")):
            in_duckdb.install_executor(sql=sql, schema=SCHEMA, catalog=structural_catalog_from_db(db), agent_source=(FIX / body).read_text(), db_path=db, home=root)
    return root


def _home(store: Path, tmp_path: Path, *which: str) -> Path:
    """A LEMMA_HOME with the store's executors for ``which`` (SQL texts) and their template index entries."""
    home = tmp_path / "home"
    (home / "executors").mkdir(parents=True)
    for sql in which:
        key = in_duckdb.executor_key(sql)
        shutil.copytree(store / "executors" / key, home / "executors" / key)
        if sql == TEMPLATE:
            in_duckdb.index_template(home, key, sql)
    return home


def _connect(home: Path, database: str = ":memory:") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database, config={"allow_unsigned_extensions": "true"})
    con.execute(f"LOAD '{EXTENSION}'")
    con.execute(f"SET lemma_home = '{home}'")
    return con


def _fake(con: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch, store: Path, sql: str, mode: str = "install", **extra: str) -> None:
    con.execute(f"SET lemma_generator = '{sys.executable} {FAKE}'")
    monkeypatch.setenv("FAKE_GEN_STORE", str(store))
    monkeypatch.setenv("FAKE_GEN_KEY", in_duckdb.executor_key(sql))
    monkeypatch.setenv("FAKE_GEN_MODE", mode)
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def _lemma(sql: str, *args: str) -> str:
    return "SELECT * FROM lemma(" + ", ".join(["'" + sql.replace("'", "''") + "'", *args]) + ")"


def _last(con: duckdb.DuckDBPyConnection) -> tuple[str, str]:
    return con.execute("SELECT engine, reason FROM lemma_last_query()").fetchone()


@needs_ext
def test_lemma_answers_with_an_installed_executor_and_lemma_query_is_the_same_function(store: Path, tmp_path: Path) -> None:
    con = _connect(_home(store, tmp_path, SQL))
    _fill(con)
    want = con.execute(SQL).fetchall()
    assert con.execute(_lemma(SQL)).fetchall() == want
    engine, reason = _last(con)
    assert engine == "lemma" and reason.endswith("via lemma()")
    assert con.execute(_lemma(SQL).replace("lemma(", "lemma_query(")).fetchall() == want
    assert _last(con)[1].endswith("via lemma_query()")


@needs_ext
def test_a_template_match_binds_the_querys_constants_and_answers_like_duckdb(store: Path, tmp_path: Path) -> None:
    con = _connect(_home(store, tmp_path, TEMPLATE))
    con.execute("SET lemma_generate = 'off'")  # a match must not need the generator
    _fill(con, seed=3)
    for text in ("SELECT SUM(cost) AS total FROM pre WHERE line > 7", "SELECT  SUM(cost) AS total\nFROM pre WHERE line >   -0", " SELECT SUM(cost) AS total FROM pre WHERE line > 0;",
                 "SELECT SUM(cost) AS total FROM pre WHERE line > 11", "SELECT SUM(cost) AS total FROM pre WHERE line > 100"):
        if "-0" in text:
            with pytest.raises(duckdb.Error, match="no proved executor"):  # `-0` is not a literal token: no match
                con.execute(_lemma(text)).fetchall()
            continue
        want = con.execute(text).fetchall()
        assert con.execute(_lemma(text)).fetchall() == want, text
        engine, reason = _last(con)
        value = re.search(r"> +(\d+)", text).group(1)
        assert engine == "lemma" and f"template {in_duckdb.executor_key(TEMPLATE)[:12]} ($lo = {value})" in reason
    # lemma_mode matches templates too: the plan is replaced by the template executor with the literal bound
    con.execute("SET lemma_mode = true")
    text = "SELECT SUM(cost) AS total FROM pre WHERE line > 4"
    got = con.execute(text).fetchall()
    con.execute("SET lemma_mode = false")
    assert got == con.execute(text).fetchall()
    con.execute("SET lemma_mode = true")
    con.execute(text).fetchall()
    assert "via lemma_mode, template" in _last(con)[1] and "$lo = 4" in _last(con)[1]


@needs_ext
@pytest.mark.parametrize(
    "text",
    [
        "SELECT SUM(cost) AS total FROM pre WHERE line > 7.5",  # a DECIMAL literal for a BIGINT parameter
        "SELECT SUM(cost) AS total FROM pre WHERE line > '7'",  # a string
        "SELECT SUM(cost) AS total FROM pre WHERE line > 99999999999999999999",  # beyond the parameter's i64
        "SELECT SUM(cost) AS total FROM pre WHERE line >= 7",  # another operator
        "SELECT SUM(cost) AS total FROM pre WHERE line > 7 OR 1 = 1",  # more text
        "SELECT SUM(cost) AS total FROM pre WHERE line > 7e1",  # not one literal token
        "SELECT SUM(cost) AS total FROM pre WHERE line > (7)",  # parentheses are text the template does not have
        "SELECT sum(cost) AS total FROM pre WHERE line > 7",  # case is kept
    ],
)
def test_a_query_that_is_not_the_template_with_fitting_literals_does_not_match(text: str, store: Path, tmp_path: Path) -> None:
    con = _connect(_home(store, tmp_path, TEMPLATE))
    con.execute("SET lemma_generate = 'off'")
    _fill(con)
    with pytest.raises(duckdb.Error, match="no proved executor for this query"):
        con.execute(_lemma(text)).fetchall()
    assert _last(con)[0] == "none"


@needs_ext
def test_the_matcher_is_sound_a_match_is_the_template_text_with_the_bound_literals(store: Path, tmp_path: Path) -> None:
    """For many near-miss texts: whenever lemma_match_template binds, substituting the bound literals into the normalized template body
    gives exactly the normalized query; and every query built that way from a template and literal tokens matches."""
    con = _connect(_home(store, tmp_path))
    templates_ = [
        TEMPLATE,
        "-- params: a DATE, b VARCHAR, c DECIMAL(15,2)\nSELECT COUNT(*) AS n FROM t WHERE d >= $a AND s IN ($b,'x') AND v < $c",
        "-- params: a BIGINT\nSELECT x FROM t WHERE x = $a AND y = $a AND z = '$a' /* $a */",
    ]
    rng = random.Random(7)
    pieces = ["7", "07", "7.25", "-7", "'a'", "'it''s'", "DATE '1995-01-01'", "date'1995-01-01'", "x", "(7)", "7 ", " 7", "7e1", "'$a'", "1.", "'"]
    checked = matched = 0
    for tmpl in templates_:
        body = in_duckdb.normalize_sql(in_duckdb.template_body(tmpl), keep_dollar=True)
        names = list(dict.fromkeys(re.findall(r"\$([A-Za-z_]\w*)", body)))
        for _ in range(300):
            literals = {n: rng.choice(pieces) for n in names}
            query = re.sub(r"(?<!')\$([A-Za-z_]\w*)", lambda m, lit=literals: lit[m.group(1)], body)  # '$a' inside quotes stays
            if rng.random() < 0.3:
                i = rng.randrange(len(query))
                query = query[:i] + rng.choice([" ", "1", "'", "-- ", "a"]) + query[i:]
            got = con.execute("SELECT lemma_match_template(?, ?)", [tmpl, query]).fetchone()[0]
            checked += 1
            if got is None:
                continue
            matched += 1
            bound = dict(item.split("=", 1) for item in got)
            assert in_duckdb.normalize_sql(_substitute_outside_quotes(body, bound)) == in_duckdb.normalize_sql(query), (tmpl, query, got)
    assert matched > 50 and checked == 900
    # and the index key of a match is the template's
    assert con.execute("SELECT lemma_template_skeleton(?) = lemma_template_skeleton(?)", [TEMPLATE, SQL]).fetchone()[0]


def _substitute_outside_quotes(body: str, literals: dict[str, str]) -> str:
    out, i = [], 0
    while i < len(body):
        j = in_duckdb._opaque_end(body, i)
        if j > i:
            out.append(body[i:j])
            i = j
            continue
        m = re.compile(r"\$([A-Za-z_]\w*)").match(body, i)
        if m:
            out.append(literals[m.group(1)])
            i = m.end()
            continue
        out.append(body[i])
        i += 1
    return "".join(out)


@needs_ext
def test_the_cxx_and_python_template_index_keys_agree(store: Path, tmp_path: Path) -> None:
    con = _connect(_home(store, tmp_path))
    texts = [SQL, TEMPLATE, "SELECT a FROM t WHERE x > 5 AND d >= DATE '1995-01-01' AND s = 'it''s' AND y IN (1, 2.5) AND t1.c = 3",
             "select \"x 1\" from t -- 5 'a'\n where y = 1.5 /* 2 */ and z = date'2001-02-03' and w = $p and v = E'x' and u = 5e3",
             "SELECT 1", "SELECT x.1 FROM t WHERE a=-5 AND b=$1", "-- params: a BIGINT\n SELECT x FROM t WHERE x IN ($a,$a)"]
    for text in texts:
        cxx = con.execute("SELECT lemma_template_skeleton(?)", [text]).fetchone()[0]
        assert cxx == in_duckdb.template_skeleton(in_duckdb.normalize_sql(in_duckdb.template_body(text), keep_dollar=True)), text


@needs_ext
def test_lemma_generate_off_is_an_error_and_lemma_query_never_generates(store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _home(store, tmp_path)
    con = _connect(home)
    _fill(con)
    con.execute("SET lemma_generate = 'off'")
    with pytest.raises(duckdb.Error, match="no proved executor for this query"):
        con.execute(_lemma(SQL)).fetchall()
    with pytest.raises(duckdb.Error, match="regenerate := true, but lemma_generate is 'off'"):
        con.execute(_lemma(SQL, "regenerate := true")).fetchall()
    con.execute("SET lemma_generate = 'block'")
    _fake(con, monkeypatch, store, SQL)
    with pytest.raises(duckdb.Error, match="no proved executor for this query"):
        con.execute(_lemma(SQL).replace("lemma(", "lemma_query(")).fetchall()
    assert not (home / "jobs").exists()
    with pytest.raises(duckdb.Error, match="'block', 'background' or 'off'"):
        con.execute("SET lemma_generate = 'later'")
        con.execute(_lemma(SQL)).fetchall()


@needs_ext
def test_generation_blocks_installs_a_template_and_later_constants_match_it(store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _home(store, tmp_path)
    con = _connect(home)
    _fill(con, seed=5)
    _fake(con, monkeypatch, store, TEMPLATE, FAKE_GEN_RECORD=str(tmp_path / "record.json"))
    text = "SELECT SUM(cost) AS total FROM pre WHERE line > 4"
    want = con.execute(text).fetchall()
    assert con.execute(_lemma(text)).fetchall() == want
    engine, reason = _last(con)
    assert engine == "lemma" and "$lo = 4" in reason and "generated now (job " in reason
    record = json.loads((tmp_path / "record.json").read_text())
    assert record["sql"].strip() == text and "--lift-constants" in record["argv"] and "--regenerate" not in record["argv"]
    (job,) = con.execute("SELECT status, exit_code, installed_key, query_key, log, snapshot_bytes FROM lemma_jobs()").fetchall()
    assert job[:4] == ("done", 0, in_duckdb.executor_key(TEMPLATE), in_duckdb.executor_key(text)) and job[5] > 0
    assert "INSTALLED" in Path(job[4]).read_text()
    assert not list((home / "jobs").glob("*/snapshot.duckdb"))  # the snapshot is gone with the job
    # another constant: the template answers, no new job
    other = "SELECT SUM(cost) AS total FROM pre WHERE line > 9"
    want = con.execute(other).fetchall()
    assert con.execute(_lemma(other)).fetchall() == want
    assert "generated" not in _last(con)[1] and con.execute("SELECT COUNT(*) FROM lemma_jobs()").fetchone()[0] == 1


@needs_ext
def test_the_snapshot_is_the_callers_transaction(store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "user.duckdb"
    con = _connect(_home(store, tmp_path), str(db))
    con.execute("CREATE TABLE pre (line BIGINT, cost DECIMAL(38,2))")
    con.execute("INSERT INTO pre VALUES (6, 1.00), (2, 2.00)")
    other = con.cursor()  # another connection: its uncommitted row is not ours
    other.execute("BEGIN")
    other.execute("INSERT INTO pre VALUES (100, 100.00)")
    con.execute("BEGIN")
    con.execute("INSERT INTO pre VALUES (9, 0.50)")
    con.execute("DELETE FROM pre WHERE line = 2")
    _fake(con, monkeypatch, store, SQL, FAKE_GEN_RECORD=str(tmp_path / "record.json"))
    con.execute("SET lemma_lift_constants = false")
    got = con.execute(_lemma(SQL)).fetchall()
    assert got == con.execute(SQL).fetchall() == [(Decimal("1.50"),)]
    record = json.loads((tmp_path / "record.json").read_text())
    assert sorted(record["tables"]["pre"]) == [[6, "1.00"], [9, "0.50"]] and record["types"]["pre"] == [["line", "BIGINT"], ["cost", "DECIMAL(38,2)"]]
    assert "--no-lift-constants" in record["argv"] and record["argv"][record["argv"].index("--source-db") + 1] == str(db)
    con.execute("ROLLBACK")
    other.execute("ROLLBACK")


@needs_ext
def test_regenerate_replaces_the_executor_only_when_the_new_one_installs(store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _home(store, tmp_path, SQL)
    con = _connect(home)
    _fill(con)
    want = con.execute(SQL).fetchall()
    dest = home / "executors" / in_duckdb.executor_key(SQL)
    _fake(con, monkeypatch, store, SQL, mode="fail")
    with pytest.raises(duckdb.Error, match=r"generating an executor failed .*the installed executor is unchanged"):
        con.execute(_lemma(SQL, "regenerate := true")).fetchall()
    assert not (dest / "generated_by").exists() and con.execute(_lemma(SQL)).fetchall() == want  # the old one still answers
    assert con.execute("SELECT status FROM lemma_jobs()").fetchall() == [("failed",)]
    _fake(con, monkeypatch, store, SQL)
    assert con.execute(_lemma(SQL, "regenerate := true")).fetchall() == want
    assert (dest / "generated_by").exists() and "generated now" in _last(con)[1]
    assert sorted(r[0] for r in con.execute("SELECT status FROM lemma_jobs()").fetchall()) == ["done", "failed"]


@needs_ext
def test_a_failed_generation_is_an_error_with_its_log(store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    con = _connect(_home(store, tmp_path))
    _fill(con)
    _fake(con, monkeypatch, store, SQL, mode="fail")
    with pytest.raises(duckdb.Error, match=r"generating an executor failed \(job .*failed, exit 3\): fake generator: the agent did not prove it.*log: "):
        con.execute(_lemma(SQL)).fetchall()
    (status, error, log) = con.execute("SELECT status, error, log FROM lemma_jobs()").fetchone()
    assert status == "failed" and "did not prove" in error and Path(log).is_file()
    # a generator that exits 0 without installing anything is an error too
    con.execute(f"SET lemma_generator = '{sys.executable} -c pass'")
    with pytest.raises(duckdb.Error, match="the generator finished .* but no installed executor answers this query"):
        con.execute(_lemma(SQL)).fetchall()


@needs_ext
def test_background_generation_errors_or_routes_labelled_until_the_executor_is_there(store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    con = _connect(_home(store, tmp_path))
    _fill(con)
    want = con.execute(SQL).fetchall()
    con.execute("SET lemma_generate = 'background'")
    _fake(con, monkeypatch, store, SQL, mode="sleep", FAKE_GEN_SLEEP="4")
    with pytest.raises(duckdb.Error, match=r"generating one in the background \(job .*lemma_jobs\(\)"):
        con.execute(_lemma(SQL)).fetchall()
    assert con.execute("SELECT status FROM lemma_jobs()").fetchall() == [("running",)]
    con.execute("SET lemma_route_unproved = true")
    assert con.execute(_lemma(SQL)).fetchall() == want  # DuckDB's answer, labelled; the same job keeps running (no second one)
    engine, reason = _last(con)
    assert engine == "duckdb" and "lemma_route_unproved" in reason and "not by a proved executor" in reason
    assert con.execute("SELECT COUNT(*) FROM lemma_jobs()").fetchone()[0] == 1
    deadline = time.time() + 60
    while con.execute("SELECT status FROM lemma_jobs()").fetchone()[0] == "running" and time.time() < deadline:
        time.sleep(0.2)
    assert con.execute("SELECT status FROM lemma_jobs()").fetchone()[0] == "done"
    assert con.execute(_lemma(SQL)).fetchall() == want and _last(con)[0] == "lemma"


@needs_ext
def test_ctrl_c_cancels_a_blocking_generation(store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _home(store, tmp_path)
    con = _connect(home)
    _fill(con)
    _fake(con, monkeypatch, store, SQL, mode="sleep", FAKE_GEN_SLEEP="120")
    errors: list[BaseException] = []

    def run() -> None:
        try:
            con.execute(_lemma(SQL)).fetchall()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t = threading.Thread(target=run)
    t.start()
    deadline = time.time() + 30
    while not list(home.glob("jobs/*/pgid")) and time.time() < deadline:
        time.sleep(0.1)
    time.sleep(0.5)
    con.interrupt()
    t.join(30)
    assert not t.is_alive() and errors and "INTERRUPT" in str(errors[0]).upper()
    (job,) = list(home.glob("jobs/*"))
    assert (job / "cancelled").is_file() and not (job / "snapshot.duckdb").exists()
    pgid = int((job / "pgid").read_text())
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    with pytest.raises(ProcessLookupError):
        os.killpg(pgid, 0)
    assert not (home / "executors" / in_duckdb.executor_key(SQL)).exists()
    assert _connect(home).execute("SELECT status FROM lemma_jobs()").fetchall() == [("cancelled",)]


@needs_ext
def test_list_and_remove_in_sql_and_the_cli_share_the_store(store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _home(store, tmp_path, SQL, TEMPLATE)
    con = _connect(home)
    _fill(con)
    con.execute(_lemma(SQL)).fetchall()
    con.execute(_lemma("SELECT SUM(cost) AS total FROM pre WHERE line > 2")).fetchall()
    con.execute(_lemma("SELECT SUM(cost) AS total FROM pre WHERE line > 2")).fetchall()
    rows = {r[0]: r for r in con.execute("SELECT key, kind, sql, params, proof, size_bytes, last_used, runs, cache_hits FROM lemma_list()").fetchall()}
    k_sql, k_tpl = in_duckdb.executor_key(SQL), in_duckdb.executor_key(TEMPLATE)
    assert set(rows) == {k_sql, k_tpl}
    assert rows[k_sql][1:4] == ("query", SQL, None) and rows[k_tpl][1:4] == ("template", TEMPLATE, "lo BIGINT")
    assert re.fullmatch(r"\d+ verified, 0 errors", rows[k_sql][4]) and rows[k_sql][5] > 0 and rows[k_sql][6] is not None
    assert rows[k_sql][7:] == (1, 0) and rows[k_tpl][7] == 2  # runs, input-cache hits (this process)
    with pytest.raises(duckdb.Error, match="at least 6 hex"):
        con.execute("SELECT * FROM lemma_remove('abc')").fetchall()
    with pytest.raises(duckdb.Error, match="no installed executor"):
        con.execute("SELECT * FROM lemma_remove('ffffff0')").fetchall()
    assert con.execute(f"SELECT key FROM lemma_remove('{k_tpl[:8]}')").fetchall() == [(k_tpl,)]
    assert not (home / "executors" / k_tpl).exists() and not (home / "templates" / in_duckdb.template_index_key(TEMPLATE)).exists()
    con.execute("SET lemma_generate = 'off'")
    with pytest.raises(duckdb.Error, match="no proved executor"):
        con.execute(_lemma("SELECT SUM(cost) AS total FROM pre WHERE line > 2")).fetchall()
    # the CLI sees the same store and removes the same way
    env = {**os.environ, "LEMMA_HOME": str(home)}
    listed = subprocess.run([sys.executable, "-m", "lemma_cli.main", "list"], cwd=ROOT, env=env, capture_output=True, text=True, check=True).stdout
    assert k_sql[:12] in listed and k_tpl[:12] not in listed and "last used 20" in listed
    in_duckdb.index_template(home, k_tpl, TEMPLATE)
    shutil.copytree(store / "executors" / k_tpl, home / "executors" / k_tpl)
    done = subprocess.run([sys.executable, "-m", "lemma_cli.main", "remove", k_tpl[:10]], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert not (home / "templates" / in_duckdb.template_index_key(TEMPLATE)).exists()
    assert [r[0] for r in con.execute("SELECT key FROM lemma_list()").fetchall()] == [k_sql]


@needs_ext
def test_an_executor_is_refused_when_the_table_types_changed(store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    con = _connect(_home(store, tmp_path, SQL, TEMPLATE))
    con.execute("CREATE TABLE pre (line INTEGER, cost DECIMAL(38,2))")
    con.execute("INSERT INTO pre VALUES (6, 1.00)")
    _fake(con, monkeypatch, store, SQL, mode="fail")  # never reached: a present executor that does not fit is an error, not a miss
    for text in (SQL, "SELECT SUM(cost) AS total FROM pre WHERE line > 3"):
        with pytest.raises(duckdb.Error, match="pre.line is INTEGER now, the executor was proved for BIGINT"):
            con.execute(_lemma(text)).fetchall()
    assert not (tmp_path / "home" / "jobs").exists()


@needs_ext
def test_generation_is_refused_without_external_access(store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    con = _connect(_home(store, tmp_path))
    _fill(con)
    _fake(con, monkeypatch, store, SQL)
    con.execute("SET enable_external_access = false")
    with pytest.raises(duckdb.Error, match="enable_external_access is false"):
        con.execute(_lemma(SQL)).fetchall()


# ---------------------------------------------------------------- the real generator, the mock model (slow: minutes, Docker, Verus)


@pytest.mark.slow
@needs_ext
def test_real_generator_lifts_proves_installs_and_answers_with_the_mock_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``lemma('<sql>')`` with the default generator command (``python -m lemma_cli.main generate``, i.e. `lemma generate`): the extension
    writes the snapshot, the CLI lifts ``line > 5`` into ``$p1 BIGINT``, the real pipeline runs (Docker sandbox, Claude Code, MCP host,
    spec, admission, Verus, the timed run on the query's own value), the install re-verifies and compiles the library, and the template
    answers this query and the next one with another constant. MOCKED: the model (research_loop/scripts/mock_anthropic_api.py, as in
    tests/test_product_smoke.py) writes decline/template_usum_checked.rs with its parameter named as the lifted one (`param_lo` ->
    `param_p1`: the same proof). Needs `lemma setup` to pass on this machine (it runs here, in a fresh HOME) and a clean git tree."""
    from lemma_cli import sandbox, setup_cmd
    from lemma_cli.common import SECRET_ENV
    from research_loop.agent_sandbox import MOCK_CA_ENV, MOCK_PORT_ENV
    from research_loop.scripts.mock_anthropic_api import Conversation, MockAnthropic, make_ca

    if not (shutil.which("docker") and sandbox.image_exists() and setup_cmd.verus_path().is_file()):
        pytest.skip("needs docker, the agent image and Verus")
    verus = setup_cmd.verus_path()
    for name in list(os.environ):
        if name.startswith("LEMMA_") or name in SECRET_ENV:
            monkeypatch.delenv(name)
    monkeypatch.setenv("RUSTUP_HOME", os.environ.get("RUSTUP_HOME") or str(Path.home() / ".rustup"))
    monkeypatch.setenv("CARGO_HOME", os.environ.get("CARGO_HOME") or str(Path.home() / ".cargo"))
    home_dir = tmp_path / "home"
    (home_dir / "tools").mkdir(parents=True)
    (home_dir / "tools" / "verus").symlink_to(verus.parent)
    monkeypatch.setenv("HOME", str(home_dir))
    lemma_home = tmp_path / "lemma_home"
    monkeypatch.setenv("LEMMA_HOME", str(lemma_home))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-LEMMASQL-dummy-NOT-A-REAL-KEY-0000")
    done = subprocess.run([sys.executable, "-m", "lemma_cli.main", "setup", "--auth", "api-key"], cwd=ROOT, capture_output=True, text=True, timeout=1800, check=False)
    print(done.stdout[-3000:], done.stderr[-2000:])
    assert done.returncode == 0 and "READY" in done.stdout

    db = tmp_path / "shop.duckdb"
    con = _connect(lemma_home, str(db))
    _fill(con, n=2000, seed=11)
    con.execute(f"SET lemma_generator = '{sys.executable} -m lemma_cli.main generate'")
    body = (FIX / "template_usum_checked.rs").read_text().replace("param_lo", "param_p1").strip("\n")
    cert, key = make_ca(tmp_path)
    text = "SELECT SUM(cost) AS total FROM pre WHERE line > 5"
    want = con.execute(text).fetchall()
    with MockAnthropic(Conversation(body), cert, key, tmp_path / "mock_requests.jsonl") as mock:
        monkeypatch.setenv(MOCK_PORT_ENV, str(mock.port))
        monkeypatch.setenv(MOCK_CA_ENV, str(cert))
        got = con.execute(_lemma(text)).fetchall()
    jobs = con.execute("SELECT status, installed_key, log FROM lemma_jobs()").fetchall()
    print(jobs, Path(jobs[0][2]).read_text()[-4000:] if jobs else "")
    assert got == want
    engine, reason = _last(con)
    lifted = "-- params: p1 BIGINT\nSELECT SUM(cost) AS total FROM pre WHERE line > $p1"
    assert engine == "lemma" and f"template {in_duckdb.executor_key(lifted)[:12]} ($p1 = 5)" in reason and "generated now" in reason
    assert [(s, k) for s, k, _log in jobs] == [("done", in_duckdb.executor_key(lifted))]
    manifest = json.loads((lemma_home / "executors" / in_duckdb.executor_key(lifted) / "manifest.json").read_text())
    assert manifest["sql"] == lifted and re.fullmatch(r"\d+ verified, 0 errors", manifest["proof"])
    other = "SELECT SUM(cost) AS total FROM pre WHERE line > 9"
    want = con.execute(other).fetchall()
    assert con.execute(_lemma(other)).fetchall() == want and "$p1 = 9" in _last(con)[1]
    assert con.execute("SELECT COUNT(*) FROM lemma_jobs()").fetchone()[0] == 1
