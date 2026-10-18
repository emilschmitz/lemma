"""Lemma inside DuckDB (lemma.toml [engine] in_duckdb): library mode, the executor cache, the DuckDB 1.5.6 extension, the measure hook.

Unit tests run everywhere. The extension tests need the build (``db_extension/duckdb_ext/build.sh``, about an hour the first time)
and Verus; they LOAD the loadable extension into the Python 1.5.6 wheel and run the statically linked CLI. Each installs proved
fixtures (``tests/fixtures/declarative_proofs``) in library mode into a temporary LEMMA_HOME and compares ``lemma_query`` and
Lemma mode row for row with DuckDB's own answer. The SF1 tests (marked slow) read research_loop/generated/tpch_sf1.duckdb READ-ONLY.
"""

from __future__ import annotations

import json
import math
import random
import re
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.assemble_library import assemble_library_program
from declarative_spec.emit import emit_declarative_spec
from research_loop import in_duckdb, official_measure
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

ROOT = Path(__file__).resolve().parents[1]
PROOFS = ROOT / "tests" / "fixtures" / "declarative_proofs"
EXT_DIR = ROOT / "db_extension" / "duckdb_ext"
EXTENSION = EXT_DIR / "build" / "release" / "extension" / "lemma" / "lemma.duckdb_extension"
CLI = EXT_DIR / "build" / "release" / "duckdb"
VERUS = Path("/home/emil/tools/verus/verus")
SF1 = ROOT / "research_loop" / "generated" / "tpch_sf1.duckdb"
if not SF1.is_file():
    SF1 = Path("/home/emil/projects/lemma-db/research_loop/generated/tpch_sf1.duckdb")  # the main checkout's gitignored data, read-only

needs_ext = pytest.mark.skipif(
    not EXTENSION.is_file() or not VERUS.is_file(), reason="build the extension first (db_extension/duckdb_ext/build.sh) and install Verus"
)

_PRE = {"pre": {"line": "bigint", "report": "bigint"}}
_JOIN = {"num": {"adsh": "varchar", "qtrs": "bigint"}, "sub": {"adsh": "varchar", "fy": "bigint"}}
_DICT = {"num": {"uom": "varchar", "value": "decimal(38,4)"}}
# (fixture, sql, schema, string encoding): a scalar SUM with WHERE, a GROUP BY, a join, a dictionary + DECIMAL filter aggregate.
SMALL = {
    "usum": ("ungrouped_sum_where.rs", "SELECT SUM(line) AS total FROM pre WHERE line > 5", _PRE, "plain"),
    "group": ("group_sum_where.rs", "SELECT report, SUM(line) AS total FROM pre WHERE line > 5 GROUP BY report", _PRE, "plain"),
    "join": (
        "join_group_sum.rs",
        "SELECT s.fy, SUM(n.qtrs) AS total FROM num n JOIN sub s ON n.adsh = s.adsh GROUP BY s.fy",
        _JOIN,
        "plain",
    ),
    "dict": ("dict_filter_count_sum.rs", "SELECT COUNT(*) AS c, SUM(value) AS s FROM num WHERE uom = 'USD'", _DICT, "dict"),
}
CAP = 64


def _catalog(key: str) -> CatalogAssumptions:
    if key == "dict":
        from research_loop.assumption_packages import assumption_package

        return assumption_package("sec_margin_dec")
    return CatalogAssumptions(tables={t: TableAssumptions(max_rows=CAP) for t in SMALL[key][2]})


# ---------------------------------------------------------------- normalization: one definition, mirrored in C++

NORMALIZE_CASES = [
    ("  SELECT  a,\n\tb FROM t ;; ", "SELECT a, b FROM t"),
    ("SELECT 'a  b' ,  \"x  y\" FROM t", "SELECT 'a  b' , \"x  y\" FROM t"),
    ("SELECT x FROM t -- c  d\n  WHERE y", "SELECT x FROM t -- c  d\n WHERE y"),
    ("SELECT /* a   b */  1", "SELECT /* a   b */ 1"),
    ("SELECT $1 ,  2 ;", "SELECT $1 ,  2"),
    ("select it''s", "select it''s"),
]


@pytest.mark.parametrize(("sql", "want"), NORMALIZE_CASES)
def test_normalize_sql(sql: str, want: str) -> None:
    assert in_duckdb.normalize_sql(sql) == want


def test_normalize_keeps_a_commented_tail_distinct_from_the_uncommented_query() -> None:
    commented = "SELECT x FROM t -- c\nWHERE y"
    plain = "SELECT x FROM t -- c WHERE y"
    assert in_duckdb.executor_key(commented) != in_duckdb.executor_key(plain)
    assert in_duckdb.executor_key("SELECT 1") == in_duckdb.executor_key(" SELECT\n1 ;")


# ---------------------------------------------------------------- the flag

def test_flag_off_refuses_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LEMMA_IN_DUCKDB", "false")
    fixture, sql, schema, _enc = SMALL["usum"]
    with pytest.raises(in_duckdb.InDuckdbDisabled):
        in_duckdb.install_executor(
            sql=sql, schema=schema, catalog=_catalog("usum"), agent_source=(PROOFS / fixture).read_text(),
            db_path=tmp_path / "none.duckdb", home=tmp_path,
        )
    assert not (tmp_path / "executors").exists()


def test_flag_off_refuses_the_in_duckdb_measure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LEMMA_IN_DUCKDB", "false")
    with pytest.raises(ValueError, match="in_duckdb is off"):
        official_measure.in_duckdb_round_timers({"sql": "SELECT 1"}, tmp_path, extension=EXTENSION, home=tmp_path)


# ---------------------------------------------------------------- library mode

def _spec(key: str, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str, str]:
    fixture, sql, schema, enc = SMALL[key]
    monkeypatch.setenv("LEMMA_STRING_ENCODING", enc)
    return emit_declarative_spec(sql, schema, _catalog(key)), (PROOFS / fixture).read_text(), sql


