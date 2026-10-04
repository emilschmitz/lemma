"""Differential fuzz of emitted declarative specs against DuckDB, on tiny integer tables.

    uv run python research_loop/scripts/decl_speceval_fuzz.py --seed 1 --count 40

For each random query the emitted spec's aggregate functions are evaluated by Verus on concrete rows
(``tests/spec_eval.py``) and must equal DuckDB's answer, group by group. Queries the emitter refuses are counted.
A mismatch is a spec that does not mean what SQL means. One Verus run at a time, through the memory guard.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from declarative_spec.emit import emit_declarative_spec  # noqa: E402
from research_loop.scripts.decl_coverage import free_mb  # noqa: E402
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions  # noqa: E402
from tests.spec_eval import prove_facts  # noqa: E402

SCHEMA = {"t": {"a": "bigint", "g": "bigint", "h": "bigint"}, "u": {"g": "bigint", "w": "bigint"}}
CAP = 5
CATALOG = CatalogAssumptions(max_rows=CAP, tables={n: TableAssumptions(max_rows=CAP) for n in SCHEMA})
ALIASES = ["x", "y", "p", "q", "res", "k", "i0", "row", "t", "u", "a", "g", "r", "sub"]


def rows(rng: random.Random) -> dict[str, list[dict]]:
    return {
        "t": [{"a": rng.randint(0, 4), "g": rng.randint(0, 2), "h": rng.randint(0, 3)} for _ in range(rng.randint(2, CAP))],
        "u": [{"g": rng.randint(0, 2), "w": rng.randint(0, 4)} for _ in range(rng.randint(2, CAP))],
    }


def pred(rng: random.Random, q: str, cols: list[str]) -> str:
    c = f"{q}{rng.choice(cols)}"
    kind = rng.choice(["cmp", "cmp", "between", "in", "or", "not"])
    op = rng.choice(["<", "<=", ">", ">=", "=", "<>"])
    if kind == "between":
        return f"{c} BETWEEN {rng.randint(0, 2)} AND {rng.randint(2, 4)}"
    if kind == "in":
        return f"{c} IN ({rng.randint(0, 2)}, {rng.randint(2, 4)})"
    if kind == "or":
        return f"({c} {op} {rng.randint(0, 4)} OR {q}{rng.choice(cols)} {op} {rng.randint(0, 4)})"
    if kind == "not":
        return f"NOT ({c} {op} {rng.randint(0, 4)})"
    return f"{c} {op} {rng.randint(0, 4)}"


def aggs(rng: random.Random, refs: list[str]) -> list[tuple[str, str]]:
    out = []
    for i in range(rng.randint(1, 3)):
        col = rng.choice(refs)
        kind = rng.choice(["count", "count", "sum", "sumx", "casesum", "countcol", "countcase", "countcase"])
        e = {
            "count": "COUNT(*)",
            "countcol": f"COUNT({col})",
            "sum": f"SUM({col})",
            "sumx": f"SUM({col} * 2 + 1)",
            "casesum": f"SUM(CASE WHEN {col} > 1 THEN 1 ELSE 0 END)",
            "countcase": f"COUNT(CASE WHEN {col} > 1 OR {col} = 0 THEN 1 END)",
        }[kind]
        out.append((e, f"c{i}"))
    return out


def query(rng: random.Random) -> tuple[str, list[str]]:
    """SQL and the group-key output names."""
    shape = rng.choice(["single", "single", "join", "self", "exists", "scalar", "derived"])
    al = rng.sample(ALIASES, 2)
    a1, a2 = al
    if shape == "single":
        frm, refs, cols = f"t {a1}", [f"{a1}.a", f"{a1}.h"], [(a1, ["a", "g", "h"])]
        where = [pred(rng, f"{a1}.", ["a", "g", "h"]) for _ in range(rng.randint(0, 2))]
        keys = [f"{a1}.g"] if rng.random() < 0.7 else []
    elif shape == "join":
        frm = f"t {a1} JOIN u {a2} ON {a1}.g = {a2}.g"
        refs = [f"{a1}.a", f"{a2}.w"]
        where = [pred(rng, f"{a1}.", ["a", "h"]), pred(rng, f"{a2}.", ["w"])][: rng.randint(0, 2)]
        keys = [rng.choice([f"{a1}.g", f"{a2}.g"])] if rng.random() < 0.7 else []
    elif shape == "self":
        frm = f"t {a1}, t {a2}"
        refs = [f"{a1}.a", f"{a2}.a", f"{a2}.h"]
        where = [f"{a1}.g = {a2}.g", f"{a1}.a < {a2}.a"]
        keys = [rng.choice([f"{a1}.h", f"{a2}.h", f"{a1}.g"])] if rng.random() < 0.8 else []
    elif shape == "exists":
        frm = f"t {a1}"
        refs = [f"{a1}.a", f"{a1}.h"]
        neg = rng.choice(["", "NOT "])
        where = [f"{neg}EXISTS (SELECT 1 FROM u {a2} WHERE {a2}.g = {a1}.g AND {a2}.w {rng.choice(['>', '<', '='])} {a1}.a)"]
        keys = [f"{a1}.g"] if rng.random() < 0.5 else []
    elif shape == "insub":
        frm = f"t {a1}"
        refs = [f"{a1}.a"]
        where = [f"{a1}.g {rng.choice(['IN', 'NOT IN'])} (SELECT g FROM u WHERE w > {rng.randint(0, 3)})"]
        keys = [f"{a1}.h"] if rng.random() < 0.5 else []
    elif shape == "scalar":
        frm = f"t {a1}"
        refs = [f"{a1}.a"]
        where = [f"{a1}.a {rng.choice(['>', '<=', '='])} (SELECT COUNT(a) FROM t WHERE h > {rng.randint(0, 2)})"]
        keys = [f"{a1}.g"] if rng.random() < 0.5 else []
    else:
        c = rng.randint(0, 2)
        sql = (
            f"SELECT k, c FROM (SELECT g AS k, COUNT(*) AS c FROM t WHERE h >= {rng.randint(0, 2)} GROUP BY g) {a1} "
            f"WHERE c > {c}"
        )
        return sql, ["k"]
    ag = aggs(rng, refs)
    sel = ", ".join([f"{k} AS k{i}" for i, k in enumerate(keys)] + [f"{e} AS {n}" for e, n in ag])
    sql = f"SELECT {sel} FROM {frm}" + (" WHERE " + " AND ".join(where) if where else "")
    if keys:
        sql += " GROUP BY " + ", ".join(keys)
        if rng.random() < 0.3:
            sql += f" HAVING COUNT(*) > {rng.randint(0, 2)}"
    return sql, [f"k{i}" for i in range(len(keys))]


def facts_for(spec: str, sql: str, duck: duckdb.DuckDBPyConnection, n_keys: int) -> tuple[list[str], list[str]] | None:
    sig = re.search(r"pub fn run_query\(([^)]*)\)", spec).group(1)
    params = ", ".join(re.findall(r"(\w+): &Cols_", sig))
    got = duck.execute(sql).fetchall()
    cols = [d[0] for d in duck.description]
    facts: list[str] = []
    funs: list[str] = []
    for row in got:
        keys = [int(v) for v in row[:n_keys]]
        for col, val in zip(cols[n_keys:], row[n_keys:], strict=True):
            if val is None or col.startswith("k"):
                continue
            m = re.search(rf"spec fn ((?:count|sum)_{re.escape(col)})\(", spec)
            if m is None:
                return None
            fn = m.group(1)
            if isinstance(val, float):
                return None
            key = f", {keys[0]}" if n_keys == 1 else ""
            if n_keys > 1:
                return None
            facts.append(f"{fn}({params}, 0{key}) == {int(val)}int")
            funs += [fn, f"{fn}_d1", f"{fn}_d2"]
    return facts, sorted({f for f in funs if re.search(rf"spec fn {f}\b", spec) and re.search(rf"spec fn {f}\([^)]*\)[^{{]*decreases", spec, re.S)})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--count", type=int, default=40)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    stats = {"refused": 0, "proved": 0, "skipped": 0, "mismatch": 0}
    for _ in range(args.count):
        sql, keys = query(rng)
        tables = rows(rng)
        duck = duckdb.connect()
        for t, cols in SCHEMA.items():
            duck.execute(f"CREATE TABLE {t} ({', '.join(c + ' BIGINT' for c in cols)})")
            duck.executemany(f"INSERT INTO {t} VALUES ({', '.join('?' for _ in cols)})", [tuple(r[c] for c in cols) for r in tables[t]])
        try:
            spec = emit_declarative_spec(sql, SCHEMA, CATALOG)
        except Exception as exc:  # noqa: BLE001
            stats["refused"] += 1
            if type(exc).__name__ not in ("DeclarativeUnsupported", "FitRefusal"):
                print("CRASH", type(exc).__name__, exc, "::", sql)
            continue
        if sql.startswith("SELECT k, c FROM"):
            continue
        made = facts_for(spec, sql, duck, len(keys))
        if made is None or not made[0]:
            stats["skipped"] += 1
            continue
        facts, funs = made
        while free_mb() < 4000:
            time.sleep(10)
        ok, out = prove_facts(spec, tables, facts, fuel=8)
        if ok:
            stats["proved"] += 1
        else:
            stats["mismatch"] += 1
            err = [ln for ln in out.splitlines() if ln.startswith("error")][:2]
            print("MISMATCH", sql, "\n   rows", tables, "\n   facts", facts[:4], "\n  ", err)
    print(stats)


if __name__ == "__main__":
    main()
