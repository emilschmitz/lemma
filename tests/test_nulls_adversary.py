"""Adversary review of NULL support (manual adversary, Sonnet subagent).

Target: `ColumnAssumption.nullable` (declarative_spec/nulls.py, emit_surface validity vectors, exporter, check.py), branch
aa34bf7. Soundness only. Verdict: research_loop/menus/nulls_ADVERSARY_VERDICT.md.

Method (a differential check of the rewrite, no model agent): the ORIGINAL SQL runs in DuckDB on data with NULLs
(three-valued logic). The REWRITTEN SQL (`_null_rewrite_sql`, two-valued, the statement the emitted spec makes) runs on the
ENCODED data: a NULL cell becomes the default value slot plus a validity column (`x IS NULL` reads `NOT x__v`, a nullable
GROUP BY key is `(valid, value)`). Any difference is a place where the spec states something other than SQL. Queries the
emitter refuses are listed separately: refusal is the correct outcome.
"""

from __future__ import annotations

import random
import re
import struct
import subprocess
from pathlib import Path

import duckdb
import pytest
import sqlglot
from sqlglot import exp

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import _null_rewrite_sql, emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.schema_types import SchemaModel
from research_loop.assumption_packages.check import violations
from research_loop.decl_query_measure import _export_table
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

SCHEMA = {
    "t": {"id": "bigint", "a": "bigint", "b": "bigint", "x": "bigint", "s": "varchar"},
    "u": {"k": "bigint", "m": "bigint"},
}
CAT = CatalogAssumptions(
    max_rows=64,
    tables={
        "t": TableAssumptions(
            max_rows=64,
            columns={"a": ColumnAssumption(nullable=True), "b": ColumnAssumption(nullable=True), "s": ColumnAssumption(nullable=True)},
        ),
        "u": TableAssumptions(max_rows=64, columns={"m": ColumnAssumption(nullable=True)}),
    },
)
NULLABLE = {("t", "a"), ("t", "b"), ("t", "s"), ("u", "m")}


def make_data(rng: random.Random):
    t = [
        (i, rng.choice([None, -1, 0, 1, 2, 3]), rng.choice([None, 0, 1, 2]), rng.randint(0, 3), rng.choice([None, "x", "y", ""]))
        for i in range(rng.randint(0, 9))
    ]
    u = [(rng.randint(0, 3), rng.choice([None, 0, 1, 2])) for _ in range(rng.randint(0, 5))]
    return t, u


def load(con: duckdb.DuckDBPyConnection, t: list, u: list, encoded: bool) -> None:
    if not encoded:
        con.execute("CREATE TABLE t (id BIGINT, a BIGINT, b BIGINT, x BIGINT, s VARCHAR)")
        con.execute("CREATE TABLE u (k BIGINT, m BIGINT)")
        for r in t:
            con.execute("INSERT INTO t VALUES (?,?,?,?,?)", list(r))
        for r in u:
            con.execute("INSERT INTO u VALUES (?,?)", list(r))
        return
    con.execute("CREATE TABLE t (id BIGINT, a BIGINT, b BIGINT, x BIGINT, s VARCHAR, a__v BOOLEAN, b__v BOOLEAN, s__v BOOLEAN)")
    con.execute("CREATE TABLE u (k BIGINT, m BIGINT, m__v BOOLEAN)")
    for i, a, b, x, s in t:
        con.execute(
            "INSERT INTO t VALUES (?,?,?,?,?,?,?,?)",
            [i, 0 if a is None else a, 0 if b is None else b, x, "" if s is None else s, a is not None, b is not None, s is not None],
        )
    for k, m in u:
        con.execute("INSERT INTO u VALUES (?,?,?)", [k, 0 if m is None else m, m is not None])


