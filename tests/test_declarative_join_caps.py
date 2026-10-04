"""Join caps and unique keys as data assumptions: the SUM fit bound, the emitted requirement, the loader assert, the check.

A join cap is stated like a row cap: ``JoinCap`` in the catalog, measured by ``assumption_packages/check.py``
(``COUNT(*)`` of exactly that join, failing with the join and the measured count), required by the emitted
``run_query`` (spec fn + ``requires``), and asserted by ``main`` on the loaded data before the call.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import _join_cap_checks, _runtime_checks, assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.lemmas import FitRefusal
from research_loop.assumption_packages.check import violations
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    JoinCap,
    TableAssumptions,
)

GUARD = Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")

SCHEMA = {
    "a": {"k": "bigint", "v": "decimal(38,4)", "tag": "varchar"},
    "b": {"k": "bigint", "w": "bigint", "tag": "varchar"},
    "u": {"k": "bigint", "z": "bigint"},
}
CAP_V = 2**62 * 10**4
SUM_AB = "SELECT b.w, SUM(a.v) AS total FROM a JOIN b ON a.k = b.k WHERE a.tag = 'x' GROUP BY b.w"
SUM_ABU = (
    "SELECT b.w, SUM(a.v) AS total FROM a JOIN b ON a.k = b.k JOIN u ON a.k = u.k WHERE a.tag = 'x' GROUP BY b.w"
)


def _catalog(*, caps: tuple[JoinCap, ...] = (), u_unique: bool = False) -> CatalogAssumptions:
    big = 2**31
    return CatalogAssumptions(
        max_rows=big,
        join_caps=caps,
        tables={
            "a": TableAssumptions(max_rows=big, columns={"v": ColumnAssumption(max_value_exclusive=CAP_V)}),
            "b": TableAssumptions(max_rows=big),
            "u": TableAssumptions(max_rows=big, unique_keys=(("k",),) if u_unique else ()),
        },
    )


AB_CAP = JoinCap("a", "b", (("k", "k"),), 2**36)


def _verify(spec: str) -> str:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    program = assemble_declarative_program(spec, "    assume(false);\n    loop invariant true decreases 0int { assume(false); }")
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(program)
    proc = subprocess.run(
        [str(GUARD), handle.name, "--triggers-mode", "silent"], capture_output=True, text=True, check=False
    )
    return proc.stdout + proc.stderr


# ---- the SUM fit bound ------------------------------------------------------------------------------------------------


def test_a_big_pair_join_sum_is_refused_without_a_declared_cap() -> None:
    with pytest.raises(FitRefusal, match="can exceed i128"):
        emit_declarative_spec(SUM_AB, SCHEMA, _catalog())


def test_a_declared_join_cap_makes_the_refused_sum_emit_and_state_the_requirement() -> None:
    spec = emit_declarative_spec(SUM_AB, SCHEMA, _catalog(caps=(AB_CAP,)))
    assert "pub const JOIN_CAP_a_b: u64 = 68719476736;" in spec
    assert "// JOIN_CAP Cols_a Cols_b k k 68719476736" in spec
    assert "join_tuples_a_b(a, b, 0) <= JOIN_CAP_a_b as int" in spec
    assert "spec fn join_tuples_a_b(" in spec and "spec fn join_tuples_a_b_d1(" in spec
    out = _verify(spec)
    assert "0 errors" in out, out[-1500:]


def test_a_cap_on_other_columns_than_the_query_joins_does_not_apply() -> None:
    other = JoinCap("a", "b", (("tag", "tag"),), 2**36)
    with pytest.raises(FitRefusal, match="can exceed i128"):
        emit_declarative_spec(SUM_AB, SCHEMA, _catalog(caps=(other,)))


def test_a_cap_still_multiplies_the_remaining_tables_unless_they_are_unique() -> None:
    # a-b capped at 2^36, but u (2^31 rows, not unique) multiplies it: 2^67 x 2^75 overflows.
    with pytest.raises(FitRefusal, match="can exceed i128"):
        emit_declarative_spec(SUM_ABU, SCHEMA, _catalog(caps=(AB_CAP,)))
    spec = emit_declarative_spec(SUM_ABU, SCHEMA, _catalog(caps=(AB_CAP,), u_unique=True))
    assert "join_tuples_a_b(" in spec


def test_a_unique_key_the_bound_used_is_required_of_the_data_in_valid_cols() -> None:
    spec = emit_declarative_spec(SUM_ABU, SCHEMA, _catalog(caps=(AB_CAP,), u_unique=True))
    valid_u = spec.split("pub open spec fn valid_cols_u")[1].split("\n}")[0]
    assert "forall|i: int, j: int|" in valid_u and "0 <= i < j <" in valid_u
    out = _verify(spec)
    assert "0 errors" in out, out[-1500:]


def test_facts_the_bound_did_not_need_are_not_required() -> None:
    small = CatalogAssumptions(
        max_rows=8,
        join_caps=(AB_CAP,),
        tables={
            n: TableAssumptions(
                max_rows=8,
                unique_keys=(("k",),),
                columns={"v": ColumnAssumption(max_value_exclusive=CAP_V)} if n == "a" else {},
            )
            for n in SCHEMA
        },
    )
    spec = emit_declarative_spec(SUM_AB, SCHEMA, small)
    assert "JOIN_CAP" not in spec and "0 <= i < j <" not in spec


# ---- the loader asserts them ---------------------------------------------------------------------------------------------

_RUST = """
#![allow(dead_code)]
struct Cols_a {{ n: usize, k: Vec<i64>, tag: Vec<String> }}
struct Cols_b {{ n: usize, k: Vec<i64>, tag: Vec<String> }}
fn main() {{
    let cols_a = Cols_a {{ n: {na}, k: vec!{ka}, tag: vec![String::new(); {na}] }};
    let cols_b = Cols_b {{ n: {nb}, k: vec!{kb}, tag: vec![String::new(); {nb}] }};
{checks}
    println!("ok");
}}
"""


def _run_rust(ka: list[int], kb: list[int], cap: int) -> subprocess.CompletedProcess[str]:
    checks = _join_cap_checks(f"// JOIN_CAP Cols_a Cols_b k k {cap}\n")
    src = _RUST.format(na=len(ka), nb=len(kb), ka=ka, kb=kb, checks=checks)
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "m.rs").write_text(src)
        built = subprocess.run(["rustc", "--edition", "2021", "-o", f"{tmp}/m", f"{tmp}/m.rs"], capture_output=True, text=True)
        assert built.returncode == 0, built.stderr[-1500:]
        return subprocess.run([f"{tmp}/m"], capture_output=True, text=True)


def test_main_accepts_data_within_the_join_cap() -> None:
    done = _run_rust([1, 1, 2], [1, 2, 2], cap=4)  # pairs: (1,1)x1, (1,1)x1, (2,2)x2 -> 4
    assert done.returncode == 0 and "ok" in done.stdout


def test_main_aborts_when_the_join_exceeds_the_cap() -> None:
    done = _run_rust([1, 1, 2], [1, 2, 2], cap=3)
    assert done.returncode != 0 and "exceed the catalog cap 3" in done.stderr


def test_unique_key_assert_rejects_a_duplicate_and_accepts_distinct_keys() -> None:
    vp = (
        "pub open spec fn valid_cols_t(t: &Cols_t) -> bool {\n    &&& t.k@.len() == t.n as int\n"
        "    &&& forall|i: int, j: int| #![trigger t.k@[i], t.k@[j]] 0 <= i < j < t.n as int ==> !(t.k@[i] == t.k@[j])\n}\n"
    )
    checks = "\n".join(_runtime_checks(vp, "t", [("k", "i64")]))
    for keys, ok in (([1, 2, 3], True), ([1, 2, 1], False)):
        src = (
            "fn main() {\n"
            f"    let n_t: usize = {len(keys)};\n    let t_k: Vec<i64> = vec!{keys};\n{checks}\n    println!(\"ok\");\n}}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "m.rs").write_text(src)
            built = subprocess.run(["rustc", "--edition", "2021", "-o", f"{tmp}/m", f"{tmp}/m.rs"], capture_output=True, text=True)
            assert built.returncode == 0, built.stderr[-1500:]
            done = subprocess.run([f"{tmp}/m"], capture_output=True, text=True)
            assert (done.returncode == 0) == ok, done.stderr[-500:]


# ---- the preflight check measures the cap ---------------------------------------------------------------------------------


def _db(a_keys: list[int], b_keys: list[int]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE TABLE a (k BIGINT, v DECIMAL(38,4), tag VARCHAR)")
    con.execute("CREATE TABLE b (k BIGINT, w BIGINT, tag VARCHAR)")
    con.execute("CREATE TABLE u (k BIGINT, z BIGINT)")
    con.executemany("INSERT INTO a VALUES (?, 1, 'x')", [(k,) for k in a_keys])
    con.executemany("INSERT INTO b VALUES (?, 1, 'x')", [(k,) for k in b_keys])
    return con


def _small(cap: int) -> CatalogAssumptions:
    return CatalogAssumptions(
        max_rows=100,
        join_caps=(JoinCap("a", "b", (("k", "k"),), cap),),
        tables={n: TableAssumptions(max_rows=100) for n in SCHEMA},
    )


def test_check_passes_a_conforming_database() -> None:
    assert violations(_small(4), _db([1, 1, 2], [1, 2, 2])) == []  # exactly 4 joined tuples


def test_check_names_the_join_and_the_measured_count_when_the_cap_is_violated() -> None:
    found = violations(_small(3), _db([1, 1, 2], [1, 2, 2]))
    assert len(found) == 1
    assert "join cap a JOIN b ON a.k = b.k" in found[0] and "cap 3" in found[0] and "measured 4" in found[0]


def test_check_reports_a_join_cap_naming_an_absent_column() -> None:
    cat = CatalogAssumptions(
        max_rows=100,
        join_caps=(JoinCap("a", "b", (("nope", "k"),), 10),),
        tables={n: TableAssumptions(max_rows=100) for n in SCHEMA},
    )
    assert any("absent" in v for v in violations(cat, _db([1], [1])))


# ---- the SEC packages ------------------------------------------------------------------------------------------------------


def test_sec_packages_declare_the_num_pre_join_cap() -> None:
    from research_loop.assumption_packages import assumption_package

    for name in ("sec_margin", "sec_margin_dec"):
        caps = assumption_package(name).join_caps
        assert [(c.left, c.right, c.max_tuples) for c in caps] == [("num", "pre", 2**36)]
        assert set(caps[0].equalities) == {("adsh", "adsh"), ("tag", "tag"), ("version", "version")}


def test_sec_margin_still_lists_exactly_45_assumptions() -> None:
    from research_loop.assumption_packages.sec_margin import ASSUMPTIONS

    assert len(ASSUMPTIONS) == 45
