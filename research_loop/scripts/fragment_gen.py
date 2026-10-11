"""Random queries from grammar G (docs/SQL_FRAGMENT.md) over a DuckDB file.

    uv run python -m research_loop.scripts.fragment_gen --db sec_edgar_dec.duckdb --seed 7 --n 500 --out q.sql

Joins follow columns that two tables share by name and type (all shared columns form the key). Filter literals are
sampled from the data. A draw is kept only when DuckDB runs it within the time budget, it returns at least one and at
most ``MAX_ROWS`` rows, and its result is not constant. Deterministic per seed. Every kept query is checked against
``declarative_spec.fragment.in_fragment``; a draw outside G is a bug here and raises.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from declarative_spec.fragment import in_fragment

SAMPLE_ROWS = 2000
MAX_ROWS = 100_000
TIMEOUT_SEC = 8.0
NUMERIC = ("int", "decimal", "double")


@dataclass
class Column:
    table: str
    name: str
    kind: str  # int | decimal | double | string | date
    pool: list = field(default_factory=list)
    nulls: bool = False

    @property
    def ref(self) -> str:
        return f"{self.table}.{self.name}"

    @property
    def low_card(self) -> bool:
        return bool(self.pool) and len(set(self.pool)) <= 0.2 * len(self.pool)


def _kind(sql_type: str) -> str | None:
    t = sql_type.upper()
    if t.startswith("DECIMAL"):
        return "decimal"
    if t in ("INTEGER", "BIGINT", "SMALLINT", "TINYINT", "HUGEINT"):
        return "int"
    if t in ("DOUBLE", "FLOAT", "REAL"):
        return "double"
    if t in ("VARCHAR", "TEXT"):
        return "string"
    if t == "DATE":
        return "date"
    return None


def _spill_dir(db: Path) -> str:
    """A private spill directory on the disk of the database file (/tmp is RAM here), removed at exit."""
    import atexit
    import shutil

    spill = tempfile.mkdtemp(prefix="spill_", dir=db.parent)
    atexit.register(shutil.rmtree, spill, True)
    return spill


def connect(path: Path, *, threads: int = 2, memory: str = "1GB") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(path), read_only=True)
    # a private spill directory: two processes on one file otherwise share <file>.tmp and delete each other's temp files
    con.execute(f"SET threads={threads}; SET memory_limit='{memory}'; SET temp_directory='{_spill_dir(path)}';")
    return con


def load_columns(path: Path, seed: int) -> dict[str, dict[str, Column]]:
    """Every supported column of every table, each with a sampled value pool (one single-threaded sample per table)."""
    con = connect(path, threads=1)
    out: dict[str, dict[str, Column]] = {}
    for (table,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY 1").fetchall():
        cols = [
            Column(table, name, kind)
            for name, dtype in con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='main' AND table_name=? ORDER BY ordinal_position",
                [table],
            ).fetchall()
            if (kind := _kind(dtype))
        ]
        names = ", ".join(c.name for c in cols)
        rows = con.execute(f"SELECT {names} FROM {table} USING SAMPLE reservoir({SAMPLE_ROWS} ROWS) REPEATABLE ({seed})").fetchall()
        for i, col in enumerate(cols):
            values = [r[i] for r in rows]
            col.nulls = any(v is None for v in values)
            col.pool = sorted((v for v in values if v is not None), key=str)  # sorted: deterministic whatever the scan order
        out[table] = {c.name: c for c in cols}
    con.close()
    return out


def schema_from_db(path: Path) -> dict[str, dict[str, str]]:
    """The declarative transpiler's schema vocabulary (int, double, string, date, decimal(p,s)) read from the file."""
    con = connect(path, threads=1)
    out: dict[str, dict[str, str]] = {}
    for table, column, dtype in con.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema='main' ORDER BY table_name, ordinal_position"
    ).fetchall():
        kind = _kind(dtype)
        if kind:
            out.setdefault(table, {})[column] = dtype.lower().replace(" ", "") if kind == "decimal" else kind
    con.close()
    return out