def encode_sql(rewritten: str, key_cols: set[str]) -> str:
    tree = sqlglot.parse_one(rewritten)

    def fn(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Is) and isinstance(node.expression, exp.Null) and isinstance(node.this, exp.Column):
            c = node.this
            return exp.Not(this=exp.column(c.name + "__v", table=c.table or None))
        return node

    tree = tree.transform(fn)
    group = tree.args.get("group")
    if group is not None:

        def key(node: exp.Expression) -> exp.Expression:
            if isinstance(node, exp.Column) and node.name in key_cols and not node.find_ancestor(exp.Is):
                return sqlglot.parse_one(f"CASE WHEN {(node.table + '.') if node.table else ''}{node.name}__v THEN {node.sql()} END")
            return node

        tree.set("group", group.transform(key))
        tree.set(
            "expressions",
            [
                e.transform(key) if isinstance(e, exp.Column) or (isinstance(e, exp.Alias) and isinstance(e.this, exp.Column)) else e
                for e in tree.expressions
            ],
        )
    return tree.sql()


def norm(rows: list, ordered: bool) -> list:
    rows = [tuple(r) for r in rows]
    return rows if ordered else sorted(rows, key=repr)


def differs(sql: str, trials: int = 150, seed: int = 1):
    """None when the rewrite is equivalent on `trials` random tables, else (t, u, duckdb rows, encoded rows)."""
    rewritten = _null_rewrite_sql(sql, SCHEMA, CAT)
    tree = sqlglot.parse_one(sql)
    group = tree.args.get("group")
    gcols: set[str] = set()
    if group is not None:
        gcols = {c.name for c in group.find_all(exp.Column) if ("t", c.name) in NULLABLE or ("u", c.name) in NULLABLE}
    enc = encode_sql(rewritten, gcols)
    ordered = "ORDER BY" in sql.upper()
    rng = random.Random(seed)
    for _ in range(trials):
        t, u = make_data(rng)
        c1, c2 = duckdb.connect(), duckdb.connect()
        load(c1, t, u, False)
        load(c2, t, u, True)
        r1 = norm(c1.execute(sql).fetchall(), ordered)
        r2 = norm(c2.execute(enc).fetchall(), ordered)
        if r1 != r2:
            return t, u, r1, r2
    return None


def accepted(sql: str) -> bool:
    try:
        emit_declarative_spec(sql, SCHEMA, CAT)
    except DeclarativeUnsupported:
        return False
    return True


