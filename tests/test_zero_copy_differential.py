"""Randomized differential run of the zero-copy path against the copy path and DuckDB (LEMMA_ZERO_COPY).

For each proved shape the zero-copy binary and the native-copy binary (the same body written over a flat Vec) are built ONCE against a database path, then
the database at that path is rewritten with many generated tables (empty, one row, chunk-boundary sizes, more than one row group, constant / sorted /
random / extreme-magnitude / nothing-matches data) and every run must print the same result rows from both binaries, equal to DuckDB's own answer.
Needs verus and the python wheel's libpython (prototype link).
"""

from __future__ import annotations

import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROOFS = ROOT / "tests" / "fixtures" / "declarative_proofs"
VERUS = Path("/home/emil/tools/verus/verus")
GUARD = ROOT / "scripts" / "ram" / "verus_guarded.sh"
SIZES = [0, 1, 2, 2047, 2048, 2049, 4096 + 7, 20000, 123000, 250001]
SEEDS = int(os.environ.get("LEMMA_ZC_DIFF_SEEDS", "3"))


def _available() -> bool:
    try:
        import sysconfig

        import _duckdb  # noqa: F401

        return VERUS.exists() and (Path(sysconfig.get_config_var("LIBDIR")) / sysconfig.get_config_var("LDLIBRARY")).exists()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _available(), reason="needs verus and the python wheel's libpython")

# name -> (spec fixture, zero body, flat body, table, columns (declared == stored), narrow cells, create-table SQL generator, reference SQL, parallel)
CASES = {
    "sum_dec38": dict(
        spec="zero_copy_sum_filter.spec.rs", zero="zero_copy_sum_filter.rs", flat="zero_copy_sum_filter_flat.rs", table="num",
        cols={"value": "DECIMAL(38,4)"}, narrow="0", ref="SELECT SUM(value) FROM num WHERE value > 5000", scale=4,
    ),
    "sum_dec38_parallel": dict(
        spec="zero_copy_sum_filter_parallel.spec.rs", zero="zero_copy_sum_filter_parallel.rs", flat="zero_copy_sum_filter_parallel_flat.rs", table="num",
        cols={"value": "DECIMAL(38,4)"}, narrow="0", ref="SELECT SUM(value) FROM num WHERE value > 5000", scale=4,
    ),
    "count_int": dict(
        spec="zero_copy_count_int.spec.rs", zero="zero_copy_count_int.rs", flat="zero_copy_count_int_flat.rs", table="num",
        cols={"qtrs": "INTEGER"}, narrow="1", ref="SELECT COUNT(*) FROM num WHERE qtrs = 3", scale=0,
    ),
    "sum_two_cols": dict(
        spec="zero_copy_sum_two_cols.spec.rs", zero="zero_copy_sum_two_cols.rs", flat="zero_copy_sum_two_cols_flat.rs", table="lineitem",
        cols={"l_extendedprice": "DECIMAL(15,2)", "l_quantity": "DECIMAL(15,2)"}, narrow="0", ref="SELECT SUM(l_extendedprice) FROM lineitem WHERE l_quantity < 24", scale=2,
    ),
}


def _v_sql(kind: str, cap: int, scale: int, seed: int, salt: int = 0) -> str:
    """SQL for one scaled-integer cell (|cell| <= cap) of row `i`, drawn from a hash of (i, seed): the generation happens inside DuckDB."""
    hi = min(cap, 10**6 * 10**scale)
    h = f"hash(i * 7919 + {seed * 100003 + salt})::HUGEINT"
    if kind == "uniform":
        return f"(({h} % {2 * hi + 1}) - {hi})"
    if kind == "constant":
        return f"{[0, 5001 * 10**scale, 3, 4 * 10**scale][seed % 4]}::HUGEINT"
    if kind == "sorted":
        return f"(({h} % {2 * hi + 1}) - {hi})"  # ordered by the caller
    if kind == "extreme":
        return f"(CASE {h} % 5 WHEN 0 THEN {cap} WHEN 1 THEN {-cap} WHEN 2 THEN {cap - 1} WHEN 3 THEN 0 ELSE 1 END)::HUGEINT"
    if kind == "nothing":
        return f"(({h} % {hi + 4999 * 10**scale + 1}) - {hi})"
    raise ValueError(kind)


def _decimal_sql(v: str, scale: int, prec: int) -> str:
    """The DECIMAL(prec, scale) whose scaled integer is the HUGEINT expression `v` (string composition: `/` on decimals is a double)."""
    return (
        f"((CASE WHEN {v} < 0 THEN '-' ELSE '' END) || (abs({v}) // {10**scale})::VARCHAR || "
        + (f"'.' || lpad((abs({v}) % {10**scale})::VARCHAR, {scale}, '0')" if scale else "''")
        + f")::DECIMAL({prec},{scale})"
    )


