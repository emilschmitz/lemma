"""Agent-chosen scans (lemma.toml [run] agent_scan, default on): the one authorized DuckDB-filter trusted item ``scan_where_<t>``.

* emission: flag on adds one scan family per table and one handle per table to ``run_query``; flag off leaves the spec as before;
* admission: the agent may call ``scan_where_<t>`` but not define or redefine any scan item;
* the host translation (research_loop/scan_export.py) keeps exactly the rows ``scan_holds_<t>`` keeps (checked against a Python
  transcription of the spec fns on DuckDB data with dates, DECIMALs, NULLs and a dictionary column);
* Verus: a sound predicate verifies (fixture ``scan_filtered_sum.rs``), a too-narrow one does not; the proved binary calls
  back into the host export and agrees with DuckDB on several tables, with pushdown on and off.
"""

from __future__ import annotations

import random
import re
import struct
import subprocess
from pathlib import Path

import duckdb
import lemma_config
import pytest

from declarative_spec import agent_scan
from declarative_spec.admit import admit_declarative_body, admit_helpers
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
from research_loop.decl_query_measure import write_query_measure
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "declarative_proofs" / "scan_filtered_sum.rs"
VERUS = Path("/home/emil/tools/verus/verus")
needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")

USUM_SQL = "SELECT SUM(line) AS total FROM pre WHERE line > 5"
PRE = {"pre": {"line": "bigint", "report": "bigint"}}
JOIN_SQL = "SELECT s.fy, SUM(n.qtrs) AS total FROM num n JOIN sub s ON n.adsh = s.adsh WHERE n.qtrs > 1 GROUP BY s.fy"
JOIN = {"num": {"adsh": "varchar", "qtrs": "bigint"}, "sub": {"adsh": "varchar", "fy": "bigint"}}


def _cat(schema: dict, rows: int = 64) -> CatalogAssumptions:
    return CatalogAssumptions(tables={t: TableAssumptions(max_rows=rows) for t in schema})


def _spec(monkeypatch: pytest.MonkeyPatch, flag: str, sql: str = USUM_SQL, schema: dict = PRE) -> str:
    monkeypatch.setenv("LEMMA_AGENT_SCAN", flag)
    return emit_declarative_spec(sql, schema, _cat(schema))


# ---- emission -----------------------------------------------------------------------------------------------------------------


def test_default_on_gives_run_query_one_scan_handle_per_table_tied_to_that_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_AGENT_SCAN", raising=False)
    assert agent_scan.enabled()  # lemma.toml default
    spec = emit_declarative_spec(USUM_SQL, PRE, _cat(PRE))
    assert re.search(r"pub fn run_query\(pre: &Cols_pre, [^)]*pre_scan: &Scan_pre\)", spec)
    assert "        scan_full_pre(pre_scan) == *pre,\n" in spec
    assert "pub fn scan_where_pre(s: &Scan_pre, pred: &Vec<ScanAtom_pre>) -> (out: (Cols_pre, Ghost<Seq<int>>))" in spec


