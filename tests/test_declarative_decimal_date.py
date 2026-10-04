"""Native DATE (days since 1970-01-01) and DECIMAL(p,s) (scaled integer) in the declarative path.

Three kinds of check, all against DuckDB:
* the SQL rewrite to exact integer SQL gives the same rows as the original query, on random data;
* the emitted spec of official TPC-H Q6 is satisfied by a Verus-proved body whose compiled binary
  prints DuckDB's (non-empty) answer;
* Q1 and Q3 emit, type-check, and their integer SQL agrees with DuckDB on a TPC-H subset.
"""

from __future__ import annotations

import datetime as dt
import random
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.bench import rows_from_stdout_general, rows_match_error
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.emit_date import SPEC_CIVIL_FNS
from declarative_spec.numeric_rewrite import rewrite_numeric
from declarative_spec.pipeline import run_declarative_metrics
from declarative_spec.schema_types import classify_sql_type
from research_loop.decl_query_measure import _canon, _time_query, decimal_scaled, write_query_measure
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions
from scripts.export_tpch import export_tpch_duckdb

VERUS = Path("/home/emil/tools/verus/verus")
EPOCH = dt.date(1970, 1, 1)

# ---- the type model ------------------------------------------------------------------------


def test_decimal_column_is_a_scaled_integer_i64_up_to_18_digits() -> None:
    info = classify_sql_type("DECIMAL(15, 2)")
    assert (info.exec_rust, info.scale, info.precision, info.spec_as) == ("i64", 2, 15, "int")
    assert info.cell_exclusive_cap == 10**15
    assert classify_sql_type("decimal(18,18)").exec_rust == "i64"


def test_wide_decimal_is_i128_and_bare_decimal_is_duckdbs_18_3() -> None:
    wide = classify_sql_type("DECIMAL(19,4)")
    assert (wide.exec_rust, wide.scale) == ("i128", 4)
    bare = classify_sql_type("decimal")
    assert (bare.precision, bare.scale, bare.exec_rust) == (18, 3, "i64")
    assert classify_sql_type("numeric(9)").scale == 0


