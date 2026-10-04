"""Random GenDB-shaped SQL over the SEC EDGAR schema, wider than the GenDB templates.

    uv run python research_loop/scripts/decl_fuzz.py OUT.sql --seed S --count 300

Every query is checked with DuckDB ``EXPLAIN`` so only valid SQL is kept. Used by
``decl_coverage.py`` for emission coverage; the generator is seeded, and the sample is saved.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
_DB = Path("/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/duckdb/sec_edgar_local.duckdb")

INT = {
    "sub": ["cik", "sic", "period", "fy", "filed", "prevrpt", "nciks", "wksi"],
    "num": ["ddate", "qtrs"],
    "tag": ["custom", "abstract"],
    "pre": ["report", "line", "inpth", "negating"],
}
STR = {
    "sub": ["adsh", "name", "countryba", "stprba", "cityba", "countryinc", "form", "fp", "accepted", "afs", "fye", "instance"],
    "num": ["adsh", "tag", "version", "uom", "coreg", "footnote"],
    "tag": ["tag", "version", "datatype", "iord", "crdr", "tlabel", "doc"],
    "pre": ["adsh", "stmt", "rfile", "tag", "version", "plabel"],
}
FLT = {"num": ["value"]}
KEYS = {
    ("num", "sub"): [("adsh", "adsh")],
    ("pre", "sub"): [("adsh", "adsh")],
    ("num", "tag"): [("tag", "tag"), ("version", "version")],
    ("pre", "tag"): [("tag", "tag"), ("version", "version")],
    ("num", "pre"): [("adsh", "adsh"), ("tag", "tag"), ("version", "version")],
}
ALIAS = {"sub": "s", "num": "n", "tag": "t", "pre": "p"}


class Gen:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        con = duckdb.connect(str(_DB), read_only=True)
        self.vals: dict[tuple[str, str], list] = {}
        for table, cols in STR.items():
            for col in cols:
                if col in ("doc", "footnote", "plabel", "tlabel", "name"):
                    limit = 40
                else:
                    limit = 80
                rows = con.execute(
                    f'SELECT DISTINCT "{col}" FROM {table} WHERE "{col}" IS NOT NULL LIMIT {limit}'
                ).fetchall()
                self.vals[(table, col)] = [r[0] for r in rows if "'" not in r[0]] or ["x"]
        for table, cols in INT.items():
            for col in cols:
                rows = con.execute(
                    f'SELECT DISTINCT "{col}" FROM {table} WHERE "{col}" IS NOT NULL LIMIT 60'
                ).fetchall()
                self.vals[(table, col)] = [r[0] for r in rows] or [0]
        con.close()

    def pick(self, xs):
        return self.rng.choice(xs)

    def chance(self, p: float) -> bool:
        return self.rng.random() < p

    # ---- predicates -----------------------------------------------------------------------

    def pred(self, table: str, alias: str) -> str:
        r = self.rng
        kind = r.choices(
            ["streq", "strin", "like", "strne", "intcmp", "between", "isnull", "valuecmp", "or", "not", "intin", "strlen"],
            weights=[6, 3, 3, 2, 6, 3, 3, 2, 2, 1, 2, 1],
        )[0]
        q = f"{alias}." if alias else ""
        if kind == "valuecmp" and table in FLT:
            return f"{q}value {self.pick(['>', '<', '>=', '<=', '=', '<>'])} {self.pick([0, 1000, 10000, 1000000])}"
        if kind in ("streq", "strin", "like", "strne", "strlen"):
            col = self.pick(STR[table])
            v = self.pick(self.vals[(table, col)])
            if kind == "streq":
                return f"{q}{col} = '{v}'"
            if kind == "strne":
                return f"{q}{col} {self.pick(['<>', '!='])} '{v}'"
            if kind == "strin":
                vs = ", ".join(f"'{self.pick(self.vals[(table, col)])}'" for _ in range(r.randint(2, 4)))
                return f"{q}{col} {self.pick(['IN', 'NOT IN'])} ({vs})"
            if kind == "like":
                s = str(v)
                pat = self.pick([s[:3] + "%", "%" + s[-3:], "%" + s[1:4] + "%", s[:2] + "_" + s[3:4] + "%"])
                return f"{q}{col} {self.pick(['LIKE', 'NOT LIKE'])} '{pat}'"
            return f"LENGTH({q}{col}) {self.pick(['>', '<', '='])} {r.randint(1, 12)}"
        if kind == "isnull":
            col = self.pick(STR[table] + INT[table] + FLT.get(table, []))
            return f"{q}{col} IS {self.pick(['NULL', 'NOT NULL'])}"
        if kind == "or":
            return f"({self.pred(table, alias)} OR {self.pred(table, alias)})"
        if kind == "not":
            return f"NOT ({self.pred(table, alias)})"
        col = self.pick(INT[table])
        v = self.pick(self.vals[(table, col)])
        if kind == "between":
            lo, hi = sorted([v, self.pick(self.vals[(table, col)])])
            return f"{q}{col} BETWEEN {lo} AND {hi}"
        if kind == "intin":
            vs = ", ".join(str(self.pick(self.vals[(table, col)])) for _ in range(r.randint(2, 4)))
            return f"{q}{col} {self.pick(['IN', 'NOT IN'])} ({vs})"
        return f"{q}{col} {self.pick(['>', '<', '>=', '<=', '=', '<>'])} {v}"

    # ---- one query ------------------------------------------------------------------------

    def query(self) -> str:
        r = self.rng
        shape = r.choices(
            ["single", "join2", "join3", "derived", "exists", "insub", "scalar", "setop", "cte", "distinct", "left", "proj"],
            weights=[18, 20, 6, 5, 6, 6, 6, 4, 3, 5, 5, 6],
        )[0]
        return getattr(self, f"q_{shape}")()

    def where(self, tables: list[str], aliases: list[str], extra: list[str] | None = None) -> str:
        preds = list(extra or [])
        for _ in range(self.rng.choice([0, 1, 1, 2, 2, 3])):
            i = self.rng.randrange(len(tables))
            preds.append(self.pred(tables[i], aliases[i]))
        return (" WHERE " + " AND ".join(preds)) if preds else ""

    def aggs(self, tables: list[str], aliases: list[str]) -> list[tuple[str, str]]:
        r = self.rng
        out: list[tuple[str, str]] = []
        for k in range(r.choice([1, 1, 2, 3, 4])):
            i = r.randrange(len(tables))
            t, a = tables[i], aliases[i]
            q = f"{a}." if a else ""
            kind = r.choices(
                ["count", "countcol", "countd", "sumint", "sumval", "avgint", "avgval", "minint", "maxint", "minstr", "maxstr",
                 "casesum", "sumexpr", "countcase", "minval"],
                weights=[8, 3, 5, 5, 5, 3, 3, 3, 3, 2, 2, 4, 3, 2, 2],
            )[0]
            name = f"a{k}"
            if kind == "count":
                out.append(("COUNT(*)", name))
            elif kind == "countcol":
                out.append((f"COUNT({q}{self.pick(INT[t] + STR[t])})", name))
            elif kind == "countd":
                out.append((f"COUNT(DISTINCT {q}{self.pick(INT[t] + STR[t])})", name))
            elif kind == "sumint":
                out.append((f"SUM({q}{self.pick(INT[t])})", name))
            elif kind == "sumval" and "num" in tables:
                out.append((f"SUM({aliases[tables.index('num')]}{'.' if aliases[0] else ''}value)", name))
            elif kind == "avgint":
                out.append((f"AVG({q}{self.pick(INT[t])})", name))
            elif kind == "avgval" and "num" in tables:
                out.append((f"AVG({aliases[tables.index('num')]}{'.' if aliases[0] else ''}value)", name))
            elif kind == "minint":
                out.append((f"MIN({q}{self.pick(INT[t])})", name))
            elif kind == "maxint":
                out.append((f"MAX({q}{self.pick(INT[t])})", name))
            elif kind == "minstr":
                out.append((f"MIN({q}{self.pick(STR[t])})", name))
            elif kind == "maxstr":
                out.append((f"MAX({q}{self.pick(STR[t])})", name))
            elif kind == "casesum":
                c = self.pick(INT[t])
                out.append((f"SUM(CASE WHEN {q}{c} {self.pick(['>', '<', '='])} {self.pick(self.vals[(t, c)])} THEN 1 ELSE 0 END)", name))
            elif kind == "sumexpr":
                c = self.pick(INT[t])
                out.append((f"SUM({q}{c} {self.pick(['+', '*', '-'])} {r.randint(1, 5)})", name))
            elif kind == "countcase":
                c = self.pick(STR[t])
                out.append((f"COUNT(CASE WHEN {q}{c} = '{self.pick(self.vals[(t, c)])}' THEN 1 END)", name))
            elif kind == "minval" and "num" in tables:
                out.append((f"{self.pick(['MIN', 'MAX'])}({aliases[tables.index('num')]}{'.' if aliases[0] else ''}value)", name))
            else:
                out.append(("COUNT(*)", name))
        return out

    def grouped(self, tables, aliases, from_sql, extra_where=None) -> str:
        r = self.rng
        n_groups = r.choice([0, 1, 1, 1, 2])
        groups: list[str] = []
        for _ in range(n_groups):
            i = r.randrange(len(tables))
            t, a = tables[i], aliases[i]
            col = self.pick(STR[t] + INT[t])
            g = f"{a}.{col}" if a else col
            if g not in groups:
                groups.append(g)
        aggs = self.aggs(tables, aliases)
        sel = ", ".join(groups + [f"{e} AS {n}" for e, n in aggs])
        sql = f"SELECT {sel} FROM {from_sql}{self.where(tables, aliases, extra_where)}"
        if groups:
            sql += " GROUP BY " + ", ".join(groups)
            if self.chance(0.3):
                e, n = self.pick(aggs)
                if "value" not in e:
                    sql += f" HAVING {e} > {r.randint(0, 20)}"
            if self.chance(0.5):
                order = self.pick([n for _e, n in aggs] + groups)
                sql += f" ORDER BY {order} {self.pick(['ASC', 'DESC'])}"
                if self.chance(0.7):
                    sql += f" LIMIT {self.pick([5, 50, 100, 500])}"
        return sql

    def q_single(self) -> str:
        t = self.pick(["sub", "num", "tag", "pre"])
        return self.grouped([t], [""], t)

    def _join(self, ts: list[str]) -> tuple[list[str], list[str], str]:
        aliases = [ALIAS[t] for t in ts]
        sql = f"{ts[0]} {aliases[0]}"
        for i in range(1, len(ts)):
            keys = None
            for j in range(i):
                keys = KEYS.get((ts[j], ts[i])) or ([(b, a) for a, b in KEYS[(ts[i], ts[j])]] if (ts[i], ts[j]) in KEYS else None)
                if keys:
                    left = aliases[j]
                    break
            assert keys
            on = " AND ".join(f"{left}.{a} = {aliases[i]}.{b}" for a, b in keys)
            sql += f" JOIN {ts[i]} {aliases[i]} ON {on}"
        return ts, aliases, sql

    def q_join2(self) -> str:
        ts = list(self.pick(list(KEYS)))
        ts, aliases, from_sql = self._join(ts)
        return self.grouped(ts, aliases, from_sql)

    def q_join3(self) -> str:
        ts = self.pick([["num", "sub", "tag"], ["pre", "sub", "tag"], ["num", "pre", "sub"], ["num", "sub", "pre"]])
        ts, aliases, from_sql = self._join(ts)
        return self.grouped(ts, aliases, from_sql)

    def q_left(self) -> str:
        ts = list(self.pick(list(KEYS)))
        ts, aliases, from_sql = self._join(ts)
        return self.grouped(ts, aliases, from_sql.replace(" JOIN ", " LEFT JOIN ", 1))

    def q_derived(self) -> str:
        t = self.pick(["sub", "pre", "tag"])
        c = self.pick(INT[t])
        inner = f"SELECT {c} AS k, COUNT(*) AS c FROM {t}{self.where([t], [''])} GROUP BY {c}"
        if self.chance(0.5):
            return f"SELECT COUNT(*) AS n, SUM(c) AS total FROM ({inner}) d WHERE c > {self.rng.randint(0, 5)}"
        return f"SELECT k, c FROM ({inner}) d ORDER BY c DESC LIMIT 20"

    def q_exists(self) -> str:
        t = self.pick(["sub"])
        child = self.pick(["num", "pre"])
        neg = self.pick(["", "NOT "])
        inner_where = self.pred(child, "c")
        sel = self.pick(["COUNT(*) AS n", "s.form, COUNT(*) AS n", "s.fy, COUNT(*) AS n"])
        sql = f"SELECT {sel} FROM sub s WHERE {neg}EXISTS (SELECT 1 FROM {child} c WHERE c.adsh = s.adsh AND {inner_where})"
        if sel != "COUNT(*) AS n":
            sql += f" GROUP BY {sel.split(',')[0]}"
        return sql

    def q_insub(self) -> str:
        child = self.pick(["num", "pre"])
        neg = self.pick(["", "NOT "])
        sel = self.pick(["COUNT(*) AS n", "s.sic, COUNT(*) AS n"])
        sql = f"SELECT {sel} FROM sub s WHERE s.adsh {neg}IN (SELECT adsh FROM {child} WHERE {self.pred(child, '')})"
        if sel != "COUNT(*) AS n":
            sql += " GROUP BY s.sic"
        return sql

    def q_scalar(self) -> str:
        t = self.pick(["sub", "pre", "tag"])
        c = self.pick(INT[t])
        agg = self.pick(["AVG", "MAX", "MIN"])
        return f"SELECT COUNT(*) AS n FROM {t} WHERE {c} > (SELECT {agg}({c}) FROM {t}{self.where([t], [''])})"

    def q_setop(self) -> str:
        t = self.pick(["sub", "pre", "tag"])
        c = self.pick(STR[t])
        op = self.pick(["UNION", "UNION ALL", "INTERSECT", "EXCEPT"])
        return f"SELECT {c} FROM {t}{self.where([t], [''])} {op} SELECT {c} FROM {t}{self.where([t], [''])}"

    def q_cte(self) -> str:
        t = self.pick(["sub", "pre", "tag"])
        c = self.pick(INT[t])
        return (
            f"WITH x AS (SELECT {c} AS k, COUNT(*) AS c FROM {t} GROUP BY {c}) "
            f"SELECT k, c FROM x WHERE c > {self.rng.randint(0, 3)} ORDER BY c DESC LIMIT 10"
        )

    def q_distinct(self) -> str:
        t = self.pick(["sub", "num", "tag", "pre"])
        cols = ", ".join(self.rng.sample(STR[t] + INT[t], self.rng.choice([1, 2, 3])))
        sql = f"SELECT DISTINCT {cols} FROM {t}{self.where([t], [''])}"
        if self.chance(0.5):
            sql += f" LIMIT {self.pick([10, 100])}"
        return sql

    def q_proj(self) -> str:
        t = self.pick(["sub", "num", "tag", "pre"])
        cols = self.rng.sample(STR[t] + INT[t] + FLT.get(t, []), self.rng.choice([1, 2, 3]))
        sql = f"SELECT {', '.join(cols)} FROM {t}{self.where([t], [''])}"
        if self.chance(0.7):
            sql += f" ORDER BY {cols[0]} {self.pick(['ASC', 'DESC'])} LIMIT {self.pick([10, 100, 1000])}"
        return sql


def generate(seed: int, count: int) -> list[str]:
    gen = Gen(seed)
    con = duckdb.connect(str(_DB), read_only=True)
    out: list[str] = []
    seen: set[str] = set()
    while len(out) < count:
        sql = gen.query()
        if sql in seen:
            continue
        try:
            con.execute("EXPLAIN " + sql)
        except duckdb.Error:
            continue
        seen.add(sql)
        out.append(sql)
    con.close()
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("out")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--count", type=int, default=300)
    args = p.parse_args()
    queries = generate(args.seed, args.count)
    Path(args.out).write_text("\n".join(f"-- Q{i}: fuzz\n{q};\n" for i, q in enumerate(queries, 1)))
    print(args.out, len(queries), file=sys.stderr)


if __name__ == "__main__":
    main()
