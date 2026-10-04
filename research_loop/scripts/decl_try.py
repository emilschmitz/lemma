"""Emit (and optionally Verus-typecheck) each query of a file, one query per line.

    uv run python research_loop/scripts/decl_try.py FILE [--tc] [--tpch] [-v]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from declarative_spec.emit import emit_declarative_spec  # noqa: E402
from research_loop.scripts.decl_coverage import context, typecheck  # noqa: E402


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    schema, catalog = context("--tpch" in sys.argv)
    for line in Path(args[0]).read_text().splitlines():
        sql = line.strip()
        if not sql or sql.startswith("--"):
            continue
        print("SQL:", sql)
        try:
            spec = emit_declarative_spec(sql, schema, catalog)
        except Exception as exc:  # noqa: BLE001
            print(f"  -> {type(exc).__name__}: {exc}")
            continue
        if "-v" in sys.argv:
            print(spec)
        print("  -> emitted;", typecheck(spec, full="--full" in sys.argv, verify="--verify" in sys.argv) if "--tc" in sys.argv or "--verify" in sys.argv else "not typechecked")


if __name__ == "__main__":
    main()
