"""research_loop.assumption_packages.check against tiny DuckDBs."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from assumption_db import build_conforming_db

from research_loop.assumption_packages.check import (
    AssumptionViolation,
    check_package,
    violations,
)
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions


def _edit(db: Path, *sql: str) -> None:
    con = duckdb.connect(str(db))
    for s in sql:
        con.execute(s)
    con.close()


def _fails_with(db: Path, *needles: str) -> None:
    with pytest.raises(AssumptionViolation) as exc:
        check_package("sec_margin", str(db))
    for n in needles:
        assert n in str(exc.value)


def test_conforming_db_passes(tmp_path: Path) -> None:
    check_package("sec_margin", str(build_conforming_db(tmp_path / "ok.duckdb")))


def test_value_cap_violation_names_column_and_measured_max(tmp_path: Path) -> None:
    db = build_conforming_db(tmp_path / "v.duckdb")
    _edit(db, "UPDATE pre SET line = 9000")
    _fails_with(db, "pre.line", "9000")


def test_negative_integer_counts_by_magnitude(tmp_path: Path) -> None:
    db = build_conforming_db(tmp_path / "n.duckdb")
    _edit(db, "UPDATE sub SET fy = -5000")
    _fails_with(db, "sub.fy", "5000")


def test_double_truncates_toward_zero_and_negatives_are_zero(tmp_path: Path) -> None:
    db = build_conforming_db(tmp_path / "d.duckdb")
    _edit(db, "ALTER TABLE num ALTER value TYPE DOUBLE", "UPDATE num SET value = -1e30")
    check_package("sec_margin", str(db))  # loaded as 0, under the cap
    _edit(db, f"UPDATE num SET value = {float(2**62)}")
    _fails_with(db, "num.value", str(2**62))


def test_string_cap_violation(tmp_path: Path) -> None:
    db = build_conforming_db(tmp_path / "s.duckdb")
    _edit(db, "UPDATE sub SET fp = 'ninechars'")
    _fails_with(db, "sub.fp", "measured max 9")


def test_row_cap_violation(tmp_path: Path) -> None:
    db = build_conforming_db(tmp_path / "r.duckdb")
    _edit(db, "INSERT INTO sub SELECT * FROM sub")
    con = duckdb.connect(str(db), read_only=True)
    found = violations(CatalogAssumptions(tables={"sub": TableAssumptions(max_rows=1)}), con)
    con.close()
    assert found == ["table sub: row cap 1 < measured 2"]


def test_duplicate_unique_key_violation(tmp_path: Path) -> None:
    db = build_conforming_db(tmp_path / "u.duckdb")
    _edit(db, "INSERT INTO sub SELECT * FROM sub")
    _fails_with(db, "sub unique key ('adsh',)", "2 rows")


def test_composite_unique_key_violation(tmp_path: Path) -> None:
    db = build_conforming_db(tmp_path / "c.duckdb")
    _edit(db, "INSERT INTO tag SELECT * FROM tag")
    _fails_with(db, "tag unique key ('tag', 'version')")


def test_missing_column_is_a_violation(tmp_path: Path) -> None:
    db = build_conforming_db(tmp_path / "m.duckdb")
    _edit(db, "ALTER TABLE sub DROP COLUMN afs")
    _fails_with(db, "sub.afs", "absent")