@pytest.mark.parametrize("bad", ["decimal(39,2)", "decimal(5,6)", "decimal(0,0)"])
def test_impossible_decimal_is_refused(bad: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        classify_sql_type(bad)


def test_date_column_is_i32_days() -> None:
    info = classify_sql_type("DATE")
    assert (info.exec_rust, info.is_date, info.spec_as) == ("i32", True, "int")


# ---- the rewrite to exact integer SQL ----------------------------------------------------------

SCHEMA = {
    "t": {
        "d": "decimal(15,2)",
        "e": "decimal(10,3)",
        "i": "integer",
        "f": "double",
        "dt": "date",
        "dt2": "date",
        "s": "varchar",
        "k": "integer",
    }
}


def _sql(sql: str) -> str:
    return rewrite_numeric(sql, SCHEMA)[0]


def _scales(sql: str) -> list[int]:
    return rewrite_numeric(sql, SCHEMA)[1]


@pytest.mark.parametrize(
    ("sql", "fragment"),
    [
        ("SELECT COUNT(*) AS c FROM t WHERE d >= 0.05", "d >= 5"),
        ("SELECT COUNT(*) AS c FROM t WHERE d = 1", "d = 100"),
        ("SELECT COUNT(*) AS c FROM t WHERE 0.5 < d", "50 < d"),
        ("SELECT COUNT(*) AS c FROM t WHERE i > 0.5", "i * 10 > 5"),
        ("SELECT COUNT(*) AS c FROM t WHERE d < e", "d * 10 < e"),
        ("SELECT COUNT(*) AS c FROM t WHERE d BETWEEN 0.06 - 0.01 AND 0.06 + 0.01", "d BETWEEN 6 - 1 AND 6 + 1"),
        ("SELECT COUNT(*) AS c FROM t WHERE d IN (0.05, 1)", "d IN (5, 100)"),
        ("SELECT COUNT(*) AS c FROM t WHERE d > 0.055", "d * 10 > 55"),
    ],
)
def test_decimal_compare_is_exact_integer_arithmetic(sql: str, fragment: str) -> None:
    assert fragment in _sql(sql)


@pytest.mark.parametrize(
    ("expr", "scale"),
    [
        ("d", 2),
        ("e", 3),
        ("i", 0),
        ("d * (1 - d)", 4),
        ("d * (1 - d) * (1 + d)", 6),
        ("d + e", 3),
        ("d - 1", 2),
        ("d * 3", 2),
        ("d * 0.5", 3),
        ("d * e", 5),
        ("d * i", 2),
        ("i * i", 0),
    ],
)
def test_sum_scale_is_the_scale_duckdb_returns(expr: str, scale: int) -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (d DECIMAL(15,2), e DECIMAL(10,3), i INTEGER)")
    con.execute("INSERT INTO t VALUES (1.50, 2.125, 7)")
    duck_type = con.execute(f"SELECT typeof(SUM({expr})) FROM t").fetchone()[0]
    duck_scale = int(duck_type.split(",")[1].rstrip(")")) if duck_type.startswith("DECIMAL") else 0
    assert duck_scale == scale
    assert _scales(f"SELECT SUM({expr}) AS s FROM t") == [scale]


def test_min_max_keep_the_scale_and_count_has_none() -> None:
    assert _scales("SELECT MIN(d) AS a, MAX(e) AS b, COUNT(*) AS c FROM t") == [2, 3, 0]


@pytest.mark.parametrize(
    ("sql", "why"),
    [
        ("SELECT SUM(d / 2) AS s FROM t", "division"),
        ("SELECT SUM(d * f) AS s FROM t", "float column"),
        ("SELECT COUNT(*) AS c FROM t WHERE f > d", "float column"),
        ("SELECT COUNT(*) AS c FROM t WHERE dt > 5", "DATE compared"),
        ("SELECT COUNT(*) AS c FROM t WHERE dt = i", "DATE compared"),
        ("SELECT COUNT(*) AS c FROM t WHERE dt >= 'last tuesday'", "YYYY-MM-DD"),
        ("SELECT SUM(dt) AS s FROM t", "SUM over a date"),
        ("SELECT SUM(dt + 1) AS s FROM t", "date"),
        ("SELECT COUNT(*) AS c FROM t WHERE dt + INTERVAL 1 DAY > DATE '2000-01-01'", "INTERVAL"),
        ("SELECT SUM(d * 1e3) AS s FROM t", "plain decimals"),
        ("SELECT SUM(CASE WHEN k > 1 THEN d ELSE 1.5 END) AS s FROM t", "CASE"),
        ("SELECT COUNT(*) AS c FROM t WHERE EXTRACT(year FROM i) = 1", "EXTRACT needs a DATE"),
    ],
)
def test_what_is_not_exactly_representable_is_refused(sql: str, why: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match=why):
        rewrite_numeric(sql, SCHEMA)


def test_scale_beyond_38_digits_is_refused() -> None:
    sql = "SELECT SUM(" + " * ".join(["e"] * 13) + ") AS s FROM t"  # scale 39
    with pytest.raises(DeclarativeUnsupported, match="scale"):
        rewrite_numeric(sql, SCHEMA)


def test_join_between_columns_of_different_scale_is_refused() -> None:
    schema = {"a": {"x": "decimal(15,2)"}, "b": {"y": "decimal(10,3)"}}
    with pytest.raises(DeclarativeUnsupported, match="join compares"):
        rewrite_numeric("SELECT COUNT(*) AS c FROM a JOIN b ON a.x = b.y", schema)
    # same scale joins as before
    rewrite_numeric("SELECT COUNT(*) AS c FROM a JOIN b ON a.x = b.x", {"a": {"x": "decimal(15,2)"}, "b": {"x": "decimal(9,2)"}})


# ---- dates ----------------------------------------------------------------------------------


def _days(text: str) -> int:
    return (dt.date.fromisoformat(text) - EPOCH).days


def test_date_literals_and_intervals_become_day_numbers() -> None:
    sql = _sql("SELECT COUNT(*) AS c FROM t WHERE dt >= DATE '1994-01-01' AND dt < DATE '1994-01-01' + INTERVAL '1' YEAR")
    assert f"dt >= {_days('1994-01-01')}" in sql
    assert f"dt < {_days('1995-01-01')}" in sql


def test_dates_before_1970_are_negative_day_numbers() -> None:
    assert "dt > -2" in _sql("SELECT COUNT(*) AS c FROM t WHERE dt > DATE '1969-12-30'")
    assert "dt > -365" in _sql("SELECT COUNT(*) AS c FROM t WHERE dt > DATE '1969-01-01'")


def test_a_date_string_compares_as_that_date() -> None:
    assert f"dt <= {_days('1998-09-02')}" in _sql("SELECT COUNT(*) AS c FROM t WHERE dt <= '1998-09-02'")


def test_two_date_columns_compare_as_integers_and_order_by_is_untouched() -> None:
    out = _sql("SELECT dt FROM t WHERE dt < dt2 ORDER BY dt")
    assert "dt < dt2" in out and "ORDER BY dt" in out


_CIVIL_DAYS = [
    "1900-02-28",
    "1900-03-01",
    "1969-12-31",
    "1970-01-01",
    "1996-02-29",
    "2000-02-29",
    "2000-03-01",
    "2024-12-31",
    "2100-02-28",
    "2100-03-01",
    "1600-03-01",
    "9999-12-31",
]


def _civil_program(assertions: list[str]) -> str:
    body = "\n".join(f"    assert({a}) by (compute_only);" for a in assertions)
    return f"use vstd::prelude::*;\nverus! {{\n{SPEC_CIVIL_FNS}\nfn t() {{\n{body}\n}}\n}}\nfn main() {{}}\n"


def _verus_text(program: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(program)
    proc = subprocess.run([str(VERUS), handle.name, "--triggers-mode", "silent"], capture_output=True, text=True, check=False)
    return proc.stdout + proc.stderr


def _civil_assertion(text: str, year: int, month: int, day: int) -> str:
    d = _days(text)
    return f"spec_civil_year({d}int) == {year} && spec_civil_month({d}int) == {month} && spec_civil_day({d}int) == {day}"


def test_civil_from_days_agrees_with_the_calendar_across_leap_and_century_edges() -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    asserts = []
    for text in _CIVIL_DAYS:
        day = dt.date.fromisoformat(text)
        asserts.append(_civil_assertion(text, day.year, day.month, day.day))
    assert "0 errors" in _verus_text(_civil_program(asserts))


def test_civil_from_days_rejects_a_wrong_date() -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    wrong = _civil_assertion("2000-02-29", 2000, 3, 1)  # 2000 is a leap year
    out = _verus_text(_civil_program([wrong]))
    assert "error" in out and "0 errors" not in out


def test_extract_over_a_date_column_uses_the_civil_functions() -> None:
    cat = CatalogAssumptions(max_rows=8, tables={"t": TableAssumptions(max_rows=8)})
    spec = emit_declarative_spec(
        "SELECT y, COUNT(*) AS n FROM (SELECT EXTRACT(year FROM dt) AS y, k FROM t) AS x GROUP BY y", SCHEMA, cat
    )
    assert "spec_civil_year((t.dt@[i0] as int))" in spec
    assert spec.count("spec fn spec_civil_year(") == 1


# ---- the rewrite gives DuckDB's rows, on random data ------------------------------------------


def _random_rows(seed: int, n: int = 40) -> list[tuple]:
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        rows.append(
            (
                Decimal(rng.randint(-99999, 99999)) / 100,
                Decimal(rng.randint(-9999, 9999)) / 1000,
                rng.randint(-5, 5),
                rng.uniform(-3, 3),
                EPOCH + dt.timedelta(days=rng.randint(-800, 800)),
                EPOCH + dt.timedelta(days=rng.randint(-800, 800)),
                rng.choice(["a", "b", "c"]),
                rng.randint(0, 3),
            )
        )
    return rows


def _typed_and_integer_db(rows: list[tuple]) -> tuple[duckdb.DuckDBPyConnection, duckdb.DuckDBPyConnection]:
    typed = duckdb.connect()
    typed.execute(
        "CREATE TABLE t (d DECIMAL(15,2), e DECIMAL(10,3), i INTEGER, f DOUBLE, dt DATE, dt2 DATE, s VARCHAR, k INTEGER)"
    )
    typed.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    ints = duckdb.connect()
    ints.execute(
        "CREATE TABLE t (d HUGEINT, e HUGEINT, i INTEGER, f DOUBLE, dt INTEGER, dt2 INTEGER, s VARCHAR, k INTEGER)"
    )
    ints.executemany(
        "INSERT INTO t VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                decimal_scaled(r[0], 2),
                decimal_scaled(r[1], 3),
                r[2],
                r[3],
                (r[4] - EPOCH).days,
                (r[5] - EPOCH).days,
                r[6],
                r[7],
            )
            for r in rows
        ],
    )
    return typed, ints


