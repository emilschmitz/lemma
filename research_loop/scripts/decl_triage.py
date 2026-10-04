"""Emission triage of adversary candidates on a small synthetic schema.

    uv run python research_loop/scripts/decl_triage.py FILE [--tc]

One query per line. Prints refusal reasons and, for queries that emit, optionally
the Verus typecheck verdict. The manual adversary reads the emitted specs of the ones
that emit and builds a hand-proved candidate for any suspected hole.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from declarative_spec.emit import emit_declarative_spec  # noqa: E402
from research_loop.scripts.decl_coverage import typecheck  # noqa: E402
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions  # noqa: E402

SCHEMA = {
    "t": {"a": "bigint", "k": "bigint", "s": "varchar"},
    "u": {"b": "bigint", "s": "varchar"},
    "kw": {"select": "bigint", "from": "varchar"},
    "dd": {"d": "date"},
    "dm": {"m": "decimal(10,2)"},
}
CATALOG = CatalogAssumptions(max_rows=16, tables={t: TableAssumptions(max_rows=16) for t in SCHEMA})


def main() -> None:
    for line in Path(sys.argv[1]).read_text().splitlines():
        sql = line.strip()
        if not sql:
            continue
        try:
            spec = emit_declarative_spec(sql, SCHEMA, CATALOG, float_abs_eps="1e20")
        except Exception as exc:  # noqa: BLE001
            print(f"REFUSED[{type(exc).__name__}] {sql}\n      {exc}")
            continue
        verdict = typecheck(spec) if "--tc" in sys.argv else ""
        print(f"EMITTED {verdict[:90]} {sql}")


if __name__ == "__main__":
    main()
