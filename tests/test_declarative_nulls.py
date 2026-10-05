"""NULL support: nullable columns, three-valued logic, NULL-skipping aggregates (``declarative_spec/nulls.py``).

A column the catalog declares ``nullable`` is loaded with a validity vector ``<col>__valid``. The emitted spec is checked
against DuckDB at rows level (Verus evaluates the spec on rows that contain NULLs), the rewrite is checked as SQL against
DuckDB on random NULL-rich data, and every refusal of a shape that is not stated yet is pinned.
"""

from __future__ import annotations

import random

import duckdb
import pytest
import sqlglot

from declarative_spec.emit import DeclarativeUnsupported, _null_rewrite_sql, emit_declarative_spec
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions
from tests.spec_eval import VERUS, prove_facts

SCHEMA = {"t": {"a": "bigint", "x": "bigint", "y": "bigint", "g": "bigint"}, "u": {"g": "bigint", "w": "bigint"}}


def _catalog(nullable: tuple[str, ...] = ("x", "y")) -> CatalogAssumptions:
    caps = {c: ColumnAssumption(max_value_exclusive=2**20, nullable=c in nullable) for c in ("a", "x", "y", "g")}
    return CatalogAssumptions(
        max_rows=8,
        tables={"t": TableAssumptions(max_rows=8, columns=caps), "u": TableAssumptions(max_rows=8)},
    )


def _emit(sql: str, **kw) -> str:
    return emit_declarative_spec(sql, SCHEMA, _catalog(**kw))


# rows with NULLs in x and y (None); a and g are never NULL
ROWS = [
    {"a": 1, "x": 1, "y": 2, "g": 0},
    {"a": 2, "x": None, "y": 2, "g": 0},
    {"a": 3, "x": 3, "y": None, "g": 1},
    {"a": 4, "x": None, "y": None, "g": 1},
    {"a": 5, "x": 2, "y": 2, "g": 0},
    {"a": 6, "x": 5, "y": 1, "g": 1},
]


def _duck() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (a BIGINT, x BIGINT, y BIGINT, g BIGINT)")
    con.execute("CREATE TABLE u (g BIGINT, w BIGINT)")
    con.executemany("INSERT INTO t VALUES (?, ?, ?, ?)", [(r["a"], r["x"], r["y"], r["g"]) for r in ROWS])
    return con


# ---- the rewrite is DuckDB's three-valued logic -----------------------------------------------------------------------

_PREDICATES = [
    "x > 1",
    "NOT (x > 1)",
    "x IS NULL",
    "x IS NOT NULL AND x > 1",
    "NOT (x > 1 OR y = 2)",
    "NOT (x > 1 AND y < 3)",
    "x = y",
    "x <> y",
    "x + y > 3",
    "x BETWEEN 1 AND 3",
    "NOT (x BETWEEN 1 AND 3)",
    "x IN (1, 2)",
    "x NOT IN (1, 2)",
    "NOT (x IN (1, 2))",
    "(x > 1) OR (a = 2)",
    "(x > 1) OR NOT (a = 2)",
    "x > 1 AND (y IS NULL OR y > 1)",
    "NOT (x IS NULL OR y IS NULL)",
    "(x > 4 OR y > 4) AND NOT (x = 1)",
]


