"""Verus-typecheck a random sample of emitted specs per schema variant, one at a time.

    uv run python -m research_loop.scripts.decl_typecheck_sample research_loop/generated/decl_coverage/dec_N.sql

The body is ``loop {}`` (diverges, so it fits any result type) and Verus runs with
``--no-verify``: this checks that the emitted spec, loaders and `run_query` signature are
well-typed Rust/Verus, not that anything is proved. Verus goes through ``verus_guarded.sh``.
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from research_loop.assumption_packages import assumption_package
from research_loop.scripts.decl_coverage import _DEC_DB, FLOAT_ABS_EPS
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema, parse_sql_file

GUARDED = ROOT / "scripts" / "ram" / "verus_guarded.sh"
STUB = "    loop {}"


def typecheck(program: str, timeout: int = 300) -> tuple[bool, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(program)
    proc = subprocess.run(
        ["bash", str(GUARDED), handle.name, "--no-verify", "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    out = proc.stdout + proc.stderr
    return proc.returncode == 0 and "error" not in out, out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sql", type=Path)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    queries = parse_sql_file(args.sql)
    for name, schema, package in (
        ("double", load_sec_schema(), "sec_margin"),
        ("decimal", load_sec_schema(_DEC_DB), "sec_margin_dec"),
    ):
        catalog = assumption_package(package)
        specs: dict[str, str] = {}
        for qid, sql in queries:
            try:
                specs[qid] = emit_declarative_spec(sql, schema, catalog, float_abs_eps=FLOAT_ABS_EPS)
            except Exception:  # noqa: S112 - refusals are counted by decl_coverage
                continue
        picked = random.Random(args.seed).sample(sorted(specs), min(args.n, len(specs)))
        ok = 0
        for qid in picked:
            passed, out = typecheck(assemble_declarative_program(specs[qid], STUB))
            ok += passed
            print(f"{name} {qid}: {'ok' if passed else 'FAIL'}", flush=True)
            if not passed:
                print(out[-1500:])
        print(f"{name}: {ok}/{len(picked)} type-check", flush=True)


if __name__ == "__main__":
    main()
