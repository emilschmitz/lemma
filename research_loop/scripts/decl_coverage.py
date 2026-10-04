"""Emission coverage of the declarative path on a saved sample of queries.

    uv run python research_loop/scripts/decl_coverage.py gen  N --seed S --count 300
    uv run python research_loop/scripts/decl_coverage.py emit N [--tpch]
    uv run python research_loop/scripts/decl_coverage.py tc   N [--tpch] --max 40 --seed S

``gen`` saves a GenDB-shaped SEC sample to research_loop/generated/decl_coverage/round_N.sql.
``emit`` runs ``emit_declarative_spec`` on every query and ranks refusals and crashes.
``tc`` Verus-typechecks (``--no-verify``, one at a time, through the memory guard)
a bounded random subset of the queries that emitted.
"""

from __future__ import annotations

import argparse
import collections
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "research_loop" / "generated" / "decl_coverage"
_GEN = Path("/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/generate_queries.py")
_DB = Path("/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/duckdb/sec_edgar_local.duckdb")
GUARD = ROOT / "scripts" / "ram" / "verus_guarded.sh"


def tpch_schema() -> dict[str, dict[str, str]]:
    import duckdb

    con = duckdb.connect()
    con.execute("load tpch")
    con.execute("call dbgen(sf=0.01)")
    out: dict[str, dict[str, str]] = {}
    for (table,) in con.execute("show tables").fetchall():
        out[table] = {r[0]: r[1].lower() for r in con.execute(f"describe {table}").fetchall()}
    return out


def tpch_catalog(schema):
    from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

    rows = {"region": 8, "nation": 32, "part": 2**21, "supplier": 2**17, "partsupp": 2**23,
            "customer": 2**21, "orders": 2**24, "lineitem": 2**26}
    unique = {"orders": (("o_orderkey",),), "customer": (("c_custkey",),), "part": (("p_partkey",),),
              "supplier": (("s_suppkey",),), "nation": (("n_nationkey",),),
              "partsupp": (("ps_partkey", "ps_suppkey"),)}
    return CatalogAssumptions(
        max_rows=2**26,
        tables={
            t: TableAssumptions(
                max_rows=rows[t],
                unique_keys=unique.get(t, ()),
                columns={
                    c: ColumnAssumption(max_string_len=256) if ty == "varchar"
                    else ColumnAssumption(max_value_exclusive=2**40)
                    for c, ty in cols.items()
                },
            )
            for t, cols in schema.items()
        },
    )


def tpch_queries() -> list[str]:
    import duckdb

    con = duckdb.connect()
    con.execute("load tpch")
    rows = con.execute("select query from tpch_queries() order by query_nr").fetchall()
    return [q.strip().rstrip(";") for (q,) in rows]


def load_sql(path: Path) -> list[str]:
    """Queries of a ``-- Q<n>...`` labeled file (GenDB or fuzz), whatever statement each starts with."""
    blocks = re.split(r"^--\s*Q\d+.*$", path.read_text(), flags=re.MULTILINE)[1:]
    out = []
    for block in blocks:
        body = "\n".join(line for line in block.splitlines() if not line.lstrip().startswith("--"))
        body = body.strip().rstrip(";").strip()
        if body:
            out.append(body)
    return out


def context(tpch: bool):
    if tpch:
        schema = tpch_schema()
        return schema, tpch_catalog(schema)
    from research_loop.assumption_packages import assumption_package
    from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema

    if os.environ.get("DECL_DEC") == "1":  # the DECIMAL(38,4) variant of the SEC database
        return load_sec_schema(_DB.with_name("sec_edgar_local_dec.duckdb")), assumption_package("sec_margin_dec")
    return load_sec_schema(), assumption_package("sec_margin")


def queries_for(round_n: str, tpch: bool, fuzz: bool = False) -> list[str]:
    if tpch:
        f = OUT / f"tpch_{round_n}.sql"
        base = tpch_queries()
        if f.is_file():
            base += [q.strip() for q in f.read_text().split(";\n") if q.strip()]
        return base
    if fuzz:
        return load_sql(OUT / f"fuzz_{round_n}.sql")
    return load_sql(OUT / f"round_{round_n}.sql")


def normalize(msg: str) -> str:
    msg = " ".join(msg.split())
    msg = re.sub(r"'[^']*'", "'_'", msg)
    msg = re.sub(r"\b\d+\b", "N", msg)
    return msg[:140]