@pytest.mark.parametrize("pred", _PREDICATES)
def test_the_rewritten_where_selects_exactly_the_rows_duckdb_selects(pred: str) -> None:
    con = _duck()
    sql = f"SELECT a FROM t WHERE {pred} ORDER BY a"
    rewritten = _null_rewrite_sql(sql, SCHEMA, _catalog())
    assert pred == 'x IS NULL' or rewritten != sql  # IS NULL already states the NULL test
    # the two-valued SQL, evaluated by DuckDB with `IS NULL` meaning NULL, selects the same rows
    assert con.execute(rewritten).fetchall() == con.execute(sql).fetchall()


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_the_rewrite_is_exact_on_random_null_rich_tables(seed: int) -> None:
    rng = random.Random(seed)
    con = duckdb.connect()
    con.execute("CREATE TABLE t (a BIGINT, x BIGINT, y BIGINT, g BIGINT)")
    con.executemany(
        "INSERT INTO t VALUES (?, ?, ?, ?)",
        [(i, rng.choice([None, 0, 1, 2, 3]), rng.choice([None, 0, 1, 2]), rng.randint(0, 2)) for i in range(60)],
    )
    atoms = ["x > 1", "x = y", "y IS NULL", "x IN (0, 2)", "y BETWEEN 1 AND 2", "x <> 3", "g = 1", "x + y < 3"]
    for _ in range(25):
        parts = [rng.choice(atoms) for _ in range(rng.randint(1, 4))]
        expr = parts[0]
        for p in parts[1:]:
            expr = f"({expr}) {rng.choice(['AND', 'OR'])} {rng.choice(['', 'NOT '])}({p})"
        sql = f"SELECT a FROM t WHERE {expr} ORDER BY a"
        assert con.execute(_null_rewrite_sql(sql, SCHEMA, _catalog())).fetchall() == con.execute(sql).fetchall(), expr


def test_aggregates_skip_null_cells_like_duckdb() -> None:
    con = _duck()
    sql = "SELECT SUM(x) AS s, COUNT(*) AS n, COUNT(x) AS cx, MIN(x) AS lo, MAX(x) AS hi, AVG(x) AS av FROM t WHERE a > 0"
    rewritten = _null_rewrite_sql(sql, SCHEMA, _catalog())
    assert rewritten.count("FILTER") == 5  # every aggregate over x except COUNT(*)
    # FILTER is DuckDB SQL, so the rewrite can be run as is
    assert con.execute(rewritten).fetchall() == con.execute(sql).fetchall()


def test_a_condition_the_rewrite_leaves_alone_is_unchanged_without_nullable_columns() -> None:
    sql = "SELECT COUNT(*) AS c FROM t WHERE a > 1 AND g = 0"
    assert _null_rewrite_sql(sql, SCHEMA, _catalog()) == sql
    assert _null_rewrite_sql("SELECT COUNT(*) AS c FROM t WHERE x > 1", SCHEMA, _catalog(nullable=())) == (
        "SELECT COUNT(*) AS c FROM t WHERE x > 1"
    )


# ---- the spec means it: Verus evaluates the spec on rows with NULLs --------------------------------------------------

needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")


def _count_fact(pred: str) -> tuple[str, list[str]]:
    sql = f"SELECT COUNT(*) AS c FROM t WHERE {pred}"
    want = _duck().execute(sql).fetchone()[0]
    return sql, [f"count_c(t, 0) == {want}int"]


@needs_verus
@pytest.mark.parametrize(
    "pred",
    [
        "x > 1",
        "NOT (x > 1)",
        "x IS NULL",
        "NOT (x > 1 OR y = 2)",
        "x = y",
        "x NOT IN (1, 2)",
        "(x > 1) OR (a = 2)",
        "NOT (x IS NULL OR y IS NULL)",
    ],
)
def test_spec_counts_the_rows_duckdb_counts_with_null_cells(pred: str) -> None:
    sql, facts = _count_fact(pred)
    spec = _emit(sql)
    assert "x__valid" in spec or "y__valid" in spec
    ok, out = prove_facts(spec, {"t": ROWS}, facts)
    assert ok, out[-1500:]
    # control: a wrong count does not prove
    wrong = [f"count_c(t, 0) == {int(facts[0].split('== ')[1].removesuffix('int')) + 1}int"]
    bad, _ = prove_facts(spec, {"t": ROWS}, wrong)
    assert not bad


@needs_verus
def test_spec_sum_and_count_column_skip_null_cells() -> None:
    sql = "SELECT SUM(x) AS s, COUNT(x) AS cx, COUNT(*) AS n FROM t WHERE a > 0"
    s, cx, n = _duck().execute(sql).fetchone()
    spec = _emit(sql)
    ok, out = prove_facts(spec, {"t": ROWS}, [f"sum_s(t, 0) == {s}int", f"count_cx(t, 0) == {cx}int", f"count_n(t, 0) == {n}int"])
    assert ok, out[-1500:]
    assert (cx, n) == (4, 6)  # the data has NULLs, so COUNT(x) differs from COUNT(*)
    bad, _ = prove_facts(spec, {"t": ROWS}, [f"count_cx(t, 0) == {n}int"])  # counting NULL cells is wrong
    assert not bad


