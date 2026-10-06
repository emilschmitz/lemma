"""Draw the shared arena: fresh GenDB SEC queries (new seed, never seen) plus TPC-H shapes, with a manifest.

    arena_draw.py --seed N --sec 12 --out DIR

Candidates come from the GenDB shuffle generator on the DECIMAL SEC database. A candidate is kept only if
(1) the declarative emitter accepts it under the container settings (dictionary strings, ``sec_margin_dec``),
(2) its normalized SQL appears in no corpus of seen queries (earlier draws, published queries, fixture and test texts), and
(3) its literal-stripped SHAPE is not the shape of any query behind a fixture or example. Picks are spread over shape classes
(recipe x tier). The manifest records the seed, the class of each pick and what it was checked against.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAIN = Path("/home/emil/projects/lemma-db")


def _sql_in_text(text: str) -> list[str]:
    """SELECT statements found in a free text (fixture comment headers, test files, logs): comment slashes stripped, up to ';' or a blank."""
    flat = re.sub(r"^\s*(//+|#+)\s?", "", text, flags=re.M)
    out = []
    for m in re.finditer(r"(?is)\bSELECT\b.+?(?=;|\n\s*\n|\"\"\"|$)", flat):
        out.append(m.group(0))
    return out


def seen_corpus() -> tuple[set[str], set[str], str]:
    """(normalized seen queries, literal-stripped shapes of seen queries, whitespace-collapsed raw text of everything scanned)."""
    from research_loop.scripts.declarative_tiers import normalize, shape_key
    from research_loop.scripts.sqlsmith_trusted_coverage import parse_sql_file

    files: list[Path] = []
    for base in (ROOT, MAIN):
        files += list((base / "harvest").glob("**/*.sql")) if (base / "harvest").is_dir() else []
        files += list((base / "holdout").glob("**/*.sql"))
        files += list((base / "tests").glob("**/*.rs")) + list((base / "tests").glob("**/*.py")) + list((base / "tests").glob("**/*.sql"))
        gen = base / "research_loop" / "generated"
        if gen.is_dir():
            files += [p for p in gen.glob("**/query.sql")] + list(gen.glob("**/*.sql"))
        files += list((base / "research_loop" / "menus").glob("*.md"))
    # other worktrees keep their own manual workspaces and draws
    for wt in (MAIN / ".claude" / "worktrees").glob("*"):
        gen = wt / "research_loop" / "generated"
        if gen.is_dir():
            files += list(gen.glob("**/query.sql")) + list(gen.glob("**/*.sql"))
    files = [f for f in dict.fromkeys(files) if f.is_file() and "/arena/" not in str(f) and f.stat().st_size < 3_000_000]
    raw: list[str] = []
    queries: set[str] = set()
    shapes: set[str] = set()
    for f in files:
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        raw.append(" ".join(text.split()))
        found = [sql for _q, sql in parse_sql_file(f)] if f.suffix == ".sql" else []
        found += _sql_in_text(text)
        for sql in found:
            try:
                queries.add(normalize(sql))
                shapes.add(shape_key(sql))
            except Exception:  # noqa: BLE001 - free-text fragments that are not SQL are skipped, not queries
                continue
    return queries, shapes, "\n".join(raw).lower()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--sec", type=int, default=6)
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--pool", type=int, default=120)
    ap.add_argument("--out", type=Path, required=True, help="arena root; the round goes to <out>/rounds/rN, the registry to <out>/seen.json")
    a = ap.parse_args()
    os.environ["LEMMA_STRING_ENCODING"] = "dict"
    os.environ["LEMMA_NARROW_CELLS"] = "0"
    db = Path(os.environ.get("LEMMA_DUCKDB_PATH") or MAIN / "holdout" / "gendb_sec_edgar" / "duckdb" / "sec_edgar_dec.duckdb")
    os.environ["LEMMA_DUCKDB_PATH"] = str(db)

    from declarative_spec.emit import emit_declarative_spec
    from declarative_spec.prompt import spec_shape
    from research_loop.assumption_packages import assumption_package
    from research_loop.scripts.declarative_tiers import normalize, shape_key, tier
    from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema, parse_sql_file

    rdir = a.out / "rounds" / f"r{a.round}"
    if (rdir / "queries").exists():
        raise SystemExit(f"ERROR: round {a.round} already drawn at {rdir}")
    rdir.mkdir(parents=True)
    seen_path = a.out / "seen.json"
    registry = json.loads(seen_path.read_text()) if seen_path.is_file() else {}
    pool_sql = rdir / f"pool_{a.seed}.sql"
    subprocess.run(
        [sys.executable, str(MAIN / "holdout" / "gendb_sec_edgar" / "generate_queries.py"), "--seed", str(a.seed),
         "--num-generate", "600", "--num-select", str(a.pool), "--db-path", str(db), "--output", str(pool_sql)],
        check=True,
    )
    pool = parse_sql_file(pool_sql)
    seen_q, seen_shapes, raw = seen_corpus()
    schema, catalog = load_sec_schema(db), assumption_package("sec_margin_dec")
    rejected: Counter = Counter()
    cands = []
    for qid, sql in pool:
        n = normalize(sql)
        if hashlib.sha1(n.encode()).hexdigest() in registry or n in seen_q or n.lower() in raw:
            rejected["query text already seen"] += 1
            continue
        if shape_key(sql) in seen_shapes:
            rejected["shape of a seen/fixture query"] += 1
            continue
        try:
            spec = emit_declarative_spec(sql, schema, catalog)
        except Exception as exc:  # noqa: BLE001 - each refusal kind is counted by its first message line
            rejected["emitter refuses: " + re.sub(r"\d+", "N", f"{type(exc).__name__}: {exc}".splitlines()[0])[:90]] += 1
            continue
        shp = spec_shape(spec)
        cands.append({"orig_qid": qid, "sql": n, "shape": shape_key(sql), "recipe": shp["recipe"], "tier": tier(sql),
                      "tables": shp["tables"], "hard": shp["hard"]})
    rng = random.Random(a.seed)
    rng.shuffle(cands)
    picked: list[dict] = []
    classes: Counter = Counter()
    used_shapes: set[str] = set()
    while len(picked) < a.sec and cands:
        cands.sort(key=lambda c: (classes[(c["recipe"], c["tier"])], c["shape"] in used_shapes))
        c = cands.pop(0)
        picked.append(c)
        classes[(c["recipe"], c["tier"])] += 1
        used_shapes.add(c["shape"])
    qdir = rdir / "queries"
    qdir.mkdir()
    from research_loop.scripts.declarative_tiers import is_heldout

    manifest = {"round": a.round, "seed": a.seed, "database": db.name, "package": "sec_margin_dec", "encoding": "dict", "pool": len(pool),
                "rejected": dict(rejected), "queries": []}
    for i, c in enumerate(picked, start=1):
        name = f"q{i:02d}"
        (qdir / f"{name}.sql").write_text(c["sql"] + "\n")
        held = is_heldout(c["shape"])
        manifest["queries"].append({"id": f"r{a.round}_{name}", "kind": "sec", "source": f"gendb seed {a.seed} {c['orig_qid']}", "recipe": c["recipe"],
                                    "tier": c["tier"], "tables": c["tables"], "hard_features": c["hard"], "heldout_shape": held, "sql": c["sql"]})
        registry[hashlib.sha1(c["sql"].encode()).hexdigest()] = {"sql": c["sql"], "round": a.round, "id": f"r{a.round}_{name}", "heldout_shape": held,
                                                               "looked_at_by": [], "burned": False, "shape": c["shape"]}
    (rdir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    seen_path.write_text(json.dumps(registry, indent=1))
    print(json.dumps({"picked": len(picked), "pool": len(pool), "rejected": dict(rejected),
                      "classes": {f"{r}/{t}": n for (r, t), n in classes.items()}, "heldout": sum(m["heldout_shape"] for m in manifest["queries"])}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
