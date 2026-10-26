"""Streaming executors, spec side of phase 1 (lemma.toml [run] stream, docs/STREAM.md, declarative_spec/stream.py).

Flag off: every spec byte-identical (sha256 of the TPC-H 22 and the 4 TPC-H templates, run defaults and test defaults, emitted by the
tree before the flag: tests/fixtures/stream_flag_off_golden.json). Flag on: the contract text (S1/S2 the only external_body items,
each marked TRUSTED with the authorization), the gate's refusals, Verus on the generic library, the host scaffold with a stub agent
(TPC-H Q1 and Q6 templates: AGENTS.md "Host scaffold"), the dev fixtures and their mutants (and mutants of the host runtime), the
admission of the agent regions, and differential runs of the compiled fixtures (binary-mode main: random chunk sizes, several
threads) against DuckDB on small random tables with NULLs, DECIMAL, DATE and strings.
"""

from __future__ import annotations

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
from declarative_spec import stream
from declarative_spec.admit import admit_stream
from declarative_spec.assemble import assemble_declarative_program, assemble_stream_program
from declarative_spec.bench import rows_from_stdout_general, rows_match_error
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from research_loop.structural_catalog import structural_catalog

ROOT = Path(__file__).resolve().parents[1]
TPCH = ROOT / "tests" / "fixtures" / "tpch22"
TPCH_SCHEMA = json.loads((TPCH / "schema.json").read_text())
TEMPLATES = ROOT / "configs" / "query_templates" / "tpch"
FIX = ROOT / "tests" / "fixtures" / "declarative_proofs" / "stream"
GOLDEN = json.loads((ROOT / "tests" / "fixtures" / "stream_flag_off_golden.json").read_text())
GUARD = ROOT / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")

T_SCHEMA = {"t": {"a": "integer", "b": "bigint", "d": "date", "s": "varchar", "m": "decimal(12,2)"}}
T_CATALOG = structural_catalog({("t", "b")})  # b is nullable
FIXTURES = {
    "ungrouped_sum_filter.rs": "SELECT SUM(b) AS sb FROM t WHERE a > 3 AND d < DATE '2000-01-01'",
    "group_string_count_sum.rs": "SELECT s, COUNT(*) AS c, SUM(m) AS sm FROM t GROUP BY s",
}
_ENV_KEYS = ("LEMMA_ASSUMPTIONS", "LEMMA_PARALLEL_VSTD", "LEMMA_STRING_ENCODING", "LEMMA_AGENT_SCAN", "LEMMA_JOIN_CHAIN", "LEMMA_STREAM")
_GOLDEN_MODES = {
    "run_defaults": {"LEMMA_TEMPLATES": "1"},
    "test_defaults": {"LEMMA_TEMPLATES": "1", "LEMMA_PARALLEL_VSTD": "off", "LEMMA_STRING_ENCODING": "plain", "LEMMA_AGENT_SCAN": "0"},
}


