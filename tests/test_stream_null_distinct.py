"""Streaming executors: a GROUP BY key on a NULLABLE column and COUNT(DISTINCT x) as a set-valued field (lemma.toml [run] stream,
docs/STREAM.md "NULL group keys and COUNT DISTINCT", declarative_spec/stream_distinct.py).

The gate accepts both (one table and over a join) and still refuses every other DISTINCT. No trusted item is added. Verus: the host
scaffold with a stub agent (an invented join with a nullable build key and a COUNT DISTINCT over two build tables; GenDB SEC q6 and
q4 streaming num, the table the stream_join rule picks on sec_edgar_dec.duckdb), the two fixtures (a nullable string key with COUNT and
SUM; COUNT DISTINCT of a nullable string per group) and their mutants (NULLs dropped, the NULL group merged into a value group, a
distinct count with duplicates, a NULL value counted, ...). The compiled fixtures (binary-mode main: random chunk sizes, several
threads) against DuckDB on random tables with NULL keys, NULL values, duplicates and an empty table. The prompt's general notes.
"""

from __future__ import annotations

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
FIX = ROOT / "tests" / "fixtures" / "declarative_proofs" / "stream"
GUARD = ROOT / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")
SEC_COLUMNS = json.loads((ROOT / "configs" / "data" / "sec_edgar_3y_dec.json").read_text())["columns"]
SEC_SCHEMA = {t: {c: ty.lower() for c, ty in cs.items()} for t, cs in SEC_COLUMNS.items()}
# The columns of sec_edgar_dec.duckdb that hold NULLs (storage statistics, 2026-10-27): pre.stmt, pre.plabel, sub.sic, tag.tlabel
# among them, so q6's and q4's GROUP BY keys are nullable.
SEC_NULLABLE = {
    ("num", "coreg"), ("num", "footnote"), ("sub", "afs"), ("sub", "cityba"), ("sub", "countryba"), ("sub", "countryinc"), ("sub", "fp"),
    ("sub", "fy"), ("sub", "fye"), ("sub", "sic"), ("sub", "stprba"), ("tag", "crdr"), ("tag", "doc"), ("tag", "tlabel"), ("pre", "plabel"),
    ("pre", "stmt"),
}

N_SCHEMA = {"t": {"a": "integer", "g": "varchar", "s": "varchar", "m": "decimal(12,2)"}}
N_CATALOG = structural_catalog({("t", "g")})  # g is nullable
FIXTURES = {
    "group_nullable_key_count_sum.rs": "SELECT g, COUNT(*) AS c, SUM(m) AS sm FROM t GROUP BY g",
    "group_count_distinct.rs": "SELECT s, COUNT(DISTINCT g) AS dg, COUNT(*) AS c FROM t GROUP BY s",
}
_ENV_KEYS = ("LEMMA_ASSUMPTIONS", "LEMMA_PARALLEL_VSTD", "LEMMA_STRING_ENCODING", "LEMMA_AGENT_SCAN", "LEMMA_JOIN_CHAIN", "LEMMA_STREAM", "LEMMA_EXAMPLES")