@pytest.mark.parametrize("key", ["usum", "join"])
def test_library_mode_keeps_the_verified_part_and_replaces_main(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    spec, body, sql = _spec(key, monkeypatch)
    lib = assemble_library_program(spec, body, sql=sql)
    program = assemble_declarative_program(spec, body)
    verified = program[: program.index("\nfn main()")]
    assert lib.startswith(verified.rstrip("\n"))  # the verus! part and the loaders are byte-identical
    assert "fn main(" not in lib and "pub extern \"C\" fn lemma_run(" in lib
    tail = lib[len(verified) :]
    # only the five commented blocks of the fixed template (the fifth, ABI 3: an owned input buffer becomes the Vec)
    assert tail.count("unsafe {") + tail.count("unsafe{") == 5
    assert all(f"// UNSAFE {i}/5. Contract:" in tail for i in range(1, 6))
    assert "unsafe" not in body
    assert "catch_unwind" in tail and "load_cols_" in tail


@pytest.mark.parametrize("key", ["usum", "group"])
def test_library_mode_checks_every_assumption_main_checks_before_run_query(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    spec, body, sql = _spec(key, monkeypatch)
    lib = assemble_library_program(spec, body, sql=sql)
    main = assemble_declarative_program(spec, body, column_bins={"pre": "/x"})
    execute = lib[lib.index("fn lemma_execute") :]
    checks = [ln.strip() for ln in main.splitlines() if ln.strip().startswith("assert!(") and "catalog" in ln]
    assert checks
    for check in checks:  # the same check, as is or through a fast helper of the template, before run_query
        message = re.search(r'"[^"]*catalog[^"]*"', check).group(0)
        assert message in execute, check
        assert execute.index(message) < execute.index("run_query(")


def test_library_mode_refuses_a_map_result(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = emit_declarative_spec("SELECT uom, COUNT(*) FROM num GROUP BY uom", {"uom": "VARCHAR"}, CatalogAssumptions(tables={"num": TableAssumptions(max_rows=8)}))
    with pytest.raises(ValueError, match="library mode returns OutRow rows"):
        assemble_library_program(spec, "    StringHashMap::new()\n", sql="SELECT uom, COUNT(*) FROM num GROUP BY uom")


# ---------------------------------------------------------------- fast checks: the same predicates, faster


def test_fast_check_rewrites_the_known_shapes_and_keeps_any_other_check_as_is() -> None:
    from declarative_spec.assemble_library import fast_check

    types = {"t_a": "i64", "t_c": "u8", "t_c__dict": "String", "t_f": "f64", "t_s": "String"}
    rng = '    assert!(t_a.iter().all(|v| (*v as i128) >= -15i128 && (*v as i128) <= 15i128), "t.a: value outside the catalog bound 15");'
    assert fast_check(rng, types) == '    assert!(lemma_all_in_range(&t_a, -15i128, 15i128), "t.a: value outside the catalog bound 15");'
    code = '    assert!(t_c.iter().all(|c| (*c as usize) < t_c__dict.len()), "t.c: a code is outside its dictionary");'
    assert fast_check(code, types) == '    assert!(lemma_all_below(&t_c, t_c__dict.len()), "t.c: a code is outside its dictionary");'
    distinct = '    assert!(t_c__dict.iter().collect::<std::collections::HashSet<_>>().len() == t_c__dict.len(), "t.c: a dictionary entry repeats");'
    assert fast_check(distinct, types) == '    assert!(lemma_all_distinct(&t_c__dict), "t.c: a dictionary entry repeats");'
    finite = '    assert!(t_f.iter().all(|v| v.is_finite()), "t.f: a value is NaN or infinite");'
    assert fast_check(finite, types) == '    assert!(lemma_par_all(&t_f, |v: &f64| v.is_finite()), "t.f: a value is NaN or infinite");'
    unique = (
        "    {\n        let mut seen_t = std::collections::HashSet::new();\n        for i in 0..n_t {\n"
        '            assert!(seen_t.insert((t_a[i].clone(),)), "t: declared unique key (a) has a duplicate");\n        }\n    }'
    )
    assert fast_check(unique, types) == '    assert!(lemma_unique_ints(&t_a), "t: declared unique key (a) has a duplicate");'
    # a string key, a two-column key and an unknown shape stay exactly as generated
    for kept in (
        unique.replace("t_a[i]", "t_s[i]"),
        unique.replace("(t_a[i].clone(),)", "(t_a[i].clone(), t_c[i].clone(),)"),
        '    assert!(n_t <= 64usize, "t: {} rows exceed the catalog cap 64", n_t);',
    ):
        assert fast_check(kept, types) == kept


_FAST_CHECK_HARNESS = r"""
fn naive_range<T: LemmaInt>(v: &[T], lo: i128, hi: i128) -> bool { v.iter().all(|x| x.wide() >= lo && x.wide() <= hi) }
fn naive_below<T: LemmaInt>(v: &[T], n: usize) -> bool { v.iter().all(|x| x.wide() < n as i128) }
fn naive_unique<T: LemmaInt + std::hash::Hash>(v: &[T]) -> bool { v.iter().collect::<std::collections::HashSet<_>>().len() == v.len() }
fn naive_distinct(v: &[String]) -> bool { v.iter().collect::<std::collections::HashSet<_>>().len() == v.len() }

struct Rng(u64);
impl Rng { fn next(&mut self) -> u64 { self.0 ^= self.0 << 13; self.0 ^= self.0 >> 7; self.0 ^= self.0 << 17; self.0 } }

fn main() {
    let mut rng = Rng(0x9E3779B97F4A7C15);
    let mut cases = 0u64;
    // lengths around the threading cut (64Ki values per part) and the empty slice
    for &len in &[0usize, 1, 2, 7, 65535, 65536, 65537, 300_001] {
        for round in 0..6 {
            let span = [1u64, 2, 30, 1000, 1 << 20, u64::MAX][round];
            let v: Vec<i64> = (0..len).map(|_| (rng.next() % span) as i64 - (span / 2) as i64).collect();
            let mut w = v.clone();
            if len > 3 && round % 2 == 0 { let i = (rng.next() as usize) % len; w[i] = w[(i + 1) % len]; }  // a duplicate
            for &(lo, hi) in &[(-15i128, 15i128), (i128::MIN, 0), (0, i128::MAX), (-1000, 999), (i64::MIN as i128, i64::MAX as i128)] {
                assert_eq!(lemma_all_in_range(&v, lo, hi), naive_range(&v, lo, hi));
                cases += 1;
            }
            assert_eq!(lemma_unique_ints(&v), naive_unique(&v));
            assert_eq!(lemma_unique_ints(&w), naive_unique(&w));
            let codes: Vec<u8> = v.iter().map(|x| (*x as u64 % 7) as u8).collect();
            for n in 0..9 { assert_eq!(lemma_all_below(&codes, n), naive_below(&codes, n)); }
            let wide: Vec<i128> = v.iter().map(|x| (*x as i128) << 64).collect();
            assert_eq!(lemma_all_in_range(&wide, -(1i128 << 80), 1i128 << 80), naive_range(&wide, -(1i128 << 80), 1i128 << 80));
            assert_eq!(lemma_unique_ints(&wide), naive_unique(&wide));
            let f: Vec<f64> = v.iter().map(|x| *x as f64).collect();
            assert_eq!(lemma_par_all(&f, |x: &f64| x.abs() < 1e3), f.iter().all(|x| x.abs() < 1e3));
            cases += 14;
        }
    }
    // a value that breaks the bound only in the last part, and one only in the first
    let mut v: Vec<u32> = vec![5; 500_000];
    v[499_999] = 6;
    assert!(!lemma_all_in_range(&v, 0, 5) && lemma_all_in_range(&v, 0, 6) && !lemma_all_below(&v, 6));
    v[499_999] = 5; v[0] = 7;
    assert!(!lemma_all_in_range(&v, 0, 5) && !lemma_par_all(&v, |x: &u32| *x < 7));
    // unique keys: dense (bitmap) and sparse (sorted copy), duplicate at both ends
    let dense: Vec<u64> = (0..200_000u64).collect();
    let sparse: Vec<u64> = (0..200_000u64).map(|i| i * 1_000_003).collect();
    assert!(lemma_unique_ints(&dense) && lemma_unique_ints(&sparse));
    for base in [dense, sparse] {
        let mut a = base.clone(); a[199_999] = a[0];
        let mut b = base.clone(); b[1] = b[0];
        assert!(!lemma_unique_ints(&a) && !lemma_unique_ints(&b));
    }
    let words: Vec<String> = ["A", "N", "R", "", "AB"].iter().map(|s| s.to_string()).collect();
    assert!(lemma_all_distinct(&words) && naive_distinct(&words));
    let mut again = words.clone(); again.push("N".to_string());
    assert!(!lemma_all_distinct(&again) && !naive_distinct(&again));
    let empty: Vec<String> = Vec::new();
    assert!(lemma_all_distinct(&empty));
    println!("ok {}", cases);
}
"""


@pytest.mark.skipif(shutil.which("rustc") is None, reason="rustc not installed")
def test_fast_checks_agree_with_the_naive_predicates(tmp_path: Path) -> None:
    """The template's check helpers (compiled alone with rustc) against the plain `iter().all` / HashSet forms `main` uses:
    random slices around the threading cut, extreme bounds, i128, duplicates at either end, dense and sparse keys, empty."""
    from declarative_spec import assemble_library

    head = assemble_library._TEMPLATE_HEAD
    helpers = head[head.index("// Fast evaluation of the generated data checks") : head.index("fn lemma_fixed<")]
    src = tmp_path / "fast_checks.rs"
    src.write_text("#![allow(dead_code)]\n" + helpers + _FAST_CHECK_HARNESS)
    exe = tmp_path / "fast_checks"
    subprocess.run(["rustc", "--edition", "2021", "-O", "-o", str(exe), str(src)], check=True, capture_output=True, timeout=300)
    out = subprocess.run([str(exe)], capture_output=True, text=True, timeout=300, check=False)
    assert out.returncode == 0 and out.stdout.startswith("ok "), out.stderr[-2000:]


# ---------------------------------------------------------------- measure hook (stubbed timers)

def test_in_duckdb_measure_interleaves_and_labels(tmp_path: Path) -> None:
    calls: list[str] = []

    def timers(_bar, _dir, *, extension, home):
        def ours() -> int:
            calls.append("ours")
            return 100

        def duck() -> int:
            calls.append("duck")
            return 300

        return ours, duck, lambda: calls.append("closed")

    out = official_measure.measure_in_duckdb({}, tmp_path, extension=tmp_path, home=tmp_path, k=3, timers=timers)
    assert out["measurement"] == official_measure.MEASUREMENT_IN_DUCKDB
    assert calls == ["ours", "duck", "duck", "ours", "ours", "duck", "closed"]
    assert out["ours_median_us"] == 100 and out["duck_median_us"] == 300 and out["speedup"] == 3.0


def test_in_duckdb_measure_closes_on_a_failed_round(tmp_path: Path) -> None:
    closed: list[bool] = []

    def timers(_bar, _dir, *, extension, home):
        def ours() -> int:
            raise RuntimeError("executor refused the data")

        return ours, (lambda: 1), lambda: closed.append(True)

    with pytest.raises(RuntimeError, match="refused"):
        official_measure.measure_in_duckdb({}, tmp_path, extension=tmp_path, home=tmp_path, k=2, timers=timers)
    assert closed == [True]


def test_lemma_query_sql_quotes_the_text() -> None:
    assert official_measure.lemma_query_sql("SELECT 'a'") == "SELECT * FROM lemma_query('SELECT ''a''')"


# ---------------------------------------------------------------- the extension (built) against DuckDB

def _fill(con: duckdb.DuckDBPyConnection, seed: int, rows: int = 50) -> None:
    rng = random.Random(seed)
    con.execute("CREATE OR REPLACE TABLE pre (line BIGINT, report BIGINT)")
    con.executemany("INSERT INTO pre VALUES (?, ?)", [(rng.randint(-20, 40), rng.randint(1, 6)) for _ in range(rows)])
    con.execute("CREATE OR REPLACE TABLE num (adsh VARCHAR, qtrs BIGINT, uom VARCHAR, value DECIMAL(38,4))")
    con.executemany(
        "INSERT INTO num VALUES (?, ?, ?, ?)",
        [
            (f"a{rng.randint(1, 12)}", rng.randint(0, 4), rng.choice(["USD", "EUR", "shares", "pure"]), Decimal(rng.randint(-10**8, 10**8)) / 10000)
            for _ in range(rows)
        ],
    )
    con.execute("CREATE OR REPLACE TABLE sub (adsh VARCHAR, fy BIGINT)")
    con.executemany("INSERT INTO sub VALUES (?, ?)", [(f"a{i}", 2000 + rng.randint(0, 3)) for i in range(1, 15)])


def _connect(home: Path, database: str = ":memory:", read_only: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database, read_only=read_only, config={"allow_unsigned_extensions": "true"})
    con.execute(f"LOAD '{EXTENSION}'")
    con.execute(f"SET lemma_home = '{home}'")
    return con


def _same(got: list, want: list, ordered: bool) -> bool:
    if len(got) != len(want):
        return False
    if not ordered:
        key = lambda r: tuple((v is None, str(type(v)), v if not isinstance(v, float) else round(v, 6)) for v in r)  # noqa: E731
        got, want = sorted(got, key=key), sorted(want, key=key)
    for a, b in zip(got, want, strict=True):
        for x, y in zip(a, b, strict=True):
            if isinstance(x, float) and isinstance(y, float):
                if not (x == y or (math.isnan(x) and math.isnan(y)) or abs(x - y) <= 1e-9 * max(abs(x), abs(y))):
                    return False
            elif x != y or type(x) is not type(y):
                return False
    return True


def _install(key_or_case, home: Path, db_path: Path, schema=None, catalog=None, encoding=None) -> Path:
    if isinstance(key_or_case, str):
        fixture, sql, schema, encoding = SMALL[key_or_case]
        catalog = _catalog(key_or_case)
    else:
        fixture, sql = key_or_case
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LEMMA_IN_DUCKDB", "true")
        mp.setenv("LEMMA_STRING_ENCODING", encoding)
        mp.setenv("LEMMA_PARALLEL_VSTD", "off")
        mp.setenv("LEMMA_JOIN_CHAIN", "0")
        mp.setenv("LEMMA_VERUS_BIN", str(ROOT / "scripts" / "ram" / "verus_guarded.sh"))
        return in_duckdb.install_executor(
            sql=sql, schema=schema, catalog=catalog, agent_source=(PROOFS / fixture).read_text(), db_path=db_path, home=home
        )


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A LEMMA_HOME with the four small fixtures installed in library mode (Verus verifies and compiles each)."""
    if not EXTENSION.is_file() or not VERUS.is_file():
        pytest.skip("build the extension first (db_extension/duckdb_ext/build.sh) and install Verus")
    root = tmp_path_factory.mktemp("lemma_home")
    db = root / "schema.duckdb"
    con = duckdb.connect(str(db))
    _fill(con, 0)
    con.close()
    for key in SMALL:
        _install(key, root, db)
    return root


@needs_ext
@pytest.mark.parametrize("seed", [1, 2])
@pytest.mark.parametrize("key", sorted(SMALL))
def test_lemma_query_matches_duckdb_row_for_row(key: str, seed: int, home: Path) -> None:
    con = _connect(home)
    _fill(con, seed)
    sql = SMALL[key][1]
    want = con.execute(sql).fetchall()
    got = con.execute(official_measure.lemma_query_sql(sql)).fetchall()
    assert want and _same(got, want, ordered=False), (got, want)
    engine, reason = con.execute("SELECT engine, reason FROM lemma_last_query()").fetchone()
    assert engine == "lemma" and "verified, 0 errors" in reason
    assert [d[1] for d in con.execute(official_measure.lemma_query_sql(sql)).description] == [d[1] for d in con.execute(sql).description]


@needs_ext
@pytest.mark.parametrize("key", ["group", "dict"])
def test_lemma_mode_replaces_the_plan_and_labels_the_engine(key: str, home: Path) -> None:
    con = _connect(home)
    _fill(con, 3)
    sql = SMALL[key][1]
    want = con.execute(sql).fetchall()
    assert con.execute("SELECT engine FROM lemma_last_query()").fetchone()[0] == "duckdb"  # lemma_mode is off by default
    con.execute("SET lemma_mode = true")
    got = con.execute(sql).fetchall()
    assert _same(got, want, ordered=False), (got, want)
    engine, reason, rows = con.execute("SELECT engine, reason, rows FROM lemma_last_query()").fetchone()
    assert engine == "lemma" and "lemma_mode" in reason and rows == len(want)
    plan = "\n".join(str(r[1]) for r in con.execute("EXPLAIN " + sql).fetchall())
    assert "lemma_query" in plan.lower() and "engine" in plan and "lemma" in plan


@needs_ext
def test_lemma_mode_off_runs_duckdb_and_says_so(home: Path) -> None:
    con = _connect(home)
    _fill(con, 4)
    con.execute("SET lemma_mode = false")
    con.execute(SMALL["usum"][1]).fetchall()
    assert con.execute("SELECT engine, reason FROM lemma_last_query()").fetchone() == ("duckdb", "lemma_mode is off")
    plan = "\n".join(str(r[1]) for r in con.execute("EXPLAIN " + SMALL["usum"][1]).fetchall())
    assert "lemma_query" not in plan.lower()


UNPROVED = "SELECT report, MAX(line) AS m FROM pre GROUP BY report"


@needs_ext
def test_unproved_query_in_lemma_mode_is_an_error_without_the_routing_flag(home: Path) -> None:
    con = _connect(home)
    _fill(con, 5)
    con.execute("SET lemma_mode = true")
    with pytest.raises(duckdb.Error, match="no proved executor for this query; run `lemma optimize`"):
        con.execute(UNPROVED).fetchall()
    with pytest.raises(duckdb.Error, match="no proved executor"):
        con.execute(official_measure.lemma_query_sql(UNPROVED)).fetchall()
    assert con.execute("SELECT engine FROM lemma_last_query()").fetchone()[0] == "none"


@needs_ext
def test_routing_flag_runs_unproved_on_duckdb_labelled(home: Path, tmp_path: Path) -> None:
    con = _connect(home)
    _fill(con, 6)
    want = con.execute(UNPROVED).fetchall()
    con.execute("SET lemma_mode = true")
    con.execute("SET lemma_route_unproved = true")
    assert con.execute(UNPROVED).fetchall() == want
    engine, reason = con.execute("SELECT engine, reason FROM lemma_last_query()").fetchone()
    assert engine == "duckdb" and "lemma_route_unproved" in reason
    got = con.execute(SMALL["usum"][1]).fetchall()  # a proved query still goes to Lemma with the flag on
    assert con.execute("SELECT engine FROM lemma_last_query()").fetchone()[0] == "lemma"
    assert _same(got, con.execute(official_measure.lemma_query_sql(SMALL["usum"][1])).fetchall(), ordered=False)
    # lemma_query() never routes: an explicit call without an executor is an error even with the flag on
    with pytest.raises(duckdb.Error, match="no proved executor"):
        con.execute(official_measure.lemma_query_sql(UNPROVED)).fetchall()


@needs_ext
def test_a_miss_is_enqueued_only_when_asked(home: Path, tmp_path: Path) -> None:
    queue_home = tmp_path / "qhome"
    con = _connect(queue_home)
    _fill(con, 7)
    with pytest.raises(duckdb.Error):
        con.execute(official_measure.lemma_query_sql(UNPROVED)).fetchall()
    assert not (queue_home / "queue").exists()
    con.execute("SET lemma_enqueue_misses = true")
    with pytest.raises(duckdb.Error):
        con.execute(official_measure.lemma_query_sql(UNPROVED)).fetchall()
    queued = queue_home / "queue" / f"{in_duckdb.executor_key(UNPROVED)}.sql"
    assert queued.read_text().strip() == UNPROVED


@needs_ext
def test_assumption_violation_is_an_error_not_rows(home: Path) -> None:
    con = _connect(home)
    _fill(con, 8, rows=CAP + 1)  # one row over the catalog cap the proof assumes
    with pytest.raises(duckdb.Error, match=f"exceed the catalog cap {CAP}"):
        con.execute(official_measure.lemma_query_sql(SMALL["usum"][1])).fetchall()
    con.execute("SET lemma_mode = true")
    with pytest.raises(duckdb.Error, match="refused the data"):
        con.execute(SMALL["group"][1]).fetchall()


@needs_ext
def test_null_in_a_column_not_declared_nullable_is_an_error(home: Path) -> None:
    con = _connect(home)
    _fill(con, 9)
    con.execute("INSERT INTO pre VALUES (NULL, 1)")
    with pytest.raises(duckdb.Error, match="has NULLs; the catalog does not declare the column nullable"):
        con.execute(official_measure.lemma_query_sql(SMALL["usum"][1])).fetchall()


@needs_ext
def test_the_executor_reads_the_callers_snapshot(home: Path, tmp_path: Path) -> None:
    db = tmp_path / "snap.duckdb"
    writer = _connect(home, str(db))
    _fill(writer, 10, rows=40)
    reader = writer.cursor()  # a second connection to the same database
    reader.execute(f"SET lemma_home = '{home}'")
    sql = SMALL["usum"][1]
    before = reader.execute(sql).fetchall()
    writer.execute("BEGIN")
    writer.execute("INSERT INTO pre SELECT 100 + i, 1 FROM range(10) t(i)")
    # the writer sees its own uncommitted rows, through Lemma as through DuckDB
    assert _same(writer.execute(official_measure.lemma_query_sql(sql)).fetchall(), writer.execute(sql).fetchall(), False)
    assert writer.execute(sql).fetchall() != before
    # the other connection does not
    assert _same(reader.execute(official_measure.lemma_query_sql(sql)).fetchall(), before, False)
    writer.execute("ROLLBACK")
    assert _same(writer.execute(official_measure.lemma_query_sql(sql)).fetchall(), before, False)


def _copy_home(home: Path, tmp_path: Path) -> tuple[Path, Path]:
    copy = tmp_path / "home"
    shutil.copytree(home, copy)
    return copy, copy / "executors" / in_duckdb.executor_key(SMALL["usum"][1]) / "manifest.json"


@needs_ext
def test_executor_for_another_duckdb_version_is_refused(home: Path, tmp_path: Path) -> None:
    copy, manifest = _copy_home(home, tmp_path)
    m = json.loads(manifest.read_text())
    m["duckdb_version"] = "v1.5.5"
    manifest.write_text(json.dumps(m))
    con = _connect(copy)
    _fill(con, 11)
    with pytest.raises(duckdb.Error, match="built for DuckDB v1.5.5, this is DuckDB v1.5.6"):
        con.execute(official_measure.lemma_query_sql(SMALL["usum"][1])).fetchall()


@needs_ext
@pytest.mark.parametrize("proof", ["12 verified, 1 errors", ""])
def test_executor_without_a_complete_proof_is_refused(proof: str, home: Path, tmp_path: Path) -> None:
    copy, manifest = _copy_home(home, tmp_path)
    m = json.loads(manifest.read_text())
    m["proof"] = proof
    manifest.write_text(json.dumps(m))
    con = _connect(copy)
    _fill(con, 12)
    with pytest.raises(duckdb.Error, match="has no complete proof"):
        con.execute(official_measure.lemma_query_sql(SMALL["usum"][1])).fetchall()


@needs_ext
def test_a_swapped_library_is_refused(home: Path, tmp_path: Path) -> None:
    copy, manifest = _copy_home(home, tmp_path)
    other = copy / "executors" / in_duckdb.executor_key(SMALL["group"][1]) / "lib.so"
    shutil.copyfile(other, manifest.parent / "lib.so")
    # A fresh process: a library is hashed when it is first loaded, and this one has not been loaded there.
    script = (
        "import duckdb, sys\n"
        "con = duckdb.connect(config={'allow_unsigned_extensions': 'true'})\n"
        f"con.execute(\"LOAD '{EXTENSION}'\")\n"
        f"con.execute(\"SET lemma_home = '{copy}'\")\n"
        "con.execute('CREATE TABLE pre (line BIGINT, report BIGINT)')\n"
        "try:\n"
        f"    con.execute({official_measure.lemma_query_sql(SMALL['usum'][1])!r}).fetchall()\n"
        "except duckdb.Error as e:\n"
        "    print(e)\n"
    )
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120, check=True).stdout
    assert "does not match the sha256 in its manifest" in out, out


@needs_ext
def test_cxx_and_python_normalization_agree() -> None:
    con = duckdb.connect(config={"allow_unsigned_extensions": "true"})
    con.execute(f"LOAD '{EXTENSION}'")
    queries = [sql for sql, _ in NORMALIZE_CASES] + [case[1] for case in SMALL.values()] + ["SELECT 'é  ü'  ,\r\n 1"]
    for sql in queries:
        norm, key = con.execute("SELECT lemma_normalize_sql(?), lemma_sql_key(?)", [sql, sql]).fetchone()
        assert norm == in_duckdb.normalize_sql(sql), sql
        assert key == in_duckdb.executor_key(sql), sql


@needs_ext
@pytest.mark.skipif(not CLI.is_file(), reason="the statically linked CLI is built by db_extension/duckdb_ext/build.sh")
def test_statically_linked_cli_answers_with_the_proved_executor(home: Path) -> None:
    sql = SMALL["group"][1]
    script = (
        "CREATE TABLE pre (line BIGINT, report BIGINT);"
        "INSERT INTO pre SELECT (i * 7) % 30 - 5, i % 4 FROM range(40) t(i);"
        f"SET lemma_home = '{home}';"
        f"COPY ({sql} ORDER BY 1) TO '/dev/stdout' (FORMAT csv, HEADER false);"
        "SET lemma_mode = true;"
        f"COPY (SELECT * FROM lemma_query('{sql}') ORDER BY 1) TO '/dev/stdout' (FORMAT csv, HEADER false);"
        "SELECT engine FROM lemma_last_query();"
    )
    out = subprocess.run([str(CLI), "-csv", "-noheader", "-c", script], capture_output=True, text=True, timeout=120, check=True).stdout
    lines = [ln for ln in out.splitlines() if ln.strip()]
    half = (len(lines) - 1) // 2
    assert half > 0 and lines[:half] == lines[half : 2 * half], out
    assert lines[-1] == "lemma"
    version = subprocess.run([str(CLI), "-c", "SELECT version()"], capture_output=True, text=True, check=True).stdout
    assert "v1.5.6" in version


# ---------------------------------------------------------------- the parallel scan: the single-threaded row order, byte for byte
# lemma_scan_inputs(sql) returns the bytes lemma_query hands to lemma_run (the executor does not run, so no catalog cap applies).
# The reference is an independent Python encoding of `SELECT ... ORDER BY rowid` on the same connection (committed rows in row
# order, then the transaction's own rows; deleted rows gone): what a single thread scanning in row order produces.

ROW_GROUP = 122880  # DuckDB's default row group: tables below span several, the last one partial


def _scan(con: duckdb.DuckDBPyConnection, sql: str) -> list[tuple]:
    return con.execute("SELECT input, name, role, n, data FROM lemma_scan_inputs(?) ORDER BY input", [sql]).fetchall()


def _pack_int(v: int, rust: str) -> bytes:
    width = {"u8": 1, "u16": 2, "u32": 4, "u64": 8, "i8": 1, "i16": 2, "i32": 4, "i64": 8, "i128": 16, "usize": 8}[rust]
    return v.to_bytes(width, "little", signed=rust.startswith("i"))


def _pack_str(s: str) -> bytes:
    data = s.encode("utf-8")
    return len(data).to_bytes(4, "little") + data


def _reference(con: duckdb.DuckDBPyConnection, manifest: dict) -> list[tuple]:
    """(input, name, role, n, bytes) per manifest input, encoded in Python from the rows in row order."""
    out: list[tuple] = []
    inputs = manifest["inputs"]
    cache: dict[str, list] = {}
    for k, e in enumerate(inputs):
        table = e["table"]
        if table not in cache:
            cols = [x["column"] for x in inputs if x["kind"] == "field" and x["table"] == table]
            names = list(dict.fromkeys(cols)) or ["rowid"]
            rows = con.execute(f"SELECT {', '.join(names)} FROM {table} ORDER BY rowid").fetchall()
            cache[table] = [dict(zip(names, r, strict=True)) for r in rows]
        rows = cache[table]
        if e["kind"] == "rows":
            out.append((k, table, "rows", len(rows), b""))
            continue
        values = [r[e["column"]] for r in rows]
        name, role = f"{table}.{e['field']}", e["role"]
        if role in ("int", "decimal"):
            scale = 10 ** e["scale"]
            cells = [0 if v is None else int(Decimal(v) * scale) for v in values]
            out.append((k, name, role, len(rows), b"".join(_pack_int(c, e["rust_type"]) for c in cells)))
        elif role == "string":
            out.append((k, name, role, len(rows), b"".join(_pack_str("" if v is None else v) for v in values)))
        elif role in ("code", "dict"):
            entries = list(dict.fromkeys(v for v in values if v is not None))
            if role == "code":
                code = {s: i for i, s in enumerate(entries)}
                out.append((k, name, role, len(rows), b"".join(_pack_int(code.get(v, 0), e["rust_type"]) for v in values)))
            else:
                if not entries and any(v is None for v in values):
                    entries = [""]
                out.append((k, name, role, len(entries), b"".join(_pack_str(s) for s in entries)))
        else:
            raise AssertionError(f"no reference encoding for role {role}")
    return out


def _big_num(con: duckdb.DuckDBPyConnection, rows: int, *, nulls: bool, value_type: str = "DECIMAL(38,4)") -> None:
    """`num` over several row groups: uom with values that first appear in different row groups (so the per-task dictionary
    numbering differs from the table's), optional NULLs, and committed deletes that leave gaps inside row groups."""
    uom = """CASE WHEN i < 200000 THEN ['USD', 'EUR'][1 + i % 2]
                  WHEN i < 300000 THEN ['shares', 'USD', 'pure', 'EUR'][1 + i % 4]
                  ELSE 'late-' || (i % 3) END"""
    value = f"CAST((i * 7919) % 2000003 - 1000001 AS {value_type}) / 100"
    if nulls:
        uom = f"CASE WHEN i % 997 = 5 THEN NULL ELSE {uom} END"
        value = f"CASE WHEN i % 1009 = 7 THEN NULL ELSE {value} END"
    con.execute(f"CREATE OR REPLACE TABLE num (adsh VARCHAR, qtrs BIGINT, uom VARCHAR, value {value_type})")
    con.execute(f"INSERT INTO num SELECT 'a' || (i % 13), i % 5, {uom}, CAST({value} AS {value_type}) FROM range({rows}) t(i)")
    con.execute("DELETE FROM num WHERE rowid % 50000 < 3 OR rowid BETWEEN 130000 AND 131000")
    con.execute("CREATE OR REPLACE TABLE sub AS SELECT 'a' || i AS adsh, 2000 + i % 4 AS fy FROM range(1, 15) t(i)")


def _nullable_home(home: Path, tmp_path: Path, key: str, edit) -> Path:
    """A copy of `home` whose manifest of `key` is edited (scan settings only; the library and its layouts are unchanged)."""
    copy = tmp_path / "home"
    shutil.copytree(home, copy)
    manifest = copy / "executors" / in_duckdb.executor_key(SMALL[key][1]) / "manifest.json"
    m = json.loads(manifest.read_text())
    edit(m)
    manifest.write_text(json.dumps(m))
    return copy


def _manifest(home: Path, key: str) -> dict:
    return json.loads((home / "executors" / in_duckdb.executor_key(SMALL[key][1]) / "manifest.json").read_text())


@needs_ext
@pytest.mark.parametrize("key", ["dict", "join"])
def test_parallel_scan_equals_the_single_threaded_row_order_byte_for_byte(key: str, home: Path) -> None:
    con = _connect(home)
    _big_num(con, 3 * ROW_GROUP + 4567, nulls=False)
    sql = SMALL[key][1]
    want = _reference(con, _manifest(home, key))
    assert want[0][3] == con.execute("SELECT COUNT(*) FROM num").fetchone()[0] > 3 * ROW_GROUP
    for threads in (1, 2, 3, 8):
        con.execute(f"SET lemma_scan_threads = {threads}")
        got = _scan(con, sql)
        assert [g[:4] for g in got] == [w[:4] for w in want], threads
        for g, w in zip(got, want, strict=True):
            assert g[4] == w[4], (threads, g[1])


@needs_ext
@pytest.mark.parametrize("threads", [1, 4])
def test_parallel_scan_encodes_nulls_as_zero_cells_and_scaled_decimals(threads: int, home: Path, tmp_path: Path) -> None:
    """NULL codes are code 0 and NULL decimals 0 where the manifest declares the column nullable (codes renumbered per task
    keep NULL at 0); a DECIMAL(18,2) column loaded at the spec's scale 4 goes through the scaled (non-copy) path."""

    def edit(m: dict) -> None:
        for e in m["inputs"]:
            if e.get("column") in ("uom", "value"):
                e["nullable"] = True
            if e.get("column") == "value":
                e["duck_type"], e["source_scale"] = "DECIMAL(18,2)", 2

    copy = _nullable_home(home, tmp_path, "dict", edit)
    con = _connect(copy)
    _big_num(con, 2 * ROW_GROUP + 999, nulls=True, value_type="DECIMAL(18,2)")
    con.execute(f"SET lemma_scan_threads = {threads}")
    manifest = _manifest(copy, "dict")
    want = _reference(con, manifest)
    got = _scan(con, SMALL["dict"][1])
    assert got == want
    assert con.execute("SELECT COUNT(*) FROM num WHERE uom IS NULL").fetchone()[0] > 0
    # without the nullable declaration, a NULL is an error raised on a scan thread, never rows
    plain = _connect(home)
    _big_num(plain, 2 * ROW_GROUP + 999, nulls=True)
    plain.execute(f"SET lemma_scan_threads = {threads}")
    with pytest.raises(duckdb.Error, match="has NULLs; the catalog does not declare the column nullable"):
        _scan(plain, SMALL["dict"][1])
    with pytest.raises(duckdb.Error, match="refused the data|has NULLs"):
        plain.execute(official_measure.lemma_query_sql(SMALL["dict"][1])).fetchall()


@needs_ext
def test_parallel_scan_reads_the_callers_snapshot_with_a_concurrent_writer(home: Path, tmp_path: Path) -> None:
    db = tmp_path / "snap_big.duckdb"
    writer = _connect(home, str(db))
    _big_num(writer, 2 * ROW_GROUP + 77, nulls=False)
    reader = writer.cursor()
    reader.execute(f"SET lemma_home = '{home}'")
    sql = SMALL["dict"][1]
    manifest = _manifest(home, "dict")
    for con in (writer, reader):
        con.execute("SET lemma_scan_threads = 8")
    before = _scan(reader, sql)
    assert before == _reference(reader, manifest)
    writer.execute("BEGIN")
    writer.execute(f"INSERT INTO num SELECT 'z', 1, 'only-in-tx', 1.5 FROM range({ROW_GROUP + 10}) t(i)")  # two local row groups
    writer.execute("DELETE FROM num WHERE rowid % 7 = 3")
    # the writer sees its own uncommitted rows and deletes, through the parallel scan as in row order
    mine = _scan(writer, sql)
    assert mine == _reference(writer, manifest) and mine != before
    writer.execute("SET lemma_scan_threads = 1")
    assert _scan(writer, sql) == mine
    # the other connection does not, at any thread count
    for threads in (1, 8):
        reader.execute(f"SET lemma_scan_threads = {threads}")
        assert _scan(reader, sql) == before
    writer.execute("COMMIT")
    reader2 = writer.cursor()
    reader2.execute(f"SET lemma_home = '{home}'")
    assert _scan(reader2, sql) == mine


def _run_library(lib_path: Path, cols_spec: list) -> tuple[int, bytes]:
    """lemma_run of an installed executor with hand-made inputs: ("rows", n) | ("owned", type code, width, values) |
    ("strings", entries). Owned buffers come from the library's allocator (ABI 3)."""
    import ctypes
    import struct

    from tests.test_in_duckdb_templates_stateful import _Col, _Out, _Param

    lib = ctypes.CDLL(str(lib_path))
    lib.lemma_alloc_input.restype = ctypes.c_void_p
    lib.lemma_alloc_input.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
    lib.lemma_run.restype = ctypes.c_int32
    keep: list = []
    cols = (_Col * len(cols_spec))()
    for k, spec in enumerate(cols_spec):
        if spec[0] == "rows":
            cols[k] = _Col(None, 0, spec[1])
        elif spec[0] == "owned":
            _kind, fmt, width, values = spec
            ptr = lib.lemma_alloc_input(k, len(values))
            assert ptr
            if fmt == "i128":
                raw = b"".join(v.to_bytes(16, "little", signed=True) for v in values)
            else:
                raw = struct.pack(f"<{len(values)}{fmt}", *values)
            if values:
                ctypes.memmove(ptr, raw, width * len(values))
            cols[k] = _Col(ptr, width * len(values), len(values))
        else:
            data = b"".join(_pack_str(s) for s in spec[1])
            keep.append(ctypes.create_string_buffer(data, len(data)))
            cols[k] = _Col(ctypes.cast(keep[-1], ctypes.c_void_p), len(data), len(spec[1]))
    out = _Out()
    code = lib.lemma_run(cols, len(cols_spec), (_Param * 1)(), 0, ctypes.byref(out))
    data = ctypes.string_at(out.ptr, out.len)
    lib.lemma_free_out(ctypes.byref(out))
    return code, data


@needs_ext
@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("code_outside", b"a code is outside its dictionary"),
        ("dict_repeats", b"a dictionary entry repeats"),
        ("row_cap", f"rows exceed the catalog cap {CAP}".encode()),
        ("ok", b"LMR1"),
    ],
)
def test_the_library_refuses_bad_codes_repeated_entries_and_too_many_rows(case: str, message: bytes, home: Path) -> None:
    """The checks stay in the library (Rust), whatever the scan did: a proved executor called directly with data the C++ scan
    would never produce is refused before run_query."""
    if case == "row_cap":
        lib = home / "executors" / in_duckdb.executor_key(SMALL["usum"][1]) / "lib.so"
        assert _manifest(home, "usum")["input_layout"] == ["rows pre", "pre.line i64"]
        code, data = _run_library(lib, [("rows", CAP + 1), ("owned", "q", 8, list(range(CAP + 1)))])
        assert code == 1 and message in data, data
        return
    lib = home / "executors" / in_duckdb.executor_key(SMALL["dict"][1]) / "lib.so"
    assert [ln.split()[-1] for ln in _manifest(home, "dict")["input_layout"]] == ["num", "u16", "String", "i128"]
    codes, entries = [0, 1, 0, 1, 1], ["USD", "EUR"]
    if case == "code_outside":
        codes[3] = 2
    elif case == "dict_repeats":
        entries = ["USD", "USD"]
    values = [10_000, -25_000, 3, 0, 7]  # DECIMAL(38,4) cells as i128
    code, data = _run_library(lib, [("rows", 5), ("owned", "H", 2, codes), ("strings", entries), ("owned", "i128", 16, values)])
    if case == "ok":
        assert code == 0 and data.startswith(message), data
    else:
        assert code == 1 and message in data and not data.startswith(b"LMR1"), data


# ---------------------------------------------------------------- SF1 (slow): the real TPC-H SF1 database, read-only
# A fixture proved under a dictionary catalog, plus the marked submissions of the replicable 2026-10-11/16 container runs
# (TPC-H Q1, Q3, Q6, Q12 at SF1): their bodies are re-verified against the spec emitted at THIS commit before they are installed.

RUNS = Path("/home/emil/projects/lemma-db/research_loop/runs")
SF1_RUNS = {
    "q1": "20261016T041513Z_q541054_05c66421",
    "q3": "20261016T043913Z_q24558_d4427a9d",
    "q6": "20261011T225850Z_q387753_67a46959",
    "q12": "20261016T051601Z_q144970_bdeac8f8",
}
SHIPMODE = "SELECT MIN(l_extendedprice) AS lo, COUNT(*) AS n FROM lineitem WHERE l_shipmode = 'AIR'"


@pytest.fixture(scope="module")
def sf1_home(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict]:
    if not EXTENSION.is_file() or not VERUS.is_file() or not SF1.is_file():
        pytest.skip("needs the built extension, Verus and research_loop/generated/tpch_sf1.duckdb")
    from research_loop.scripts.declarative_round import tpch_schema_and_catalog
    from research_loop.scripts.in_duckdb_install_run import install_run

    root = tmp_path_factory.mktemp("lemma_home_sf1")
    schema, catalog = tpch_schema_and_catalog(SF1)
    installed: dict = {}
    try:
        _install(("dict_shipmode_min_count.rs", SHIPMODE), root, SF1, schema=schema, catalog=catalog, encoding="dict")
        installed["shipmode_dict"] = SHIPMODE
    except Exception as exc:  # noqa: BLE001  # reported by the test of that query, not hidden
        installed["shipmode_dict"] = exc
    for name, run in SF1_RUNS.items():
        if not (RUNS / run / "workspace" / "mcp_results" / "submitted.json").is_file():
            installed[name] = None
            continue
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("LEMMA_IN_DUCKDB", "true")
            mp.setenv("LEMMA_VERUS_BIN", str(ROOT / "scripts" / "ram" / "verus_guarded.sh"))
            try:
                directory = install_run(RUNS / run, root)
                installed[name] = json.loads((directory / "manifest.json").read_text())["sql"]
            except Exception as exc:  # noqa: BLE001
                installed[name] = exc
    return root, installed


@pytest.mark.slow
@pytest.mark.parametrize("name", ["shipmode_dict", *SF1_RUNS])
def test_sf1_lemma_query_matches_duckdb(name: str, sf1_home: tuple[Path, dict]) -> None:
    root, installed = sf1_home
    sql = installed[name]
    if sql is None:
        pytest.skip(f"run {SF1_RUNS[name]} not on this machine")
    if isinstance(sql, Exception):
        pytest.fail(f"{name} did not install: {str(sql)[-1500:]}")
    ordered = re.search(r"order by", sql, re.I) is not None
    con = _connect(root, str(SF1), read_only=True)
    want = con.execute(sql).fetchall()
    got = con.execute(official_measure.lemma_query_sql(sql)).fetchall()
    assert want and _same(got, want, ordered), (got[:5], want[:5])
    con.execute("SET lemma_mode = true")
    assert _same(con.execute(sql).fetchall(), want, ordered)
    assert con.execute("SELECT engine FROM lemma_last_query()").fetchone()[0] == "lemma"


@pytest.mark.slow
@pytest.mark.parametrize("fixture", ["tpch_q3_join_group_topk.rs", "tpch_q14_promo_ratio.rs"])
def test_a_body_proved_for_a_smaller_catalog_is_not_installed_at_sf1(fixture: str, tmp_path: Path) -> None:
    """The Q3/Q14 reference bodies are proved under the mini catalog; under SF1's row caps their overflow bounds fail. Install
    must refuse (Verus errors), leaving no executor behind, so DuckDB is never answered by an unproved library."""
    if not VERUS.is_file() or not SF1.is_file():
        pytest.skip("needs Verus and research_loop/generated/tpch_sf1.duckdb")
    from research_loop.scripts.declarative_round import tpch_schema_and_catalog
    from tests.test_declarative_tpch_q3_q14_q19 import Q3, Q14

    sql = Q3 if "q3" in fixture else Q14
    schema, catalog = tpch_schema_and_catalog(SF1)
    with pytest.raises(RuntimeError, match="did not verify and compile"):
        _install((fixture, sql), tmp_path, SF1, schema=schema, catalog=catalog, encoding="plain")
    assert not (tmp_path / "executors" / in_duckdb.executor_key(sql)).exists()
    assert not [p for p in (tmp_path / "executors").iterdir() if p.name.startswith(".")]