EQUIVALENT = [
    "SELECT COUNT(*) AS c FROM t WHERE a > 1",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (a > 1)",
    "SELECT COUNT(*) AS c FROM t WHERE a <> b",
    "SELECT COUNT(*) AS c FROM t WHERE a = b",
    "SELECT COUNT(*) AS c FROM t WHERE a > 1 OR b > 1",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (a > 1 OR b > 1)",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (a > 1 AND b > 1)",
    "SELECT COUNT(*) AS c FROM t WHERE a > 1 OR a IS NULL",
    "SELECT COUNT(*) AS c FROM t WHERE a IS NULL OR b IS NULL",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (a IS NULL)",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (a > 1 AND b IS NULL)",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (a IS NULL OR b > 1)",
    "SELECT COUNT(*) AS c FROM t WHERE NOT ((a > 1 OR b > 1) AND (a < 3 OR b < 1))",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (a > 1 AND false)",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (a > 1 OR true)",
    "SELECT COUNT(*) AS c FROM t WHERE a IN (1, 2)",
    "SELECT COUNT(*) AS c FROM t WHERE a NOT IN (1, 2)",
    "SELECT COUNT(*) AS c FROM t WHERE a BETWEEN 0 AND 2",
    "SELECT COUNT(*) AS c FROM t WHERE a NOT BETWEEN 0 AND 2",
    "SELECT COUNT(*) AS c FROM t WHERE x BETWEEN a AND 2",
    "SELECT COUNT(*) AS c FROM t WHERE a BETWEEN b AND x",
    "SELECT COUNT(*) AS c FROM t WHERE s = 'x'",
    "SELECT COUNT(*) AS c FROM t WHERE s <> 'x'",
    "SELECT COUNT(*) AS c FROM t WHERE s LIKE 'x%'",
    "SELECT COUNT(*) AS c FROM t WHERE s NOT LIKE 'x%'",
    "SELECT COUNT(*) AS c FROM t WHERE s <> 'x' OR s IS NULL",
    "SELECT COUNT(*) AS c FROM t WHERE -a > 1",
    "SELECT SUM(a) AS s FROM t",
    "SELECT SUM(a) AS s, COUNT(a) AS c, COUNT(*) AS n, MIN(a) AS lo, MAX(a) AS hi FROM t",
    "SELECT AVG(a) AS m FROM t",
    "SELECT COUNT(DISTINCT a) AS c FROM t",
    "SELECT SUM(a + b) AS s FROM t",
    "SELECT SUM(-a) AS s FROM t",
    "SELECT SUM(a) AS s FROM t WHERE a > 100",
    "SELECT MAX(a) AS m, MIN(b) AS n FROM t WHERE x = 99",
    "SELECT SUM(a) AS s FROM t WHERE b > 0 OR a > 0",
    "SELECT a, COUNT(*) AS c FROM t GROUP BY a",
    "SELECT a, b, COUNT(*) AS c FROM t GROUP BY a, b",
    "SELECT s, a, COUNT(*) AS c FROM t GROUP BY s, a",
    "SELECT COUNT(*) AS c FROM t GROUP BY a",
    "SELECT x, COUNT(a) AS s FROM t GROUP BY x",
    "SELECT x, COUNT(DISTINCT a) AS s FROM t GROUP BY x",
    "SELECT a, COUNT(*) AS c FROM t GROUP BY a HAVING COUNT(*) > 1",
    "SELECT COUNT(*) AS c FROM t, u WHERE t.a = u.m",
    "SELECT COUNT(*) AS c FROM t WHERE EXISTS (SELECT 1 FROM u WHERE u.m = t.a)",
    "SELECT COUNT(*) AS c FROM t WHERE NOT EXISTS (SELECT 1 FROM u WHERE u.m = t.a)",
    "SELECT COUNT(*) AS c FROM t WHERE a IN (SELECT k FROM u)",
    "SELECT COUNT(*) AS c FROM t WHERE x NOT IN (SELECT m FROM u WHERE m IS NOT NULL)",
    "SELECT COUNT(*) AS c FROM t WHERE x NOT IN (SELECT k FROM u WHERE m > 100)",
    "SELECT COUNT(*) AS c FROM t WHERE a IN (SELECT k FROM u WHERE m > 100)",
    "SELECT COUNT(*) AS c FROM t WHERE NOT EXISTS (SELECT 1 FROM u WHERE u.k = t.a AND u.m > 100)",
    "SELECT COUNT(*) AS c FROM t x JOIN t y ON x.id = y.id WHERE x.a > y.b",
    "SELECT SUM(m) AS s FROM u",
    "SELECT COUNT(m) AS c FROM u",
]


@pytest.mark.parametrize("sql", EQUIVALENT)
def test_the_null_rewrite_states_what_duckdb_computes(sql: str) -> None:
    assert accepted(sql)
    assert differs(sql) is None


# ---- OPEN: the rewrite states something other than SQL ------------------------------------------------------------------

NOT_BETWEEN = [
    "SELECT COUNT(*) AS c FROM t WHERE x NOT BETWEEN a AND 0",
    "SELECT COUNT(*) AS c FROM t WHERE x NOT BETWEEN a AND b",
    "SELECT COUNT(*) AS c FROM t WHERE a NOT BETWEEN b AND 0",
]
NOT_IN_EMPTY = [
    "SELECT COUNT(*) AS c FROM t WHERE a NOT IN (SELECT k FROM u WHERE k > 100)",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (a IN (SELECT k FROM u WHERE m > 100))",
    "SELECT COUNT(*) AS c FROM t WHERE a NOT IN (SELECT k FROM u WHERE m > 100)",
]


@pytest.mark.xfail(strict=True, reason="BUG: F(BETWEEN) needs every nullable operand non-NULL, but x NOT BETWEEN NULL AND 0 is TRUE for x > 0")
@pytest.mark.parametrize("sql", NOT_BETWEEN)
def test_not_between_with_a_nullable_bound(sql: str) -> None:
    assert accepted(sql)
    assert differs(sql, trials=300) is None


