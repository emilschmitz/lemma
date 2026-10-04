"""The column loader is verified, and the trusted file reader aborts when its data breaks the loader's requires."""

from __future__ import annotations

import struct
import subprocess
import tempfile
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.pipeline import run_declarative_metrics
from research_loop.decl_query_measure import write_query_measure
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
)

VERUS = Path("/home/emil/tools/verus/verus")
_SQL = "SELECT k, COUNT(*) AS cnt FROM t GROUP BY k"

# Hash-map count; sound for any column bound the catalog states.
_BODY = """
    let mut i: usize = cols.n;
    let mut map: HashMapWithView<u64, u64> = HashMapWithView::new();
    while i > 0
        invariant
            i <= cols.n,
            valid_cols_t(cols),
            forall|k: u64|
                #[trigger] map@.contains_key(k) <==> (exists|j: int|
                    i as int <= j < cols.n as int && cols.k@[j] == k),
            forall|k: u64|
                map@.contains_key(k) ==> map@[k] as int == group_count(cols.k@, i as int, k),
        decreases i,
    {
        let i_old = i;
        proof {
            let keys = cols.k@;
            let start = i_old as int;
            assert(keys.len() == cols.n as int);
            assert(0 < start);
            assert(0 <= ROW_CAP_t <= u64::MAX as int);
        }
        i = i - 1;
        let k = cols.k[i];
        let prev: u64 = if map.contains_key(&k) {
            *map.get(&k).unwrap()
        } else {
            0
        };
        proof {
            let keys = cols.k@;
            let start = i_old as int;
            let ii = i as int;
            assert(ii + 1 == start);
            assert(keys[ii] == k);
            lemma_group_count_le_suffix(keys, ii, k);
            lemma_group_count_le_suffix(keys, start, k);
            lemma_group_count_witness(keys, start, k);
            if map@.contains_key(k) {
                assert(prev as int == group_count(keys, start, k));
                assert(group_count(keys, ii, k) == group_count(keys, start, k) + 1);
                assert(group_count(keys, ii, k) <= keys.len() - ii);
                assert(prev as int + 1 <= ROW_CAP_t);
            } else {
                assert(!(exists|j: int| start <= j < keys.len() && keys[j] == k));
                assert(!(group_count(keys, start, k) > 0));
                assert(group_count(keys, start, k) == 0);
                assert(group_count(keys, ii, k) == 1);
                assert(prev == 0);
                assert(prev as int + 1 <= ROW_CAP_t);
            }
            lemma_count_step_fits_u64(prev, ROW_CAP_t);
        }
        let next = prev + 1;
        map.insert(k, next);
        proof {
            let keys = cols.k@;
            assert(next as int == group_count(keys, i as int, k));
        }
    }
    map
"""


def _catalog(rows: int = 64, domain: int = 32) -> CatalogAssumptions:
    return CatalogAssumptions(
        tables={"t": TableAssumptions(max_rows=rows, columns={"k": ColumnAssumption(max_value_exclusive=domain)})}
    )


def _spec() -> str:
    return emit_declarative_spec(_SQL, {"t": {"k": "ubigint"}}, _catalog())


def _verus(src: str) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
        f.write(src)
    proc = subprocess.run(
        [str(VERUS), f.name, "--triggers-mode", "silent"],
        capture_output=True, text=True, timeout=180, check=False,
    )
    return proc.stdout + proc.stderr


def _bin(path: Path, keys: list[int], *, header: int | None = None, extra: bytes = b"") -> str:
    blob = struct.pack("<Q", len(keys) if header is None else header) + b"".join(struct.pack("<Q", k) for k in keys)
    path.write_bytes(blob + extra)
    return str(path)


def test_loader_is_verified_and_requires_lengths_and_caps() -> None:
    program = assemble_declarative_program(_spec(), _BODY)
    loader = program[program.index("fn load_cols_t") :]
    assert "external_body" not in program[program.index("fn load_cols_t") - 40 : program.index("fn load_cols_t")]
    head = loader[: loader.index("{\n    Cols_t")]
    assert "t_k@.len() == n_t as int" in head
    assert "n_t as int <= ROW_CAP_t" in head
    assert "t_k@[i] as int <= 31" in head
    assert "ensures\n        valid_cols_t(&cols)" in head
    # no loader of the assembled program is trusted
    assert "#[verifier::external_body]\nfn load_cols" not in program


