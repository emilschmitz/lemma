"""Differential check of the NULL rewrite, reusable by every test that adds a predicate kind.

The ORIGINAL SQL runs in DuckDB on random tables with NULLs (three-valued logic). The REWRITTEN SQL
(`declarative_spec.emit._null_rewrite_sql`, two-valued, the statement the emitted spec makes) runs on the ENCODED data: a
NULL cell becomes a default value slot plus a validity column (`x IS NULL` reads `NOT x__v`, a nullable GROUP BY key is
`(valid, value)`). The NULL calculus is a host rewrite checked this way, not a trusted lemma: any new predicate kind in
`declarative_spec/nulls.py` must be added to `EQUIVALENT` in tests/test_nulls_adversary.py (or call `assert_equivalent`).
"""

from __future__ import annotations

import random

import duckdb
import sqlglot
from sqlglot import exp

from declarative_spec.emit import _null_rewrite_sql, emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
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


def assert_equivalent(sql: str, trials: int = 300, seed: int = 1) -> None:
    """The emitter accepts `sql` and its rewrite computes what DuckDB computes on `trials` random tables with NULLs."""
    assert accepted(sql), sql
    found = differs(sql, trials=trials, seed=seed)
    assert found is None, (sql, found)