@pytest.mark.xfail(strict=True, reason="BUG: `a NOT IN (empty subquery)` is TRUE for NULL a, the rewrite requires a IS NOT NULL")
@pytest.mark.parametrize("sql", NOT_IN_EMPTY)
def test_not_in_an_empty_subquery_keeps_null_cells(sql: str) -> None:
    assert accepted(sql)
    assert differs(sql, trials=300) is None


def test_minimal_witnesses_of_the_two_bugs() -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (id BIGINT, a BIGINT, x BIGINT)")
    con.execute("INSERT INTO t VALUES (0, NULL, 5), (1, NULL, NULL)")
    # x = 5 NOT BETWEEN NULL AND 0  ->  NOT (5 >= NULL AND 5 <= 0) = NOT (NULL AND FALSE) = TRUE
    assert con.execute("SELECT COUNT(*) FROM t WHERE x NOT BETWEEN a AND 0").fetchone() == (1,)
    # NULL NOT IN (empty set) is TRUE
    con.execute("CREATE TABLE u (k BIGINT)")
    assert con.execute("SELECT COUNT(*) FROM t WHERE a NOT IN (SELECT k FROM u)").fetchone() == (2,)


def test_the_emitted_spec_of_not_between_drops_the_row() -> None:
    spec = emit_declarative_spec("SELECT COUNT(*) AS c FROM t WHERE x NOT BETWEEN a AND 0", SCHEMA, CAT)
    row_hit = spec.split("spec fn row_hit")[1].split("\n}")[0]
    assert "t.a__valid@[i0]" in row_hit  # requires a non-NULL: the row (a NULL, x = 5) is not kept, SQL keeps it


# ---- refusals are the correct outcome ----------------------------------------------------------------------------------------

REFUSED = [
    "SELECT COUNT(*) AS c FROM t JOIN u ON t.a = u.k",
    "SELECT COUNT(*) AS c FROM t JOIN u ON t.x = u.m",
    "SELECT COUNT(*) AS c FROM t LEFT JOIN u ON t.a = u.k",
    "SELECT a FROM t ORDER BY a LIMIT 3",
    "SELECT id FROM t ORDER BY a LIMIT 3",
    "SELECT DISTINCT a FROM t",
    "SELECT a, COUNT(*) AS c FROM t GROUP BY a ORDER BY a",
    "SELECT SUM(a) AS s FROM t HAVING SUM(a) > 2",
    "SELECT x, COUNT(*) AS c FROM t GROUP BY x HAVING COUNT(a) > 1",
    "SELECT x, SUM(a) AS s FROM t GROUP BY x",
    "SELECT x, MAX(a) AS s FROM t GROUP BY x",
    "SELECT SUM(a) + 1 AS s FROM t",
    "SELECT COUNT(*) AS c FROM t WHERE a > (SELECT MAX(m) FROM u)",
    "SELECT COUNT(*) AS c FROM t WHERE x IN (SELECT m FROM u)",
    "SELECT COUNT(*) AS c FROM t WHERE x NOT IN (SELECT m FROM u)",
    "SELECT COUNT(*) AS c FROM (SELECT a FROM t) q WHERE a > 1",
    "SELECT SUM(q.a) AS s FROM (SELECT a FROM t) q",
    "SELECT COUNT(*) AS c FROM (SELECT SUM(a) AS s FROM t) q",
    "WITH q AS (SELECT a FROM t) SELECT COUNT(*) AS c FROM q WHERE a > 1",
    "SELECT COUNT(*) AS c FROM t WHERE a IS DISTINCT FROM b",
    "SELECT COUNT(*) AS c FROM t WHERE (a < 1) IS TRUE",
    "SELECT COUNT(*) AS c FROM t WHERE (a < 1) IS UNKNOWN",
    "SELECT COUNT(*) AS c FROM t WHERE a = NULL",
    "SELECT COUNT(*) AS c FROM t WHERE a NOT IN (1, NULL)",
    "SELECT COUNT(*) AS c FROM t WHERE COALESCE(a, 5) > 1",
    "SELECT COUNT(*) AS c FROM t WHERE NULLIF(a, 1) > 0",
    "SELECT SUM(CASE WHEN a > 1 THEN 1 ELSE 5 END) AS s FROM t",
    "SELECT COUNT(*) AS c FROM t UNION ALL SELECT COUNT(*) AS c FROM u",
]


