"""Funnel of a SQL file through grammar G, the declarative transpiler and (optionally) the Verus typecheck.

    uv run python -m research_loop.scripts.fragment_coverage Q.sql --db sec_edgar_dec.duckdb --package sec_margin_dec \\
        [--typecheck N] [--json out.json]

Per query: ``in_fragment``, ``emit_declarative_spec`` (a refusal is bucketed by its message), level, and, for the first N
that emit, ``verus --no-verify`` on the assembled program with a diverging body (types only, no proof; one run at a
time through ``verus_guarded.sh``).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.fragment import fragment_level
from research_loop.assumption_packages import assumption_package
from research_loop.scripts.fragment_gen import features, schema_from_db
from research_loop.scripts.sqlsmith_trusted_coverage import parse_sql_file


FLOAT_ITEMS = re.compile(r"f64|\breal\b|host_\w*to_f64|lemma_f64_")  # G_high and G_med specs must name none of these
GUARDED = ROOT / "scripts" / "ram" / "verus_guarded.sh"
_HOST_REGION = re.compile(r"// HOST_LEMMAS_START.*?// HOST_LEMMAS_END", re.S)
_STRING_OR_COMMENT = re.compile(r'"(?:[^"\\]|\\.)*"|//[^\n]*')


def _code(spec: str) -> str:
    """The spec outside the host lemma region with string literals and comments blanked (a filter on 'real estate' is no float)."""
    return _STRING_OR_COMMENT.sub('""', _HOST_REGION.sub("", spec))


STUB = "    loop {}"  # diverges, so it fits any result type


def typecheck(program: str, timeout: int = 300) -> tuple[bool, str]:
    """``verus --no-verify``: the spec, loaders and signature are well-typed Rust/Verus (nothing is proved)."""
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(program)
    proc = subprocess.run(
        ["bash", str(GUARDED), handle.name, "--no-verify", "--triggers-mode", "silent"],
        capture_output=True, text=True, check=False, timeout=timeout,
    )
    out = proc.stdout + proc.stderr
    return proc.returncode == 0 and "error" not in out, out


def reason_class(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}".splitlines()[0]
    text = re.sub(r"'[^']*'", "'_'", text)
    return re.sub(r"\d+", "N", text)[:140]


def transpile(sql: str, schema: dict, catalog) -> tuple[str | None, str]:
    """``(spec, "")`` or ``(None, reason)``."""
    try:
        return emit_declarative_spec(sql, schema, catalog), ""
    except Exception as exc:  # every refusal and crash is bucketed by message
        return None, reason_class(exc)


def run(queries: list[tuple[str, str]], db: Path, package: str, typecheck_n: int) -> list[dict]:
    schema, catalog = schema_from_db(db), assumption_package(package)
    nullable = {(t, c) for t, ta in catalog.tables.items() for c, ca in ta.columns.items() if ca.nullable}
    rows: list[dict] = []
    typed = 0
    for qid, sql in queries:
        level, why = fragment_level(sql, schema, nullable)
        ok = level is not None
        row = {"qid": qid, "in_g": ok, "level": level, "g_reason": why, "features": sorted(features(sql)) if ok else []}
        spec, reason = transpile(sql, schema, catalog)
        row["transpile"] = "ok" if spec else "refused"
        if spec:
            row["float_items"] = bool(FLOAT_ITEMS.search(_code(spec)))  # outside string literals and comments: a filter on 'real estate' is no float
        row["reason"] = reason
        if spec and typed < typecheck_n:
            typed += 1
            passed, out = typecheck(assemble_declarative_program(spec, STUB))
            row["typecheck"] = "ok" if passed else "FAIL"
            if not passed:
                row["typecheck_error"] = out[-600:]
        rows.append(row)
        print(f"{qid} g={ok} transpile={row['transpile']} {reason} {row.get('typecheck', '')}", flush=True)
    return rows


def funnel(rows: list[dict]) -> str:
    n = len(rows)
    in_g = [r for r in rows if r["in_g"]]
    emitted = [r for r in in_g if r["transpile"] == "ok"]
    typed = [r for r in emitted if "typecheck" in r]
    floats = sum(r.get("float_items", False) for r in emitted)
    lines = [f"queries {n}", f"specs naming a float item (f64, real, host_*_to_f64, lemma_f64_*): {floats}", f"in G {len(in_g)}", f"transpile ok {len(emitted)}", f"typecheck run {len(typed)} ok {sum(r['typecheck'] == 'ok' for r in typed)}"]
    refusals = Counter(r["reason"] for r in in_g if r["transpile"] != "ok")
    lines += [f"  refused {c:4d}  {why}" for why, c in refusals.most_common()]
    outside = Counter(r["g_reason"] for r in rows if not r["in_g"])
    lines += [f"  outside G {c:4d}  {why}" for why, c in outside.most_common()]
    return "\n".join(lines)


def pair_matrix(rows: list[dict], level: str) -> list[str]:
    """Markdown: for every feasible pair of constructs at ``level``, how many queries have both and how many of those the
    transpiler refused or the typecheck failed."""
    from research_loop.scripts.fragment_gen import feasible_pairs

    out = ["| pair | queries | transpile refused | typecheck failed |", "|---|---:|---:|---:|"]
    for a, b in feasible_pairs(level):
        both = [r for r in rows if {a, b} <= set(r["features"])]
        refused = sum(r["transpile"] != "ok" for r in both)
        failed = sum(r.get("typecheck") == "FAIL" for r in both)
        out.append(f"| {a} x {b} | {len(both)} | {refused} | {failed} |")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sql", type=Path)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--package", required=True)
    ap.add_argument("--typecheck", type=int, default=0)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--pairs-level", choices=("high", "med", "full"), help="also write the pairwise construct matrix for this level")
    ap.add_argument("--pairs-out", type=Path)
    args = ap.parse_args()
    rows = run(parse_sql_file(args.sql), args.db, args.package, args.typecheck)
    print(funnel(rows))
    if args.pairs_level:
        args.pairs_out.write_text("\n".join(pair_matrix(rows, args.pairs_level)) + "\n")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