def emit_all(sqls, schema, catalog):
    from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
    from declarative_spec.lemmas import FitRefusal

    ok: list[tuple[str, str]] = []
    refused: dict[str, list[str]] = collections.defaultdict(list)
    crashed: dict[str, list[str]] = collections.defaultdict(list)
    for sql in sqls:
        try:
            ok.append((sql, emit_declarative_spec(sql, schema, catalog, float_abs_eps="1e20")))
        except (DeclarativeUnsupported, FitRefusal) as exc:
            refused[normalize(f"{type(exc).__name__}: {exc}")].append(sql)
        except Exception as exc:  # noqa: BLE001  report every crash
            crashed[normalize(f"{type(exc).__name__}: {exc}")].append(sql)
    return ok, refused, crashed


def cmd_emit(args) -> None:
    schema, catalog = context(args.tpch)
    sqls = queries_for(args.round, args.tpch, args.fuzz)
    ok, refused, crashed = emit_all(sqls, schema, catalog)
    total = len(sqls)
    print(
        f"total={total} emitted={len(ok)} ({100 * len(ok) / total:.1f}%) "
        f"refused={sum(map(len, refused.values()))} crashed={sum(map(len, crashed.values()))}"
    )
    for title, bucket in (("REFUSALS", refused), ("CRASHES", crashed)):
        print(f"--- {title} ranked")
        for reason, qs in sorted(bucket.items(), key=lambda kv: -len(kv[1])):
            print(f"{len(qs):4d}  {reason}")
            print("      e.g. " + " ".join(qs[0].split())[:220])


def free_mb() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable"):
            return int(line.split()[1]) // 1024
    return 0


def typecheck(spec: str, *, full: bool = False, verify: bool = False) -> str:
    """Verus ``--no-verify`` typecheck, or (``verify``) a full run with ``assume(false)`` as the body so that
    only the host lemmas are proved."""
    from declarative_spec.assemble import assemble_declarative_program

    prog = assemble_declarative_program(spec, "    assume(false);\n    loop invariant true decreases 0int { assume(false); }" if verify else "    loop {}")
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(prog)
    try:
        proc = subprocess.run(
            [str(GUARD), handle.name, *([] if verify else ["--no-verify"]), "--triggers-mode", "silent"],
            capture_output=True, text=True, check=False, timeout=300,
        )
    finally:
        os.unlink(handle.name)
    if proc.returncode == 0:
        return "OK"
    text = proc.stdout + proc.stderr
    if full:
        return text
    return "FAIL: " + " | ".join(line for line in text.splitlines() if line.startswith("error"))[:500]


def cmd_tc(args) -> None:
    schema, catalog = context(args.tpch)
    ok, _r, _c = emit_all(queries_for(args.round, args.tpch, args.fuzz), schema, catalog)
    rng = random.Random(args.seed)
    rng.shuffle(ok)
    buckets: dict[str, list[str]] = collections.defaultdict(list)
    for sql, spec in ok[: args.max]:
        while free_mb() < 4000:
            time.sleep(10)
        verdict = typecheck(spec)
        if verdict != "OK":
            first = verdict.removeprefix("FAIL: ").split(" | ")[0]
            buckets[normalize(first)].append(sql)
    failed = sum(map(len, buckets.values()))
    print(f"typechecked={min(args.max, len(ok))} failed={failed}")
    for reason, qs in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        print(f"{len(qs):4d}  {reason}")
        print("      e.g. " + " ".join(qs[0].split())[:400])


def cmd_gen(args) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if args.fuzz:
        from research_loop.scripts.decl_fuzz import generate

        out = OUT / f"fuzz_{args.round}.sql"
        qs = generate(args.seed, args.count)
        out.write_text("\n".join(f"-- Q{i}: fuzz\n{q};\n" for i, q in enumerate(qs, 1)))
        print(out, len(qs))
        return
    out = OUT / f"round_{args.round}.sql"
    subprocess.run(
        [sys.executable, str(_GEN), "--seed", str(args.seed), "--num-generate", str(args.count * 4),
         "--num-select", str(args.count), "--db-path", str(_DB), "--output", str(out)],
        check=True,
    )
    print(out, len(load_sql(out)))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["gen", "emit", "tc"])
    p.add_argument("round")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--count", type=int, default=300)
    p.add_argument("--max", type=int, default=40)
    p.add_argument("--tpch", action="store_true")
    p.add_argument("--fuzz", action="store_true")
    args = p.parse_args()
    {"gen": cmd_gen, "emit": cmd_emit, "tc": cmd_tc}[args.cmd](args)


if __name__ == "__main__":
    main()