@pytest.mark.parametrize("sql", REFUSED)
def test_what_the_rewrite_cannot_state_is_refused(sql: str) -> None:
    assert not accepted(sql)


# ---- (5) loader and spec text -----------------------------------------------------------------------------------------------


def test_validity_vector_length_is_in_valid_cols_and_asserted_by_the_loader() -> None:
    spec = emit_declarative_spec("SELECT SUM(a) AS s FROM t", SCHEMA, CAT)
    valid = spec.split("pub open spec fn valid_cols_t")[1].split("\n}")[0]
    assert "t.a__valid@.len() == t.n as int" in valid
    program = assemble_declarative_program(spec, "    Vec::new()", column_bins={"t": "/nonexistent/t.bin"})
    assert "t_a__valid.len() == n_t" in program
    main = program.split("fn main()")[1]
    assert main.index("t_a__valid.len() == n_t") < main.index("run_query(")


def test_aggregate_hit_includes_the_validity_bit_and_a_condition_reads_validity_before_the_value() -> None:
    spec = emit_declarative_spec("SELECT SUM(a) AS s FROM t", SCHEMA, CAT)
    assert "t.a__valid@[" in spec
    spec = emit_declarative_spec("SELECT COUNT(*) AS c FROM t WHERE NOT (a > 1)", SCHEMA, CAT)
    row_hit = spec.split("spec fn row_hit")[1].split("\n}")[0]
    assert "t.a__valid@[i0]" in row_hit and row_hit.index("t.a__valid@[i0]") < row_hit.index("t.a@[i0]")


def test_null_group_is_one_group_with_an_option_key() -> None:
    spec = emit_declarative_spec("SELECT a, COUNT(*) AS c FROM t GROUP BY a", SCHEMA, CAT)
    assert "Option<i64>" in spec.split("pub struct OutRow")[1].split("}")[0]


# ---- (6) check.py and the exporter -----------------------------------------------------------------------------------------


def _tiny(null_in_a: bool, nullable_a: bool):
    con = duckdb.connect()
    con.execute("CREATE TABLE t (a BIGINT, b BIGINT)")
    con.execute("INSERT INTO t VALUES (?, 1), (?, 2)", [None if null_in_a else 1, 5])
    cat = CatalogAssumptions(
        max_rows=10, tables={"t": TableAssumptions(max_rows=10, columns={"a": ColumnAssumption(nullable=nullable_a)})}
    )
    return con, cat, violations(cat, con)


def test_check_flags_a_null_in_a_column_not_declared_nullable() -> None:
    _con, _cat, found = _tiny(null_in_a=True, nullable_a=False)
    assert any("t.a: not declared nullable but 1 NULL cells" in f for f in found)
    assert not any("t.b" in f for f in found)


def test_check_accepts_declared_nullable_and_no_null_columns() -> None:
    assert _tiny(null_in_a=True, nullable_a=True)[2] == []
    assert _tiny(null_in_a=False, nullable_a=False)[2] == []
    assert _tiny(null_in_a=False, nullable_a=True)[2] == []  # over-declaring nullable is sound


def test_exporter_refuses_a_null_in_an_undeclared_column_even_without_check_py() -> None:
    """The exporter is the second guard: a check.py false negative cannot reach a proof."""
    con, cat, _ = _tiny(null_in_a=True, nullable_a=False)
    model = SchemaModel.from_caller({"t": {"a": "bigint", "b": "bigint"}}, "t").with_nullable(cat)
    with pytest.raises(ValueError, match="not declare the column nullable"):
        _export_table(con, model, "t", [("a", "i64"), ("b", "i64")])