def test_two_tables_get_two_handles_and_exactly_one_trusted_function_each(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(monkeypatch, "1", JOIN_SQL, JOIN)
    assert "n_scan: &Scan_num" in spec and "s_scan: &Scan_sub" in spec  # one handle per run_query parameter (the aliases)
    trusted_fns = re.findall(r"#\[verifier::external_body\]\npub fn (\w+)", spec)
    assert sorted(f for f in trusted_fns if f.startswith("scan_")) == ["scan_where_num", "scan_where_sub"]
    # only integer columns are scan columns: the string join key is not
    assert "pub enum ScanCol_num { qtrs }" in spec and "pub enum ScanCol_sub { fy }" in spec


def test_flag_off_spec_has_no_scan_items_and_flag_on_only_adds_them(monkeypatch: pytest.MonkeyPatch) -> None:
    off = _spec(monkeypatch, "0")
    assert "Scan_" not in off and "scan_where" not in off
    on = _spec(monkeypatch, "1")
    assert on == agent_scan.add_scans(off)
    assert agent_scan.without_scans(on) == off  # flag off is exactly the spec minus the scan block and handles
    assert on.replace(", pre_scan: &Scan_pre)", ")").replace("        scan_full_pre(pre_scan) == *pre,\n", "").count("\n") > off.count("\n")


def test_flag_off_assembled_program_has_no_scan_handle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    body = "    let mut res: Vec<OutRow> = Vec::new();\n    res"
    off = assemble_declarative_program(_spec(monkeypatch, "0"), body, column_bins={"pre": str(tmp_path / "cols_pre.bin")})
    assert "scan_open_" not in off
    on = assemble_declarative_program(_spec(monkeypatch, "1"), body, column_bins={"pre": str(tmp_path / "cols_pre.bin")})
    assert f'let scan_pre = scan_open_pre("{tmp_path}");' in on and "&scan_pre)" in on


def test_a_self_join_gets_no_scan_handles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_SCAN", "1")
    spec = agent_scan.add_scans("pub struct Cols_t {\n    pub n: usize,\n    pub a: Vec<i64>,\n}\n// AGENT_HELPERS_START\npub fn run_query(x: &Cols_t, y: &Cols_t) -> (res: u64)\n    requires\n")
    assert "Scan_t" not in spec


# ---- admission -----------------------------------------------------------------------------------------------------------------


def test_the_agent_may_call_scan_where_but_not_define_scan_items(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(monkeypatch, "1")
    text = FIXTURE.read_text()
    assert admit_declarative_body(extract_agent_edit(text)).ok
    assert admit_helpers(extract_agent_helpers(text), spec).ok
    for name in ("scan_where_pre", "scan_rows_pre", "scan_holds_pre", "lemma_scan_rows_pre", "scan_key_pre", "lemma_scan_file"):
        res = admit_helpers(f"fn {name}() {{ }}", spec)
        assert not res.ok and any("redefines a host name" in v for v in res.violations), name


def test_the_agent_cannot_add_a_trusted_scan_of_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(monkeypatch, "1")
    res = admit_helpers("#[verifier::external_body]\nfn my_scan(s: &Scan_pre) -> (out: Cols_pre) ensures out == scan_full_pre(s) { unimplemented!() }", spec)
    assert not res.ok
    assert not admit_declarative_body("    assume(scan_full_pre(pre_scan).n == 0);\n    Vec::new()").ok


# ---- the host translation keeps exactly the rows scan_holds keeps -----------------------------------------------------------

_T = {"t": {"k": "bigint", "d": "date", "x": "decimal(10,2)", "s": "varchar"}}
_T_SQL = "SELECT COUNT(*) AS c, MIN(d) AS md, SUM(k) AS sk FROM t WHERE s <> 'q' AND d > DATE '1990-01-01' AND (x IS NULL OR x > -100)"


def _t_db(path: Path) -> Path:
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE t AS SELECT i - 20 AS k, DATE '1995-01-01' + (i * 3)::INTEGER AS d, "
        "CASE WHEN i % 5 = 0 THEN NULL ELSE CAST(((i * 37) % 1000 - 500) / 4.0 AS DECIMAL(10,2)) END AS x, "
        "['a', 'b', 'c'][1 + i % 3] AS s FROM range(60) r(i)"
    )
    con.close()
    return path


def _read_cols(path: Path, fields: list[tuple[str, str]]) -> tuple[int, dict]:
    raw = path.read_bytes()
    n = struct.unpack_from("<Q", raw, 0)[0]
    off = 8
    fmt = {"i64": "q", "i32": "i", "i16": "h", "i8": "b", "u64": "Q", "u32": "I", "u16": "H", "u8": "B", "usize": "Q"}
    out: dict = {}
    for fname, fty in fields:
        if fname.endswith("__dict"):
            m = struct.unpack_from("<Q", raw, off)[0]
            off += 8
            vals = []
            for _ in range(m):
                ln = struct.unpack_from("<I", raw, off)[0]
                vals.append(raw[off + 4 : off + 4 + ln].decode())
                off += 4 + ln
            out[fname] = vals
        elif fty == "bool":
            out[fname] = [b != 0 for b in raw[off : off + n]]
            off += n
        elif fty == "i128":
            out[fname] = [int.from_bytes(raw[off + 16 * i : off + 16 * i + 16], "little", signed=True) for i in range(n)]
            off += 16 * n
        else:
            w = struct.calcsize(fmt[fty])
            out[fname] = list(struct.unpack_from(f"<{n}{fmt[fty]}", raw, off))
            off += w * n
    assert off == len(raw)
    return n, out


def _holds(cols: dict, scan_cols: dict[str, bool], atoms: list[tuple], i: int) -> bool:
    """Python transcription of scan_holds_<t> (agent_scan.py): every atom holds; a NULL cell of a nullable column holds no atom."""
    for kind, col, a, b in atoms:
        if scan_cols[col] and not cols[f"{col}__valid"][i]:
            return False
        v = cols[col][i]
        if kind == "R" and not a <= v <= b:
            return False
        if kind == "I" and v not in a:
            return False
    return True


def _key(atoms: list[tuple]) -> str:
    return ";".join(f"R:{c}:{a}:{b}" if k == "R" else f"I:{c}:{','.join(str(v) for v in a)}" for k, c, a, b in atoms)


@pytest.mark.parametrize("pushdown", ["0", "1"])
def test_scan_export_keeps_exactly_the_rows_the_spec_predicate_keeps(pushdown: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scan_export import export_scan

    monkeypatch.setenv("LEMMA_AGENT_SCAN", "1")
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    monkeypatch.setenv("LEMMA_PUSHDOWN", pushdown)
    cat = CatalogAssumptions(max_rows=64, tables={"t": TableAssumptions(max_rows=64, columns={"x": ColumnAssumption(nullable=True, scale=2)})})
    db = _t_db(tmp_path / "t.duckdb")
    sql = _T_SQL if pushdown == "0" else _T_SQL + " AND k > -10"
    prepared = write_query_measure(sql=sql, schema=_T, catalog=cat, db_path=db, dest=tmp_path / "data")
    spec = emit_declarative_spec(sql, _T, cat)
    fields = re.findall(r"pub\s+(\w+):\s+Vec<([^>]+)>", re.search(r"pub struct Cols_t\s*\{([^}]+)\}", spec).group(1))
    scan_cols = {f: nullable for f, _ty, nullable in agent_scan.scan_columns(fields)}
    assert set(scan_cols) == {"k", "d", "x"} and scan_cols["x"] and not scan_cols["k"]
    n, full = _read_cols(Path(prepared["bins"]["t"]), fields)
    rng = random.Random(7)
    keys = [
        [],
        [("R", "k", -5, 12)],
        [("R", "d", 9135, 9200), ("R", "k", -100, 100)],  # days since 1970: 1995-01-04 ..
        [("R", "x", -2000, 3000)],  # scaled by 100; NULL x rows never hold
        [("I", "k", [-20, -1, 0, 7, 39], None)],
        [("I", "x", [], None)],
        [("R", "k", 5, 4)],
    ] + [[("R", "k", lo, lo + rng.randint(0, 30)), ("R", "x", -rng.randint(0, 12000), rng.randint(0, 12000))] for lo in (-25, -3, 10)]
    for atoms in keys:
        path = export_scan(tmp_path / "data", "t", _key(atoms))
        m, got = _read_cols(path, fields)
        want = [i for i in range(n) if _holds(full, scan_cols, atoms, i)]
        assert m == len(want), atoms
        for fname, _ty in fields:
            if fname.endswith("__dict"):
                assert got[fname] == full[fname]  # the full table's dictionary
            else:
                assert got[fname] == [full[fname][i] for i in want], (atoms, fname)


def test_scan_export_refuses_unknown_and_non_integer_columns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scan_export import export_scan

    monkeypatch.setenv("LEMMA_AGENT_SCAN", "1")
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    cat = CatalogAssumptions(max_rows=64, tables={"t": TableAssumptions(max_rows=64, columns={"x": ColumnAssumption(nullable=True, scale=2)})})
    db = _t_db(tmp_path / "t.duckdb")
    write_query_measure(sql=_T_SQL, schema=_T, catalog=cat, db_path=db, dest=tmp_path / "data")
    for key in ("R:s:0:1", "R:nope:0:1", "R:k:1", "X:k:1:2"):
        with pytest.raises(ValueError):
            export_scan(tmp_path / "data", "t", key)


# ---- Verus: a sound predicate verifies, a too-narrow one does not; the binary agrees with DuckDB ------------------------------


def _program(spec: str, text: str, column_bins: dict | None = None) -> str:
    return assemble_declarative_program(spec, extract_agent_edit(text), helpers=extract_agent_helpers(text), column_bins=column_bins)


def _verify(monkeypatch: pytest.MonkeyPatch, text: str) -> tuple[bool, str]:
    from declarative_spec.pipeline import verify_assembled

    monkeypatch.setenv("LEMMA_VERUS_BIN", str(ROOT / "scripts" / "ram" / "verus_guarded.sh"))
    return verify_assembled(_program(_spec(monkeypatch, "1"), text), timeout_sec=600)


@needs_verus
def test_a_sound_scan_predicate_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = _verify(monkeypatch, FIXTURE.read_text())
    assert ok and re.search(r"verification results:: \d+ verified, 0 errors", out), out[-2000:]


@needs_verus
@pytest.mark.parametrize("mutation", [("line, 6, ", "line, 7, "), ("0x7fff_ffff_ffff_ffffi128", "1000i128")])
def test_a_too_narrow_scan_predicate_fails_verification(monkeypatch: pytest.MonkeyPatch, mutation: tuple[str, str]) -> None:
    text = FIXTURE.read_text()
    assert text.count(mutation[0]) == 2  # the push and the loop invariant naming it: the proof is otherwise unchanged
    ok, out = _verify(monkeypatch, text.replace(*mutation))
    assert not ok and re.search(r"verification results:: \d+ verified, [1-9]\d* errors", out), out[-2000:]


@needs_verus
@pytest.mark.parametrize("pushdown", ["1", "0"])
def test_the_proved_scan_body_matches_duckdb_on_several_tables(pushdown: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.bench import rows_from_stdout_general, rows_match_error
    from declarative_spec.pipeline import run_declarative_metrics

    monkeypatch.setenv("LEMMA_VERUS_BIN", str(ROOT / "scripts" / "ram" / "verus_guarded.sh"))
    monkeypatch.setenv("LEMMA_PUSHDOWN", pushdown)
    spec = _spec(monkeypatch, "1")
    db = tmp_path / "pre.duckdb"
    data = tmp_path / "data"
    binary = None
    rng = random.Random(11)
    for size in (0, 1, 13, 64, 64, 40):
        values = [rng.choice([-(2**62), -3, 0, 5, 6, 7, 1000, 2**62, rng.randint(-50, 50)]) for _ in range(size)]
        db.unlink(missing_ok=True)
        con = duckdb.connect(str(db))
        con.execute("CREATE TABLE pre (line BIGINT, report BIGINT)")
        if values:
            con.executemany("INSERT INTO pre VALUES (?, 0)", [(v,) for v in values])
        con.close()
        prepared = write_query_measure(sql=USUM_SQL, schema=PRE, catalog=_cat(PRE), db_path=db, dest=data)
        if binary is None:
            metrics = run_declarative_metrics(spec_rs=spec, agent_source=FIXTURE.read_text(), work_dir=tmp_path / "run", column_bins=prepared["bins"])
            assert metrics["proof_verified"] and metrics["status"] == "SUCCESS", str(metrics.get("compiler_error"))[-2000:]
            binary, stdout = str(tmp_path / "run" / "declarative_query"), metrics["stdout"]
        else:
            run = subprocess.run([binary], capture_output=True, text=True, timeout=120, check=False, cwd=tmp_path / "run")
            assert run.returncode == 0, run.stderr[-2000:]
            stdout = run.stdout
        got = rows_from_stdout_general(stdout)
        assert rows_match_error(got, prepared["rows"], prepared["kinds"]) is None, (size, got, prepared["rows"])
        assert list(data.glob("scan_pre_*.bin")), "the body's scan went through the host export"



def _verify_scan_lemmas(tmp_path: Path, spec: str) -> list[str]:
    """Verus on each host lemma_scan_rows_<t> of the assembled program alone (host-proved, not trusted): one result line per table."""
    body = "None" if "(res: Option<" in spec else "Vec::new()"  # it only has to type-check: only the host lemma is verified
    path = tmp_path / "program.rs"
    path.write_text(assemble_declarative_program(spec, body, helpers=""))
    out = []
    for t in re.findall(r"pub proof fn (lemma_scan_rows_\w+)\(", spec):
        p = subprocess.run([str(ROOT / "scripts" / "ram" / "verus_guarded.sh"), str(path), "--crate-type=lib", "--rlimit",
                            str(lemma_config.get("verus_rlimit")), "--verify-root", "--verify-function", t],
                           capture_output=True, text=True, timeout=600)
        out.append(t + ": " + (re.search(r"verification results:: .*", p.stdout + p.stderr) or [p.stderr[-1500:]])[0])
    return out


SEC_Q6_DDL = """
CREATE TABLE num (adsh VARCHAR, tag VARCHAR, version VARCHAR, uom VARCHAR, value DECIMAL(38,4));
CREATE TABLE sub (adsh VARCHAR, name VARCHAR, fy {fy_type});
CREATE TABLE pre (adsh VARCHAR, tag VARCHAR, version VARCHAR, stmt VARCHAR, plabel VARCHAR);
INSERT INTO sub VALUES ('a', 'x', 2023), ('b', 'y', NULL);
"""
SEC_Q6_SQL = """SELECT s.name, p.stmt, n.tag, p.plabel, SUM(n.value) AS total_value, COUNT(*) AS cnt
FROM num n JOIN sub s ON n.adsh = s.adsh JOIN pre p ON n.adsh = p.adsh AND n.tag = p.tag AND n.version = p.version
WHERE n.uom = 'USD' AND p.stmt = 'IS' AND s.fy = 2023 AND n.value IS NOT NULL
GROUP BY s.name, p.stmt, n.tag, p.plabel ORDER BY total_value DESC LIMIT 200"""


@needs_verus
def test_the_host_scan_row_lemma_verifies_with_assumptions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = _verify_scan_lemmas(tmp_path, _spec(monkeypatch, "1"))
    assert len(out) == 1 and "1 verified, 0 errors" in out[0], out


@needs_verus
@pytest.mark.parametrize("fy_type", ["INTEGER", "BIGINT"])
def test_the_host_scan_row_lemma_verifies_on_a_nullable_column_without_assumptions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                                                   fy_type: str) -> None:
    # SEC Q6 (2026-10-19, assumptions = false): lemma_scan_rows_sub over the nullable `fy` left the not-kept branch to Z3 and failed
    # its last ensures (78 verified, 1 errors, host-owned line); both branches are now proved.
    from research_loop.structural_catalog import structural_catalog_from_db

    db = tmp_path / "t.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute(SEC_Q6_DDL.format(fy_type=fy_type))
        schema = {t: dict(con.execute(f"SELECT column_name, lower(data_type) FROM information_schema.columns WHERE table_name = '{t}'").fetchall())
                  for t in ("num", "sub", "pre")}
    monkeypatch.setenv("LEMMA_AGENT_SCAN", "1")
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "0")
    spec = emit_declarative_spec(SEC_Q6_SQL, schema, structural_catalog_from_db(db))
    assert "c.fy__valid@[i]" in spec  # the scan column is nullable, as in SEC
    out = _verify_scan_lemmas(tmp_path, spec)
    assert out and all("1 verified, 0 errors" in line for line in out), out