def _canon_row(row: tuple, scales: list[int]) -> tuple:
    return tuple(_canon("i128", v, s) if isinstance(v, (Decimal, dt.date)) else v for v, s in zip(row, scales, strict=True))


_EQUIVALENCE_QUERIES = [
    "SELECT SUM(d) AS s, COUNT(*) AS c FROM t WHERE d >= 0.05",
    "SELECT SUM(d * (1 - e)) AS s FROM t WHERE e BETWEEN -0.5 AND 0.5",
    "SELECT k, SUM(d * e) AS s, MIN(d) AS lo, MAX(e) AS hi FROM t GROUP BY k",
    "SELECT COUNT(*) AS c FROM t WHERE d < e",
    "SELECT COUNT(*) AS c FROM t WHERE d = 0.5 OR e = 0.5 OR d IN (0.05, 1, -2.5)",
    "SELECT s, SUM(d + e) AS x, SUM(d - 1) AS y FROM t WHERE i > 0.5 GROUP BY s",
    "SELECT COUNT(*) AS c FROM t WHERE dt >= DATE '1970-01-01' AND dt < DATE '1970-01-01' + INTERVAL '1' YEAR",
    "SELECT COUNT(*) AS c, MIN(dt) AS first, MAX(dt2) AS last FROM t WHERE dt < dt2 AND dt > DATE '1968-02-29' + INTERVAL 1 MONTH",
    "SELECT k, COUNT(*) AS c FROM t WHERE dt <= '1971-06-15' GROUP BY k",
    "SELECT SUM(d * 3) AS a, SUM(d * 0.5) AS b, SUM(i * i) AS c FROM t",
    "SELECT dt, d FROM t WHERE d > 100 ORDER BY dt LIMIT 5",
]