def literal(col: Column, value) -> str:
    if col.kind == "string":
        return "'" + str(value).replace("'", "''") + "'"
    if col.kind == "date":
        return f"DATE '{value}'"
    if col.kind == "double":
        return repr(float(value))
    if col.kind == "decimal":
        return format(Decimal(value), "f")
    return str(int(value))


class Infeasible(Exception):
    """The wanted constructs cannot be built over this schema/tree; the caller redraws or gives the pair up."""


PRED_SHAPES = ("cmp", "in_list", "between", "is_null", "colcol")
SUBS = ("sub_scalar", "sub_notin", "sub_in", "sub_exists", "sub_notexists")
AGGS = ("sum", "avg", "min", "max", "count_star", "count_col", "count_distinct", "case_agg", "arith_agg")
FEATURES = (
    ("project", "global", "group", "j1", "j2", "j3", "j4")
    + PRED_SHAPES
    + ("or", "not")
    + SUBS
    + ("having", "order", "limit", "distinct")
    + AGGS
)
_EXCLUSIVE = (("project", "global", "group"), ("j1", "j2", "j3", "j4"))
_AGG_SHAPES = {"group", "global"}


def feasible_pair(a: str, b: str) -> bool:
    """Pairs of constructs that can occur in one query of G (structural rules, not data)."""
    for g in _EXCLUSIVE:
        if a in g and b in g:
            return False
    pair = {a, b}

    if pair & set(AGGS) and "project" in pair:
        return False
    if "having" in pair and pair & {"project", "global"}:
        return False
    if "distinct" in pair and pair & {"global", "group"}:
        return False
    if "order" in pair and "global" in pair or "limit" in pair and "global" in pair:
        return False
    if "distinct" in pair and pair & set(AGGS):
        return False
    if pair & set(SUBS) - {"sub_scalar"} and "j4" in pair:
        return False  # no table left to subquery over
    return True


_NO_SUBS = {"project", "global", "having", "distinct", "avg", "count_distinct", "case_agg", "j3", "j4", *SUBS}
LEVEL_EXCLUDED = {
    "high": _NO_SUBS | {"j2", "arith_agg", "order", "limit"},
    "med": _NO_SUBS | {"order"},  # ORDER BY and LIMIT come together here: 'limit' stands for both
    "full": set(),
}


def feasible_pairs(level: str) -> list[tuple[str, str]]:
    """Feasible pairs of constructs at ``level`` (see docs/SQL_FRAGMENT.md for what each level leaves out)."""
    keep = [f for f in FEATURES if f not in LEVEL_EXCLUDED[level]]
    return [(a, b) for i, a in enumerate(keep) for b in keep[i + 1 :] if feasible_pair(a, b)]


def features(sql: str) -> set[str]:
    """The constructs of G that this query uses (outer block only, plus which subquery kinds occur)."""
    import sqlglot
    from sqlglot import exp

    top = sqlglot.parse_one(sql)
    out: set[str] = set()
    agg_classes = {exp.Sum: "sum", exp.Avg: "avg", exp.Min: "min", exp.Max: "max"}
    group, items = top.args.get("group"), top.expressions
    has_agg = any(isinstance(i.find(exp.AggFunc), exp.AggFunc) for i in items)
    out.add("group" if group else "global" if has_agg else "project")
    out.add(f"j{min(4, 1 + len(top.args.get('joins') or []))}")
    for key, name in (("having", "having"), ("order", "order"), ("limit", "limit"), ("distinct", "distinct")):
        if top.args.get(key):
            out.add(name)
    for item in items:
        inner = item.this if isinstance(item, exp.Alias) else item
        for cls, name in agg_classes.items():
            if isinstance(inner, cls):
                out.add(name)
        if isinstance(inner, exp.Count):
            out.add("count_star" if isinstance(inner.this, exp.Star) else "count_distinct" if isinstance(inner.this, exp.Distinct) else "count_col")
        arg = getattr(inner, "this", None)
        if isinstance(inner, exp.AggFunc) and arg is not None:
            if arg.find(exp.Case):
                out.add("case_agg")
            if isinstance(arg, (exp.Paren, exp.Add, exp.Sub, exp.Mul)):
                out.add("arith_agg")
    where = top.args.get("where")
    if where is not None:
        for node in where.walk():
            if isinstance(node, exp.Select) and node is not top:
                pass
        own = lambda n: n.find_ancestor(exp.Select) is top
        for node in where.find_all(exp.EQ, exp.NEQ, exp.GT, exp.LT, exp.GTE, exp.LTE):
            if not own(node):
                continue
            if isinstance(node.left, exp.Column) and isinstance(node.right, exp.Column):
                out.add("colcol")
            elif isinstance(node.left, exp.Subquery) or isinstance(node.right, exp.Subquery):
                out.add("sub_scalar")
            elif isinstance(node.parent, (exp.Where, exp.And, exp.Or, exp.Not, exp.Paren)):
                out.add("cmp")
        for node in where.find_all(exp.In):
            if own(node):
                negated = isinstance(node.parent, exp.Not)
                out.add(("sub_notin" if negated else "sub_in") if node.args.get("query") else "in_list")
        for node in where.find_all(exp.Exists):
            if own(node):
                out.add("sub_notexists" if isinstance(node.parent, exp.Not) else "sub_exists")
        for node in where.find_all(exp.Between):
            if own(node):
                out.add("between")
        for node in where.find_all(exp.Is):
            if own(node):
                out.add("is_null")
        if any(own(n) for n in where.find_all(exp.Or)):
            out.add("or")
        if any(own(n) and isinstance(n.this, exp.Paren) for n in where.find_all(exp.Not)):
            out.add("not")
    return out