def _write_db(path: Path, case: dict, n: int, kind: str, seed: int) -> None:
    import duckdb

    path.unlink(missing_ok=True)
    con = duckdb.connect(str(path))
    order = " ORDER BY 1" if kind == "sorted" else ""
    cols = case["cols"]
    if "value" in cols:
        v = _v_sql(kind, 46116860184273879039999, 4, seed)
        con.execute(f"CREATE TABLE num AS SELECT {_decimal_sql('v', 4, 38)} AS value FROM (SELECT {v} AS v FROM range({n}) t(i){order})")
    elif "qtrs" in cols:
        if kind == "constant":
            e = "3"
        elif kind == "sorted":
            e = f"(hash(i * 7919 + {seed})::HUGEINT % 7)::INTEGER - 3"
        else:
            e = f"[3, 3, 4, 1, -7, 65535, -65535][1 + (hash(i + {seed})::HUGEINT % 7)::INTEGER]::INTEGER"
        con.execute(f"CREATE TABLE num AS SELECT ({e})::INTEGER AS qtrs FROM range({n}) t(i){' ORDER BY 1' if kind == 'sorted' else ''}")
    else:
        p = _v_sql(kind, 999999999999999, 2, seed)
        q = f"[0, 100, 2399, 2400, 2401, 5000, -1][1 + (hash(i * 31 + {seed})::HUGEINT % 7)::INTEGER]::HUGEINT" if kind != "constant" else "100::HUGEINT"
        con.execute(
            f"CREATE TABLE lineitem AS SELECT {_decimal_sql('p', 2, 15)} AS l_extendedprice, {_decimal_sql('q', 2, 15)} AS l_quantity "
            f"FROM (SELECT {p} AS p, {q} AS q FROM range({n}) t(i){order})"
        )
    con.close()


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    sys.path.insert(0, str(ROOT))
    os.environ["LEMMA_ZERO_COPY"] = "1"
    from declarative_spec import zero_copy
    from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
    from declarative_spec.schema_types import SchemaModel
    from research_loop.scripts import zero_copy_oneshot as zo

    out = {}
    for name, c in CASES.items():
        os.environ["LEMMA_NARROW_CELLS"] = c["narrow"]
        d = tmp_path_factory.mktemp(name)
        db = d / "t.duckdb"
        model = SchemaModel.from_caller({c["table"]: c["cols"]}, c["table"])
        spec = (PROOFS / c["spec"]).read_text()
        exes = {}
        for mode, body_file in (("zero_copy", c["zero"]), ("copy", c["flat"])):
            text = (PROOFS / body_file).read_text()
            prog = zero_copy.assemble_zero_copy_program(
                spec, extract_agent_edit(text), helpers=extract_agent_helpers(text), db_path=str(db), schema=model, stored_types=c["cols"], mode=mode
            )
            sub = d / mode
            sub.mkdir()
            rs = sub / "q.rs"
            rs.write_text(prog)
            lib, extra = zo.python_wheel_link(sub)
            b = subprocess.run(
                [str(GUARD), str(rs), "--triggers-mode", "silent", "--rlimit", "3", "--compile", "--", "-C", "opt-level=2", "-L", str(lib), "-C", f"link-arg=-Wl,-rpath,{lib}", *extra],
                capture_output=True, text=True, cwd=sub, timeout=1800,
            )
            assert ", 0 errors" in b.stdout + b.stderr, (b.stdout + b.stderr)[-2000:]
            exes[mode] = sub / "q"
        out[name] = (db, exes)
    return out


def _rows(exe: Path) -> list[str]:
    r = subprocess.run([str(exe)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    return [ln for ln in r.stdout.splitlines() if ln.startswith("ROW")]


@pytest.mark.parametrize("name", list(CASES))
def test_zero_copy_equals_copy_equals_duckdb_on_generated_tables(built, name):
    import duckdb

    c = CASES[name]
    db, exes = built[name]
    checked = 0
    for kind in ("uniform", "constant", "sorted", "extreme", "nothing"):
        for n in SIZES:
            if kind in ("sorted", "extreme", "nothing") and n not in (0, 2049, 20000, 123000):
                continue
            for seed in range(SEEDS if n < 100000 else 1):
                _write_db(db, c, n, kind, seed)
                zero, copy = _rows(exes["zero_copy"]), _rows(exes["copy"])
                assert zero == copy, (name, kind, n, seed, zero, copy)
                want = duckdb.connect(str(db), read_only=True).execute(c["ref"]).fetchone()[0]
                got = zero[0].removeprefix("ROW").strip()
                if want is None:
                    assert got == "NULL", (name, kind, n, seed, got)
                else:
                    scaled = int(want * 10 ** c["scale"]) if c["scale"] else int(want)
                    assert int(got) == scaled, (name, kind, n, seed, got, want)
                checked += 1
    assert checked >= 30