@pytest.mark.parametrize("sql", _EQUIVALENCE_QUERIES)
@pytest.mark.parametrize("seed", [1, 2])
def test_rewritten_integer_sql_returns_duckdbs_rows(sql: str, seed: int) -> None:
    typed, ints = _typed_and_integer_db(_random_rows(seed))
    int_sql, scales = rewrite_numeric(sql, SCHEMA)
    want = sorted(_canon_row(r, scales) for r in typed.execute(sql).fetchall())
    got = sorted(tuple(r) for r in ints.execute(int_sql).fetchall())
    assert want, "the check needs a non-empty answer"
    assert got == want


# ---- the stored columns and the result columns, as DuckDB gives them ------------------------------


def test_decimal_and_date_export_exact_integers_including_i128(tmp_path: Path) -> None:
    db = tmp_path / "m.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE w (a DECIMAL(38,2), b DECIMAL(15,2), d DATE, k INTEGER)")
    big = Decimal("123456789012345678901234567890123456.78")
    con.execute(
        "INSERT INTO w VALUES (?, ?, ?, 1), (?, ?, ?, 2)",
        [big, Decimal("-0.05"), dt.date(1969, 12, 31), Decimal("-" + str(big)), Decimal("1234.50"), dt.date(2024, 2, 29)],
    )
    con.close()
    schema = {"w": {"a": "decimal(38,2)", "b": "decimal(15,2)", "d": "date", "k": "integer"}}
    cat = CatalogAssumptions(max_rows=8, tables={"w": TableAssumptions(max_rows=8)})
    sql = "SELECT SUM(a) AS sa, SUM(b) AS sb, MIN(d) AS first FROM w"
    prepared = write_query_measure(
        sql=sql, schema=schema, catalog=cat, db_path=db, dest=tmp_path / "out"
    )
    blob = Path(prepared["bins"]["w"]).read_bytes()
    assert int.from_bytes(blob[:8], "little") == 2
    # struct field order is alphabetical: a (i128), b (i64), d (i32), k (i64)
    off = 8
    a = [int.from_bytes(blob[off + 16 * j : off + 16 * j + 16], "little", signed=True) for j in range(2)]
    assert a == [12345678901234567890123456789012345678, -12345678901234567890123456789012345678]
    off += 32
    b = [int.from_bytes(blob[off + 8 * j : off + 8 * j + 8], "little", signed=True) for j in range(2)]
    assert b == [-5, 123450]
    off += 16
    d = [int.from_bytes(blob[off + 4 * j : off + 4 * j + 4], "little", signed=True) for j in range(2)]
    assert d == [-1, (dt.date(2024, 2, 29) - EPOCH).days]
    assert prepared["rows"] == [[0, 123445, -1]]