class Drawer:
    def __init__(self, columns: dict[str, dict[str, Column]], rng: random.Random, level: str = "full", nullable: set[tuple[str, str]] = frozenset(), bounds: dict[tuple[str, str], int] | None = None) -> None:
        self.level = level
        self.bounds = bounds or {}  # (table, column) -> exclusive cap from the catalog; int * int is drawn only when the product fits INTEGER (rule T3)
        self.nullable = nullable  # (table, column) the catalog declares nullable: no SUM/MIN/MAX/AVG over them in a grouped query (rule T2)
        self.grouped = False
        self.cols = columns
        self.rng = rng
        self.edges: dict[tuple[str, str], list[tuple[Column, Column]]] = {}
        for a in columns:
            for b in columns:
                if a == b:
                    continue
                pairs = [(columns[a][n], columns[b][n]) for n in columns[a] if n in columns[b] and columns[a][n].kind == columns[b][n].kind]
                if pairs:
                    self.edges[(a, b)] = pairs

    def pick(self, items, weights=None):
        return self.rng.choices(items, weights)[0] if weights else self.rng.choice(items)

    def join_tree(self, size: int) -> tuple[list[str], list[str]]:
        """Tables and their ``JOIN ... ON`` clauses."""
        tables = [self.pick(sorted(self.cols))]
        joins: list[str] = []
        while len(tables) < size:
            options = sorted((a, b) for (a, b) in self.edges if a in tables and b not in tables)
            if not options:
                raise Infeasible(f"join of {size} tables")
            a, b = self.pick(options)
            on = " AND ".join(f"{x.ref} = {y.ref}" for x, y in self.edges[(a, b)])
            tables.append(b)
            joins.append(f"JOIN {b} ON {on}")
        return tables, joins

    def predicate(self, tables: list[str], shape: str | None = None) -> str:
        pool = [c for t in tables for c in self.cols[t].values() if c.pool]
        if shape == "is_null":
            pool = [c for c in pool if c.nulls]
            if not pool:
                raise Infeasible("no nullable column")
        if shape == "between":
            pool = [c for c in pool if c.kind != "string" and len(c.pool) > 1]
        col = self.pick(pool)
        ref = col.ref
        lit = lambda: literal(col, self.pick(col.pool))
        if shape is None:
            if col.nulls and self.rng.random() < 0.15:
                shape = "is_null"
            else:
                shape = self.pick(["cmp", "in_list", "between", "colcol"], [5, 2, 2 if col.kind != "string" else 0, 1])
        if shape == "is_null":
            return f"{ref} IS {'NOT ' if self.rng.random() < 0.5 else ''}NULL"
        if shape == "in_list":
            vals = sorted({lit() for _ in range(self.rng.randint(1, 4))})
            return f"{ref} {'NOT ' if self.rng.random() < 0.2 else ''}IN ({', '.join(vals)})"
        if shape == "between":
            lo, hi = sorted(self.rng.sample(col.pool, 2))
            return f"{ref} BETWEEN {literal(col, lo)} AND {literal(col, hi)}"
        if shape == "colcol":
            same = [c for t in tables for c in self.cols[t].values() if c.kind == col.kind and c.pool and c.ref != ref]
            if not same:
                raise Infeasible("no second column of the same type")
            op = self.pick(["=", "<>", "<", "<=", ">", ">="] if col.kind != "string" else ["=", "<>"])
            return f"{ref} {op} {self.pick(same).ref}"
        ops = ["=", "<>"] if col.kind == "string" else ["=", "<>", "<", "<=", ">", ">="]
        return f"{ref} {self.pick(ops)} {lit()}"

    def boolean(self, tables: list[str], shapes: list[str | None], *, use_or: bool = False, use_not: bool = False) -> str:
        """Predicates joined by AND/OR; ``use_or`` makes at least one OR, ``use_not`` wraps one predicate in NOT (...)."""
        terms = [self.predicate(tables, s) for s in shapes]
        if use_not:
            i = self.rng.randrange(len(terms))
            terms[i] = f"NOT ({terms[i]})"
        expr = terms[0]
        ors = [use_or and i == 1 for i in range(len(terms))]
        for i, term in enumerate(terms[1:], 1):
            op = "OR" if ors[i] else self.pick(["AND", "OR"], [3, 1])
            expr = f"({expr} {op} {term})"
        return expr

    def numeric_expr(self, tables: list[str], form: str | None = None) -> str | None:
        nums = [c for t in tables for c in self.cols[t].values() if c.kind in NUMERIC and c.pool and not self._skip(c)]
        if not nums:
            return None
        a = self.pick(nums)
        form = form or self.pick(["col", "colcol", "collit", "case"], [4, 2, 2, 2])
        if form == "colcol":
            b = self.pick(nums)
            ops = ["+", "-"]
            if "int" not in (a.kind, b.kind) or (self.bounds.get((a.table, a.name), 2**31) * self.bounds.get((b.table, b.name), 2**31) < 2**31):
                ops.append("*")
            return f"({a.ref} {self.pick(ops)} {b.ref})"
        if form == "collit":
            return f"({a.ref} {self.pick(['+', '-', '*'])} {self.pick([1, 2, 3, 10])})"
        if form == "case":
            return f"CASE WHEN {self.predicate(tables)} THEN {a.ref} ELSE {self.pick([0, 1])} END"
        return a.ref

    def _skip(self, col: Column) -> bool:
        return self.in_agg and self.grouped and (col.table, col.name) in self.nullable

    in_agg = False

    def aggregate(self, tables: list[str], kind: str | None = None) -> str:
        self.in_agg = True
        try:
            return self._aggregate(tables, kind)
        finally:
            self.in_agg = False

    def _aggregate(self, tables: list[str], kind: str | None) -> str:
        full = self.level == "full"
        everything = [c for t in tables for c in self.cols[t].values() if c.pool]
        minmax = [c for c in everything if c.kind != "string" and (full or c.kind != "double") and not self._skip(c)]  # rule T1
        nums = [c for c in everything if c.kind in NUMERIC and not self._skip(c)]
        kind = kind or self.pick(list(AGGS[:7]), [4, 2 if full else 0, 2, 2, 3, 1, 2 if full else 0])
        if kind == "count_star":
            return "COUNT(*)"
        if kind == "count_col":
            return f"COUNT({self.pick(everything).ref})"
        if kind == "count_distinct":
            return f"COUNT(DISTINCT {self.pick(everything).ref})"
        if kind in ("case_agg", "arith_agg"):
            fn = "SUM" if not full else self.pick(["SUM", "MIN", "MAX", "AVG"])
            expr = self.numeric_expr(tables, "case" if kind == "case_agg" else self.pick(["colcol", "collit"]))
            if expr is None:
                raise Infeasible("no numeric column")
            return f"{fn}({expr})"
        fn = kind.upper()
        if fn in ("MIN", "MAX") and (not full or self.rng.random() < 0.3):
            if not minmax:
                raise Infeasible("no numeric or date column for MIN/MAX")
            return f"{fn}({self.pick(minmax).ref})"
        if not full:
            if not nums:
                raise Infeasible("no numeric column")
            if self.level == "med" and self.rng.random() < 0.4:
                return f"SUM({self.numeric_expr(tables, self.pick(['colcol', 'collit']))})"
            return f"SUM({self.pick(nums).ref})"
        expr = self.numeric_expr(tables, "col" if self.rng.random() < 0.6 else None)
        if expr is None:
            raise Infeasible("no numeric column")
        return f"{fn}({expr})"

    def subquery_predicate(self, tables: list[str], kind: str) -> str:
        if kind == "sub_scalar":
            t = self.pick(sorted(self.cols))
            nums = [c for c in self.cols[t].values() if c.kind in NUMERIC and c.pool]
            outer = [c for tt in tables for c in self.cols[tt].values() if c.kind in NUMERIC and c.pool]
            if not nums or not outer:
                raise Infeasible("no numeric columns for a scalar subquery")
            where = f" WHERE {self.boolean([t], [None])}" if self.rng.random() < 0.6 else ""
            agg = self.pick(["MAX", "MIN", "AVG"])
            return f"{self.pick(outer).ref} {self.pick(['<', '>', '<=', '>='])} (SELECT {agg}({self.pick(nums).ref}) FROM {t}{where})"
        options = sorted((a, b) for (a, b) in self.edges if a in tables and b not in tables)
        if not options:
            raise Infeasible("no table to subquery over")
        a, b = self.pick(options)
        pairs = self.edges[(a, b)]
        if kind in ("sub_notin", "sub_in"):
            keys = [(x, y) for x, y in pairs if x.kind in ("int", "string", "date")]
            if not keys:
                raise Infeasible("no key column for IN")
            x, y = self.pick(keys)
            where = f" WHERE {self.boolean([b], [None])}" if self.rng.random() < 0.7 else ""
            return f"{x.ref} {'NOT ' if kind == 'sub_notin' else ''}IN (SELECT {y.ref} FROM {b}{where})"
        corr = " AND ".join(f"{y.ref} = {x.ref}" for x, y in pairs)
        filt = f" AND {self.boolean([b], [None])}" if self.rng.random() < 0.7 else ""
        return f"{'NOT ' if kind == 'sub_notexists' else ''}EXISTS (SELECT 1 FROM {b} WHERE {corr}{filt})"

    def query(self, want: frozenset[str] = frozenset()) -> str | tuple:
        """One query containing every construct of ``want`` (raises ``Infeasible``). A tuple is a GROUP BY draft."""
        rng = self.rng
        sizes = [int(f[1]) for f in want if f in ("j1", "j2", "j3", "j4")]
        size = sizes[0] if sizes else self.pick([1, 2, 3, 4], {"high": [1, 0, 0, 0], "med": [10, 90, 0, 0], "full": [30, 40, 20, 10]}[self.level])
        tables, joins = self.join_tree(size)
        frm = (f"FROM {tables[0]} " + " ".join(joins)).strip()
        agg_wanted = [a for a in AGGS if a in want]
        if self.level != "full":
            shape = "group"
        elif "project" in want or "distinct" in want:
            shape = "project"
        elif "group" in want or "having" in want:
            shape = "group"
        elif "global" in want:
            shape = "global"
        elif agg_wanted:
            shape = self.pick(["global", "group"], [3, 5])
        else:
            shape = self.pick(["project", "global", "group"], [3, 3, 5])
        forced: list[str | None] = [s for s in PRED_SHAPES if s in want]
        n_random = self.pick([0, 1, 2, 3], [15, 40, 30, 15]) if not want else rng.choice([0, 0, 1])
        n = max(len(forced), 2 if "or" in want else 1 if "not" in want else 0, n_random)
        shapes = forced + [None] * (n - len(forced))
        preds = []
        if shapes:
            preds.append(self.boolean(tables, shapes, use_or="or" in want, use_not="not" in want))
        sub_kinds = [s for s in SUBS if s in want]
        if not sub_kinds and not want and self.level == "full" and rng.random() < 0.25:
            sub_kinds = [self.pick(list(SUBS), [3, 2, 1, 2, 1])]
        for kind in sub_kinds:
            preds.append(self.subquery_predicate(tables, kind))
        where = f" WHERE {' AND '.join(preds)}" if preds else ""
        everything = [c for t in tables for c in self.cols[t].values() if c.pool]
        do_limit = "limit" in want or (not want and rng.random() < 0.6)
        do_order = "order" in want or do_limit or (not want and rng.random() < 0.7)
        if self.level == "high":
            do_order = do_limit = False
        elif self.level == "med":
            do_order = do_limit = do_limit or do_order
        limit = f" LIMIT {self.pick([5, 10, 20, 100])}" if do_limit else ""
        if shape == "project":
            chosen = rng.sample(everything, min(len(everything), rng.randint(1, 4)))
            items = [c.ref for c in chosen]
            names = [c.name for c in chosen]
            if rng.random() < 0.25 and (e := self.numeric_expr(tables)):
                items.append(f"{e} AS e1")
                names.append("e1")
            distinct = "DISTINCT " if "distinct" in want or (not want and self.level == "full" and rng.random() < 0.15) else ""
            order = f" ORDER BY {', '.join(names) if len(set(names)) == len(names) else ', '.join(c.ref for c in chosen)}" if do_order else ""
            return f"SELECT {distinct}{', '.join(items)} {frm}{where}{order}{limit};"
        self.grouped = shape == "group"
        calls = [self.aggregate(tables, k) for k in agg_wanted]
        calls += [self.aggregate(tables) for _ in range(max(0, rng.randint(1, 3) - len(calls)))] if not want else []
        if not calls:
            calls = [self.aggregate(tables)]
        agg_items = [f"{c} AS m{i + 1}" for i, c in enumerate(calls)]
        if shape == "global":
            return f"SELECT {', '.join(agg_items)} {frm}{where};"
        low = [c for c in everything if c.low_card] or everything
        keys = rng.sample(low, min(len(low), self.pick([1, 2], [3, 1])))
        key_refs = [k.ref for k in keys]
        sql = f"SELECT {', '.join(key_refs + agg_items)} {frm}{where} GROUP BY {', '.join(key_refs)}"
        return sql, calls, [f"m{i + 1}" for i in range(len(calls))], key_refs, "having" in want, do_order, limit


