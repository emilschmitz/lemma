"""Order-sensitive check of the pin (round 2 finding 5): the cell SEQUENCE the zero-copy pin yields equals DuckDB's row order, cell by cell.

The proved differential bodies are permutation-invariant (SUM, COUNT); a chunk placed in the wrong order would pass them. This compares every cell in order,
for tables shaped by DELETE, UPDATE, INSERT growth, several storage types, constant vectors and views. No Verus needed: a plain rustc probe over `zero_copy_ffi.rs`.
"""

from __future__ import annotations

import datetime
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _available() -> bool:
    try:
        import sysconfig

        import _duckdb  # noqa: F401

        return (Path(sysconfig.get_config_var("LIBDIR")) / sysconfig.get_config_var("LDLIBRARY")).exists()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _available(), reason="needs the python wheel's libpython (prototype link)")


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    from research_loop.scripts import zero_copy_oneshot as zo

    d = tmp_path_factory.mktemp("probe")
    lib, extra = zo.python_wheel_link(d)
    out = d / "probe"
    r = subprocess.run(
        ["rustc", "-O", "--edition", "2021", str(ROOT / "tests" / "fixtures" / "zero_copy_probe.rs"), "-o", str(out), "-L", str(lib), "-C", f"link-arg=-Wl,-rpath,{lib}", *extra],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr[-1500:]
    return out


def _scaled(v, scale):
    if isinstance(v, Decimal):
        return int(v.scaleb(scale))
    if isinstance(v, datetime.date):
        return (v - datetime.date(1970, 1, 1)).days
    return int(v)


def _compare(probe: Path, tmp: Path, setup: list[str], sql: str, scales: list[int]):
    import duckdb

    db = tmp / "t.duckdb"
    for ext in ("", ".wal"):
        Path(str(db) + ext).unlink(missing_ok=True)
    con = duckdb.connect(str(db))
    for s in setup:
        con.execute(s)
    con.close()
    r = subprocess.run([str(probe), str(db), sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]
    got = [tuple(int(x) for x in ln.split()) for ln in r.stdout.splitlines() if not ln.startswith(("META", "COL", "LENS"))]
    want = [tuple(_scaled(v, sc) for v, sc in zip(row, scales)) for row in duckdb.connect(str(db), read_only=True).execute(sql).fetchall()]
    assert got == want
    return len(got)


N = 130000  # more than one row group (122,880 rows)


def test_decimal_and_integer_columns_come_back_in_row_order(probe, tmp_path):
    assert _compare(probe, tmp_path, [f"CREATE TABLE t AS SELECT ((i * 37) % 100003)::DECIMAL(38,4) v FROM range({N}) r(i)"], "SELECT v FROM t", [4]) == N
    assert _compare(probe, tmp_path, [f"CREATE TABLE t AS SELECT (i % 256 - 128)::TINYINT v, (i % 65536 - 32768)::SMALLINT w FROM range({N}) r(i)"], "SELECT v, w FROM t", [0, 0]) == N


def test_row_order_survives_delete_update_and_insert_growth(probe, tmp_path):
    setup = [
        f"CREATE TABLE t AS SELECT ((i * 37) % 100003)::DECIMAL(18,3) v, i::BIGINT k FROM range({N}) r(i)",
        "DELETE FROM t WHERE k % 7 = 0",
        "UPDATE t SET v = v + 1 WHERE k % 11 = 0",
        "INSERT INTO t VALUES (1.5, 5)",
    ]
    assert _compare(probe, tmp_path, setup, "SELECT v, k FROM t", [3, 0]) > 100000
    grow = ["CREATE TABLE t(v INTEGER)"] + [f"INSERT INTO t SELECT i FROM range({a}, {a + 777}) r(i)" for a in range(0, 777 * 40, 777)]
    assert _compare(probe, tmp_path, grow, "SELECT v FROM t", [0]) == 777 * 40


def test_dates_hugeint_constant_vectors_and_views(probe, tmp_path):
    dates = ["CREATE TABLE t(d DATE)", "INSERT INTO t VALUES ('2020-01-01'), ('1970-01-01'), ('9999-12-31'), ('0001-01-01')"]
    assert _compare(probe, tmp_path, dates, "SELECT d FROM t", [0]) == 4
    huge = ["CREATE TABLE t(h HUGEINT)", "INSERT INTO t SELECT (i::HUGEINT * 1000000007 * 1000000007 * 1000000007) - 12345678901234567890 FROM range(5000) r(i)"]
    assert _compare(probe, tmp_path, huge, "SELECT h FROM t", [0]) == 5000
    const = ["CREATE TABLE t AS SELECT 42::BIGINT v FROM range(100000) r(i)"]
    assert _compare(probe, tmp_path, const, "SELECT v FROM t", [0]) == 100000
    view = ["CREATE TABLE b AS SELECT i::BIGINT x FROM range(100000) r(i)", "CREATE VIEW t AS SELECT 7::BIGINT c, x FROM b"]
    assert _compare(probe, tmp_path, view, "SELECT c, x FROM t", [0, 0]) == 100000
    ordered = ["CREATE TABLE t AS SELECT i::BIGINT v FROM range(100000) r(i)", "CREATE VIEW vv AS SELECT v FROM t ORDER BY v DESC"]
    assert _compare(probe, tmp_path, ordered, "SELECT v FROM vv", [0]) == 100000