def test_result_columns_match_by_position_not_by_duckdb_name(tmp_path: Path) -> None:
    db = tmp_path / "p.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE q (k INTEGER, v DECIMAL(15,2))")
    con.execute("INSERT INTO q VALUES (1, 1.25), (1, 2.50), (2, 4.00)")
    con.close()
    schema = {"q": {"k": "integer", "v": "decimal(15,2)"}}
    cat = CatalogAssumptions(max_rows=8, tables={"q": TableAssumptions(max_rows=8)})
    # No alias: DuckDB names the column `sum(v)`, the spec field is `sum`.
    prepared = write_query_measure(
        sql="SELECT k, SUM(v) FROM q GROUP BY k", schema=schema, catalog=cat, db_path=db, dest=tmp_path / "o1"
    )
    assert sorted(prepared["rows"]) == [[1, 375], [2, 400]]
    # Aggregate before the key: OutRow follows the SELECT order too.
    swapped = write_query_measure(
        sql="SELECT SUM(v), k FROM q GROUP BY k", schema=schema, catalog=cat, db_path=db, dest=tmp_path / "o2"
    )
    assert sorted(swapped["rows"]) == [[375, 1], [400, 2]]
    spec = emit_declarative_spec("SELECT SUM(v), k FROM q GROUP BY k", schema, cat)
    out_row = spec.split("pub struct OutRow {")[1]
    assert out_row.index("pub sum:") < out_row.index("pub k:")


def test_a_spec_scale_that_is_not_duckdbs_is_refused() -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE q (v DECIMAL(15,2))")
    con.execute("INSERT INTO q VALUES (1.25)")
    assert _time_query(con, "SELECT SUM(v) AS s FROM q", [("s", "i128")], [2])[1] == [[125]]
    with pytest.raises(ValueError, match="scale 3 in the spec"):
        _time_query(con, "SELECT SUM(v) AS s FROM q", [("s", "i128")], [3])
    with pytest.raises(ValueError, match="OutRow has 2"):
        _time_query(con, "SELECT SUM(v) AS s FROM q", [("a", "i128"), ("b", "i128")], [2, 0])


# ---- floats: a configurable epsilon, reported ------------------------------------------------


def test_float_results_match_within_the_relative_tolerance() -> None:
    assert rows_match_error([["9.50000000001"]], [[9.5]], ["float"]) is None
    err = rows_match_error([["9.5001"]], [[9.5]], ["float"])
    assert err is not None and "float tolerance" in err


def test_the_tolerance_is_carried_end_to_end_into_the_results() -> None:
    from declarative_spec.pipeline import _apply_speed_bar

    bar = {"duck_us": 1000, "rows": [[4.0]], "kinds": ["float"]}
    ok = _apply_speed_bar(
        {"status": "SUCCESS", "proof_verified": True, "latency_us": 5, "stdout": "ROW\x1f4.000000001\n"}, bar
    )
    assert ok["status"] == "SUCCESS"
    bad = _apply_speed_bar(
        {"status": "SUCCESS", "proof_verified": True, "latency_us": 5, "stdout": "ROW\x1f4.01\n"}, bar
    )
    assert bad["status"] == "FAILURE"


# ---- TPC-H on native DECIMAL(15,2) and DATE -----------------------------------------------------

