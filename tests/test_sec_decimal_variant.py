"""The DECIMAL variant of the SEC database: build, losslessness counts, schema, package, emission."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import duckdb
import pytest

from declarative_spec.emit import emit_declarative_spec
from research_loop.assumption_packages import assumption_package
from research_loop.assumption_packages.check import AssumptionViolation, check_package
from research_loop.assumption_packages.sec_margin import (
    DEC_VALUE_EXCLUSIVE,
    DEC_VALUE_SCALE,
    SEC_NUM_VALUE_EXCLUSIVE,
    VALUE_EXCLUSIVE,
)
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "make_decimal_variant", _ROOT / "holdout" / "gendb_sec_edgar" / "make_decimal_variant.py"
)
assert _spec is not None and _spec.loader is not None
variant = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(variant)


def _double_db(path: Path, values: list[float]) -> Path:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE num (adsh VARCHAR, ddate INTEGER, value DOUBLE)")
    con.execute("CREATE TABLE sub (adsh VARCHAR, fy INTEGER)")
    con.executemany("INSERT INTO num VALUES ('a', 20230101, ?)", [(v,) for v in values])
    con.execute("INSERT INTO sub VALUES ('a', 2023)")
    con.close()
    return path


def _dec_db(tmp_path: Path, values: list[float], scale: int = DEC_VALUE_SCALE) -> Path:
    src = _double_db(tmp_path / "dbl.duckdb", values)
    dest = tmp_path / "dec.duckdb"
    variant.build(src, dest, scale)
    return dest


# ---- build and losslessness ------------------------------------------------------------------


def test_build_types_only_the_double_column_and_copies_everything_else(tmp_path: Path) -> None:
    dest = _dec_db(tmp_path, [1.5, 2.25, -3.0])
    con = duckdb.connect(str(dest), read_only=True)
    types = dict(con.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='num'").fetchall())
    assert types == {"adsh": "VARCHAR", "ddate": "INTEGER", "value": "DECIMAL(38,4)"}
    assert con.execute("SELECT COUNT(*) FROM sub").fetchone() == (1,)
    assert [r[0] for r in con.execute("SELECT CAST(value * 10000 AS BIGINT) FROM num ORDER BY 1").fetchall()] == [-30000, 15000, 22500]


def test_build_refuses_to_overwrite_and_leaves_the_source_untouched(tmp_path: Path) -> None:
    src = _double_db(tmp_path / "dbl.duckdb", [1.0])
    dest = tmp_path / "dec.duckdb"
    variant.build(src, dest, 4)
    with pytest.raises(SystemExit):
        variant.build(src, dest, 4)
    con = duckdb.connect(str(src), read_only=True)
    assert con.execute("SELECT typeof(value) FROM num").fetchone() == ("DOUBLE",)


def test_exact_two_decimal_values_are_lossless(tmp_path: Path) -> None:
    src = _double_db(tmp_path / "dbl.duckdb", [0.1, 0.2, 1234.56, 999997.13])
    con = duckdb.connect(str(src), read_only=True)
    row = variant.losslessness(con, "num", "value", 4)
    assert (row["rounded"], row["beyond_double"], row["max_decimals"]) == (0, 0, 2)


def test_values_past_the_scale_and_past_double_exactness_are_counted(tmp_path: Path) -> None:
    # 0.123456 has 6 decimals: scale 4 rounds it. 1.884e17 * 10^4 is far past 2^53.
    src = _double_db(tmp_path / "dbl.duckdb", [0.123456, 1.5, 1.884e17])
    con = duckdb.connect(str(src), read_only=True)
    row = variant.losslessness(con, "num", "value", 4)
    assert row["rounded"] == 1
    assert row["beyond_double"] == 1
    assert row["max_decimals"] == 6


# ---- schema ----------------------------------------------------------------------------------


def test_schema_follows_the_database_file_for_decimal_columns(tmp_path: Path) -> None:
    dest = _dec_db(tmp_path, [1.0])
    schema = load_sec_schema(dest)
    assert schema["num"]["value"] == "decimal(38,4)"
    assert schema["num"]["ddate"] == "int"  # every other column keeps its schema.sql type
    assert schema["sub"] == load_sec_schema()["sub"]


def test_default_schema_stays_double_and_is_not_mutated_by_a_variant_load() -> None:
    assert load_sec_schema()["num"]["value"] == "double"
    real = _ROOT / "holdout" / "gendb_sec_edgar" / "duckdb" / "sec_edgar_local_dec.duckdb"
    if real.is_file():
        assert load_sec_schema(real)["num"]["value"] == "decimal(38,4)"
        assert load_sec_schema()["num"]["value"] == "double"


# ---- the package -----------------------------------------------------------------------------


def test_decimal_cap_is_the_double_cap_in_stored_units_and_covers_the_measured_maximum() -> None:
    assert DEC_VALUE_EXCLUSIVE == VALUE_EXCLUSIVE * 10**DEC_VALUE_SCALE
    cat = assumption_package("sec_margin_dec")
    col = cat.tables["num"].columns["value"]
    assert (col.max_value_exclusive, col.scale) == (DEC_VALUE_EXCLUSIVE, DEC_VALUE_SCALE)
    # Largest published value 1.884e17 stores as 1.884e21 at scale 4, under the cap.
    assert SEC_NUM_VALUE_EXCLUSIVE * 10**DEC_VALUE_SCALE < DEC_VALUE_EXCLUSIVE
    # The same fact in stored units fits an i128 sum over a two-table row product.
    assert DEC_VALUE_EXCLUSIVE * 2**31 < 2**127
    # The DOUBLE package is unchanged.
    assert assumption_package("sec_margin").tables["num"].columns["value"].max_value_exclusive == VALUE_EXCLUSIVE


def _sec_shaped(tmp_path: Path, values: list[float]) -> tuple[Path, Path]:
    """A tiny database with every table and column the package names, DOUBLE and DECIMAL."""
    src = tmp_path / "sec_dbl.duckdb"
    con = duckdb.connect(str(src))
    schema = (_ROOT / "holdout" / "gendb_sec_edgar" / "schema.sql").read_text()
    schema = re.sub(r"--[^\n]*", "", schema)
    schema = re.sub(r",?\s*FOREIGN KEY\s*\([^)]+\)\s*REFERENCES\s+\w+\([^)]+\)", "", schema)
    schema = re.sub(r"\s*PRIMARY KEY(?!\s*\()", "", schema)
    schema = re.sub(r",\s*PRIMARY KEY\s*\([^)]*\)", "", schema)
    con.execute(schema)
    con.executemany(
        "INSERT INTO num (adsh, tag, version, ddate, qtrs, uom, coreg, value, footnote) "
        "VALUES ('a', 't', 'v', 20230101, 0, 'USD', 'c', ?, 'f')",
        [(v,) for v in values],
    )
    con.close()
    dest = tmp_path / "sec_dec.duckdb"
    variant.build(src, dest, DEC_VALUE_SCALE)
    return src, dest


def test_check_accepts_the_decimal_package_on_the_decimal_database(tmp_path: Path) -> None:
    _, dec = _sec_shaped(tmp_path, [1.5, 999997.13, 1.884e17])
    check_package("sec_margin_dec", str(dec))


def test_check_refuses_a_value_over_the_scaled_cap(tmp_path: Path) -> None:
    # 5e18 >= 2^62 (4.6e18): too big in real units, so too big in stored units too.
    _, dec = _sec_shaped(tmp_path, [1.0, 5e18])
    with pytest.raises(AssumptionViolation, match="value cap < "):
        check_package("sec_margin_dec", str(dec))


def test_check_refuses_a_package_whose_scale_is_not_the_columns(tmp_path: Path) -> None:
    dbl, dec = _sec_shaped(tmp_path, [1.5])
    with pytest.raises(AssumptionViolation, match="units of 10\\^-0"):
        check_package("sec_margin", str(dec))  # raw cap on a DECIMAL column would be a loosened cap
    with pytest.raises(AssumptionViolation, match="units of 10\\^-4"):
        check_package("sec_margin_dec", str(dbl))


# ---- emission on the DECIMAL schema ----------------------------------------------------------

_SCHEMA = {
    "num": {"adsh": "string", "tag": "string", "uom": "string", "ddate": "int", "value": "decimal(38,4)"},
    "sub": {"adsh": "string", "cik": "int", "fy": "int"},
}
_DOUBLE_SCHEMA = {t: {**c, **({"value": "double"} if "value" in c else {})} for t, c in _SCHEMA.items()}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT tag, SUM(value) AS total FROM num WHERE uom = 'USD' GROUP BY tag HAVING SUM(value) > 1000000 "
        "ORDER BY total DESC LIMIT 50",
        "SELECT tag, MAX(value) AS top, MIN(value) AS bottom FROM num WHERE value > 0.5 GROUP BY tag ORDER BY tag LIMIT 50",
        "SELECT s.cik, SUM(n.value) AS total FROM num n JOIN sub s ON n.adsh = s.adsh WHERE s.fy = 2023 "
        "GROUP BY s.cik HAVING SUM(n.value) > 1000000 ORDER BY total DESC LIMIT 100",
    ],
)
def test_gendb_shaped_value_queries_emit_exact_integer_specs(sql: str) -> None:
    spec = emit_declarative_spec(sql, _SCHEMA, assumption_package("sec_margin_dec"))
    assert "pub value: Vec<i128>" in spec
    assert "Vec<f64>" not in spec  # (the host f64 lemma text is always present)
    # every helper the spec calls is defined in it (the DOUBLE MAX spec calls undefined max_row_hit)
    for name in ("max_row_hit", "max_key_at", "min_row_hit", "min_key_at"):
        if re.search(rf"\b{name}\(", spec):
            assert re.search(rf"fn {name}\b", spec), name


def test_avg_of_a_decimal_emits_the_exact_real_quotient() -> None:
    sql = "SELECT tag, AVG(value) AS a FROM num GROUP BY tag LIMIT 5"
    spec = emit_declarative_spec(sql, _SCHEMA, assumption_package("sec_margin_dec"))
    assert "pub value: Vec<i128>" in spec
    assert "FLOAT_ABS_EPS" not in spec



def test_draws_pick_the_package_that_matches_the_database_file(tmp_path: Path) -> None:
    from research_loop.scripts.declarative_draws import package_for_db

    dbl, dec = _sec_shaped(tmp_path, [1.5])
    assert package_for_db(dbl) == "sec_margin"
    assert package_for_db(dec) == "sec_margin_dec"
    check_package(package_for_db(dbl), str(dbl))
    check_package(package_for_db(dec), str(dec))


# ---- the measure export of a DECIMAL(38,4) column --------------------------------------------


def _measure(tmp_path: Path, db: Path, schema: dict, sql: str) -> dict:
    from research_loop.decl_query_measure import write_query_measure

    pkg = "sec_margin_dec" if "decimal" in schema["num"]["value"] else "sec_margin"
    return write_query_measure(
        sql=sql,
        schema=schema,
        catalog=assumption_package(pkg),
        db_path=db,
        dest=tmp_path / "bins",
    )


def _two_col_db(path: Path, values: list[str], sql_type: str) -> Path:
    con = duckdb.connect(str(path))
    con.execute(f"CREATE TABLE num (tag VARCHAR, value {sql_type})")
    con.executemany("INSERT INTO num VALUES ('t', ?)", [(v,) for v in values])
    con.close()
    return path


_MEASURE_SQL = "SELECT tag, SUM(value) AS total FROM num GROUP BY tag LIMIT 10"


def test_exported_decimal_column_is_16_bytes_a_cell_and_double_is_8(tmp_path: Path) -> None:
    values = ["1.5", "2.25", "3.0"]
    dec = _two_col_db(tmp_path / "d.duckdb", values, "DECIMAL(38,4)")
    dbl = _two_col_db(tmp_path / "f.duckdb", values, "DOUBLE")
    schema_dec = {"num": {"tag": "string", "value": "decimal(38,4)"}}
    schema_dbl = {"num": {"tag": "string", "value": "double"}}
    size_dec = Path(_measure(tmp_path, dec, schema_dec, _MEASURE_SQL)["bins"]["num"]).stat().st_size
    size_dbl = Path(_measure(tmp_path / "x", dbl, schema_dbl, _MEASURE_SQL)["bins"]["num"]).stat().st_size
    assert size_dec - size_dbl == 3 * (16 - 8)


def test_a_decimal_beyond_i64_is_exported_and_summed_exactly(tmp_path: Path) -> None:
    # 1.884e17 at scale 4 is 1.884e21 > 2^63: only an i128 holds it. DuckDB's answer is the exact scaled sum.
    values = ["188400000000000000.1234", "0.0001", "-5.5"]
    dec = _two_col_db(tmp_path / "d.duckdb", values, "DECIMAL(38,4)")
    got = _measure(tmp_path, dec, {"num": {"tag": "string", "value": "decimal(38,4)"}}, _MEASURE_SQL)
    assert got["rows"][0][1] == 1884000000000000001234 + 1 - 55000
    assert 1884000000000000001234 > 2**63
