"""Deterministic, LLM-free data profile of one query on one DuckDB file (``lemma.toml`` [data] ``data_profile = "stats"``).

Input: the SQL text and the database. Output: a small markdown file with exact numbers, every one computed by a generated SQL query on
the database (no EXPLAIN, no plan, no sampling, no timings in the file, so the same data gives the same file):

* per table: row count; per used column: type, min, max, NULL fraction, distinct count
* per filter conjunct: rows matching and selectivity; per table, all its conjuncts combined
* per join equality: distinct keys of each side (all rows, and after that side's own filters) and the keys the two sides share
* the joined, filtered rows, and how many rows of each table take part in them
* per group key: distinct values overall and after filters; the number of result groups
* the result row count; for ORDER BY + LIMIT: the rows tied with the last returned row, and how many of them the LIMIT cuts off

The module is schema-driven: it reads table and column names from the query and the database and names none itself. A statistic that
does not apply to the query (no filter, no join, no group key, no LIMIT) is omitted. The profile covers the top-level SELECT; each side of a
set operation is profiled on its own; a derived table over plain joins in FROM is inlined; any other derived table (subquery in FROM or JOIN)
is profiled as a relation of its own (its rows, its output columns, the filters and join keys on it); a source that is neither (a CTE,
a table function) is not profiled, and no single-table statistic uses a condition that references it (the query-level numbers still are).
Every generated query has a timeout; a query that fails or times out raises :class:`ProfileError` with the query text (no partial profile).
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import sqlglot
from sqlglot import exp

DIALECT = "duckdb"
MEMORY_LIMIT = "2GB"
QUERY_TIMEOUT_SEC = 120.0
_CELL = 40


class ProfileError(RuntimeError):
    """A generated statistics query failed or timed out. The message carries the query text."""


@dataclass
class _Source:
    alias: str
    relation: exp.Expression  # the FROM/JOIN item: a base table, or a derived table (aliased subquery)
    label: str  # the base table's name, or "derived" for a subquery
    columns: list[str]  # lower-cased column names of the relation, in order
    derived: bool

    @property
    def from_sql(self) -> str:
        return _sql(self.relation)


class _Runner:
    """Runs generated queries on a read-only connection; each one under a timeout."""

    def __init__(self, db_path: Path, timeout_sec: float) -> None:
        self.con = duckdb.connect(str(db_path), read_only=True)
        self.con.execute(f"PRAGMA memory_limit='{MEMORY_LIMIT}'")
        self.timeout_sec = timeout_sec
        self.queries = 0

    def run(self, sql: str) -> list[tuple]:
        self.queries += 1
        timer = threading.Timer(self.timeout_sec, self.con.interrupt)
        timer.start()
        try:
            return self.con.execute(sql).fetchall()
        except duckdb.InterruptException as exc:
            raise ProfileError(f"statistics query timed out after {self.timeout_sec:g}s:\n{sql}") from exc
        except duckdb.Error as exc:
            raise ProfileError(f"statistics query failed ({exc}):\n{sql}") from exc
        finally:
            timer.cancel()

    def one(self, sql: str) -> tuple:
        return self.run(sql)[0]

    def count(self, sql: str) -> int:
        return int(self.one(f"SELECT count(*) FROM ({sql})")[0])


def _sql(node: exp.Expression) -> str:
    return node.sql(dialect=DIALECT)


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _cell(value: Any) -> str:
    if value is None:
        return "NULL"
    text = str(value).replace("|", "/").replace("\n", " ")
    return text if len(text) <= _CELL else text[: _CELL - 3] + "..."


def _num(value: int) -> str:
    return f"{value:,}"


def _ratio(part: int, whole: int) -> str:
    return "n/a" if whole == 0 else f"{part / whole:.6g}"


def _conjuncts(node: exp.Expression | None) -> list[exp.Expression]:
    if node is None:
        return []
    while isinstance(node, exp.Paren):
        node = node.this
    if isinstance(node, exp.And):
        return _conjuncts(node.left) + _conjuncts(node.right)
    return [node]


def _from_select(select: exp.Select) -> exp.Expression | None:
    clause = select.args.get("from_") or select.args.get("from")
    return clause.this if clause is not None else None


class _SelectProfile:
    def __init__(self, select: exp.Select, runner: _Runner) -> None:
        self.select = select
        self.r = runner
        self.sources: list[_Source] = []
        self.skipped: list[str] = []
        self.unprofiled: set[str] = set()  # lower-cased aliases of FROM/JOIN items that are not profiled
        self._collect_sources()
        self.by_alias = {s.alias.lower(): s for s in self.sources}
        self.out_alias = {
            item.alias.lower(): item.this for item in select.expressions if isinstance(item, exp.Alias)
        }

    # ---- sources and column resolution

    def _collect_sources(self) -> None:
        nodes = [_from_select(self.select)] + [j.this for j in self.select.args.get("joins") or []]
        for node in nodes:
            if node is None:
                continue
            if isinstance(node, exp.Subquery) and node.alias and isinstance(node.this, exp.Query):
                described = self.r.run(f"DESCRIBE SELECT * FROM {_sql(node)}")
                self.sources.append(_Source(node.alias, node, "derived", [str(c[0]).lower() for c in described], True))
                continue
            if not isinstance(node, exp.Table):
                if node.alias_or_name:
                    self.unprofiled.add(node.alias_or_name.lower())
                self.skipped.append(f"`{_cell(_sql(node))}` (not a base table or an aliased derived table)")
                continue
            described = self.r.run(
                f"SELECT column_name FROM information_schema.columns WHERE table_name = '{node.name}' "
                + (f"AND table_schema = '{node.db}' " if node.db else "")
                + "ORDER BY ordinal_position"
            )
            if not described:
                self.unprofiled.add(node.alias_or_name.lower())
                self.skipped.append(f"`{node.name}` (not a base table of the database)")
                continue
            self.sources.append(_Source(node.alias_or_name, node, node.name, [str(c[0]).lower() for c in described], False))

    def _owner(self, col: exp.Column) -> str | None:
        """Lower-cased alias of the source a column belongs to; None for an output alias or a column of an unprofiled source."""
        name = col.name.lower()
        if col.table:
            q = col.table.lower()
            if q in self.by_alias:
                return q
            for s in self.sources:
                if not s.derived and s.relation.name.lower() == q:
                    return s.alias.lower()
            return None
        owners = [s.alias.lower() for s in self.sources if name in s.columns]
        if len(owners) == 1:
            return owners[0]
        if len(owners) > 1:
            raise ProfileError(f"column `{col.name}` is ambiguous between {owners}")
        return None

    def _columns_of(self, node: exp.Expression) -> list[exp.Column]:
        """Columns that belong to this SELECT: its own, and the correlated references (qualified by one of its aliases) inside subqueries."""
        out = []
        for col in node.find_all(exp.Column):
            if col.find_ancestor(exp.Select) is not self.select and not (col.table and col.table.lower() in self.by_alias):
                continue
            out.append(col)
        return out

    def _unresolved(self, node: exp.Expression) -> bool:
        """True when ``node`` reads a column of no profiled source: a column of an unprofiled FROM/JOIN item (or one this module cannot
        place). Such a condition is not a single-source filter or a join of two profiled sources; using it as one would give a wrong number."""
        for col in node.find_all(exp.Column):
            own = col.find_ancestor(exp.Select) is self.select
            if col.table and col.table.lower() in self.unprofiled:
                return True
            if own and self._owner(col) is None and (col.table or col.name.lower() not in self.out_alias):
                return True
        return False

    def aliases_of(self, node: exp.Expression) -> list[str]:
        found = {a for c in self._columns_of(node) if (a := self._owner(c)) is not None}
        return sorted(found, key=lambda a: [s.alias.lower() for s in self.sources].index(a))

    # ---- query pieces

    def _predicates(self) -> tuple[dict[str, list[exp.Expression]], list[tuple[exp.Column, exp.Column]]]:
        """Single-source conjuncts per alias (from WHERE and every JOIN ... ON) and column equalities between two sources."""
        filters: dict[str, list[exp.Expression]] = {s.alias.lower(): [] for s in self.sources}
        equalities: list[tuple[exp.Column, exp.Column]] = []
        where = self.select.args.get("where")
        conds = _conjuncts(where.this if where else None)
        for join in self.select.args.get("joins") or []:
            conds += _conjuncts(join.args.get("on"))
        for cond in conds:
            if self._unresolved(cond):
                continue
            aliases = self.aliases_of(cond)
            if isinstance(cond, exp.EQ) and isinstance(cond.left, exp.Column) and isinstance(cond.right, exp.Column):
                left, right = self._owner(cond.left), self._owner(cond.right)
                if left and right and left != right:
                    equalities.append((cond.left, cond.right))
                    continue
            if len(aliases) == 1:
                filters[aliases[0]].append(cond)
        return filters, equalities

    def _stripped(self, items: list[exp.Expression], *, keep_group: bool) -> exp.Select:
        s = self.select.copy()
        s.set("expressions", items)
        for key in ("order", "limit", "offset", "qualify", "windows"):
            s.set(key, None)
        if not keep_group:
            for key in ("group", "having", "distinct"):
                s.set(key, None)
        return s

    def _resolve(self, node: exp.Expression, *, alias_first: bool) -> exp.Expression:
        """GROUP BY / ORDER BY item -> the expression it denotes (ordinal and output alias resolved)."""
        if isinstance(node, exp.Literal) and not node.is_string:
            item = self.select.expressions[int(node.this) - 1]
            return item.this if isinstance(item, exp.Alias) else item
        if isinstance(node, exp.Column) and not node.table and node.name.lower() in self.out_alias:
            if alias_first or self._owner(node) is None:
                return self.out_alias[node.name.lower()]
        return node

    # ---- sections

    def render(self) -> list[str]:
        out: list[str] = []
        if self.skipped:
            out += ["Not profiled per table: " + "; ".join(self.skipped) + ".", ""]
        filters, equalities = self._predicates()
        totals = {s.alias.lower(): self.r.count(f"SELECT 1 FROM {s.from_sql}") for s in self.sources}
        out += self._tables(totals)
        out += self._columns(totals)
        out += self._filters(filters, totals)
        out += self._joins(filters, equalities)
        out += self._groups(filters, totals)
        out += self._result()
        return out

    def _tables(self, totals: dict[str, int]) -> list[str]:
        if not self.sources:
            return []
        out = ["## Tables", "", "| table | alias | rows |", "|---|---|---|"]
        out += [f"| {s.label} | {s.alias} | {_num(totals[s.alias.lower()])} |" for s in self.sources]
        return out + [""]

    def _columns(self, totals: dict[str, int]) -> list[str]:
        used: dict[str, set[str]] = {s.alias.lower(): set() for s in self.sources}
        for col in self._columns_of(self.select):
            owner = self._owner(col)
            if owner is not None and col.name.lower() in self.by_alias[owner].columns:
                used[owner].add(col.name.lower())
        out: list[str] = []
        for s in self.sources:
            names = sorted(used[s.alias.lower()])
            if not names:
                continue
            total = totals[s.alias.lower()]
            out += [f"### Columns of {s.alias} ({s.label}, {_num(total)} rows)", "", "| column | type | min | max | NULL fraction | distinct |", "|---|---|---|---|---|---|"]
            types = {str(r[0]).lower(): str(r[1]) for r in self.r.run(f"DESCRIBE SELECT * FROM {s.from_sql}")}
            for name in names:
                q = _ident(name)
                lo, hi, nulls, distinct = self.r.one(
                    f"SELECT min({q}), max({q}), count(*) - count({q}), count(DISTINCT {q}) FROM {s.from_sql}"
                )
                out.append(f"| {name} | {types[name]} | {_cell(lo)} | {_cell(hi)} | {_ratio(int(nulls), total)} | {_num(int(distinct))} |")
            out.append("")
        if out:
            out = ["## Columns used", ""] + out
        return out

    def _filters(self, filters: dict[str, list[exp.Expression]], totals: dict[str, int]) -> list[str]:
        rows: list[str] = []
        for s in self.sources:
            key = s.alias.lower()
            conds = filters[key]
            if not conds:
                continue
            total = totals[key]
            for cond in conds:
                n = self.r.count(f"SELECT 1 FROM {s.from_sql} WHERE {_sql(cond)}")
                rows.append(f"| {s.alias} | `{_cell(_sql(cond))}` | {_num(n)} / {_num(total)} | {_ratio(n, total)} |")
            if len(conds) > 1:
                both = " AND ".join(f"({_sql(c)})" for c in conds)
                n = self.r.count(f"SELECT 1 FROM {s.from_sql} WHERE {both}")
                rows.append(f"| {s.alias} | all of the above together | {_num(n)} / {_num(total)} | {_ratio(n, total)} |")
        if not rows:
            return []
        return ["## Filters (single-table conditions)", "", "| table | condition | rows matching | selectivity |", "|---|---|---|---|"] + rows + [""]

    def _side(self, col: exp.Column, filters: dict[str, list[exp.Expression]]) -> tuple[_Source, str, str, str]:
        owner = self._owner(col)
        s = self.by_alias[owner]
        key = _ident(col.name)
        where = " AND ".join(f"({_sql(c)})" for c in filters[owner])
        return s, key, f"FROM {s.from_sql}", f"WHERE {where}" if where else ""

    def _joins(self, filters: dict[str, list[exp.Expression]], equalities: list[tuple[exp.Column, exp.Column]]) -> list[str]:
        out: list[str] = []
        if equalities:
            out += ["## Joins (column equalities)", "", "| join | distinct keys left (all / after filters) | distinct keys right (all / after filters) | keys in common after filters |", "|---|---|---|---|"]
            for left, right in equalities:
                ls, lk, lfrom, lwhere = self._side(left, filters)
                rs, rk, rfrom, rwhere = self._side(right, filters)
                l_all = int(self.r.one(f"SELECT count(DISTINCT {lk}) {lfrom}")[0])
                l_fil = int(self.r.one(f"SELECT count(DISTINCT {lk}) {lfrom} {lwhere}")[0])
                r_all = int(self.r.one(f"SELECT count(DISTINCT {rk}) {rfrom}")[0])
                r_fil = int(self.r.one(f"SELECT count(DISTINCT {rk}) {rfrom} {rwhere}")[0])
                both = self.r.count(
                    f"SELECT DISTINCT {lk} AS k {lfrom} {lwhere} INTERSECT SELECT DISTINCT {rk} {rfrom} {rwhere}"
                )
                out.append(
                    f"| {ls.alias}.{left.name} = {rs.alias}.{right.name} | {_num(l_all)} / {_num(l_fil)} | {_num(r_all)} / {_num(r_fil)} | {_num(both)} |"
                )
            out.append("")
        if len(self.sources) > 1 or self.select.args.get("where") is not None:
            # A derived table has no rowid: how many of its rows take part is not reported for it (n/a), never approximated.
            based = [s for s in self.sources if not s.derived]
            count_items = [exp.Count(this=exp.Star())] + [
                exp.Count(this=exp.Distinct(expressions=[exp.column("rowid", table=s.alias)])) for s in based
            ]
            sel = self._stripped([exp.alias_(i, f"c{n}") for n, i in enumerate(count_items)], keep_group=False)
            row = self.r.one(_sql(sel))
            out += ["## Rows after all joins and filters", "", f"Joined rows: {_num(int(row[0]))}.", ""]
            if len(self.sources) > 1 or filters:
                out += ["| table | rows of the table that still match | of |", "|---|---|---|"]
                total_by = {s.alias.lower(): self.r.count(f"SELECT 1 FROM {s.from_sql}") for s in self.sources}
                matched = {s.alias.lower(): int(v) for s, v in zip(based, row[1:])}
                for s in self.sources:
                    m = matched.get(s.alias.lower())
                    out.append(f"| {s.alias} | {'n/a' if m is None else _num(m)} | {_num(total_by[s.alias.lower()])} |")
                out.append("")
        return out

    def _groups(self, filters: dict[str, list[exp.Expression]], totals: dict[str, int]) -> list[str]:
        group = self.select.args.get("group")
        if group is None or not group.expressions:
            return []
        keys = [self._resolve(k, alias_first=False) for k in group.expressions]
        rows: list[str] = []
        for key in keys:
            aliases = self.aliases_of(key)
            overall = "n/a"
            if len(aliases) == 1 and not list(key.find_all(exp.Select)) and not self._unresolved(key):
                s = self.by_alias[aliases[0]]
                overall = _num(int(self.r.one(f"SELECT count(DISTINCT {_sql(key)}) FROM {s.from_sql}")[0]))
            sel = self._stripped([exp.alias_(exp.Count(this=exp.Distinct(expressions=[key.copy()])), "d")], keep_group=False)
            after = _num(int(self.r.one(_sql(sel))[0]))
            rows.append(f"| `{_cell(_sql(key))}` | {overall} | {after} |")
        n_groups = self.r.count(_sql(self._stripped([exp.Literal.number(1)], keep_group=True)))
        return (
            ["## Group keys", "", "| key | distinct values in its table | distinct values after filters and joins |", "|---|---|---|"]
            + rows
            + ["", f"Result groups{' after HAVING' if self.select.args.get('having') is not None else ''} (before LIMIT): {_num(n_groups)}.", ""]
        )

    def _result(self) -> list[str]:
        limit, offset = self.select.args.get("limit"), self.select.args.get("offset")
        order = self.select.args.get("order")
        grouped = self.select.args.get("group") is not None
        aggregated = any(list(i.find_all(exp.AggFunc)) for i in self.select.expressions)
        out = ["## Result", ""]
        if aggregated and not grouped:
            out.append("Result rows: 1 (ungrouped aggregate).")
            return out + [""]
        base = _sql(self._stripped(list(self.select.expressions), keep_group=True))
        base_rows = self.r.count(base)
        if limit is None:
            return out + [f"Result rows: {_num(base_rows)}.", ""]
        out.append(f"Result rows before LIMIT: {_num(base_rows)}.")
        lim = int(limit.expression.this)
        off = int(offset.expression.this) if offset is not None else 0
        out.append(f"Result rows returned: {_num(max(0, min(lim, base_rows - off)))} (LIMIT {lim}" + (f" OFFSET {off}" if off else "") + ").")
        if order is not None and base_rows > lim + off:
            out += self._ties(order, lim + off, base_rows)
        return out + [""]

    def _ties(self, order: exp.Order, cut: int, base_rows: int) -> list[str]:
        keys = [(self._resolve(o.this, alias_first=True), o) for o in order.expressions]
        items: list[exp.Expression] = []
        if self.select.args.get("distinct") is not None:
            items += list(self.select.expressions)
        items += [exp.alias_(k.copy(), f"__k{i}") for i, (k, _o) in enumerate(keys)]
        inner = _sql(self._stripped(items, keep_group=True))
        names = [f"__k{i}" for i in range(len(keys))]
        by = ", ".join(
            _sql(exp.Ordered(this=exp.column(n), desc=o.args.get("desc"), nulls_first=o.args.get("nulls_first"))) for n, (_k, o) in zip(names, keys)
        )
        same = " AND ".join(f"w.{n} IS NOT DISTINCT FROM c.{n}" for n in names)
        sql = (
            f"WITH w AS (SELECT *, row_number() OVER (ORDER BY {by}) AS __rn FROM ({inner})), "
            f"c AS (SELECT * FROM w WHERE __rn = {cut}) "
            f"SELECT count(*) FILTER (WHERE {same}), count(*) FILTER (WHERE {same} AND w.__rn > {cut}) FROM w, c"
        )
        tied, beyond = (int(v) for v in self.r.one(sql))
        return [
            f"Rows tied with the last returned row on the ORDER BY key (the row at the cut): {_num(tied)}, of which {_num(beyond)} fall beyond the LIMIT "
            "(which of the tied rows are returned is not determined by the key)."
        ]


def _inline_derived(select: exp.Select) -> exp.Select:
    """``SELECT .. FROM (SELECT <outputs> FROM <joins> WHERE w) AS d [WHERE ..] GROUP BY ..`` -> the same query over the inner tables
    (outer references to an output become the output's expression), so its tables and filters are profiled. Anything else is returned unchanged."""
    source = _from_select(select)
    inner = source.this if isinstance(source, exp.Subquery) else None
    if (
        not isinstance(inner, exp.Select)
        or select.args.get("joins")
        or any(inner.args.get(k) for k in ("group", "having", "order", "limit", "offset", "distinct", "with_", "with"))
        or any(list(i.find_all(exp.AggFunc)) for i in inner.expressions)
    ):
        return select
    alias = source.alias.lower()
    outputs = {item.alias_or_name.lower(): (item.this if isinstance(item, exp.Alias) else item) for item in inner.expressions}

    def swap(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Column) and node.name.lower() in outputs and (not node.table or node.table.lower() == alias):
            return outputs[node.name.lower()].copy()
        return node

    out = select.copy()
    out.set("expressions", [item if isinstance(item, exp.Alias) or not isinstance(item, exp.Column) else exp.alias_(item.copy(), item.name) for item in out.expressions])
    for key in ("expressions", "where", "group", "having", "order"):
        node = out.args.get(key)
        if isinstance(node, list):
            out.set(key, [n.transform(swap) for n in node])
        elif node is not None:
            out.set(key, node.transform(swap))
    key = "from_" if "from_" in out.args else "from"
    out.set(key, inner.args.get(key if key in inner.args else "from_").copy())
    out.set("joins", [j.copy() for j in inner.args.get("joins") or []] or None)
    conds = [c for c in (inner.args["where"].this if inner.args.get("where") else None, out.args["where"].this if out.args.get("where") else None) if c is not None]
    if conds:
        out.set("where", exp.Where(this=exp.and_(*[c.copy() for c in conds])))
    return out


def _selects(expression: exp.Expression) -> list[exp.Select]:
    if isinstance(expression, exp.Select):
        return [_inline_derived(expression)]
    if isinstance(expression, exp.SetOperation):
        return _selects(expression.this) + _selects(expression.expression)
    raise ProfileError(f"unsupported top-level SQL shape: {type(expression).__name__}")


def build_profile(sql: str, db_path: Path | str, *, timeout_sec: float = QUERY_TIMEOUT_SEC) -> str:
    """The markdown profile of ``sql`` on the database at ``db_path`` (opened read-only, memory limit 2GB)."""
    # No transpiler gate here: whether the SQL is supported is decided by the spec emitter (which first rewrites DECIMAL/DATE and
    # ratios of aggregates, so a raw `parse_query` refused SQL the emitter accepts, e.g. `100.00 * SUM(..) / SUM(..)`).
    # The profile is informational text for the agent and is not an input of the spec or the proof.
    runner = _Runner(Path(db_path), timeout_sec)
    try:
        selects = _selects(sqlglot.parse_one(sql))
        lines = [
            "# Data profile",
            "",
            "Exact statistics of the database for this query, computed by SQL on the data (no sampling, no query plan). They describe the data as it is;",
            "they are not assumptions. Whatever you prove must hold for every database that satisfies the assumption package, not only for these numbers.",
            "",
        ]
        for n, select in enumerate(selects, start=1):
            if len(selects) > 1:
                lines += [f"# Branch {n} of {len(selects)}", ""]
            lines += _SelectProfile(select, runner).render()
        return "\n".join(lines).rstrip("\n") + "\n"
    finally:
        runner.con.close()


def main(argv: list[str]) -> int:
    """``python -m research_loop.data_profile <db.duckdb> <query.sql> [out.md]``"""
    if len(argv) not in (2, 3):
        print(main.__doc__, file=sys.stderr)
        return 2
    started = time.monotonic()
    text = build_profile(Path(argv[1]).read_text(), argv[0])
    if len(argv) == 3:
        Path(argv[2]).write_text(text)
    else:
        print(text, end="")
    print(f"data profile: {len(text)} bytes in {time.monotonic() - started:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
