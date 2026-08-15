#!/usr/bin/env python3
"""Create prove_loop/<round>_qN/ shells from a GenDB resample SQL file.

Writes query.sql, runquery_agent.rs (host shell), meta.json, and verify_local.py.
Does not run Verus. Catalog: sec_prove_loop_catalog_assumptions().
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_loop.assemble_runquery import write_runquery_agent_file
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema, parse_sql_file
from research_loop.sec_table_assumptions import sec_prove_loop_catalog_assumptions
from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.column_projection import project_multi_schema_for_query
from verus_transpiler.parse_sql import normalize_schema

VERIFY_LOCAL = '''#!/usr/bin/env python3
"""Local verify: transpile → admit → assemble → Verus (timeout=360)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from research_loop.admit_agent_runquery import admit_agent_runquery
from research_loop.harness import run_verus_verify
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.scripts.sqlsmith_trusted_coverage import _assemble_program, load_sec_schema
from research_loop.sec_table_assumptions import sec_prove_loop_catalog_assumptions
from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.column_projection import project_multi_schema_for_query
from verus_transpiler.parse_sql import normalize_schema

DIR = Path(__file__).resolve().parent


def main() -> int:
    sql = (DIR / "query.sql").read_text(encoding="utf-8")
    agent_src = (DIR / "runquery_agent.rs").read_text(encoding="utf-8")
    schema = load_sec_schema()
    _flat, multi = normalize_schema(schema)
    projected = project_multi_schema_for_query(sql, multi)
    catalog = sec_prove_loop_catalog_assumptions()
    spec_rs = transpile_sql_to_verus(sql, projected, catalog_assumptions=catalog)
    (DIR / "spec_transpiled.rs").write_text(spec_rs, encoding="utf-8")

    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    admit = admit_agent_runquery(agent_src, method_spec_rs=spec_rs)
    print("ADMIT", admit.ok, admit.violations)
    if not admit.ok:
        return 1
    assert admit.run_query_fn is not None

    program = _assemble_program(
        sql=sql,
        spec_rs=spec_rs,
        run_query_body=admit.run_query_fn,
        schema=schema,
        projected=projected,
        ret_type=ret_type,
    )
    out = DIR / "assembled.rs"
    out.write_text(program, encoding="utf-8")
    print("ASSEMBLED", out, "bytes", len(program))

    ok, msg = run_verus_verify(str(out), timeout=360)
    print("VERIFY", ok)
    if not ok:
        err = DIR / "verify_error.log"
        err.write_text(msg, encoding="utf-8")
        print(msg[-4000:])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sql-file", type=Path, required=True)
    parser.add_argument("--round", required=True, help="e.g. r14")
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT / "research_loop" / "generated" / "prove_loop",
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    queries = parse_sql_file(args.sql_file)
    if args.limit > 0:
        queries = queries[: args.limit]
    schema = load_sec_schema()
    _flat, multi = normalize_schema(schema)
    catalog = sec_prove_loop_catalog_assumptions()
    args.root.mkdir(parents=True, exist_ok=True)

    for qid, sql in queries:
        num = qid.lstrip("Qq")
        d = args.root / f"{args.round}_q{num}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "query.sql").write_text(sql.strip() + "\n", encoding="utf-8")
        projected = project_multi_schema_for_query(sql, multi)
        spec_rs = transpile_sql_to_verus(sql, projected, catalog_assumptions=catalog)
        (d / "spec.rs").write_text(spec_rs, encoding="utf-8")
        ret_type = resolve_ret_type_from_method_spec(spec_rs)
        write_runquery_agent_file(
            d / "runquery_agent.rs",
            ret_type=ret_type,
            sql_query=sql,
            method_spec_rs=spec_rs,
        )
        (d / "meta.json").write_text(
            json.dumps(
                {"source": args.round, "qid": qid, "ret_type": ret_type},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (d / "verify_local.py").write_text(VERIFY_LOCAL, encoding="utf-8")
        print(d.name, ret_type)
    print(f"bootstrapped {len(queries)} dirs under {args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