def test_exporter_writes_validity_bits_and_default_slots_and_handles_all_null_and_empty() -> None:
    for rows, valid in (([None, 7, None], [0, 1, 0]), ([None, None], [0, 0]), ([], [])):
        con = duckdb.connect()
        con.execute("CREATE TABLE t (a BIGINT)")
        for r in rows:
            con.execute("INSERT INTO t VALUES (?)", [r])
        cat = CatalogAssumptions(max_rows=10, tables={"t": TableAssumptions(max_rows=10, columns={"a": ColumnAssumption(nullable=True)})})
        model = SchemaModel.from_caller({"t": {"a": "bigint"}}, "t").with_nullable(cat)
        blob = _export_table(con, model, "t", [("a", "i64"), ("a__valid", "bool")])
        n = struct.unpack_from("<Q", blob, 0)[0]
        assert n == len(rows)
        vals = list(struct.unpack_from(f"<{n}q", blob, 8))
        bits = list(blob[8 + 8 * n : 8 + 9 * n])
        assert bits == valid and all(v == 0 for v, b in zip(vals, bits, strict=True) if not b)  # a NULL slot holds the default


def test_sec_margin_declares_the_seventeen_nullable_columns() -> None:
    from research_loop.assumption_packages import assumption_package

    cat = assumption_package("sec_margin")
    declared = {(t, c) for t, ta in cat.tables.items() for c, ca in ta.columns.items() if ca.nullable}
    assert ("num", "coreg") in declared and ("pre", "stmt") in declared and ("tag", "crdr") in declared
    assert len(declared) == 17


# ---- (7) dictionary + nullable string --------------------------------------------------------------------------------------


def _dict_nullable_export(values: list):
    con = duckdb.connect()
    con.execute("CREATE TABLE t (id BIGINT, s VARCHAR)")
    for i, v in enumerate(values):
        con.execute("INSERT INTO t VALUES (?, ?)", [i, v])
    cat = CatalogAssumptions(
        max_rows=10, tables={"t": TableAssumptions(max_rows=10, columns={"s": ColumnAssumption(nullable=True, max_distinct=300)})}
    )
    model = SchemaModel.from_caller({"t": {"id": "bigint", "s": "varchar"}}, "t").with_nullable(cat)
    blob = _export_table(con, model, "t", [("s", "u16"), ("s__dict", "String"), ("s__valid", "bool")])
    n = struct.unpack_from("<Q", blob, 0)[0]
    off = 8 + 2 * n
    m = struct.unpack_from("<Q", blob, off)[0]
    off += 8
    entries = []
    for _ in range(m):
        ln = struct.unpack_from("<I", blob, off)[0]
        entries.append(blob[off + 4 : off + 4 + ln].decode())
        off += 4 + ln
    return entries, list(blob[off : off + n])


def test_dictionary_plus_nullable_string_exports_a_valid_relation() -> None:
    entries, bits = _dict_nullable_export(["x", None, "y", None, "x"])
    assert bits == [1, 0, 1, 0, 1] and len(set(entries)) == len(entries)


@pytest.mark.xfail(strict=True, reason="the NULL cell's default code 0 is stringified and enters the dictionary as the entry '0'")
def test_dictionary_of_a_nullable_string_holds_only_the_columns_values() -> None:
    entries, _bits = _dict_nullable_export(["x", None, "y", None, "x"])
    assert sorted(entries) == ["x", "y"]


# ---- Verus: the loader with validity vectors verifies ------------------------------------------------------------------------

VERUS = Path("/home/emil/tools/verus/verus")


@pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")
def test_nullable_loader_verifies(tmp_path: Path) -> None:
    spec = emit_declarative_spec("SELECT a, COUNT(*) AS c FROM t GROUP BY a", SCHEMA, CAT)
    stub = "    assume(false);\n    loop invariant true decreases 0int { assume(false); }"
    path = tmp_path / "n.rs"
    path.write_text(assemble_declarative_program(spec, stub, column_bins={"t": str(tmp_path / "t.bin")}))
    guarded = Path(__file__).resolve().parent.parent / "scripts" / "ram" / "verus_guarded.sh"
    proc = subprocess.run([str(guarded), str(path), "--triggers-mode", "silent"], capture_output=True, text=True, check=False)
    out = proc.stdout + proc.stderr
    assert re.search(r"verification results:: \d+ verified, 0 errors", out), out[-1200:]