Q6 = """SELECT sum(l_extendedprice * l_discount) AS revenue
FROM lineitem
WHERE l_shipdate >= date '1994-01-01'
  AND l_shipdate < date '1994-01-01' + interval '1' year
  AND l_discount BETWEEN 0.06 - 0.01 AND 0.06 + 0.01
  AND l_quantity < 24"""

Q1 = """SELECT l_returnflag, l_linestatus, sum(l_quantity) AS sum_qty, sum(l_extendedprice) AS sum_base_price,
  sum(l_extendedprice * (1 - l_discount)) AS sum_disc_price,
  sum(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge, count(*) AS count_order
FROM lineitem
WHERE l_shipdate <= date '1998-12-01' - interval '90' day
GROUP BY l_returnflag, l_linestatus
ORDER BY l_returnflag, l_linestatus"""

Q3 = """SELECT l_orderkey, sum(l_extendedprice * (1 - l_discount)) AS revenue, o_orderdate, o_shippriority
FROM customer, orders, lineitem
WHERE c_mktsegment = 'BUILDING' AND c_custkey = o_custkey AND l_orderkey = o_orderkey
  AND o_orderdate < date '1995-03-15' AND l_shipdate > date '1995-03-15'
GROUP BY l_orderkey, o_orderdate, o_shippriority
ORDER BY revenue DESC, o_orderdate
LIMIT 10"""

_Q6_WHERE = (
    "l_shipdate >= date '1994-01-01' AND l_shipdate < date '1995-01-01' "
    "AND l_discount BETWEEN 0.05 AND 0.07 AND l_quantity < 24"
)


@pytest.fixture(scope="module")
def tpch_small(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict, CatalogAssumptions]:
    """A small TPC-H database in native types: every query below has a non-empty answer."""
    root = tmp_path_factory.mktemp("tpch")
    try:
        full = export_tpch_duckdb(0.01, root / "full.duckdb", tables=("lineitem", "orders", "customer"))
    except duckdb.Error as exc:
        pytest.skip(f"DuckDB tpch extension unavailable: {exc}")
    small = root / "small.duckdb"
    con = duckdb.connect(str(small))
    con.execute(f"ATTACH '{full}' AS src (READ_ONLY)")
    con.execute(
        f"""CREATE TABLE lineitem AS
        SELECT * FROM (
            (SELECT * FROM src.lineitem WHERE {_Q6_WHERE} ORDER BY l_orderkey, l_linenumber LIMIT 14)
            UNION
            (SELECT * FROM src.lineitem
             WHERE l_shipdate > date '1995-03-15'
               AND l_orderkey IN (SELECT o_orderkey FROM src.orders JOIN src.customer ON c_custkey = o_custkey
                                  WHERE c_mktsegment = 'BUILDING' AND o_orderdate < date '1995-03-15')
             ORDER BY l_orderkey, l_linenumber LIMIT 14)
            UNION
            (SELECT * FROM src.lineitem ORDER BY l_orderkey, l_linenumber LIMIT 22)
        ) ORDER BY l_orderkey, l_linenumber"""
    )
    con.execute(
        "CREATE TABLE orders AS SELECT * FROM src.orders WHERE o_orderkey IN (SELECT l_orderkey FROM lineitem)"
    )
    con.execute(
        "CREATE TABLE customer AS SELECT * FROM src.customer WHERE c_custkey IN (SELECT o_custkey FROM orders)"
    )
    schema = {t: {r[0]: r[1] for r in con.execute(f"DESCRIBE {t}").fetchall()} for t in ("lineitem", "orders", "customer")}
    sizes = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in schema}
    con.close()
    assert max(sizes.values()) <= 64, sizes
    catalog = CatalogAssumptions(max_rows=64, tables={t: TableAssumptions(max_rows=64) for t in schema})
    return small, schema, catalog


def test_tpch_money_and_dates_are_native_types(tpch_small: tuple[Path, dict, CatalogAssumptions]) -> None:
    _db, schema, _cat = tpch_small
    li = schema["lineitem"]
    assert {li[c] for c in ("l_quantity", "l_extendedprice", "l_discount", "l_tax")} == {"DECIMAL(15,2)"}
    assert {li[c] for c in ("l_shipdate", "l_commitdate", "l_receiptdate")} == {"DATE"}
    assert schema["orders"]["o_orderdate"] == "DATE" and schema["orders"]["o_totalprice"] == "DECIMAL(15,2)"


