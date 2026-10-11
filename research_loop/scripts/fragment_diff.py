"""Meaning check of queries from G against DuckDB on small random tables.

    uv run python -m research_loop.scripts.fragment_diff --level med --seed 1 --cases 30

A random query of the level is drawn over a small synthetic database (integer columns, one nullable, duplicates, small
values). Its tables are cut down to a few random rows (``CAP``; the spec is unfolded by Verus, which does not scale to 50
rows), DuckDB answers the query on them, and Verus must prove each answered aggregate value equals the spec's helper
function at that group (``tests/spec_eval.py::prove_facts``, the harness the other declarative tests use). Each case
also runs a control: the same facts with one value moved by one must NOT prove. Verus runs one at a time through the
memory guard.

What this covers: per-group COUNT / SUM values over joins, filters (comparisons, IN, BETWEEN, IS NULL,
AND/OR/NOT), NULL cells, duplicates, one or two integer group keys. What it does not (no executable form exists for
it, so nothing is invented; MIN and MAX are bound predicates ('exists a row with this value and all rows <='), and
the Verus harness does not prove them (it fails on true facts, so those queries are skipped, not scored): which groups appear, HAVING, ORDER BY and LIMIT tie handling, AVG and other float results,
COUNT DISTINCT, strings, DECIMAL and DATE scaling (see the other ``tests/test_declarative_*`` files), subqueries.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from declarative_spec.emit import emit_declarative_spec
from research_loop.scripts.decl_coverage import free_mb
from research_loop.scripts.fragment_coverage import reason_class
from research_loop.scripts.fragment_gen import draw, schema_from_db
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions
from tests.spec_eval import prove_facts

CAP = 5
NULLABLE = {("f", "n")}


def make_db(path: Path, rng: random.Random) -> dict[str, list[dict]]:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE f (k BIGINT, g BIGINT, a BIGINT, h BIGINT, n BIGINT)")
    con.execute("CREATE TABLE d (k BIGINT, w BIGINT)")
    f = [{"k": rng.randint(0, 3), "g": rng.randint(0, 2), "a": rng.randint(-1, 4), "h": rng.randint(0, 3), "n": None if rng.random() < 0.3 else rng.randint(0, 3)} for _ in range(60)]
    d = [{"k": rng.randint(0, 3), "w": rng.randint(0, 4)} for _ in range(20)]
    con.executemany("INSERT INTO f VALUES (?, ?, ?, ?, ?)", [tuple(r.values()) for r in f])
    con.executemany("INSERT INTO d VALUES (?, ?)", [tuple(r.values()) for r in d])
    con.close()
    return {"f": f, "d": d}


def facts_for(spec: str, rows: list[tuple], cols: list[str], n_keys: int, params: str, shift: int) -> tuple[list[str], int] | None:
    """Verus facts ``helper(args, key) == value`` for every aggregate cell DuckDB returned; ``shift`` moves each by one (control)."""
    facts: list[str] = []
    for row in rows:
        keys = [int(v) for v in row[:n_keys]]
        key = "" if n_keys == 0 else f", {keys[0]}int" if n_keys == 1 else ", (" + ", ".join(f"{k}int" for k in keys) + ")"
        for col, val in zip(cols[n_keys:], row[n_keys:], strict=True):
            if val is None:
                return None  # an all-NULL aggregate has no value in a spec that carries no NULL (rule T2 keeps it out)
            if isinstance(val, float):
                return None
            m = re.search(rf"spec fn ((?:count|sum)_{re.escape(col)})\(", spec)
            if m:
                facts.append(f"{m.group(1)}({params}, 0{key}) == {int(val) + shift}int")
                continue
            return None
    return facts, len(facts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--level", choices=("high", "med", "full"), default="med")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--cases", type=int, default=20)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    stats: Counter = Counter()
    reasons: Counter = Counter()
    report: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "small.duckdb"
        source = make_db(db, rng)
        queries, _, _ = draw(db, args.seed, args.cases * 3, level=args.level, pairwise=False, nullable=NULLABLE)
        schema = schema_from_db(db)
        for sql in queries:
            if stats["proved"] + stats["mismatch"] >= args.cases:
                break
            tables = {t: rng.sample(rs, CAP) for t, rs in source.items()}
            duck = duckdb.connect()
            for t, cols in (("f", ["k", "g", "a", "h", "n"]), ("d", ["k", "w"])):
                duck.execute(f"CREATE TABLE {t} ({', '.join(c + ' BIGINT' for c in cols)})")
                duck.executemany(f"INSERT INTO {t} VALUES ({', '.join('?' for _ in cols)})", [tuple(r[c] for c in cols) for r in tables[t]])
            catalog = CatalogAssumptions(
                max_rows=CAP,
                tables={t: TableAssumptions(max_rows=CAP, columns={"n": ColumnAssumption(nullable=True)} if t == "f" else {}) for t in schema},
            )
            try:
                spec = emit_declarative_spec(sql, schema, catalog)
            except Exception as exc:  # noqa: BLE001 - refusals are the coverage script's business
                stats["refused"] += 1
                reasons[reason_class(exc)] += 1
                continue
            plain = re.sub(r"\s+LIMIT\s+\d+;?$", "", re.sub(r"\s+ORDER BY .*?(?=\s+LIMIT|;|$)", "", sql.rstrip(";")))  # all groups, not the top-N cut
            got = duck.execute(plain).fetchall()
            names = [x[0] for x in duck.description]
            n_keys = len(re.findall(r"\bGROUP BY\b(.*)$", plain)[0].split(",")) if " GROUP BY " in plain else 0
            sig = re.search(r"pub fn run_query\(([^)]*)\)", spec).group(1)
            params = ", ".join(re.findall(r"(\w+): &Cols_", sig))
            group_text = plain.split(" GROUP BY ", 1)[1] if " GROUP BY " in plain else ""
            if any(re.search(rf"\b{c}\b", group_text) for _t, c in NULLABLE):
                stats["skipped_nullable_group_key"] += 1  # the key of such a group is an Option; the harness states only integer keys
                continue
            made = facts_for(spec, got, names, n_keys, params, 0) if got else None
            if made is None or not made[0]:
                stats["skipped_no_facts"] += 1
                continue
            while free_mb() < 4000:
                time.sleep(10)
            ok, out = prove_facts(spec, tables, made[0])
            control_facts = facts_for(spec, got, names, n_keys, params, 1)[0][:1]
            ctl_ok, _ = prove_facts(spec, tables, control_facts)
            if ctl_ok:
                stats["control_failed"] += 1  # a wrong value proved: the harness cannot tell here
            if ok:
                stats["proved"] += 1
            else:
                stats["mismatch"] += 1
                report.append({"sql": sql, "rows": tables, "facts": made[0][:4], "error": [ln for ln in out.splitlines() if ln.startswith("error")][:3]})
                report[-1]["failing_facts"] = [f for f in made[0] if not prove_facts(spec, tables, [f])[0]]
                print("MISMATCH", sql, report[-1]["error"], report[-1]["failing_facts"][:3], flush=True)
            print(dict(stats), flush=True)
    print(json.dumps({"level": args.level, "seed": args.seed, "stats": stats, "refusals_on_the_small_catalog": reasons}, indent=1))
    if args.out:
        args.out.write_text(json.dumps({"level": args.level, "seed": args.seed, "stats": stats, "refusals_on_the_small_catalog": reasons, "mismatches": report}, indent=1))


if __name__ == "__main__":
    main()