def finish_group(drawer: Drawer, con, parts) -> str:
    """HAVING from a value the grouped result really takes, then ORDER BY the full output and LIMIT."""
    sql, calls, aliases, key_refs, want_having, do_order, limit = parts
    rng = drawer.rng
    if want_having or (rng.random() < 0.3 and drawer.level == "full"):
        call = rng.choice(calls)
        values = [r[0] for r in fetch(con, f"SELECT {call} FROM {sql.split(' FROM ', 1)[1]}")]
        values = sorted(v for v in values if v is not None and not isinstance(v, float))  # sorted: the group order of a parallel scan is not fixed
        if not values:
            raise Infeasible("no HAVING threshold")
        v = rng.choice(values)
        if not isinstance(v, (int, Decimal)):
            raise Infeasible("HAVING threshold is not a number")
        lit = format(v, "f") if isinstance(v, Decimal) else str(v)
        sql += f" HAVING {call} {rng.choice(['>', '>=', '<', '<='])} {lit}"
    if do_order:
        sql += f" ORDER BY {', '.join(key_refs + aliases)}{limit}"
    return sql + ";"


def fetch(con, sql: str, timeout: float = TIMEOUT_SEC) -> list:
    """All rows of a helper query (a HAVING threshold); a timeout or DuckDB error rejects the draw."""
    timer = threading.Timer(timeout, con.interrupt)
    timer.start()
    try:
        return con.execute(sql).fetchall()
    except duckdb.Error as exc:
        raise Infeasible(f"helper query failed: {str(exc).splitlines()[0][:60]}") from exc
    finally:
        timer.cancel()


