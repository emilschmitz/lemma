#!/usr/bin/env python3
"""Demo-only helpers — not imported by production pipeline."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def clear_cache() -> None:
    """Remove all cached optimized query binaries and cache index."""
    cache = ROOT / "db_extension" / "cache.json"
    if cache.exists():
        cache.unlink()
    for pattern in (
        ROOT / "db_extension" / "bin" / "q_*",
        ROOT / "build" / "queries" / "q_*",
    ):
        for p in pattern.parent.glob(pattern.name):
            if p.is_file():
                p.unlink()


def seed_demo_body(query_id: int) -> Path:
    """Write hardcoded columnar RunQuery body for demo (from benchmark fixtures)."""
    sys.path.insert(0, str(ROOT))
    from research_loop.benchmark_runqueries import RUNQUERIES

    if query_id not in RUNQUERIES:
        raise SystemExit(f"No demo fixture for Q{query_id}. Pick one of: {sorted(RUNQUERIES)}")

    full = RUNQUERIES[query_id].strip()
    m = re.search(r"method\s+RunQuery[^{]+\{", full, re.DOTALL)
    if not m:
        raise SystemExit(f"Could not parse RunQuery fixture for Q{query_id}")
    start = m.end()
    depth, i = 1, start
    while i < len(full) and depth:
        if full[i] == "{":
            depth += 1
        elif full[i] == "}":
            depth -= 1
        i += 1
    body = full[start : i - 1].strip()
    body = re.sub(
        r"MulU64U32\(ep,\s*disc\)",
        "MulU64U32(ep as NativeU64, disc)",
        body,
    )
    out = ROOT / "research_loop" / "agent_workspace" / "runquery_agent.dfy"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("{\n" + body + "\n}\n")
    return out


def sql_one_line(query_id: int) -> str:
    sys.path.insert(0, str(ROOT))
    from research_loop.ssb_workload import queries

    return re.sub(r"\s+", " ", queries[query_id - 1].strip())


def lemma_select_line_for_query(sql: str) -> str:
    """DuckDB SELECT for lemma() with result column alias (from query metadata, not hardcoded)."""
    import duckdb

    sys.path.insert(0, str(ROOT))
    from db_extension.utils import escape_sql_string_literal, lemma_select_line, setup_db

    con = duckdb.connect()
    setup_db(con, quiet=True)
    return lemma_select_line(con, sql)


def lemma_show_line(sql: str) -> str:
    """Generic short box header 'value' — use when you don't need the query's AS name."""
    sys.path.insert(0, str(ROOT))
    from db_extension.utils import escape_sql_string_literal

    inner = escape_sql_string_literal(sql.strip())
    return f"SELECT * FROM lemma_show('{inner}')"


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: demo_lib.py clear | seed <query_id>")
    cmd = sys.argv[1]
    if cmd == "clear":
        clear_cache()
        print("Cache cleared.")
    elif cmd == "seed":
        qid = int(sys.argv[2])
        path = seed_demo_body(qid)
        print(f"Seeded demo body → {path}")
    else:
        raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