def _set_env(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def stream_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The run defaults (assumptions = false, dict strings, agent scans, parallel auto) with the stream flag and templates on."""
    _set_env(monkeypatch, {"LEMMA_STREAM": "1", "LEMMA_TEMPLATES": "1", "LEMMA_PUSHDOWN": "0"})


def _emit_t(sql: str) -> str:
    return emit_declarative_spec(sql, T_SCHEMA, T_CATALOG)


def _template(name: str) -> str:
    return (TEMPLATES / f"{name}.sql").read_text()


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
    """A proof failure (Verus ran and reported errors), not a compile error of the mutated text."""
    return re.search(r"verification results:: \d+ verified, [1-9]\d* errors", out) is not None


def _needs_verus() -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")


def _fixture_program(name: str, *, mutate=None, column_bins: dict[str, str] | None = None) -> str:
    regions = stream.extract_regions((FIX / name).read_text())
    if mutate is not None:
        regions = mutate(dict(regions))
    return assemble_stream_program(_emit_t(FIXTURES[name]), regions, column_bins=column_bins)


# ---- flag off: byte-identical ---------------------------------------------------------------------------------------------------


def test_flag_is_in_lemma_toml_off_by_default_and_documented(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_STREAM", raising=False)
    assert lemma_config.default("stream") is False
    assert lemma_config.schema()["stream"][0] == "run"
    assert stream.enabled() is False
    flags = (ROOT / "docs" / "FLAGS.md").read_text()
    assert "`stream`" in flags and "stream_flag_off_golden.json" in flags


@pytest.mark.parametrize("mode", sorted(_GOLDEN_MODES))
def test_flag_off_emits_byte_identical_specs(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, _GOLDEN_MODES[mode])
    sqls = {f"tpch_{p.stem}": p.read_text() for p in sorted(TPCH.glob("q*.sql"))}
    sqls |= {f"tmpl_{p.stem}": p.read_text() for p in sorted(TEMPLATES.glob("q*.sql"))}
    want = GOLDEN[mode]
    assert sorted(sqls) == sorted(want)
    for name, sql in sqls.items():
        try:
            text = emit_declarative_spec(sql.strip(), TPCH_SCHEMA, None)
        except Exception as exc:  # noqa: BLE001 - the refusal text is part of what must not change
            text = f"REFUSED {type(exc).__name__}: {exc}"
        assert hashlib.sha256(text.encode()).hexdigest() == want[name], name


# ---- flag on: the contract text and the gate --------------------------------------------------------------------------------------


def test_q6_contract_has_s1_s2_as_the_only_trusted_items(stream_on: None) -> None:
    spec = emit_declarative_spec(_template("q06"), TPCH_SCHEMA, None)
    assert stream.is_stream(spec)
    assert "pub fn run_query(" not in spec and "AGENT_EDIT_START" not in spec
    bodies = [m.start() for m in re.finditer(r"#\[verifier::external_body\]", spec)]
    names = [re.search(r"pub fn (\w+)", spec[i:]).group(1) for i in bodies]
    assert names == ["chunk_lineitem", "str_ent", "stream_end_lineitem"]
    for i in bodies:
        before = spec[:i].rsplit("\n\n", 1)[1]
        assert "// TRUSTED S" in before and "authorized by Emil 2026-10-25" in before, before
    assert spec.count("TRUSTED S1") == 2 and spec.count("TRUSTED S2") == 1
    assert "assume(" not in spec and "admit(" not in spec and "arbitrary(" not in spec
    # `external` (no spec at all, invisible to Verus) only for the three helpers of S1's body
    assert re.findall(r"#\[verifier::external\]\nfn (\w+)", spec) == ["lemma_stream_slice", "lemma_stream_str_bytes", "lemma_stream_strings_ok"]
    for mark in ("AGENT_STATE_START", "AGENT_HELPERS_START", *(m for pair in stream.BODY_REGIONS.values() for m in pair)):
        assert spec.count(mark) == 1, mark
    assert "pub struct Params {\n    pub ship_lo: i32,\n    pub ship_hi: i32,\n    pub disc_lo: i64,\n    pub disc_hi: i64,\n    pub quantity: i64,\n}" in spec
    assert "pub type Key = ();" in spec
    assert "pub struct Agg {\n    pub sum_revenue: int,\n    pub hits: int,\n}" in spec
    assert "pub uninterp spec fn stream_table_lineitem(id: u64) -> Cols_lineitem;" in spec
    assert "res matches Some(r) ==> run_query_ok(&t@, p.ship_lo, p.ship_hi, p.disc_lo, p.disc_hi, p.quantity, r)," in spec
    assert "r matches StreamOut::Rows(res) ==> run_query_ok(&stream_table_lineitem(e.sid()), e.params().ship_lo," in spec
    assert "#[verifier::type_invariant]" in spec


def test_q1_contract_is_grouped_with_rational_avg_fields(stream_on: None) -> None:
    spec = emit_declarative_spec(_template("q01"), TPCH_SCHEMA, None)
    assert "pub type Key = (Seq<char>, Seq<char>);" in spec
    agg = re.search(r"pub struct Agg \{\n(.*?)\n\}", spec, re.S).group(1)
    assert [line.split(":")[0].strip().removeprefix("pub ") for line in agg.splitlines()] == [
        "sum_sum_qty", "sum_sum_base_price", "sum_sum_disc_price", "sum_sum_charge", "avg_avg_qty_sum", "avg_avg_qty_count",
        "avg_avg_price_sum", "avg_avg_price_count", "avg_avg_disc_sum", "avg_avg_disc_count", "count_count_order", "hits",
    ]
    assert "pub l_returnflag: StrCol<'a>," in spec and "pub l_shipdate: &'a [i32]," in spec


def test_min_max_and_nullable_fields(stream_on: None) -> None:
    spec = _emit_t("SELECT MIN(b) AS mn, MAX(d) AS mx, COUNT(b) AS cb, COUNT(*) AS c FROM t WHERE a > 0")
    agg = re.search(r"pub struct Agg \{\n(.*?)\n\}", spec, re.S).group(1)
    assert "pub min_mn: Option<int>," in agg and "pub max_mx: Option<int>," in agg
    assert "min_mn: omin(a.min_mn, b.min_mn)" in spec and "max_mx: omax(a.max_mx, b.max_mx)" in spec
    # a NULL cell's value is promised only where it is valid; its validity always
    assert "forall|r: int| #![trigger c.b@[r]] 0 <= r < c.len && t.b__valid@[c.off + r] ==> c.b@[r] == t.b@[c.off + r]" in spec
    assert "forall|r: int| #![trigger c.b__valid@[r]] 0 <= r < c.len ==> c.b__valid@[r] == t.b__valid@[c.off + r]" in spec


def test_stream_strings_are_plain_even_with_dict_default(stream_on: None) -> None:
    assert lemma_config.get("string_encoding") == "dict"
    spec = _emit_t("SELECT s, COUNT(*) AS c FROM t GROUP BY s")
    assert "__dict" not in spec and "pub s: Vec<String>," in spec


@pytest.mark.parametrize(
    "sql, why",
    [
        ("SELECT s, a FROM t WHERE a > 3", "not a recognized fold|not an aggregate"),
        ("SELECT COUNT(DISTINCT a) AS c FROM t", "DISTINCT"),
        ("SELECT t.s, COUNT(*) AS c FROM t JOIN t AS u ON t.a = u.a GROUP BY t.s", "one table"),
        ("SELECT COUNT(*) AS c FROM t WHERE rowid < 5", "rowid"),
        ("SELECT first(a) AS f FROM t", "order-dependent"),
    ],
)
def test_the_gate_refuses_loudly(sql: str, why: str, stream_on: None) -> None:
    with pytest.raises((DeclarativeUnsupported, ValueError), match=why):
        _emit_t(sql)


def test_the_gate_refuses_a_nullable_group_key(stream_on: None) -> None:
    with pytest.raises(DeclarativeUnsupported, match="nullable"):
        _emit_t("SELECT b, COUNT(*) AS c FROM t GROUP BY b")


@pytest.mark.parametrize("setting, value, why", [("LEMMA_ASSUMPTIONS", "1", "assumptions"), ("LEMMA_STATEFUL", "1", "stateful")])
def test_settings_the_stream_does_not_compose_with_are_refused(setting: str, value: str, why: str, stream_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(setting, value)
    with pytest.raises(DeclarativeUnsupported, match=why):
        emit_declarative_spec(_template("q06"), TPCH_SCHEMA, None)


def test_in_duckdb_composes_with_the_stream_and_emits_the_same_spec(stream_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """in_duckdb only allows library mode; the ABI 6 template (assemble_library.assemble_stream_library_program) takes the same spec."""
    spec = emit_declarative_spec(_template("q06"), TPCH_SCHEMA, None)
    monkeypatch.setenv("LEMMA_IN_DUCKDB", "1")
    assert emit_declarative_spec(_template("q06"), TPCH_SCHEMA, None) == spec


def test_run_query_assembler_refuses_a_stream_spec(stream_on: None) -> None:
    with pytest.raises(ValueError, match="assemble_stream_program"):
        assemble_declarative_program(_emit_t(FIXTURES["ungrouped_sum_filter.rs"]), "None")


# ---- admission ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_admission_accepts_the_fixtures(name: str, stream_on: None) -> None:
    regions = stream.extract_regions((FIX / name).read_text())
    res = admit_stream(**regions, spec_rs=_emit_t(FIXTURES[name]))
    assert res.ok, res.violations


@pytest.mark.parametrize(
    "region, text, why",
    [
        ("step", "    assume(false);\n    true", "assume"),
        ("step", "    proof { admit(); }\n    true", "admit"),
        ("helpers", "#[verifier::external_body]\npub fn cheat() -> (r: bool) ensures r { true }", "external"),
        ("finish", "    let e = exec_new(Stream_t { id: 0, raw: 0 }, *p);\n    None", "stream internals"),
        ("step", "    let r = RawChunk_t { j: 0, off: 0, len: 0, a: 0 };\n    true", "stream internals"),
        ("step", "    let c2 = chunk_t(&Stream_t { id: c.sid, raw: 0 }, &x);\n    true", "stream internals"),
        ("step", "    let e = stream_end_t(&sh);\n    true", "stream internals"),
        ("step", "    let x = c.s.raw[0].w0;\n    true", "stream internals"),
        ("helpers", "pub open spec fn qacc_inv(s: &QAcc) -> bool { true }\npub open spec fn st_val(s: &QAcc, k: Key) -> Agg { agg_zero() }\npub fn f(c: &Chunk_t) -> Chunk_t { Chunk_t { sid: 0, off: 0, len: 0, a: c.a, s: c.s } }", "stream internals"),
        ("state", "pub struct QAcc<'a> {\n    pub r: &'a [i32],\n}", "no references"),
        ("state", "pub struct Other {\n    pub z: u8,\n}", "QAcc"),
        ("helpers", "pub open spec fn st_val(s: &QAcc, k: Key) -> Agg { agg_zero() }", "qacc_inv"),
        ("helpers", "pub open spec fn qacc_inv(s: &QAcc) -> bool { true }", "st_val"),
        ("merge", "    unsafe { None }", "host access"),
        ("helpers", "pub open spec fn qacc_inv(s: &QAcc) -> bool { true }\npub open spec fn st_val(s: &QAcc, k: Key) -> Agg { agg_zero() }\npub open spec fn agg_row(x: int) -> int { 0 }", "host name"),
    ],
)
def test_admission_rejects(region: str, text: str, why: str, stream_on: None) -> None:
    regions = stream.extract_regions((FIX / "group_string_count_sum.rs").read_text())
    regions[region] = text
    res = admit_stream(**regions, spec_rs=_emit_t(FIXTURES["group_string_count_sum.rs"]))
    assert not res.ok
    assert any(why in v for v in res.violations), res.violations


# ---- S1's checked part: the selection range and UTF-8 check, compiled alone with rustc ---------------------------------------------

_S1_CHECK_MAIN = r"""
fn inline(s: &[u8]) -> StrRaw {
    let mut b = [0u8; 16];
    b[..4].copy_from_slice(&(s.len() as u32).to_le_bytes());
    b[4..4 + s.len()].copy_from_slice(s);
    StrRaw { w0: u64::from_le_bytes(b[..8].try_into().unwrap()), w1: u64::from_le_bytes(b[8..].try_into().unwrap()) }
}
fn long(s: &'static [u8]) -> StrRaw {
    let mut b = [0u8; 8];
    b[..4].copy_from_slice(&(s.len() as u32).to_le_bytes());
    b[4..].copy_from_slice(&s[..4]);
    StrRaw { w0: u64::from_le_bytes(b), w1: s.as_ptr() as u64 }
}
fn main() {
    let ents = || vec![inline(b"A"), inline(b""), long("a string longer than twelve".as_bytes()), inline("ünï".as_bytes())];
    let mut sel: Vec<u32> = (0..2048).map(|r| (r * 7 % 4) as u32).collect();
    let mut out = Vec::new();
    out.push(lemma_stream_strings_ok(&[], &[]));                  // empty chunk
    out.push(lemma_stream_strings_ok(&sel, &ents()));                // every index < 4
    sel[2047] = 4;
    out.push(lemma_stream_strings_ok(&sel, &ents()));                // the last row's index == nents
    sel[2047] = 0;
    sel[0] = u32::MAX;
    out.push(lemma_stream_strings_ok(&sel, &ents()));                // the first row's index far out of range
    sel[0] = 3;
    out.push(lemma_stream_strings_ok(&sel, &ents()[..3]));           // index 3 of 3 entries
    out.push(lemma_stream_strings_ok(&[0], &[]));                  // an index into no entries
    let mut e = ents();
    e[3] = inline(&[0x41, 0xff]);
    out.push(lemma_stream_strings_ok(&sel, &e));  // an entry not UTF-8 (inline)
    static BAD: [u8; 14] = [0x61; 14];
    let mut bad_long = BAD;
    bad_long[13] = 0xc3;                                          // a truncated 2-byte sequence at the end
    let bad: &'static [u8] = Box::leak(Box::new(bad_long));
    let mut e = ents();
    e[2] = long(bad);
    out.push(lemma_stream_strings_ok(&sel, &e));  // a long entry not UTF-8
    println!("{:?}", out);
}
"""


def test_s1_selection_and_utf8_check(stream_on: None, tmp_path: Path) -> None:
    """S1's body refuses a chunk (None) unless every selection index is in range and every entry is UTF-8: no out-of-range index
    reaches `ents@[sel@[r]]` and no non-UTF-8 byte reaches a `&str` (str_ent) or a proof claim about `Seq<char>`. The check (a
    branch-free maximum over the selection since 2026-10-26) is extracted from the emitted spec and run on edge cases."""
    spec = emit_declarative_spec(_template("q01"), TPCH_SCHEMA, None)
    items = []
    for name in ("pub struct StrRaw", "fn lemma_stream_str_bytes", "fn lemma_stream_strings_ok"):
        start = spec.index(name)
        start = spec.rindex("\n", 0, spec.rindex("#[", 0, start) if name.startswith("fn") else start) + 1
        items.append(spec[start : spec.index("\n}\n", start) + 3].replace("#[verifier::external]\n", ""))
    src = tmp_path / "s1_check.rs"
    src.write_text("#![allow(dead_code)]\n" + "\n".join(items) + _S1_CHECK_MAIN)
    subprocess.run(["rustc", "-O", "--edition", "2021", "-o", str(tmp_path / "s1_check"), str(src)], check=True, capture_output=True)
    out = subprocess.run([str(tmp_path / "s1_check")], check=True, capture_output=True, text=True).stdout.strip()
    assert out == "[true, true, false, false, false, false, false, false]", out


# ---- Verus: library, host scaffold, fixtures, mutants -----------------------------------------------------------------------------


def test_stream_lib_verifies(tmp_path: Path) -> None:
    _needs_verus()
    out = _verus((ROOT / "research_loop" / "verus_lib" / "stream_lib.rs").read_text(), tmp_path, "stream_lib")
    assert _verified(out), out[-3000:]
    assert "external_body" not in stream.lib_slice() and "assume" not in stream.lib_slice()


@pytest.mark.parametrize("name", ["q01", "q06"])
def test_host_scaffold_verifies_with_a_stub_agent(name: str, stream_on: None, tmp_path: Path) -> None:
    """AGENTS.md "Host scaffold": every host item (agg lemmas, chunk view, runtime) is proved with q_step false, q_merge None, q_finish None."""
    _needs_verus()
    spec = emit_declarative_spec(_template(name), TPCH_SCHEMA, None)
    out = _verus(assemble_stream_program(spec, stream.STUB), tmp_path, f"stub_{name}")
    assert _verified(out), out[-4000:]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT MIN(b) AS mn, MAX(d) AS mx, SUM(b) AS sb, AVG(b) AS ab, COUNT(*) AS c, COUNT(b) AS cb FROM t WHERE d < DATE '2000-01-01' AND s <> 'zz'",
        "SELECT s, MIN(a) AS mn, MAX(d) AS mx, SUM(a) AS sx, AVG(a) AS av, COUNT(*) AS c FROM t WHERE a > 3 GROUP BY s HAVING COUNT(*) > 1 ORDER BY s LIMIT 5",
    ],
    ids=["ungrouped_minmax_nullable", "grouped_minmax_having_order_limit"],
)
def test_host_scaffold_verifies_for_min_max_nulls_and_finish_clauses(sql: str, stream_on: None, tmp_path: Path) -> None:
    _needs_verus()
    out = _verus(assemble_stream_program(_emit_t(sql), stream.STUB), tmp_path, "stub_t")
    assert _verified(out), out[-4000:]


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_fixture_verifies(name: str, stream_on: None, tmp_path: Path) -> None:
    _needs_verus()
    out = _verus(_fixture_program(name), tmp_path, name.removesuffix(".rs"))
    assert _verified(out), out[-4000:]


def _sub(region: str, old: str, new: str):
    def mutate(regions: dict[str, str]) -> dict[str, str]:
        assert old in regions[region], (region, old)
        regions[region] = regions[region].replace(old, new, 1)
        return regions

    return mutate


FIXTURE_MUTANTS = {
    "skip_first_row": ("ungrouped_sum_filter.rs", _sub("step", "let mut r: usize = 0;", "let mut r: usize = 1;")),
    "skip_last_row": ("group_string_count_sum.rs", _sub("step", "while r < c.len\n", "while r + 1 < c.len\n")),
    "wrong_offset": ("ungrouped_sum_filter.rs", _sub("step", "let a = c.a[r];", "let a = if r + 1 < c.len { c.a[r + 1] } else { c.a[r] };")),
    "merge_drops_b": ("ungrouped_sum_filter.rs", _sub("merge", "Some(QAcc { sum, hits, nb })", "Some(a)")),
    "merge_drops_b_grouped": ("group_string_count_sum.rs", _sub("merge", "while j < b.keys.len()", "while j < b.keys.len() && false")),
}


@pytest.mark.parametrize("mutant", sorted(FIXTURE_MUTANTS))
def test_fixture_mutants_do_not_verify(mutant: str, stream_on: None, tmp_path: Path) -> None:
    _needs_verus()
    name, mutate = FIXTURE_MUTANTS[mutant]
    out = _verus(_fixture_program(name, mutate=mutate), tmp_path, mutant)
    assert _fails(out), out[-3000:]


RUNTIME_MUTANTS = {
    "segment_records_wrong_offset": ("let s = Seg { j: raw.j as usize, off: c.off, len: c.len };", "let s = Seg { j: raw.j as usize, off: c.off + 1, len: c.len };"),
    "no_contiguity_check": ("if !filled[j] || soff[j] != o || slen[j] > n - o {", "if !filled[j] || slen[j] > n - o {"),
    "no_end_check": ("    if o != n {\n        return StreamOut::Error;\n    }\n", ""),
    "no_doubled_chunk_check": ("if s.j >= m || filled[s.j] {", "if s.j >= m {"),
    "no_count_check": ("    if segs.len() != m {\n        return StreamOut::Error;\n    }\n", ""),
    "merge_drops_segments": ("segs.append(&mut segs_b);", "segs_b.clear();"),
}


@pytest.mark.parametrize("mutant", sorted(RUNTIME_MUTANTS))
def test_runtime_mutants_do_not_verify(mutant: str, stream_on: None, tmp_path: Path) -> None:
    """The scheduling glue is not trusted: a runtime that could answer from a lost, doubled or misplaced chunk does not verify."""
    _needs_verus()
    old, new = RUNTIME_MUTANTS[mutant]
    program = _fixture_program("ungrouped_sum_filter.rs")
    assert program.count(old) == 1, mutant
    out = _verus(program.replace(old, new), tmp_path, mutant)
    assert _fails(out), out[-3000:]


# ---- differential: the compiled fixtures (binary-mode main) against DuckDB ------------------------------------------------------


def _random_table(con: duckdb.DuckDBPyConnection, rng: random.Random, n: int) -> None:
    con.execute("CREATE OR REPLACE TABLE t (a INTEGER NOT NULL, b BIGINT, d DATE NOT NULL, s VARCHAR NOT NULL, m DECIMAL(12,2) NOT NULL)")
    keys = ["", "x", "short", "a string longer than twelve", "ünïcödé", "A", "x" * 40]
    rows = []
    for _ in range(n):
        b = None if rng.random() < 0.25 else rng.randint(-(10**15), 10**15)
        rows.append((rng.randint(-5, 20), b, rng.randint(9000, 11500), rng.choice(keys), rng.randint(-(10**11), 10**11) / 100))
    if rows:
        con.executemany("INSERT INTO t VALUES (?, ?, DATE '1970-01-01' + CAST(? AS INTEGER), ?, CAST(? AS DECIMAL(12,2)))", rows)


def _prepare(sql: str, db: Path, dest: Path) -> dict:
    from research_loop.decl_query_measure import write_query_measure

    return write_query_measure(sql=sql, schema=T_SCHEMA, catalog=T_CATALOG, db_path=db, dest=dest)


@pytest.fixture(scope="module")
def stream_binaries(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[Path, Path]]:
    """Each fixture compiled once, reading its column file from a fixed path (each test copies its export there)."""
    _needs_verus()
    tmp = tmp_path_factory.mktemp("stream_bin")
    mp = pytest.MonkeyPatch()
    for key in _ENV_KEYS:
        mp.delenv(key, raising=False)
    mp.setenv("LEMMA_STREAM", "1")
    mp.setenv("LEMMA_PUSHDOWN", "0")
    out: dict[str, tuple[Path, Path]] = {}
    try:
        for name in FIXTURES:
            cols = tmp / f"{name}.cols.bin"
            program = _fixture_program(name, column_bins={"t": str(cols)})
            stem = name.removesuffix(".rs")
            log = _verus(program, tmp, stem, "--compile", "--", "-C", "opt-level=3")
            assert _verified(log), log[-3000:]
            assert (tmp / stem).is_file(), log[-2000:]
            out[name] = (tmp / stem, cols)
    finally:
        mp.undo()
    return out


@pytest.mark.parametrize("name", sorted(FIXTURES))
@pytest.mark.parametrize("seed, n", [(1, 0), (2, 1), (3, 37), (4, 3000)])
def test_differential_against_duckdb(name: str, seed: int, n: int, stream_on: None, stream_binaries, tmp_path: Path) -> None:
    binary, cols = stream_binaries[name]
    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    _random_table(con, random.Random(seed), n)
    con.close()
    prep = _prepare(FIXTURES[name], db, tmp_path / "prep")
    cols.write_bytes(Path(prep["bins"]["t"]).read_bytes())
    for chunk_max in (1, 7, 2048):
        for threads in (1, 3, 8):
            proc = subprocess.run([str(binary), str(chunk_max), str(threads), str(seed)], capture_output=True, text=True, timeout=120, check=False)
            assert proc.returncode == 0, (chunk_max, threads, proc.stdout[-1000:], proc.stderr[-2000:])
            assert f"STREAM_THREADS: {threads}" in proc.stdout
            chunks = int(re.search(r"STREAM_CHUNKS: (\d+)", proc.stdout).group(1))
            assert (chunks == n) if chunk_max == 1 else (chunks <= n)
            err = rows_match_error(rows_from_stdout_general(proc.stdout), prep["rows"], prep["kinds"], prep.get("order_cols"), bool(prep.get("limited")), prep.get("tie_rows"))
            assert err is None, (chunk_max, threads, err, proc.stdout[-2000:], prep["rows"])


def test_declined_sum_overflow_is_a_decline_not_a_wrong_answer(stream_on: None, stream_binaries, tmp_path: Path) -> None:
    """An agent step that declines (q_step false) on a non-empty table: the main prints LEMMA_DECLINED, exits 3, prints no row."""
    _needs_verus()
    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    _random_table(con, random.Random(9), 50)
    con.close()
    prep = _prepare(FIXTURES["ungrouped_sum_filter.rs"], db, tmp_path / "prep")
    regions = dict(stream.extract_regions((FIX / "ungrouped_sum_filter.rs").read_text()))
    regions["step"] = "    false"
    program = assemble_stream_program(_emit_t(FIXTURES["ungrouped_sum_filter.rs"]), regions, column_bins={"t": prep["bins"]["t"]})
    log = _verus(program, tmp_path, "declines", "--compile")
    assert _verified(log), log[-3000:]
    proc = subprocess.run([str(tmp_path / "declines"), "7", "3", "1"], capture_output=True, text=True, timeout=120, check=False)
    assert proc.returncode == 3 and "LEMMA_DECLINED" in proc.stdout, (proc.stdout, proc.stderr)
    assert "ROW" not in proc.stdout


def test_a_fold_whose_row_term_reads_other_rows_is_refused_by_the_spec_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SQL check refuses DISTINCT first; the spec gate refuses it again (a per-row term with a quantifier is not chunk-local)."""
    _set_env(monkeypatch, {"LEMMA_TEMPLATES": "1", "LEMMA_PARALLEL_VSTD": "off", "LEMMA_AGENT_SCAN": "0", "LEMMA_STRING_ENCODING": "plain"})
    spec = _emit_t("SELECT COUNT(DISTINCT a) AS c FROM t")
    monkeypatch.setenv("LEMMA_STREAM", "1")
    with pytest.raises(DeclarativeUnsupported, match="other rows"):
        stream.to_stream(spec)
