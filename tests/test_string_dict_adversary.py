"""Adversary review of dictionary-encoded string columns (manual adversary, Sonnet subagent).

Target: `LEMMA_STRING_ENCODING=dict` (declarative_spec/string_encoding.py, emit_surface._string_views/_dict_checks,
assemble._runtime_checks, decl_query_measure._export_table). Soundness only. Verdict:
research_loop/menus/string_dictionary_ADVERSARY_VERDICT.md. Verus only through scripts/ram/verus_guarded.sh.
"""

from __future__ import annotations

import os
import re
import struct
import subprocess
import tempfile
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import _runtime_checks, assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.schema_types import SchemaModel
from declarative_spec.string_encoding import code_type
from research_loop.decl_query_measure import _export_table
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

ROOT = Path(__file__).resolve().parent.parent
GUARDED = ROOT / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")
needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")

SCHEMA = {
    "t": {"a": "bigint", "s": "varchar", "g": "varchar"},
    "u": {"k": "varchar", "w": "bigint", "s": "varchar"},
}
CAT = CatalogAssumptions(max_rows=64, tables={n: TableAssumptions(max_rows=64) for n in SCHEMA})


def spec(sql: str, mode: str, schema: dict | None = None) -> str:
    old = os.environ.get("LEMMA_STRING_ENCODING")
    os.environ["LEMMA_STRING_ENCODING"] = mode
    try:
        return emit_declarative_spec(sql, schema or SCHEMA, CAT)
    finally:
        if old is None:
            del os.environ["LEMMA_STRING_ENCODING"]
        else:
            os.environ["LEMMA_STRING_ENCODING"] = old


# ---------------------------------------------------------------------------------------------
# (2) the spec means the same as the plain encoding.
# ---------------------------------------------------------------------------------------------

SAME = [
    "SELECT COUNT(*) AS c FROM t WHERE s = 'AIR'",
    "SELECT COUNT(*) AS c FROM t WHERE s <> 'AIR'",
    "SELECT COUNT(*) AS c FROM t WHERE s LIKE 'A%'",
    "SELECT COUNT(*) AS c FROM t WHERE s NOT LIKE '%x'",
    "SELECT COUNT(*) AS c FROM t WHERE s IN ('A', 'B')",
    "SELECT COUNT(*) AS c FROM t WHERE s IN (SELECT k FROM u)",
    "SELECT COUNT(DISTINCT s) AS c FROM t",
    "SELECT s, g, COUNT(*) AS c FROM t GROUP BY s, g",
    "SELECT s FROM t ORDER BY s LIMIT 3",
    "SELECT DISTINCT s FROM t",
    "SELECT COUNT(*) AS c FROM t JOIN u ON t.s = u.k",
    "SELECT COUNT(*) AS c FROM t x JOIN t y ON x.s = y.s",
    "SELECT COUNT(*) AS c FROM t JOIN u ON t.s = u.s",
    "SELECT SUM(u.w) AS c FROM t JOIN u ON t.s = u.k WHERE t.g = u.s",
    "SELECT COUNT(*) AS c FROM t WHERE s = g",
    "SELECT COUNT(*) AS c FROM t WHERE s = ''",
    "SELECT COUNT(*) AS c FROM t WHERE s = 'ZZZ'",
    "SELECT SUM(CASE WHEN s = 'A' THEN 1 ELSE 0 END) AS c FROM t",
    "SELECT g, COUNT(*) AS c FROM t GROUP BY g HAVING g = 'x'",
]


def _statements(text: str) -> str:
    text = re.sub(r"pub struct Cols_\w+ \{.*?\n\}\n", "", text, flags=re.S)
    text = re.sub(r"pub open spec fn valid_cols_\w+.*?\n\}\n", "", text, flags=re.S)
    return text.replace("@@", "@")


def _undo_accessor(text: str) -> str:
    return re.sub(r"(\w+)\.(\w+)__dict@\[\1\.\2@\[(\w+)\] as int\]@", r"\1.\2@[\3]@", text)


@pytest.mark.parametrize("sql", SAME)
def test_dict_spec_is_the_plain_spec_once_the_accessor_is_undone(sql: str) -> None:
    """Every statement (row_hit, keys, outputs, ensures) is textually identical to the plain one after
    `t.c__dict@[t.c@[i] as int]@` is read back as `t.c@[i]@`: no other change, no raw code in a statement."""
    assert _undo_accessor(_statements(spec(sql, "dict"))) == _statements(spec(sql, "plain"))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS c FROM t WHERE s < 'M'",
        "SELECT COUNT(*) AS c FROM t WHERE s BETWEEN 'A' AND 'C'",
        "SELECT MIN(s) AS lo FROM t",
        "SELECT COUNT(*) AS c FROM t WHERE LOWER(s) = 'air'",
        "SELECT COUNT(*) AS c FROM t WHERE LENGTH(s) > 3",
    ],
)
def test_string_ordering_min_max_and_functions_are_refused_in_both_encodings(sql: str) -> None:
    for mode in ("plain", "dict"):
        with pytest.raises(Exception, match="string|MIN or MAX|expression operand"):
            spec(sql, mode)