_Q6_BODY = """
    let mut acc: i128 = 0;
    let mut any: bool = false;
    let mut i: usize = lineitem.n;
    while i > 0
        invariant
            i <= lineitem.n,
            valid_cols_lineitem(lineitem),
            acc as int == sum_revenue(lineitem, i as int),
            any <==> (exists|j: int| i as int <= j < lineitem.n as int && #[trigger] row_hit(lineitem, j)),
            -((lineitem.n - i) as int) * 1000000000000000000000000000000 <= acc as int,
            acc as int <= ((lineitem.n - i) as int) * 1000000000000000000000000000000,
        decreases i,
    {
        i = i - 1;
        let hit = lineitem.l_shipdate[i] >= LO_DAY && lineitem.l_shipdate[i] < 9131
            && lineitem.l_discount[i] >= LO_DISC && lineitem.l_discount[i] <= 7
            && lineitem.l_quantity[i] < 2400;
        proof {
            assert(hit == row_hit(lineitem, i as int));
        }
        if hit {
            let p = lineitem.l_extendedprice[i] as i128;
            let d = lineitem.l_discount[i] as i128;
            proof {
                assert(-999999999999999int <= p as int <= 999999999999999int);
                assert(-999999999999999int <= d as int <= 999999999999999int);
                assert(-1000000000000000000000000000000int <= (p as int) * (d as int) <= 1000000000000000000000000000000int)
                    by (nonlinear_arith)
                    requires
                        -999999999999999int <= p as int <= 999999999999999int,
                        -999999999999999int <= d as int <= 999999999999999int;
            }
            let prod: i128 = p * d;
            acc = acc + prod;
            any = true;
        }
    }
    let mut v: Vec<OutRow> = Vec::new();
    v.push(OutRow { revenue: if any { Some(acc) } else { None } });
    v
"""


def _q6_body(lo_day: int = 8766, lo_disc: int = 5) -> str:
    return _Q6_BODY.replace("LO_DAY", str(lo_day)).replace("LO_DISC", str(lo_disc))


def test_q6_proved_body_prints_duckdbs_non_empty_answer(
    tpch_small: tuple[Path, dict, CatalogAssumptions], tmp_path: Path
) -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    db, schema, cat = tpch_small
    spec = emit_declarative_spec(Q6, schema, cat)
    assert "// OUT_SCALES: 4" in spec
    assert "(lineitem.l_discount@[i0] as int) >= 5 && (lineitem.l_discount@[i0] as int) <= 7" in spec
    assert f"(lineitem.l_shipdate@[i0] as int) >= {_days('1994-01-01')}" in spec
    prepared = write_query_measure(sql=Q6, schema=schema, catalog=cat, db_path=db, dest=tmp_path)
    revenue = prepared["rows"][0][0]
    assert revenue is not None and revenue > 0
    assert revenue == decimal_scaled(duckdb.connect(str(db), read_only=True).execute(Q6).fetchone()[0], 4)
    metrics = run_declarative_metrics(
        spec_rs=spec, agent_source=_q6_body(), work_dir=tmp_path / "run", column_bins=prepared["bins"]
    )
    assert metrics["status"] == "SUCCESS" and metrics["proof_verified"], metrics.get("compiler_error", "")[-1500:]
    got = rows_from_stdout_general(metrics["stdout"])
    assert got == [[str(revenue)]]
    assert rows_match_error(got, prepared["rows"], prepared["kinds"]) is None


@pytest.mark.parametrize(
    ("lo_day", "lo_disc"),
    [(8766, 6), (8700, 5)],  # discount from 0.06, or a ship-date window that starts too early
)
def test_q6_body_with_a_different_constant_does_not_prove(
    tpch_small: tuple[Path, dict, CatalogAssumptions], tmp_path: Path, lo_day: int, lo_disc: int
) -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    _db, schema, cat = tpch_small
    spec = emit_declarative_spec(Q6, schema, cat)
    metrics = run_declarative_metrics(
        spec_rs=spec, agent_source=_q6_body(lo_day, lo_disc), work_dir=tmp_path / "run"
    )
    assert metrics["status"] == "FAILURE" and not metrics["proof_verified"]


