"""Regenerate an evaluation pool and a random pick from one seed. No prover, no container: it only resamples.

    uv run python -m research_loop.scripts.resample_eval --seed S --level med --pool-n 500 --pick 10 --out DIR \\
        [--burned burned.json] [--replay DIR_OF_AN_EARLIER_RUN/manifest.json]

1. The pool: ``pool_n`` queries of grammar level ``--level`` drawn with ``fragment_gen.draw(seed=S)`` (one seeded
   ``random.Random``, sorted choices, literals sampled from the data with a repeatable single-thread sample). A draw is
   kept only when DuckDB runs it, it returns a non-constant non-empty result, it is exactly of that level (``med`` means
   two tables), it transpiles, its largest table has >= ``--min-fact-rows`` rows, and DuckDB (all cores, hot) takes
   >= ``--min-ms``.
2. The pick: ``pick_seed = int(sha256("S:pick")[:8], 16)`` (recorded). The pool is shuffled with ``Random(pick_seed)`` and the
   first ``--pick`` queries are taken that are not in ``burned.json`` (a list of SQL texts or their sha256) and are not
   near-duplicates (same tables, group columns, filter columns, aggregate signature) of one already picked.

Determinism: same seed + same database file + same code => byte-identical ``pool.sql`` and ``pick/``. Two inputs are
wall-clock: the DuckDB timeout of the draw and the ``--min-ms`` timing. Both are recorded in ``manifest.json``
(``decisions``, ``ms``); ``--replay`` feeds them back so a replay re-measures nothing and takes the same decisions (a
live timeout the record does not list raises). Without ``--replay`` a rerun on the same quiet machine repeats them, and
the manifest says which candidates were close to a threshold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from pathlib import Path

import duckdb
import sqlglot
from sqlglot import exp

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from declarative_spec.fragment import fragment_level
from research_loop.assumption_packages import assumption_package
from research_loop.scripts.fragment_coverage import transpile
from research_loop.scripts.fragment_gen import connect, draw, provenance, schema_from_db
from research_loop.scripts.fragment_pool import signature, timed

DEFAULT_DB = ROOT / "holdout" / "gendb_sec_edgar" / "duckdb" / "sec_edgar_dec.duckdb"


def pick_seed(seed: int) -> int:
    return int(hashlib.sha256(f"{seed}:pick".encode()).hexdigest()[:8], 16)


def normal(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


def burned_set(path: Path | None) -> set[str]:
    """SQL texts (normalised) and their sha256 from ``burned.json``."""
    if path is None:
        return set()
    entries = json.loads(path.read_text())
    return {normal(e) for e in entries} | {hashlib.sha256(normal(e).encode()).hexdigest() for e in entries} | set(entries)


def pick_from(pool: list[str], seed: int, k: int, burned: set[str]) -> list[int]:
    """Indices into ``pool`` of the pick: shuffled by the derived seed, skipping burned and near-duplicate queries."""
    order = list(range(len(pool)))
    random.Random(pick_seed(seed)).shuffle(order)
    chosen: list[int] = []
    seen: set[tuple] = set()
    for i in order:
        sql = normal(pool[i])
        if sql in burned or hashlib.sha256(sql.encode()).hexdigest() in burned:
            continue
        sig = signature(sql)
        if sig in seen:
            continue
        seen.add(sig)
        chosen.append(i)
        if len(chosen) == k:
            break
    return chosen


def resample(
    db: Path,
    package: str,
    seed: int,
    level: str,
    pool_n: int,
    pick: int,
    out: Path,
    *,
    burned: Path | None = None,
    min_fact_rows: int = 100_000,
    min_ms: float = 20.0,
    replay: dict | None = None,
    catalog=None,
) -> dict:
    catalog_given = catalog is not None
    schema, catalog = schema_from_db(db), catalog or assumption_package(package)
    nullable = {(t, c) for t, ta in catalog.tables.items() for c, ca in ta.columns.items() if ca.nullable}
    con = connect(db, threads=1)
    rows_of = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in schema}
    con.close()
    ms_in = (replay or {}).get("ms")
    ms_out: dict[str, float] = {}

    def judge(sql: str, index: int) -> str | None:
        got, _ = fragment_level(sql, schema, nullable)
        if got != level:
            return "wrong_level"
        tables = [t.name.lower() for t in sqlglot.parse_one(sql).find_all(exp.Table)]
        if max(rows_of[t] for t in tables) < min_fact_rows:
            return "fact_table_too_small"
        if transpile(sql, schema, catalog)[0] is None:
            return "transpile_refused"
        if min_ms > 0:
            if ms_in is not None and str(index) in ms_in:
                ms = ms_in[str(index)]
            elif ms_in is not None:
                raise RuntimeError(f"replay diverged: candidate {index} was not timed in the recorded run")
            else:
                ms, _ = timed(db, sql)
            ms_out[str(index)] = round(ms, 2)
            if ms < min_ms:
                return "duckdb_under_min_ms"
        return None

    pool, rejects, info = draw(
        db, seed, pool_n, pairwise=False, level=level, package=None if catalog_given else package, nullable=nullable, judge=judge,
        replay=(replay or {}).get("decisions"),
    )
    chosen = pick_from(pool, seed, pick, burned_set(burned))
    out.mkdir(parents=True, exist_ok=True)
    (out / "pick").mkdir(exist_ok=True)
    (out / "pool.sql").write_text("".join(f"-- Q{i}:\n{q}\n\n" for i, q in enumerate(pool, 1)))
    for rank, i in enumerate(chosen, 1):
        (out / "pick" / f"q{rank:02d}.sql").write_text(pool[i].rstrip(";") + ";\n")
    manifest = {
        **provenance(db, package, level, seed, pool_n=pool_n, pick=pick, pick_seed=pick_seed(seed),
                     thresholds={"min_fact_rows": min_fact_rows, "min_duckdb_ms": min_ms, "draw_timeout_sec": 8.0},
                     burned=str(burned) if burned else None),
        "candidates": info["candidates"],
        "rejects": rejects,
        "decisions": info["decisions"],
        "ms": ms_out,
        "pool_sha256": hashlib.sha256((out / "pool.sql").read_bytes()).hexdigest(),
        "pick_pool_indices": chosen,
        "pick_files": {f"q{r:02d}.sql": hashlib.sha256((out / "pick" / f"q{r:02d}.sql").read_bytes()).hexdigest() for r in range(1, len(chosen) + 1)},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--level", choices=("high", "med"), required=True)
    ap.add_argument("--pool-n", type=int, default=500)
    ap.add_argument("--pick", type=int, default=10)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--burned", type=Path)
    ap.add_argument("--db", type=Path, default=Path(os.environ.get("LEMMA_DUCKDB_PATH") or DEFAULT_DB))
    ap.add_argument("--package", default="sec_margin_dec")
    ap.add_argument("--min-fact-rows", type=int, default=100_000)
    ap.add_argument("--min-ms", type=float, default=20.0)
    ap.add_argument("--replay", type=Path, help="manifest.json of an earlier run with the same seed: reuse its timeout and timing decisions")
    args = ap.parse_args()
    replay = json.loads(args.replay.read_text()) if args.replay else None
    manifest = resample(args.db, args.package, args.seed, args.level, args.pool_n, args.pick, args.out,
                        burned=args.burned, min_fact_rows=args.min_fact_rows, min_ms=args.min_ms, replay=replay)
    print(json.dumps({"pool": args.pool_n, "picked": manifest["pick_pool_indices"], "rejects": manifest["rejects"]}))


if __name__ == "__main__":
    main()