# ---- emission, typecheck and the refusals --------------------------------------------------------------------------------


def test_nullable_columns_get_a_validity_vector_in_the_struct_and_valid_cols() -> None:
    spec = _emit("SELECT COUNT(*) AS c FROM t WHERE x > 1")
    struct = spec.split("pub struct Cols_t {")[1].split("}")[0]
    assert "pub x__valid: Vec<bool>," in struct and "pub x: Vec<i64>," in struct
    assert "pub y" not in struct  # y is nullable but this query does not read it
    valid = spec.split("pub open spec fn valid_cols_t")[1].split("\n}")[0]
    assert "t.x__valid@.len() == t.n as int" in valid


def test_is_null_reads_the_validity_bit_only_for_a_nullable_column() -> None:
    spec = _emit("SELECT COUNT(*) AS c FROM t WHERE x IS NULL AND a IS NOT NULL")
    assert "!t.x__valid@[i0]" in spec and "a__valid" not in spec


@pytest.mark.parametrize(
    ("sql", "why"),
    [
        ("SELECT x, COUNT(*) AS c FROM t GROUP BY x HAVING x > 1", "HAVING"),
        ("SELECT x + 1 AS z FROM t WHERE a > 1", "the SELECT list"),
        ("SELECT a FROM t ORDER BY x", "ORDER BY"),
        ("SELECT COUNT(*) AS c FROM t JOIN u ON t.x = u.g", "a JOIN condition"),
        ("SELECT g, SUM(x) AS s FROM t GROUP BY g", "grouped query"),
        ("SELECT g, COUNT(*) AS c FROM t GROUP BY g HAVING SUM(x) > 1", "HAVING"),
        ("SELECT COUNT(*) AS c FROM t WHERE a > (SELECT AVG(x) FROM t)", "outermost SELECT list"),
    ],
)
def test_shapes_that_need_null_group_keys_or_cells_are_refused(sql: str, why: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match=why):
        _emit(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT x, COUNT(*) AS c FROM t WHERE x IS NOT NULL GROUP BY x",
        "SELECT g, SUM(x) AS s FROM t WHERE x IS NOT NULL GROUP BY g",
        "SELECT x FROM t WHERE x IS NOT NULL AND a > 0 ORDER BY x LIMIT 3",
    ],
)
def test_a_nullable_column_proved_not_null_by_the_where_is_usable_as_a_key_or_cell(sql: str) -> None:
    _emit(sql)


@needs_verus
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS c FROM t WHERE x > 1 OR y IS NULL",
        "SELECT SUM(x) AS s, MIN(x) AS lo, MAX(y) AS hi, COUNT(y) AS cy FROM t WHERE a > 1",
        "SELECT g, COUNT(*) AS c, COUNT(x) AS cx FROM t WHERE NOT (y = 2) GROUP BY g",
    ],
)
def test_emitted_specs_typecheck_and_their_host_lemmas_verify(sql: str) -> None:
    from research_loop.scripts.decl_coverage import typecheck

    out = typecheck(_emit(sql), verify=True)
    assert out == "OK", out


# ---- the loader and the exporter ---------------------------------------------------------------------------------------------


def _db_file(tmp_path, rows) -> str:
    path = tmp_path / "n.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (a BIGINT, x BIGINT, y BIGINT, g BIGINT)")
    con.executemany("INSERT INTO t VALUES (?, ?, ?, ?)", [(r["a"], r["x"], r["y"], r["g"]) for r in rows])
    con.close()
    return str(path)


