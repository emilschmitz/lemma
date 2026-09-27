"""DuckDB catalog measurement against a small file, one assertion per case.

Each case is a real query or a real input to the measurement helpers. The
file covers row counts, exclusive value caps, abs-sum caps, unique keys,
identifier quoting, unsigned integers, and the official pin (max table count).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from db_extension.dataset_config import (
    _quote_duckdb_ident,
    _safe_duckdb_table_name,
    effective_dataset_size,
    table_column_abs_sum_caps,
    table_column_value_caps,
    table_row_counts,
    table_unique_keys,
)
from research_loop.experiment_stream import duckdb_error_is_contention

duckdb = pytest.importorskip("duckdb")


def _build_db(path: Path) -> None:
    con = duckdb.connect(str(path))
    try:
        grid_cols = ", ".join(f"c{i} INTEGER" for i in range(40))
        grid_vals = ", ".join(str(i + 1) for i in range(40))
        con.execute(f"CREATE TABLE grid ({grid_cols})")
        con.execute(f"INSERT INTO grid VALUES ({grid_vals})")

        sum_cols = ", ".join(f"s{i} INTEGER" for i in range(20))
        sum_vals = ", ".join(str(i + 1) for i in range(20))
        con.execute(f"CREATE TABLE sums ({sum_cols})")
        con.execute(f"INSERT INTO sums VALUES ({sum_vals})")

        for i in range(10):
            con.execute(f"CREATE TABLE t{i:02d} (x INTEGER)")
            if i:
                con.execute(f"INSERT INTO t{i:02d} SELECT r FROM range({i}) u(r)")
        con.execute("CREATE VIEW v_skip AS SELECT * FROM t01")

        con.execute('CREATE TABLE odd ("a""b" INTEGER, line INTEGER)')
        con.execute("INSERT INTO odd VALUES (7, 5)")

        con.execute("CREATE TABLE neg (line INTEGER)")
        con.execute("INSERT INTO neg VALUES (-482), (100)")

        con.execute("CREATE TABLE nulls (line INTEGER)")
        con.execute("INSERT INTO nulls VALUES (NULL), (NULL)")

        con.execute("CREATE TABLE empty_t (x INTEGER)")

        con.execute("CREATE TABLE flt (whole DOUBLE, frac DOUBLE)")
        con.execute("INSERT INTO flt VALUES (20.0, 1.5)")

        con.execute("CREATE TABLE ub (n UBIGINT)")
        con.execute("INSERT INTO ub VALUES (9)")

        con.execute("CREATE TABLE ubig (n UBIGINT)")
        con.execute("INSERT INTO ubig VALUES (18446744073709551615)")

        con.execute("CREATE TABLE mixed (line INTEGER, bad DOUBLE)")
        con.execute("INSERT INTO mixed VALUES (5, CAST('NaN' AS DOUBLE))")

        con.execute("CREATE TABLE names (name VARCHAR)")
        con.execute("INSERT INTO names VALUES ('x')")

        con.execute("CREATE TABLE bigsum (v HUGEINT)")
        con.execute("INSERT INTO bigsum VALUES (18446744073709551615)")

        con.execute("CREATE TABLE sub (adsh VARCHAR)")
        con.execute("INSERT INTO sub VALUES ('a'), ('b')")
        con.execute("CREATE TABLE num (adsh VARCHAR)")
        con.execute("INSERT INTO num VALUES ('a'), ('a')")
        con.execute("CREATE TABLE tag (tag VARCHAR, version VARCHAR)")
        con.execute(
            "INSERT INTO tag VALUES ('Assets', '2024'), ('Assets', '2023')"
        )
    finally:
        con.close()


@pytest.fixture(scope="module")
def duck_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("duck") / "integration.duckdb"
    _build_db(path)
    return path


@pytest.fixture
def duck_env(duck_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(duck_path))
    monkeypatch.delenv("LEMMA_DATASET_SIZE", raising=False)
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.delenv("LEMMA_PRIMARY_TABLE", raising=False)
    monkeypatch.delenv("LEMMA_BENCH_TABLE", raising=False)
    return duck_path


def _cases() -> list[tuple]:
    cases: list[tuple] = []
    for i in range(40):
        cases.append((f"cap_c{i}", "value_cap", ("grid", f"c{i}"), i + 2))
    for i in range(20):
        cases.append((f"abs_s{i}", "abs_sum", ("sums", f"s{i}"), i + 2))
    for i in range(10):
        cases.append((f"rows_t{i:02d}", "rows", f"t{i:02d}", i))
    cases.extend(
        [
            ("view_absent", "rows_absent", "v_skip", None),
            ("quoted_col", "value_cap", ("odd", 'a"b'), 8),
            ("quoted_sibling", "value_cap", ("odd", "line"), 6),
            ("neg_abs", "value_cap", ("neg", "line"), 483),
            ("nulls_omitted", "value_absent", ("nulls", "line"), None),
            ("empty_count", "rows", "empty_t", 0),
            ("float_integral", "value_cap", ("flt", "whole"), 21),
            ("float_frac_omitted", "value_absent", ("flt", "frac"), None),
            ("ubigint_small", "value_cap", ("ub", "n"), 10),
            ("ubigint_max_omitted", "value_absent", ("ubig", "n"), None),
            ("nan_sibling", "value_cap", ("mixed", "line"), 6),
            ("nan_omitted", "value_absent", ("mixed", "bad"), None),
            ("varchar_omitted", "value_absent", ("names", "name"), None),
            ("unique_sub", "unique_has", ("sub", ("adsh",)), True),
            ("unique_num_dup", "unique_lacks", "num", None),
            ("unique_tag", "unique_has", ("tag", ("tag", "version")), True),
            ("abs_overflow_omitted", "abs_absent", ("bigsum", "v"), None),
            ("safe_pre", "safe", "pre", True),
            ("safe_empty", "safe", "", False),
            ("safe_space", "safe", "pre sub", False),
            ("safe_quote", "safe", 'a"b', False),
            ("safe_underscore", "safe", "line_order", True),
            ("lock_conflict", "contention", "IO Error: Could not set lock on file", True),
            ("lock_conflicting", "contention", "Conflicting lock is held", True),
            ("lock_database", "contention", "database is locked", True),
            ("not_a_lock", "contention", "Binder Error: column missing", False),
            ("not_a_lock_empty", "contention", "", False),
            ("quote_plain", "quote", "line", '"line"'),
            ("quote_embedded", "quote", 'a"b', '"a""b"'),
            ("official_is_max_table", "official_is_max", None, None),
            ("official_capped_by_env", "official_capped", 3, 3),
        ]
    )
    return cases


CASES = _cases()
assert len(CASES) >= 100, len(CASES)


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_duckdb_integration(case: tuple, duck_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _id, kind, payload, expected = case
    if kind == "value_cap":
        table, column = payload
        caps = table_column_value_caps()
        assert caps is not None
        assert caps[table][column] == expected
    elif kind == "value_absent":
        table, column = payload
        caps = table_column_value_caps() or {}
        assert column not in caps.get(table, {})
    elif kind == "abs_sum":
        table, column = payload
        sums = table_column_abs_sum_caps()
        assert sums is not None
        assert sums[table][column] == expected
    elif kind == "abs_absent":
        table, column = payload
        sums = table_column_abs_sum_caps() or {}
        assert column not in sums.get(table, {})
    elif kind == "rows":
        counts = table_row_counts()
        assert counts is not None
        assert counts[payload] == expected
    elif kind == "rows_absent":
        counts = table_row_counts()
        assert counts is not None
        assert payload not in counts
    elif kind == "unique_has":
        table, key = payload
        keys = table_unique_keys()
        assert keys is not None
        assert key in keys[table]
    elif kind == "unique_lacks":
        keys = table_unique_keys() or {}
        assert payload not in keys
    elif kind == "safe":
        assert _safe_duckdb_table_name(payload) is expected
    elif kind == "contention":
        assert duckdb_error_is_contention(payload) is expected
    elif kind == "quote":
        quoted = _quote_duckdb_ident(payload)
        assert quoted == expected
        con = duckdb.connect(str(duck_env), read_only=True)
        try:
            con.execute(f"SELECT {quoted} FROM odd").fetchone()
        finally:
            con.close()
    elif kind == "official_is_max":
        counts = table_row_counts()
        assert counts is not None
        assert effective_dataset_size() == max(counts.values())
    elif kind == "official_capped":
        monkeypatch.setenv("LEMMA_DATASET_SIZE", str(payload))
        assert effective_dataset_size() == expected
    else:
        raise AssertionError(kind)