def _integer_copy(con: duckdb.DuckDBPyConnection, schema: dict) -> duckdb.DuckDBPyConnection:
    """The tables as stored for the spec: DATE as days, DECIMAL as the scaled integer."""
    ints = duckdb.connect()
    for table, cols in schema.items():
        select, defs = [], []
        for col, sql_type in cols.items():
            info = classify_sql_type(sql_type)
            if info.is_date:
                select.append(f'("{col}" - DATE \'1970-01-01\') AS "{col}"')
                defs.append(f'"{col}" INTEGER')
            elif info.precision is not None:
                select.append(f'CAST("{col}" * {10**info.scale} AS HUGEINT) AS "{col}"')
                defs.append(f'"{col}" HUGEINT')
            else:
                select.append(f'"{col}"')
                defs.append(f'"{col}" {sql_type}')
        rows = con.execute(f"SELECT {', '.join(select)} FROM {table}").fetchall()
        ints.execute(f'CREATE TABLE {table} ({", ".join(defs)})')
        ints.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' for _ in cols)})", rows)
    return ints


@pytest.mark.parametrize("name", ["Q1", "Q3", "Q6"])
def test_official_query_integer_form_returns_duckdbs_non_empty_rows(
    tpch_small: tuple[Path, dict, CatalogAssumptions], name: str
) -> None:
    db, schema, _cat = tpch_small
    sql = {"Q1": Q1, "Q3": Q3, "Q6": Q6}[name]
    con = duckdb.connect(str(db), read_only=True)
    int_sql, scales = rewrite_numeric(sql, schema)
    want = [_canon_row(r, scales) for r in con.execute(sql).fetchall()]
    got = [tuple(r) for r in _integer_copy(con, schema).execute(int_sql).fetchall()]
    assert want and all(any(cell for cell in row) for row in want)
    assert got == want  # same rows, same ORDER BY order


@pytest.mark.parametrize(("name", "scales"), [("Q1", "0,0,2,2,4,6,0"), ("Q3", "0,4,0,0"), ("Q6", "4")])
def test_official_query_spec_states_the_result_scales_and_type_checks(
    tpch_small: tuple[Path, dict, CatalogAssumptions], name: str, scales: str
) -> None:
    _db, schema, cat = tpch_small
    spec = emit_declarative_spec({"Q1": Q1, "Q3": Q3, "Q6": Q6}[name], schema, cat)
    assert f"// OUT_SCALES: {scales}\npub struct OutRow" in spec
    if VERUS.is_file():
        program = assemble_declarative_program(spec, "    Vec::new()")
        with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
            handle.write(program)
        proc = subprocess.run(
            [str(VERUS), handle.name, "--no-verify", "--triggers-mode", "silent"], capture_output=True, text=True, check=False
        )
        assert "error" not in proc.stdout + proc.stderr, proc.stdout + proc.stderr


def test_q1_with_avg_over_a_decimal_emits_the_average_in_natural_units(
    tpch_small: tuple[Path, dict, CatalogAssumptions],
) -> None:
    _db, schema, cat = tpch_small
    spec = emit_declarative_spec(
        Q1.replace("count(*)", "avg(l_quantity) AS avg_qty, count(*)"), schema, cat
    )
    assert "avg_avg_qty" in spec and "* 100real" in spec  # l_quantity is DECIMAL(15,2)
    assert "pub avg_qty: f64" in spec


def test_q3_result_has_date_keys_that_measure_as_day_numbers(
    tpch_small: tuple[Path, dict, CatalogAssumptions], tmp_path: Path
) -> None:
    db, schema, cat = tpch_small
    prepared = write_query_measure(sql=Q3, schema=schema, catalog=cat, db_path=db, dest=tmp_path)
    assert prepared["rows"], "Q3 has a non-empty answer on the subset"
    first = prepared["rows"][0]
    assert first[1] > 0 and first[2] < _days("1995-03-15")