def test_export_writes_the_validity_vector_and_a_default_value_for_a_null_cell(tmp_path) -> None:
    import struct
    from pathlib import Path

    from research_loop.decl_query_measure import write_query_measure

    db = _db_file(tmp_path, ROWS)
    prepared = write_query_measure(
        sql="SELECT SUM(x) AS s, COUNT(x) AS cx FROM t WHERE a > 0",
        schema=SCHEMA,
        catalog=_catalog(),
        db_path=Path(db),
        dest=tmp_path / "out",
    )
    blob = Path(prepared["bins"]["t"]).read_bytes()
    n = struct.unpack_from("<Q", blob, 0)[0]
    assert n == len(ROWS)
    # struct order: a (i64), x (i64), x__valid (bool); y is not read, so it is not exported
    a = struct.unpack_from(f"<{n}q", blob, 8)
    x = struct.unpack_from(f"<{n}q", blob, 8 + 8 * n)
    valid = list(blob[8 + 16 * n : 8 + 17 * n])
    assert len(blob) == 8 + 17 * n
    assert list(a) == [r["a"] for r in ROWS]
    assert valid == [0 if r["x"] is None else 1 for r in ROWS]
    assert list(x) == [0 if r["x"] is None else r["x"] for r in ROWS]  # NULL cells hold the default
    assert prepared["rows"] == [[sum(r["x"] for r in ROWS if r["x"] is not None), 4]]


def test_a_null_in_a_column_the_catalog_does_not_declare_nullable_is_refused(tmp_path) -> None:
    from pathlib import Path

    from research_loop.decl_query_measure import write_query_measure

    db = _db_file(tmp_path, ROWS)
    with pytest.raises(ValueError, match="does not declare the column nullable"):
        write_query_measure(
            sql="SELECT SUM(x) AS s FROM t WHERE a > 0",
            schema=SCHEMA,
            catalog=_catalog(nullable=()),
            db_path=Path(db),
            dest=tmp_path / "out2",
            )