def run_checked(con, sql: str, timeout: float = TIMEOUT_SEC) -> tuple[str, list | None]:
    """``(status, rows)``: status ``ok`` or why DuckDB refused / the draw was rejected."""
    timer = threading.Timer(timeout, con.interrupt)
    timer.start()
    try:
        rows = con.execute(sql).fetchmany(MAX_ROWS + 1)
    except duckdb.InterruptException:
        return "timeout", None
    except duckdb.Error as exc:
        return f"duckdb_error: {str(exc).splitlines()[0][:80]}", None
    finally:
        timer.cancel()
    if not rows:
        return "empty", None
    if len(rows) > MAX_ROWS:
        return "too_many_rows", None
    flat = {v for r in rows for v in r}
    if len(rows) == 1 and flat <= {None, 0, 0.0}:
        return "constant", None
    if len(rows) > 1 and all(len({r[i] for r in rows}) == 1 for i in range(len(rows[0]))):
        return "constant", None
    return "ok", rows


def draw(
    db: Path,
    seed: int,
    n: int,
    *,
    log=None,
    pairwise: bool = True,
    level: str = "full",
    package: str | None = None,
    nullable: set[tuple[str, str]] | None = None,
    judge=None,
    replay: dict[str, str] | None = None,
) -> tuple[list[str], dict[str, int], dict]:
    """``n`` kept queries, the reject counts, and the pair coverage.

    With ``pairwise`` the draw steers: while some feasible pair of constructs has not occurred together, every other
    draw is forced to contain the next uncovered pair (random choice among them). Pairs whose forced draws keep being
    rejected (``MAX_TRIES``) are reported as uncovered, never skipped silently.

    Deterministic for one (seed, database file, code): a single ``random.Random(seed)`` and sorted choices. The one
    wall-clock input is the DuckDB timeout; every candidate that timed out is recorded in the returned
    ``decisions`` (candidate index -> "timeout") and ``replay`` feeds them back, so a replay never re-measures; a live
    timeout that the replay does not list raises. ``judge(sql, index)`` is an extra filter (a reason string drops the
    candidate); it must itself be deterministic or record its own decisions."""
    columns = load_columns(db, seed)
    nullable = set(nullable or ())
    bounds: dict[tuple[str, str], int] = {}
    if package:
        from research_loop.assumption_packages import assumption_package

        tables = assumption_package(package).tables
        nullable = {(t, c) for t, ta in tables.items() for c, ca in ta.columns.items() if ca.nullable}
        bounds = {(t, c): ca.max_value_exclusive for t, ta in tables.items() for c, ca in ta.columns.items() if ca.max_value_exclusive}
    schema = schema_from_db(db)
    drawer = Drawer(columns, random.Random(seed), level, nullable, bounds)
    con = connect(db)
    kept: list[str] = []
    seen: set[str] = set()
    rejects: dict[str, int] = {}
    covered: dict[tuple[str, str], int] = {p: 0 for p in feasible_pairs(level)}
    tries: dict[tuple[str, str], int] = {}
    decisions: dict[str, str] = {}
    candidate = -1

    def reject(why: str) -> None:
        why = why.split(":")[0]
        rejects[why] = rejects.get(why, 0) + 1

    while len(kept) < n:
        pending = [p for p, c in covered.items() if c == 0 and tries.get(p, 0) < MAX_TRIES]
        target = None
        if pairwise and pending and (len(pending) >= n - len(kept) or drawer.rng.random() < 0.5):
            target = drawer.pick(pending)
            tries[target] = tries.get(target, 0) + 1
        want = frozenset(target) if target else frozenset()
        try:
            part = drawer.query(want)
            sql = finish_group(drawer, con, part) if isinstance(part, tuple) else part
        except Infeasible as why:
            reject(f"infeasible {why}")
            continue
        if sql in seen:
            continue
        seen.add(sql)
        candidate += 1
        ok, why = in_fragment(sql, level, schema, nullable)
        if not ok:
            raise AssertionError(f"generator drew a query outside G: {why}\n{sql}")
        t0 = time.time()
        if replay is not None and str(candidate) in replay:
            status = replay[str(candidate)]
        else:
            status, _ = run_checked(con, sql)
            if status == "timeout" and replay is not None:
                raise RuntimeError(f"replay diverged: candidate {candidate} timed out now but not in the recorded run\n{sql}")
        if status == "timeout":
            decisions[str(candidate)] = "timeout"
        if log and time.time() - t0 > 5:
            log(f"slow {status} {time.time() - t0:.0f}s {sql[:200]}")
        if status != "ok":
            reject(status)
            continue
        if judge is not None and (why := judge(sql, candidate)):
            reject(why)
            continue
        feats = features(sql)
        if target and not set(target) <= feats:
            reject("steering_missed")  # the AST does not show the construct that was asked for
        for p in covered:
            if set(p) <= feats:
                covered[p] += 1
        kept.append(sql)
        if log and len(kept) % 25 == 0:
            log(f"{len(kept)}/{n} uncovered pairs {sum(1 for c in covered.values() if c == 0)}")
    con.close()
    return kept, rejects, {"covered": covered, "uncovered": [p for p, c in covered.items() if c == 0], "decisions": decisions, "candidates": candidate + 1}