def test_loader_two_column_table_restates_both_lengths() -> None:
    spec = emit_declarative_spec(
        "SELECT a, COUNT(*) AS c FROM u WHERE b > 1 GROUP BY a",
        {"u": {"a": "ubigint", "b": "ubigint"}},
        CatalogAssumptions(tables={"u": TableAssumptions(max_rows=8)}),
    )
    program = assemble_declarative_program(spec, "    HashMapWithView::new()\n")
    assert "u_a@.len() == n_u as int" in program
    assert "u_b@.len() == n_u as int" in program


@pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")
def test_verus_accepts_matching_lengths_and_rejects_mismatched() -> None:
    program = assemble_declarative_program(_spec(), _BODY)
    probe = "fn probe_{n}() {{ let _c = load_cols_t({rows}, {col}); }}\n"
    good = probe.format(n="good", rows="0", col="Vec::new()")
    bad = probe.format(n="bad", rows="3", col="Vec::new()")
    marker = "\nfn main()"
    # a call inside verus! is checked against `requires`
    inside = program.index("\n}\n\n", program.index("fn load_cols_t"))
    ok = program[:inside] + "\n" + good + program[inside:]
    assert "0 errors" in _verus(ok)
    broken = program[:inside] + "\n" + bad + program[inside:]
    out = _verus(broken)
    assert "precondition not satisfied" in out, out
    assert marker in program


def _run_with_file(tmp_path: Path, keys: list[int], **kw) -> dict:
    expected = kw.pop("expected", len(keys))
    bin_path = _bin(tmp_path / "cols_t.bin", keys, **kw)
    return run_declarative_metrics(
        spec_rs=_spec(),
        agent_source=_BODY,
        work_dir=tmp_path / "build",
        column_bins={"t": bin_path},
        speed_bar={"duck_us": 10**9, "rows": [], "table_rows": {"t": expected}},
    )


@pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")
def test_reader_accepts_a_file_that_meets_every_requirement(tmp_path: Path) -> None:
    m = _run_with_file(tmp_path, [1, 2, 2, 31], expected=4)
    # rows differ from the empty bar, but the binary ran
    assert m["proof_verified"], m.get("compiler_error")
    assert "differ" in m["compiler_error"]


@pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")
@pytest.mark.parametrize(
    ("keys", "kw", "needle"),
    [
        ([1, 2, 3], {"expected": 4}, "DuckDB pin has 4"),
        ([1, 2, 3], {"extra": b"\x00" * 8}, "trailing or missing bytes"),
        ([1, 40, 3], {}, "outside the catalog bound 31"),
        (list(range(30)) * 3, {}, "exceed the catalog cap 64"),
    ],
)
def test_reader_aborts_loudly_when_data_breaks_the_requirements(
    tmp_path: Path, keys: list[int], kw: dict, needle: str
) -> None:
    m = _run_with_file(tmp_path, keys, **kw)
    assert m["status"] == "FAILURE"
    assert needle in m["compiler_error"], m["compiler_error"]


def test_timed_run_without_a_printable_result_is_refused() -> None:
    open_ended = emit_declarative_spec(
        _SQL,
        {"t": {"k": "ubigint"}},
        CatalogAssumptions(tables={"t": TableAssumptions(max_rows=8)}),
    )
    with pytest.raises(ValueError, match="printable result"):
        assemble_declarative_program(open_ended, "    HashMapWithView::new()\n", column_bins={"t": "/tmp/x.bin"})


def test_map_dump_covers_signed_keys_and_checks_the_count() -> None:
    spec = emit_declarative_spec(
        "SELECT k, COUNT(*) AS cnt FROM t GROUP BY k",
        {"t": {"k": "bigint"}},
        _catalog(),
    )
    program = assemble_declarative_program(spec, "    HashMapWithView::new()\n", column_bins={"t": "/tmp/x.bin"})
    assert "let mut key: i64 = 0;" in program
    assert "printed == res.len()" in program