def test_group_by_string_count_uses_the_surface_emitter_in_dict_mode() -> None:
    """The one shape whose spec text differs: plain used the legacy count emitter (StringHashMap)."""
    d = spec("SELECT s, COUNT(*) AS c FROM t GROUP BY s", "dict")
    assert "StringHashMap" not in d and "Vec<String>" not in d.split("pub struct OutRow")[0].replace("__dict: Vec<String>", "")
    assert "t.s__dict@[t.s@[" in d


def test_join_on_string_keys_compares_through_each_columns_own_dictionary() -> None:
    d = spec("SELECT COUNT(*) AS c FROM t JOIN u ON t.s = u.k", "dict")
    assert "t.s__dict@[t.s@[" in d and "u.k__dict@[u.k@[" in d
    # no comparison of a raw code with another column's code anywhere in the statements
    stmts = _statements(d)
    assert not re.search(r"\.(?:s|k)@\[\w+\](?! as int)\s*(?:==|!=|<|>)", stmts)


# ---------------------------------------------------------------------------------------------
# (1) the loader relation: export round trip and runtime checks.
# ---------------------------------------------------------------------------------------------

TRICKY = [
    "a", "a ", "", "é", "é", "😀", "line\nbreak", "tab\t", "A", "back\\slash", "x" * 100_000, "nul\x00byte", "\r\n",
]


def _decode(blob: bytes, fields: list[str]) -> dict[str, object]:
    n = struct.unpack_from("<Q", blob, 0)[0]
    off, out = 8, {}
    for name in fields:
        if name == "s__dict":
            m = struct.unpack_from("<Q", blob, off)[0]
            off += 8
            entries = []
            for _ in range(m):
                ln = struct.unpack_from("<I", blob, off)[0]
                entries.append(blob[off + 4 : off + 4 + ln].decode("utf-8"))
                off += 4 + ln
            out[name] = entries
        elif name == "s":
            out[name] = n
        else:
            raise AssertionError(name)
    return out


def _codes(blob: bytes, n: int, width: int) -> list[int]:
    fmt = {1: "B", 2: "H", 4: "I"}[width]
    return list(struct.unpack_from(f"<{n}{fmt}", blob, 8))