@pytest.fixture
def stream_on(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LEMMA_STREAM", "1")
    monkeypatch.setenv("LEMMA_TEMPLATES", "1")
    monkeypatch.setenv("LEMMA_PUSHDOWN", "0")


def _emit(sql: str) -> str:
    return emit_declarative_spec(sql, N_SCHEMA, N_CATALOG)


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


def _fixture_program(name: str, *, mutate=None, column_bins: dict[str, str] | None = None) -> str:
    regions = stream.extract_regions((FIX / name).read_text())
    if mutate is not None:
        regions = mutate(dict(regions))
    return assemble_stream_program(_emit(FIXTURES[name]), regions, column_bins=column_bins)


def _trusted(spec: str) -> list[str]:
    return [re.search(r"pub fn (\w+)", spec[m.start():]).group(1) for m in re.finditer(r"#\[verifier::external_body\]", spec)]


# ---- unchanged without a nullable key or a COUNT DISTINCT -----------------------------------------------------------------------------

# sha256 of these specs and prompts emitted by the tree before this change (tests/fixtures/stream_phase2a_flag_on_golden.json, made at
# 1a415e2); phase 1's own golden is tests/fixtures/stream_phase1_flag_on_golden.json (tests/test_stream_join.py)
_TPCH_SCHEMA = json.loads((ROOT / "tests" / "fixtures" / "tpch22" / "schema.json").read_text())
_Q12 = (ROOT / "configs" / "queries" / "tpch" / "tpch_q12.sql").read_text()
_SEC_Q3 = """SELECT s.name, s.cik, SUM(n.value) AS total_value
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD' AND s.fy = 2022 AND n.value IS NOT NULL
GROUP BY s.name, s.cik
ORDER BY total_value DESC
LIMIT 100"""
_GJ = {"t": {"a": "integer", "k": "varchar", "m": "decimal(12,2)"}, "u": {"k": "varchar", "g": "varchar", "w": "integer"}}
_GOLDEN_2A = {
    "join": ("-- stream: t\nSELECT u.g, COUNT(*) AS c, SUM(t.m) AS sm FROM t JOIN u ON t.k = u.k WHERE u.k IS NOT NULL GROUP BY u.g", _GJ, {("u", "k")}),
    "join2": ("-- stream: t\nSELECT v.h, COUNT(*) AS c, SUM(t.m) AS sm FROM t JOIN u ON t.k = u.k JOIN v ON u.g = v.g GROUP BY v.h", {**_GJ, "v": {"g": "varchar", "h": "integer"}}, set()),
    "join_avg_tmpl": ("-- stream: t\nSELECT u.g, AVG(t.m) AS am, COUNT(t.a) AS ca FROM t JOIN u ON t.k = u.k WHERE t.a > 2 GROUP BY u.g HAVING COUNT(*) > 1 ORDER BY u.g LIMIT 3", _GJ, {("t", "a")}),
    "q12_orders": (stream_join.with_header(_Q12, "orders"), _TPCH_SCHEMA, None),
    "q12_lineitem": (stream_join.with_header(_Q12, "lineitem"), _TPCH_SCHEMA, None),
    "sec_q3": (stream_join.with_header(_SEC_Q3, "num"), SEC_SCHEMA, {("sub", "fy")}),
    "p1_minmax": ("SELECT s, MIN(a) AS mn, MAX(d) AS mx, SUM(a) AS sx, AVG(a) AS av, COUNT(*) AS c FROM t WHERE a > 3 GROUP BY s HAVING COUNT(*) > 1 ORDER BY s LIMIT 5",
                  {"t": {"a": "integer", "b": "bigint", "d": "date", "s": "varchar", "m": "decimal(12,2)"}}, {("t", "b")}),
}


def test_phase2a_specs_and_prompts_are_byte_identical(stream_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    from declarative_spec.stream_prompt import build_stream_prompt

    golden = json.loads((ROOT / "tests" / "fixtures" / "stream_phase2a_flag_on_golden.json").read_text())
    for name, (sql, schema, nullable) in _GOLDEN_2A.items():
        spec = emit_declarative_spec(sql, schema, None if nullable is None else structural_catalog(nullable))
        assert hashlib.sha256(spec.encode()).hexdigest() == golden[name], name
        for ex in ("none", "full"):
            monkeypatch.setenv("LEMMA_EXAMPLES", ex)
            text = build_stream_prompt(sql=sql, spec_path="s.rs", edit_path="e.rs", lemma_index="IDX", last_error="", in_docker=True, spec_text=spec, restart_note="")
            assert hashlib.sha256(text.encode()).hexdigest() == golden[f"{name}_prompt_{ex}"], (name, ex)
        monkeypatch.delenv("LEMMA_EXAMPLES")


# ---- the scorer: a NULL group key beside value keys (2026-10-27: sorting None against a str raised TypeError) --------------------------


def _hex(s: str) -> str:
    return s.encode().hex()


def test_scorer_matches_rows_with_a_null_string_key_in_any_order() -> None:
    expect = [("", 2, 10), (None, 3, 7), ("x", 1, -4)]
    got = [["NULL", "3", "7"], [_hex("x"), "1", "-4"], [_hex(""), "2", "10"]]  # another order than DuckDB's
    assert rows_match_error(got, expect, ["str", "int", "int"], None, False, None) is None
    wrong = [["NULL", "3", "7"], [_hex("x"), "1", "-4"], ["NULL", "2", "10"]]  # the empty string's group answered as NULL
    assert rows_match_error(wrong, expect, ["str", "int", "int"], None, False, None) is not None


def test_scorer_matches_rows_with_null_integer_and_float_cells() -> None:
    expect = [(None, 1.5), (3, None), (-1, 2.0), (None, None)]
    got = [["3", "NULL"], ["NULL", "NULL"], ["-1", "2.0"], ["NULL", "1.5"]]
    assert rows_match_error(got, expect, ["int", "float"], None, False, None) is None
    assert rows_match_error([["3", "NULL"], ["NULL", "NULL"], ["-1", "2.0"], ["NULL", "2.5"]], expect, ["int", "float"], None, False, None) is not None


# ---- the contract text and the gate ---------------------------------------------------------------------------------------------------


def test_a_nullable_group_key_is_a_validity_value_pair(stream_on: None) -> None:
    spec = _emit(FIXTURES["group_nullable_key_count_sum.rs"])
    assert "pub type Key = (bool, Seq<char>);" in spec
    assert "(if t.g__valid@[i0] { (true, (t.g@[i0]@)) } else { (false, Seq::<char>::empty()) })" in spec  # key_at, the batch spec's
    assert "pub g__valid: &'a [bool]," in spec  # the chunk view carries the validity
    assert _trusted(spec) == ["chunk_t", "str_ent", "stream_end_t"]
    assert "pub g: Option<String>," in spec  # the NULL group's output row


def test_count_distinct_is_a_set_field_merged_by_union(stream_on: None) -> None:
    spec = _emit(FIXTURES["group_count_distinct.rs"])
    assert "pub struct Agg {\n    pub count_c: int,\n    pub set_count_distinct_dg: Set<Seq<char>>,\n    pub hits: int,\n}" in spec
    assert "set_count_distinct_dg: a.set_count_distinct_dg.union(b.set_count_distinct_dg)," in spec
    assert "set_count_distinct_dg: stream_set_count_distinct_dg(t, lo, hi, k, p)," in spec  # agg_rng: a range fold of unions
    assert "agg_rng(t, 0, t.n as int, k, p).set_count_distinct_dg.len() == count_distinct_dg(t, 0, k)," in spec  # lemma_agg_total
    assert "set_count_distinct_dg: (if hit_dg(t, i0) && key_at(t, i0) == k {" in spec  # a NULL value is not counted (hit_dg)
    assert _trusted(spec) == ["chunk_t", "str_ent", "stream_end_t"]
    assert "assume(" not in spec and "admit(" not in spec and "arbitrary(" not in spec


def test_count_distinct_over_a_join_nests_one_set_fold_per_table(stream_on: None) -> None:
    spec = emit_declarative_spec(stream_join.with_header(_JOIN_DISTINCT, "t"), _J_SCHEMA, _J_CATALOG)
    assert stream_join.is_join(spec)
    for name in ("set_count_distinct_dw_d0", "set_count_distinct_dw_d1", "set_count_distinct_dw_d2"):
        assert f"pub open spec fn {name}(" in spec and f"pub proof fn lemma_{name}_count(" in spec, name
    assert "set_count_distinct_dw: set_count_distinct_dw_d1(t, b_u, b_v, i0, 0, k, p)," in spec  # agg_row: the row's build matches
    assert _trusted(spec) == ["chunk_t", "str_ent", "stream_end_t"]


@pytest.mark.parametrize(
    "sql, why",
    [
        ("SELECT DISTINCT g FROM t", "only COUNT\\(DISTINCT x\\)"),
        ("SELECT s, SUM(DISTINCT a) AS x FROM t GROUP BY s", "only COUNT\\(DISTINCT x\\)"),
        ("SELECT s, COUNT(DISTINCT a, g) AS x FROM t GROUP BY s", "only COUNT\\(DISTINCT x\\)"),
        ("SELECT s, AVG(DISTINCT m) AS x FROM t GROUP BY s", "only COUNT\\(DISTINCT x\\)"),
    ],
)
def test_the_gate_still_refuses_other_distincts(sql: str, why: str, stream_on: None) -> None:
    with pytest.raises(DeclarativeUnsupported, match=why):
        _emit(sql)


def test_key_guard_check() -> None:
    nullable = {"t": {"g"}}
    head = "pub open spec fn row_hit(t: &Cols_t, i0: int) -> bool {\n    &&& 0 <= i0 < t.n as int\n    &&& (true)\n}\n\n"

    def key(body: str) -> str:
        return head + f"pub open spec fn key_at(t: &Cols_t, i0: int) -> (bool, Seq<char>) {{\n    {body}\n}}\n"

    stream.check_key_guards(key("(if t.g__valid@[i0] { (true, (t.g@[i0]@)) } else { (false, Seq::<char>::empty()) })"), nullable)
    with pytest.raises(DeclarativeUnsupported, match="outside its validity guard"):
        stream.check_key_guards(key("(t.g@[i0]@)"), nullable)
    with pytest.raises(DeclarativeUnsupported, match="under the validity of"):
        stream.check_key_guards(key("(if t.g__valid@[i0] { (true, (t.g@[i0]@)) } else { (false, (t.g@[i0]@)) })"), nullable)
    with pytest.raises(DeclarativeUnsupported, match="not a nullable column"):
        stream.check_key_guards(key("(if t.s__valid@[i0] { (true, (t.s@[i0]@)) } else { (false, Seq::<char>::empty()) })"), nullable)
    # `WHERE g IS NOT NULL`: the emitter reads the value unguarded and row_hit tests the bit
    filtered = head.replace("&&& (true)", "&&& (t.g__valid@[i0])")
    stream.check_key_guards(filtered + "pub open spec fn key_at(t: &Cols_t, i0: int) -> Seq<char> {\n    (t.g@[i0]@)\n}\n", nullable)


def test_admission_accepts_the_fixtures(stream_on: None) -> None:
    for name, sql in FIXTURES.items():
        res = admit_stream(**stream.extract_regions((FIX / name).read_text()), spec_rs=_emit(sql))
        assert res.ok, (name, res.violations)


# ---- the prompt ------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("examples", ["full", "none"])
def test_prompt_notes_for_null_keys_and_distinct(examples: str, stream_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.stream_prompt import build_stream_prompt

    monkeypatch.setenv("LEMMA_EXAMPLES", examples)

    def prompt(sql: str) -> str:
        return build_stream_prompt(sql=sql, spec_path="s.rs", edit_path="e.rs", lemma_index="IDX", last_error="", in_docker=True, spec_text=_emit(sql), restart_note="")

    null = prompt(FIXTURES["group_nullable_key_count_sum.rs"])
    assert "ONE group of their" in null and "`(true, v)`" in null and "COUNT(DISTINCT x)` is a SET field" not in null
    dist = prompt(FIXTURES["group_count_distinct.rs"])
    assert "`COUNT(DISTINCT x)` is a SET field of `Agg` (`set_count_distinct_dg: Set<Seq<char>>`)" in dist and "the UNION" in dist
    assert "ONE group of their" not in dist
    assert ("## COUNT DISTINCT fast" in dist) == (examples == "full")  # technique advice is a RECIPE
    plain = prompt("SELECT s, COUNT(*) AS c FROM t GROUP BY s")
    assert "## NULL group keys and COUNT DISTINCT" not in plain and "## COUNT DISTINCT fast" not in plain


# ---- Verus: host scaffold with a stub agent --------------------------------------------------------------------------------------------

_J_SCHEMA = {"t": {"a": "integer", "k": "varchar", "m": "decimal(12,2)"}, "u": {"k": "varchar", "g": "varchar", "w": "integer"}, "v": {"w": "integer", "h": "varchar"}}
_J_CATALOG = structural_catalog({("u", "g"), ("v", "h")})
_JOIN_NULL_KEY = "SELECT u.g, COUNT(*) AS c, SUM(t.m) AS sm FROM t JOIN u ON t.k = u.k GROUP BY u.g"
_JOIN_DISTINCT = "SELECT u.g, COUNT(DISTINCT v.h) AS dw, SUM(t.m) AS sm FROM t JOIN u ON t.k = u.k JOIN v ON u.w = v.w GROUP BY u.g"
# SEC q6 / q4 verbatim (configs/queries/sec_edgar/); the stream_join rule on sec_edgar_dec.duckdb streams num in both (rows after each
# table's own filters, 2026-10-27: q6 num 33,234,006, pre 1,767,049, sub 26,612; q4 num 33,234,006, tag 1,070,662, pre 1,242,132,
# sub 5,242).
_SEC = {name: "\n".join(ln for ln in (ROOT / "configs" / "queries" / "sec_edgar" / f"{name}.sql").read_text().splitlines() if not ln.startswith("--")) for name in ("q6", "q4")}


@pytest.mark.parametrize(
    "case",
    ["one_table_null_key", "one_table_distinct", "join_null_build_key", "join_distinct_two_builds", "sec_q6_stream_num", "sec_q4_stream_num"],
)
def test_host_scaffold_verifies_with_a_stub_agent(case: str, stream_on: None, tmp_path: Path) -> None:
    """AGENTS.md "Host scaffold": every host item (the set folds and their lemmas, agg lemmas, chunk view, runtime) is proved with a stub
    agent: `N verified, 0 errors`."""
    _needs_verus()
    spec = {
        "one_table_null_key": lambda: _emit(FIXTURES["group_nullable_key_count_sum.rs"]),
        "one_table_distinct": lambda: _emit("SELECT g, COUNT(DISTINCT s) AS ds, COUNT(DISTINCT a) AS da, SUM(m) AS sm FROM t WHERE a > 3 GROUP BY g"),
        "join_null_build_key": lambda: emit_declarative_spec(stream_join.with_header(_JOIN_NULL_KEY, "t"), _J_SCHEMA, _J_CATALOG),
        "join_distinct_two_builds": lambda: emit_declarative_spec(stream_join.with_header(_JOIN_DISTINCT, "t"), _J_SCHEMA, _J_CATALOG),
        "sec_q6_stream_num": lambda: emit_declarative_spec(stream_join.with_header(_SEC["q6"], "num"), SEC_SCHEMA, structural_catalog(SEC_NULLABLE)),
        "sec_q4_stream_num": lambda: emit_declarative_spec(stream_join.with_header(_SEC["q4"], "num"), SEC_SCHEMA, structural_catalog(SEC_NULLABLE)),
    }[case]()
    if case.startswith("sec_q"):
        assert re.search(r"pub type Key = [^;]*\(bool, Seq<char>\)", spec), "the SEC key is nullable"
    regions = stream_join.stub(spec) if stream_join.is_join(spec) else stream.STUB
    out = _verus(assemble_stream_program(spec, regions), tmp_path, f"stub_{case}")
    assert _verified(out), out[-4000:]


# ---- Verus: the fixtures and their mutants ------------------------------------------------------------------------------------------


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
    # a NULL key row is skipped: the NULL group loses its rows
    ("group_nullable_key_count_sum.rs", "nulls_dropped"): _sub("step", "            if !add_null(s, 1, m as i128) {\n                return false;\n            }\n", ""),
    # a NULL key row goes to its (empty-string) entry's value group
    ("group_nullable_key_count_sum.rs", "null_merged_into_a_value_group"): _sub("step", "        if c.g__valid[r] {\n", "        if true {\n"),
    # the NULL group has no output row
    ("group_nullable_key_count_sum.rs", "null_group_not_output"): _sub("finish", "    if s.ncnt > 0 {\n", "    if false {\n"),
    # q_merge forgets b's NULL group
    ("group_nullable_key_count_sum.rs", "merge_drops_null_group"): _sub("merge", "    if !add_null(&mut m, b.ncnt, b.nsum) {\n        return None;\n    }\n", ""),
    # the distinct count counts the group's rows (duplicates included)
    ("group_count_distinct.rs", "distinct_counted_with_duplicates"): _sub("finish", "let dg = s.sets[j].len() as u64;", "let dg = s.cnt[j];"),
    # a NULL value is counted as a value (its empty-string entry)
    ("group_count_distinct.rs", "null_value_counted"): _sub("step", "        if c.g__valid[r] {\n", "        if true {\n"),
    # q_merge keeps b's counts but not b's values
    ("group_count_distinct.rs", "merge_drops_b_values"): _sub("merge", "            add_val(&mut m, jm, b.lists[j][i].as_str());\n", ""),
}


@pytest.mark.parametrize("case", sorted(MUTANTS), ids=lambda c: f"{c[0].removesuffix('.rs')}:{c[1]}")
def test_fixture_mutants_do_not_verify(case: tuple[str, str], stream_on: None, tmp_path: Path) -> None:
    _needs_verus()
    out = _verus(_fixture_program(case[0], mutate=MUTANTS[case]), tmp_path, case[1])
    assert _fails(out), out[-3000:]


# ---- differential: the compiled fixtures (binary-mode main) against DuckDB --------------------------------------------------------------


def _random_table(con: duckdb.DuckDBPyConnection, rng: random.Random, n: int, keys: int, null_rate: float) -> None:
    con.execute("CREATE OR REPLACE TABLE t (a INTEGER NOT NULL, g VARCHAR, s VARCHAR NOT NULL, m DECIMAL(12,2) NOT NULL)")
    # the empty string is a value distinct from NULL; long and non-ASCII strings; few distinct values (many duplicates)
    vals = ["", "x", "a string longer than twelve", "ünïcödé", *(f"v{i}" for i in range(keys))]
    rows = [
        (rng.randint(-5, 5), None if rng.random() < null_rate else rng.choice(vals), rng.choice(vals[: 2 + keys]), rng.randint(-(10**11), 10**11) / 100)
        for _ in range(n)
    ]
    if rows:
        con.executemany("INSERT INTO t VALUES (?, ?, ?, CAST(? AS DECIMAL(12,2)))", rows)


@pytest.fixture(scope="module")
def binaries(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[Path, Path]]:
    _needs_verus()
    tmp = tmp_path_factory.mktemp("stream_null_distinct_bin")
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
@pytest.mark.parametrize(
    "seed, n, keys, null_rate",
    [(1, 0, 3, 0.3), (2, 1, 1, 1.0), (3, 40, 2, 0.5), (4, 3000, 6, 0.2), (5, 500, 0, 1.0), (6, 2500, 40, 0.05)],
    ids=["empty", "one_null_row", "few_keys", "large", "all_null", "many_keys"],
)
def test_differential_against_duckdb(name: str, seed: int, n: int, keys: int, null_rate: float, stream_on: None, binaries, tmp_path: Path) -> None:
    from research_loop.decl_query_measure import write_query_measure

    binary, cols = binaries[name]
    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    _random_table(con, random.Random(seed), n, keys, null_rate)
    con.close()
    prep = write_query_measure(sql=FIXTURES[name], schema=N_SCHEMA, catalog=N_CATALOG, db_path=db, dest=tmp_path / "prep")
    cols.write_bytes(Path(prep["bins"]["t"]).read_bytes())
    for chunk_max in (1, 7, 2048):
        for threads in (1, 3, 8):
            proc = subprocess.run([str(binary), str(chunk_max), str(threads), str(seed)], capture_output=True, text=True, timeout=120, check=False)
            assert proc.returncode == 0, (chunk_max, threads, proc.stdout[-1000:], proc.stderr[-2000:])
            err = rows_match_error(rows_from_stdout_general(proc.stdout), prep["rows"], prep["kinds"], prep.get("order_cols"), bool(prep.get("limited")), prep.get("tie_rows"))
            assert err is None, (chunk_max, threads, err, proc.stdout[-2000:], prep["rows"])
