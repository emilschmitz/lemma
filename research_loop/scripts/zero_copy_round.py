"""Which queries of an arena round does the zero-copy path support? (mechanical, no prover involved)

  zero_copy_round.py classify --queries DIR [--kind sec|tpch] [--out FILE.jsonl]

For every ``*.sql`` in DIR: emit the declarative spec exactly as the pipeline does (narrow cells ON, the setting under which INTEGER columns are
loaded at their stored width), then ask the zero-copy assembler's own ``resolve`` whether the spec's one input table and every loaded field is a
native fixed-width column of the database. Each query ends in exactly one state:

* ``supported``      the zero-copy assembler accepts the spec (a Verus body over ``PinnedCol`` is still needed to run it);
* ``refused``        zero_copy.ZeroCopyUnsupported, with its exact reason (strings, validity masks, two tables, floats, a narrowed width, ...);
* ``no_spec``        the declarative emitter itself has no spec for the query (the copy path has none either).

Refusals are part of the result: the summary line is supported/total. Nothing here chooses a path silently; this only reports.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SEC_DB = "/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/duckdb/sec_edgar_dec.duckdb"


def classify_one(sql: str, kind: str) -> dict:
    os.environ["LEMMA_NARROW_CELLS"] = "1"
    import lemma_config
    lemma_config.set_cli("zero_copy", True, "this script")
    os.environ.setdefault("LEMMA_DUCKDB_PATH", SEC_DB)
    from declarative_spec import zero_copy
    from declarative_spec.schema_types import DeclarativeUnsupported, SchemaModel
    from research_loop.scripts import declarative_manual as dm
    from research_loop.trust_configs import apply_trust_config

    try:
        with apply_trust_config("adversary_declarative0"):
            spec = dm.regenerate_spec(kind, sql)
    except Exception as exc:  # the emitter refuses or fails: the copy path has no spec either
        return {"state": "no_spec", "reason": f"{type(exc).__name__}: {str(exc)[:300]}"}
    try:
        import duckdb

        schema, catalog = dm._job_env(kind)
        resolved = dm._project(sql, schema)
        first = re.search(r"\bFROM\s+(\w+)", sql, re.I).group(1)
        model = SchemaModel.from_caller(resolved, first).with_nullable(catalog)
        db = os.environ["LEMMA_DUCKDB_PATH"] if kind == "sec" else os.environ["LEMMA_TPCH_DB"]
        con = duckdb.connect(db, read_only=True)
        tbl = next(t for t in model.original_table_names.values() if t.casefold() == first.casefold())
        stored = {r[0]: r[1] for r in con.execute(f'DESCRIBE "{tbl}"').fetchall()}
        res = zero_copy.resolve(spec, model, stored)
        if "Arc<" in spec:
            pass
        return {"state": "supported", "table": res.table, "columns": res.columns, "parallel": "Arc<" in spec}
    except DeclarativeUnsupported as exc:
        return {"state": "refused", "reason": str(exc)[:400]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["classify"])
    ap.add_argument("--queries", required=True)
    ap.add_argument("--kind", default="")
    ap.add_argument("--out")
    a = ap.parse_args()
    rows = []
    for f in sorted(Path(a.queries).glob("*.sql")):
        sql = f.read_text().strip().rstrip(";")
        kind = a.kind or ("tpch" if re.search(r"\blineitem|orders|customer|supplier|partsupp|nation|region\b", sql, re.I) and "num" not in sql else "sec")
        r = {"query": f.stem, "kind": kind, **classify_one(sql, kind)}
        rows.append(r)
        print(json.dumps(r))
    n = sum(r["state"] == "supported" for r in rows)
    print(f"SUPPORTED {n}/{len(rows)}  refused {sum(r['state'] == 'refused' for r in rows)}  no_spec {sum(r['state'] == 'no_spec' for r in rows)}")
    if a.out:
        Path(a.out).write_text("".join(json.dumps(r) + "\n" for r in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