def _db(values: list[str | None]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (a BIGINT, s VARCHAR, g VARCHAR)")
    if values:
        con.executemany("INSERT INTO t VALUES (?, ?, 'g')", [(i, v) for i, v in enumerate(values)])
    return con


def test_export_round_trips_tricky_strings_exactly() -> None:
    """Emoji, NUL, newline, CRLF, trailing space, empty, composed vs decomposed e, 100 kB: dict[code[i]] == DuckDB's cell."""
    values = TRICKY + TRICKY[::-1] + ["a"] * 5
    con = _db(values)
    model = SchemaModel.from_caller(SCHEMA, "t")
    blob = _export_table(con, model, "t", [("s", "u8"), ("s__dict", "String")])
    n = struct.unpack_from("<Q", blob, 0)[0]
    codes = _codes(blob, n, 1)
    entries = _decode_dict_after_codes(blob, n, 1)
    assert len(set(entries)) == len(entries)  # pairwise distinct
    duck_cells = [r[0] for r in con.execute("SELECT s FROM t ORDER BY a").fetchall()]
    assert [entries[c] for c in codes] == duck_cells == values
    assert len(entries) == con.execute("SELECT COUNT(DISTINCT s) FROM t").fetchone()[0]


def _decode_dict_after_codes(blob: bytes, n: int, width: int) -> list[str]:
    off = 8 + n * width
    m = struct.unpack_from("<Q", blob, off)[0]
    off += 8
    out = []
    for _ in range(m):
        ln = struct.unpack_from("<I", blob, off)[0]
        out.append(blob[off + 4 : off + 4 + ln].decode("utf-8"))
        off += 4 + ln
    assert off == len(blob)
    return out


def test_python_and_duckdb_agree_on_which_strings_are_equal() -> None:
    """The exporter dedupes by Python `str` equality; the spec compares Seq<char>. DuckDB must agree (binary collation)."""
    con = _db(TRICKY)
    py = len(set(TRICKY))
    assert con.execute("SELECT COUNT(DISTINCT s) FROM t").fetchone()[0] == py == len(TRICKY)
    assert con.execute("SELECT 'a' = 'A', 'a' = 'a ', 'é' = 'e' || chr(769)").fetchone() == (False, False, False)


@pytest.mark.parametrize(("n_distinct", "width", "ok"), [(256, 1, True), (257, 1, False), (65536, 2, True), (65537, 2, False)])
def test_code_width_boundary_and_a_too_small_cap_fails_loudly(n_distinct: int, width: int, ok: bool) -> None:
    """u8 holds 256 entries (codes 0..255), 257 raises at export; u16 holds 65536, 65537 raises."""
    values = [f"v{i}" for i in range(n_distinct)]
    con = _db(values)
    model = SchemaModel.from_caller(SCHEMA, "t")
    fty = {1: "u8", 2: "u16", 4: "u32"}[width]
    if ok:
        blob = _export_table(con, model, "t", [("s", fty), ("s__dict", "String")])
        assert max(_codes(blob, n_distinct, width)) == n_distinct - 1
    else:
        with pytest.raises(ValueError, match="cannot pack"):
            _export_table(con, model, "t", [("s", fty), ("s__dict", "String")])
    assert code_type(256) == "u8" and code_type(257) == "u16" and code_type(65536) == "u16" and code_type(65537) == "u32"


def test_null_cell_is_refused_at_export() -> None:
    con = _db(["a", None, "b"])
    model = SchemaModel.from_caller(SCHEMA, "t")
    with pytest.raises(ValueError, match="NULL"):
        _export_table(con, model, "t", [("s", "u8"), ("s__dict", "String")])


def test_empty_table_exports_an_empty_dictionary() -> None:
    con = _db([])
    model = SchemaModel.from_caller(SCHEMA, "t")
    blob = _export_table(con, model, "t", [("s", "u8"), ("s__dict", "String")])
    assert blob == struct.pack("<Q", 0) + struct.pack("<Q", 0)


_VALID = (
    "pub open spec fn valid_cols_t(t: &Cols_t) -> bool {\n"
    "    &&& t.s@.len() == t.n as int\n"
    "    &&& forall|i: int| #![trigger t.s@[i]] 0 <= i < t.n as int ==> (t.s@[i] as int) < t.s__dict@.len()\n"
    "    &&& forall|a: int, b: int| #![trigger t.s__dict@[a]@, t.s__dict@[b]@] 0 <= a < b < t.s__dict@.len() ==> "
    "t.s__dict@[a]@ != t.s__dict@[b]@\n}\n"
)


def _run_checks(codes: list[int], dictionary: list[str]) -> subprocess.CompletedProcess[str]:
    checks = "\n".join(_runtime_checks(_VALID, "t", [("s", "u8"), ("s__dict", "String")]))
    def lit(d: str) -> str:
        return '"' + "".join(f"\\u{{{ord(ch):x}}}" for ch in d) + '".to_string()'

    rust_dict = ", ".join(lit(d) for d in dictionary)
    src = (
        "fn main() {\n"
        f"    let n_t: usize = {len(codes)};\n    let t_s: Vec<u8> = vec!{codes};\n"
        f"    let t_s__dict: Vec<String> = vec![{rust_dict}];\n{checks}\n    println!(\"ok\");\n}}\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "m.rs").write_text(src)
        built = subprocess.run(["rustc", "--edition", "2021", "-o", f"{tmp}/m", f"{tmp}/m.rs"], capture_output=True, text=True)
        assert built.returncode == 0, built.stderr[-1500:]
        return subprocess.run([f"{tmp}/m"], capture_output=True, text=True)


@pytest.mark.parametrize(
    ("codes", "dictionary", "ok"),
    [
        ([], [], True),  # empty table
        ([0, 1, 0], ["a", "a "], True),  # trailing space is a different string
        ([0, 1], ["\u00e9", "e\u0301"], True),  # composed vs decomposed
        ([0, 0], ["a"], True),
        ([0], [], False),  # n > 0 with an empty dictionary
        ([1], ["a"], False),  # code one beyond the dictionary
        ([0, 1], ["a", "a"], False),  # repeated entry
    ],
)
def test_runtime_asserts_decide_exactly_the_relation(codes: list[int], dictionary: list[str], ok: bool) -> None:
    dictionary = [d.replace("\\u{e9}", "é").replace("e\\u{301}", "é") for d in dictionary]
    done = _run_checks(codes, dictionary)
    assert (done.returncode == 0) is ok, done.stderr[-300:]


def _assembled(sql: str) -> str:
    os.environ["LEMMA_STRING_ENCODING"] = "dict"
    try:
        s = emit_declarative_spec(sql, SCHEMA, CAT)
    finally:
        del os.environ["LEMMA_STRING_ENCODING"]
    return assemble_declarative_program(s, "    Vec::new()", column_bins={"t": "/nonexistent/t.bin", "u": "/nonexistent/u.bin"})


def test_runtime_checks_run_before_run_query_on_every_table_including_same_named_columns() -> None:
    program = _assembled("SELECT COUNT(*) AS c FROM t JOIN u ON t.s = u.s")
    main = program.split("fn main()")[1]
    call = main.index("run_query(")
    for needle in (
        "t_s__dict",
        "u_s__dict",
        'assert!(t_s.iter().all(|c| (*c as usize) < t_s__dict.len()',
        'assert!(u_s.iter().all(|c| (*c as usize) < u_s__dict.len()',
        "t.s: a dictionary entry repeats",
        "u.s: a dictionary entry repeats",
    ):
        positions = [m.start() for m in re.finditer(re.escape(needle), main)]
        assert positions, needle
        assert min(positions) < call, f"{needle} is not asserted before run_query"


def test_self_join_loads_and_checks_the_table_once() -> None:
    program = _assembled("SELECT COUNT(*) AS c FROM t x JOIN t y ON x.s = y.s")
    main = program.split("fn main()")[1]
    assert main.count("a code is outside its dictionary") == 1


def test_table_without_a_string_column_has_no_dictionary_check() -> None:
    os.environ["LEMMA_STRING_ENCODING"] = "dict"
    try:
        s = emit_declarative_spec("SELECT SUM(a) AS c FROM t", SCHEMA, CAT)
    finally:
        del os.environ["LEMMA_STRING_ENCODING"]
    assert "__dict" not in s


# ---------------------------------------------------------------------------------------------
# Verus: the loader verifies for a two-table dictionary program (one heavy job).
# ---------------------------------------------------------------------------------------------


@needs_verus
def test_two_table_dictionary_loader_verifies(tmp_path: Path) -> None:
    os.environ["LEMMA_STRING_ENCODING"] = "dict"
    try:
        s = emit_declarative_spec("SELECT COUNT(*) AS c FROM t JOIN u ON t.s = u.s", SCHEMA, CAT)
    finally:
        del os.environ["LEMMA_STRING_ENCODING"]
    stub = "    assume(false);\n    loop invariant true decreases 0int { assume(false); }"
    program = assemble_declarative_program(s, stub, column_bins={"t": str(tmp_path / "t.bin"), "u": str(tmp_path / "u.bin")})
    path = tmp_path / "two.rs"
    path.write_text(program)
    proc = subprocess.run([str(GUARDED), str(path), "--triggers-mode", "silent"], capture_output=True, text=True, check=False)
    out = proc.stdout + proc.stderr
    assert re.search(r"verification results:: \d+ verified, 0 errors", out), out[-1500:]


# ---------------------------------------------------------------------------------------------
# Open findings.
# ---------------------------------------------------------------------------------------------


def test_the_reviewed_commit_ships_every_file_it_needs() -> None:
    """Commit 3f9e6a0 omitted research_loop/table_assumptions.py (`max_distinct`), the dict exporter in
    decl_query_measure.py and the check.py distinct cap; they existed only as uncommitted edits in the author's worktree."""
    from research_loop.table_assumptions import ColumnAssumption

    assert "max_distinct" in ColumnAssumption.__dataclass_fields__
    text = (ROOT / "research_loop" / "decl_query_measure.py").read_text()
    assert "__dict" in text and "dictionaries" in text
    assert "max_distinct" in (ROOT / "research_loop" / "assumption_packages" / "check.py").read_text()


def test_keyword_named_string_column_gets_a_consistent_dictionary_and_checks() -> None:
    schema = {"t": {"type": "varchar", "a": "bigint"}}
    os.environ["LEMMA_STRING_ENCODING"] = "dict"
    try:
        s = emit_declarative_spec("SELECT COUNT(*) AS c FROM t WHERE type = 'x'", schema, CAT)
    finally:
        del os.environ["LEMMA_STRING_ENCODING"]
    assert "pub r#type: Vec<u32>," in s and "pub r#type__dict: Vec<String>," in s
    program = assemble_declarative_program(s, "    Vec::new()", column_bins={"t": "/nonexistent/t.bin"})
    assert "t_type__dict" in program and "t.type: a code is outside its dictionary" in program


def test_quoted_uppercase_column_is_a_pre_existing_loud_failure_in_both_encodings() -> None:
    """Aside (not dict-specific): `"S" = 'x'` emits the bare token `S` (an unknown identifier, Verus rejects it)."""
    schema = {"t": {"S": "varchar", "a": "bigint"}}
    for mode in ("plain", "dict"):
        assert "(S == " in spec('SELECT COUNT(*) AS c FROM t WHERE "S" = \'x\'', mode, schema)