MAX_TRIES = 40


def provenance(db: Path, package: str | None, level: str, seed: int | None, **extra) -> dict:
    """Everything needed to say what produced a file: code version, grammar text, database fingerprint, tool versions, command."""
    import hashlib
    import platform
    import subprocess

    import sqlglot

    def vcs(*args: str) -> str:
        return subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT, check=False).stdout.strip()

    con = connect(db, threads=1)
    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY 1").fetchall()}
    con.close()
    doc = ROOT / "docs" / "SQL_FRAGMENT.md"
    return {
        "seed": seed,
        "level": level,
        "package": package,
        "git_sha": vcs("rev-parse", "HEAD"),
        "git_dirty": bool(vcs("status", "--porcelain", "--", "declarative_spec", "research_loop/scripts", "docs/SQL_FRAGMENT.md")),
        "grammar_doc_sha256": hashlib.sha256(doc.read_bytes()).hexdigest() if doc.is_file() else None,
        "db": {"path": str(db), "size_bytes": db.stat().st_size, "table_rows": counts},
        "duckdb": duckdb.__version__,
        "sqlglot": sqlglot.__version__,
        "python": platform.python_version(),
        "argv": sys.argv,
        **extra,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=None, help="default: $LEMMA_DUCKDB_PATH or the SEC DECIMAL file")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--out", type=Path, required=True, help="a .sql file of '-- Qi:' labeled queries")
    ap.add_argument("--package", default="sec_margin_dec", help="assumption package: its nullable columns are kept out of grouped SUM/MIN/MAX/AVG")
    ap.add_argument("--no-pairwise", action="store_true")
    ap.add_argument("--replay", type=Path, help="a manifest.json of an earlier run: reuse its recorded timeout decisions")
    ap.add_argument("--level", choices=("high", "med", "full"), default="full")
    args = ap.parse_args()
    db = args.db or Path(os.environ.get("LEMMA_DUCKDB_PATH") or ROOT / "holdout" / "gendb_sec_edgar" / "duckdb" / "sec_edgar_dec.duckdb")
    replay = json.loads(args.replay.read_text())["decisions"] if args.replay else None
    kept, rejects, pairs = draw(db, args.seed, args.n, log=lambda m: print(m, file=sys.stderr, flush=True), pairwise=not args.no_pairwise, level=args.level, package=args.package, replay=replay)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(f"-- Q{i}:\n{q}\n\n" for i, q in enumerate(kept, 1)))
    args.out.with_suffix(".manifest.json").write_text(
        json.dumps(
            {**provenance(db, args.package, args.level, args.seed, n=args.n, pairwise=not args.no_pairwise, timeout_sec=TIMEOUT_SEC),
             "rejects": rejects, "uncovered_pairs": pairs["uncovered"], "feasible_pairs": len(feasible_pairs(args.level)),
             "candidates": pairs["candidates"], "decisions": pairs["decisions"], "queries_sha256": __import__("hashlib").sha256(args.out.read_bytes()).hexdigest()},
            indent=1,
        )
    )
    print(f"kept {len(kept)} rejects {rejects} uncovered pairs {len(pairs['uncovered'])}/{len(feasible_pairs(args.level))}")


if __name__ == "__main__":
    main()