@needs_verus
def test_the_assembled_nullable_program_verifies_its_loader_and_compiles(tmp_path) -> None:
    import re
    import subprocess

    from declarative_spec.assemble import assemble_declarative_program

    spec = _emit("SELECT SUM(x) AS s, COUNT(x) AS cx FROM t WHERE a > 0")
    program = assemble_declarative_program(
        spec, "    assume(false);\n    loop invariant true decreases 0int { assume(false); }",
        column_bins={"t": str(tmp_path / "t.bin")},
    )
    assert "t_x__valid" in program
    src = tmp_path / "q.rs"
    src.write_text(program)
    guard = "/home/emil/projects/lemma-db/.claude/worktrees/agent-addcd33571290f391/scripts/ram/verus_guarded.sh"
    import pathlib

    guard = str(pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh")
    proc = subprocess.run(
        [guard, str(src), "--triggers-mode", "silent", "--compile", "--", "-C", "opt-level=0"],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert re.search(r"verification results:: \d+ verified, 0 errors", proc.stdout + proc.stderr), proc.stdout[-1500:]


# ---- the preflight and the SEC packages --------------------------------------------------------------------------------------


def test_check_names_a_column_that_has_nulls_but_is_not_declared_nullable() -> None:
    from research_loop.assumption_packages.check import violations

    cat = CatalogAssumptions(max_rows=100, tables={"t": TableAssumptions(max_rows=100)})  # nothing declared nullable
    found = violations(cat, _duck())
    assert "t.x: not declared nullable but 2 NULL cells" in found
    assert "t.y: not declared nullable but 2 NULL cells" in found
    assert not any("t.a:" in f or "t.g:" in f for f in found)


def test_check_accepts_nulls_in_the_declared_nullable_columns() -> None:
    from research_loop.assumption_packages.check import violations

    assert violations(_catalog(), _duck()) == []


def test_the_sec_packages_declare_the_nullable_columns_measured_on_the_real_database() -> None:
    from research_loop.assumption_packages import assumption_package
    from research_loop.assumption_packages.sec_margin import NULLABLE_COLUMNS

    assert ("pre", "stmt") in NULLABLE_COLUMNS and ("sub", "fy") in NULLABLE_COLUMNS and ("tag", "crdr") in NULLABLE_COLUMNS
    assert ("num", "value") not in NULLABLE_COLUMNS and ("sub", "form") not in NULLABLE_COLUMNS
    for name in ("sec_margin", "sec_margin_dec"):
        cat = assumption_package(name)
        for table, column in NULLABLE_COLUMNS:
            assert cat.tables[table].columns[column].nullable, (name, table, column)
        flagged = {(t, c) for t, ta in cat.tables.items() for c, ca in ta.columns.items() if ca.nullable}
        assert flagged == set(NULLABLE_COLUMNS)


def test_a_real_sec_style_query_with_nullable_filters_emits() -> None:
    from research_loop.assumption_packages import assumption_package
    from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema

    schema, cat = load_sec_schema(), assumption_package("sec_margin")
    for sql in (
        "SELECT p.report, COUNT(*) AS c FROM pre p WHERE p.stmt = 'BS' GROUP BY p.report",
        "SELECT s.fy, COUNT(*) AS c FROM sub s WHERE s.fy = 2022 AND s.fp = 'FY' GROUP BY s.fy",
        "SELECT t.crdr, COUNT(*) AS c FROM tag t WHERE t.crdr IS NOT NULL GROUP BY t.crdr",
        "SELECT COUNT(*) AS c FROM num n JOIN sub s ON n.adsh = s.adsh WHERE s.sic BETWEEN 4000 AND 4999",
    ):
        emit_declarative_spec(sql, schema, cat)


# ---- what a WHERE proves non-NULL --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "where",
    [
        "x > 1",  # a comparison is neither TRUE nor FALSE for a NULL x
        "NOT (x > 1)",
        "x IN (1, 2) AND a > 0",
        "x BETWEEN 1 AND 3",
        "x IS NOT NULL",
        "NOT (x IS NULL)",
        "(x > 1 OR x < 0) AND a > 0",  # both OR branches settle x
    ],
)
def test_where_conditions_that_prove_a_column_not_null_allow_it_as_a_group_key(where: str) -> None:
    _emit(f"SELECT x, COUNT(*) AS c FROM t WHERE {where} GROUP BY x")


@pytest.mark.parametrize(
    "where",
    ["x > 1 OR a = 2", "x IS NULL", "a > 0", "NOT (x IS NOT NULL)", "x > 1 OR y > 1"],
)
def test_a_group_key_the_where_does_not_prove_non_null_is_an_optional_pair_key(where: str) -> None:
    spec = _emit(f"SELECT x, COUNT(*) AS c FROM t WHERE {where} GROUP BY x")
    assert "(bool, i64)" in spec or "(bool, int)" in spec
    assert "Option<i64>" in spec


@needs_verus
def test_a_group_key_proved_by_a_comparison_counts_like_duckdb() -> None:
    sql = "SELECT x, COUNT(*) AS c FROM t WHERE x > 1 GROUP BY x"
    want = {int(k): int(c) for k, c in _duck().execute(sql).fetchall()}
    spec = _emit(sql)
    facts = [f"count_c(t, 0, {k}) == {v}int" for k, v in want.items()]
    ok, out = prove_facts(spec, {"t": ROWS}, facts)
    assert ok, out[-1500:]
    assert want == {2: 1, 3: 1, 5: 1}


@needs_verus
def test_the_null_group_counts_like_duckdb() -> None:
    sql = "SELECT x, COUNT(*) AS c FROM t GROUP BY x"
    want = {k: int(c) for k, c in _duck().execute(sql).fetchall()}
    spec = _emit(sql)
    facts = [
        f"count_c(t, 0, (false, 0int)) == {want[None]}int" if k is None else f"count_c(t, 0, (true, {k}int)) == {c}int"
        for k, c in want.items()
    ]
    ok, out = prove_facts(spec, {"t": ROWS}, facts)
    assert ok, out[-1500:]
    assert want == {None: 2, 1: 1, 3: 1, 2: 1, 5: 1}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS c FROM sub WHERE countryba = 'US'",
        "SELECT countryba, COUNT(*) AS c FROM sub GROUP BY countryba",
        "SELECT COUNT(*) AS c FROM sub WHERE countryba IS NULL",
    ],
)
def test_a_nullable_string_column_keeps_its_validity_vector_with_dictionary_codes(
    sql: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_loop.scripts.declarative_round import sec_catalog, sec_schema

    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    spec = emit_declarative_spec(sql, sec_schema(), sec_catalog())
    assert "countryba__valid" in spec
