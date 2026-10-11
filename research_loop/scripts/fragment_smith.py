"""SQLsmith conditioned on G: rejection sampling of stock DuckDB SQLsmith output.

    uv run python -m research_loop.scripts.fragment_smith --db sec_edgar_dec.duckdb --seed 5 --batches 50 --out DIR

Raw queries come from DuckDB's sqlsmith extension, unmodified (``CALL sqlsmith(max_queries=..., seed=...)``, batch ``i``
uses seed ``seed + i``). Each one goes through ``fragment_level`` (syntactic, cheap). Only those inside G are run in
DuckDB (short timeout, 1 GB, 2 threads); the ones that return at least one row and are not constant are kept. Writes the
accepted queries as ``accepted.sql`` and the counts as ``stats.json``. Nothing here changes what SQLsmith emits.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from declarative_spec.fragment import fragment_level
from research_loop.assumption_packages import assumption_package
from research_loop.scripts.fragment_gen import connect, features, provenance, run_checked, schema_from_db

BATCH = 2000


def raw_batch(db: Path, seed: int, n: int) -> list[str]:
    """``n`` raw SQLsmith statements for the catalog of ``db``."""
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "all.log"
        con = duckdb.connect(str(db), read_only=True)
        con.execute("LOAD sqlsmith")
        con.execute(f"CALL sqlsmith(max_queries={n}, seed={seed}, verbose_output=false, complete_log='{log}')").fetchall()
        con.close()
        text = log.read_text(errors="replace")
    return [q.strip() for q in text.split(";\n") if q.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--batches", type=int, default=10)
    ap.add_argument("--batch-size", type=int, default=BATCH)
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--package", default="sec_margin_dec")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    db = args.db or Path(os.environ.get("LEMMA_DUCKDB_PATH") or ROOT / "holdout" / "gendb_sec_edgar" / "duckdb" / "sec_edgar_dec.duckdb")
    args.out.mkdir(parents=True, exist_ok=True)
    schema = schema_from_db(db)
    nullable = {(t, c) for t, ta in assumption_package(args.package).tables.items() for c, ca in ta.columns.items() if ca.nullable}
    con = connect(db, threads=2, memory="1GB")
    stats: Counter = Counter()
    levels: Counter = Counter()
    refused: Counter = Counter()
    accepted: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    for b in range(args.batches):
        for sql in raw_batch(db, args.seed + b, args.batch_size):
            stats["generated"] += 1
            level, why = fragment_level(sql, schema, nullable, "duckdb")  # DuckDB syntax: the most favourable reading of SQLsmith's output
            if level is None:
                refused[why.split(" ")[0]] += 1
                continue
            stats["in_g"] += 1
            levels[level] += 1
            if sql in seen:
                stats["duplicate"] += 1
                continue
            seen.add(sql)
            status, _ = run_checked(con, sql + ";", args.timeout)
            if status != "ok":
                stats["rejected_" + status.split(":")[0]] += 1
                continue
            stats["accepted"] += 1
            accepted.append((args.seed + b, level, sql))
        print(f"batch {b + 1}/{args.batches} {dict(stats)}", file=sys.stderr, flush=True)
        (args.out / "stats.json").write_text(
            json.dumps({**provenance(db, args.package, "smith_conditioned_on_G", args.seed, batch_size=args.batch_size, batch_seeds=f"{args.seed}..{args.seed + args.batches - 1}", timeout_sec=args.timeout), "batches_done": b + 1, "stats": stats, "levels_in_g": levels, "outside_g_by_rule": refused}, indent=1)
        )
        (args.out / "accepted.sql").write_text("".join(f"-- Q{i}: batch_seed={s} level={lv}\n{q};\n\n" for i, (s, lv, q) in enumerate(accepted, 1)))
    shape: Counter = Counter()
    for _, _, sql in accepted:
        shape.update(features(sql))
    (args.out / "shape_counts.json").write_text(json.dumps(shape, indent=1))
    print(json.dumps({"stats": stats, "levels": levels}, indent=1))


if __name__ == "__main__":
    main()