def test_loader_with_unchecked_conjunct_is_refused() -> None:
    spec = _spec().replace(
        "    && cols.k@.len() == cols.n as int",
        "    && cols.k@.len() == cols.n as int\n    && cols.n as int != 7",
        1,
    )
    with pytest.raises(ValueError, match="cannot check at runtime"):
        assemble_declarative_program(spec, "    HashMapWithView::new()\n", column_bins={"t": "/tmp/x.bin"})


def _tiny_db(path: Path, rows: list[tuple]) -> None:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (k UBIGINT, s VARCHAR, extra DOUBLE)")
    con.executemany("INSERT INTO t VALUES (?, ?, ?)", rows)
    con.close()


_SCHEMA = {"t": {"k": "UBIGINT", "s": "VARCHAR", "extra": "DOUBLE"}}


def test_measure_exports_only_the_columns_the_spec_reads_and_the_row_count(tmp_path: Path) -> None:
    db = tmp_path / "m.duckdb"
    _tiny_db(db, [(1, "a", 0.5), (1, "b", 1.5), (2, "c", None)])
    prep = write_query_measure(
        sql=_SQL,
        schema={"t": {"k": "UBIGINT"}},
        catalog=_catalog(),
        db_path=db,
        dest=tmp_path / "d",
        float_abs_eps=None,
    )
    assert prep["table_rows"] == {"t": 3}
    assert prep["kinds"] is None
    assert prep["rows"] == [[1, 2], [2, 1]]
    blob = Path(prep["bins"]["t"]).read_bytes()
    assert len(blob) == 8 + 3 * 8


@pytest.mark.parametrize("null_in", ["s", "k"])
def test_measure_refuses_a_null_in_a_column_the_query_reads(tmp_path: Path, null_in: str) -> None:
    db = tmp_path / "n.duckdb"
    _tiny_db(db, [(None if null_in == "k" else 1, None if null_in == "s" else "a", 0.5), (2, "a", 0.5)])
    with pytest.raises(ValueError, match="has NULLs"):
        write_query_measure(
            sql="SELECT k, COUNT(*) AS c FROM t WHERE s = 'a' GROUP BY k",
            schema=_SCHEMA,
            catalog=_catalog(),
            db_path=db,
            dest=tmp_path / "d",
            float_abs_eps=None,
        )


def test_measure_ignores_a_null_in_a_column_the_query_does_not_read(tmp_path: Path) -> None:
    db = tmp_path / "u.duckdb"
    _tiny_db(db, [(1, "a", None), (2, "b", None)])
    prep = write_query_measure(
        sql="SELECT k, COUNT(*) AS c FROM t WHERE s = 'a' GROUP BY k",
        schema=_SCHEMA,
        catalog=_catalog(),
        db_path=db,
        dest=tmp_path / "d",
        float_abs_eps=None,
    )
    assert prep["table_rows"] == {"t": 2}


def test_agent_file_with_host_uses_passes_import_vetting() -> None:
    spec = _spec()
    assert "broadcast use vstd::std_specs::hash::axiom_u64_obeys_hash_table_key_model;" in spec
    agent = spec.replace("// AGENT_EDIT_START\n// AGENT_EDIT_END", "// AGENT_EDIT_START\n    HashMapWithView::new()\n// AGENT_EDIT_END")
    m = run_declarative_metrics(spec_rs=spec, agent_source=agent, work_dir=None, timeout_sec=1)
    # The host's own axiom broadcast is not an agent import; failure may come later, never from vetting.
    assert "use is an assume" not in m.get("compiler_error", "")
    sneaky = agent.replace("use vstd::prelude::*;", "use vstd::prelude::*;\nbroadcast use vstd::std_specs::hash::axiom_i64_obeys_hash_table_key_model;", 1)
    m2 = run_declarative_metrics(spec_rs=spec, agent_source=sneaky, work_dir=None, timeout_sec=1)
    assert "use is an assume" in m2["compiler_error"]
