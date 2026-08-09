#!/usr/bin/env python3
"""Host-side Trusted capability scorer (no agent sandbox).

For each SQL query: shell pipeline status, agent-visible Trusted surface, MethodSpec
fold quality, and a coarse ``capability_guess`` for proof readiness.

Usage::

    uv run python research_loop/scripts/trusted_capability_score.py \\
        --sql-files holdout/gendb_sec_edgar/queries.sql \\
        holdout/gendb_sec_edgar/queries_all.sql
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUTPUT = ROOT / "research_loop" / "generated" / "trusted_capability_score.json"

_FIXED_FOLD_HELPERS = (
    "multi_agg_helper",
    "method_spec_helper",
    "join_method_spec_helper",
    "join_sum_helper",
    "join_count_helper",
    "join_projection_helper",
    "join_anti_multi_agg_helper",
    "join_right_match_helper",
    "derived_m_helper",
    "sum_map_helper",
    "count_map_helper",
    "sum_helper",
    "count_helper",
)
_DYNAMIC_FOLD_HELPER = re.compile(
    r"pub open spec fn ((?:exists_(?:corr_)?\w+|subquery_\w+)_helper)\b"
)
_COUNT_DISTINCT_RE = re.compile(r"\bCOUNT\s*\(\s*DISTINCT\b", re.IGNORECASE)


@dataclass
class CapabilityResult:
    source: str
    id: str
    shell_ok: bool
    shell_status: str
    has_agg_step: bool
    has_distinct_set: bool
    fold_arbitrary: bool
    capability_guess: str
    ret_type: str | None = None
    sql_has_count_distinct: bool = False
    sql_is_multi_agg: bool = False
    sql_is_scalar: bool = False
    sql_is_simple_map: bool = False
    fold_helpers: list[str] | None = None
    reason: str = ""
    sql_preview: str = ""


def fold_helper_names(spec_rs: str) -> list[str]:
    """Names of recursive MethodSpec fold helpers used by the query."""
    names: list[str] = []
    for name in _FIXED_FOLD_HELPERS:
        if f"pub open spec fn {name}" in spec_rs:
            names.append(name)
    for m in _DYNAMIC_FOLD_HELPER.finditer(spec_rs):
        name = m.group(1)
        if name not in names:
            names.append(name)
    return names


def extract_fold_helper_bodies(spec_rs: str) -> list[str]:
    """Bodies of recursive MethodSpec fold helpers (not global string TRUSTED stubs)."""
    chunks: list[str] = []
    for name in fold_helper_names(spec_rs):
        marker = f"pub open spec fn {name}"
        start = spec_rs.index(marker)
        rest = spec_rs[start + 1 :]
        nxt = rest.find("\npub open spec fn ")
        chunk = spec_rs[start:] if nxt == -1 else spec_rs[start : start + 1 + nxt]
        chunks.append(chunk)
    return chunks


def fold_has_arbitrary(spec_rs: str) -> bool:
    return any("arbitrary()" in c for c in extract_fold_helper_bodies(spec_rs))


def _sql_shape_flags(sql: str, schema: dict) -> tuple[bool, bool, bool, bool]:
    """Return (count_distinct, multi_agg, scalar, simple_map) heuristics."""
    from verus_transpiler.parse_sql import normalize_schema, parse_sql

    flat, multi = normalize_schema(schema)
    q = parse_sql(sql, schema if multi else flat)
    count_distinct = any(a.agg_type == "COUNT_DISTINCT" for a in q.agg_specs)
    if not count_distinct:
        count_distinct = bool(_COUNT_DISTINCT_RE.search(sql))
    multi_agg = q.is_multi_agg
    scalar = not q.groupby_columns and len(q.agg_specs) <= 1 and not q.is_projection
    simple_map = bool(q.groupby_columns) and len(q.agg_specs) <= 1 and not multi_agg
    return count_distinct, multi_agg, scalar, simple_map


def _agent_visible_surface(spec_rs: str, ret_type: str) -> str:
    from research_loop.assemble_verified_program import prepare_agent_visible_spec

    return prepare_agent_visible_spec(spec_rs, ret_type)


def _has_agg_step(visible: str) -> bool:
    return re.search(r"pub exec fn agg_step_(?:state_new_)?\w+", visible) is not None


def _has_distinct_set(visible: str) -> bool:
    return (
        re.search(r"pub exec fn set_insert_\w+", visible) is not None
        or re.search(r"pub open spec fn hashset_\w+_view\b", visible) is not None
    )


def guess_capability(
    *,
    shell_ok: bool,
    shell_status: str,
    fold_arbitrary: bool,
    has_agg_step: bool,
    sql_has_count_distinct: bool,
    sql_is_multi_agg: bool,
    sql_is_scalar: bool,
    sql_is_simple_map: bool,
) -> str:
    if shell_status == "transpile_fail":
        return "transpile_fail"
    if shell_status == "other":
        return "transpile_fail"
    if not shell_ok:
        return "shell_fail"
    if fold_arbitrary:
        return "needs_trusted"
    needs_step_surface = sql_has_count_distinct or sql_is_multi_agg
    if needs_step_surface:
        return "ready" if has_agg_step else "needs_trusted"
    if sql_is_scalar or sql_is_simple_map:
        return "ready"
    # Projection / seq / join-without-multi-agg shells with real folds.
    return "ready"


def score_query(
    *,
    source: str,
    qid: str,
    sql: str,
    schema: dict,
) -> CapabilityResult:
    from research_loop.scripts.sqlsmith_trusted_coverage import classify_query

    preview = " ".join(sql.split())[:120]
    shell = classify_query(sql, qid, schema)
    shell_ok = shell.status == "ok_shell"

    count_distinct = multi_agg = is_scalar = is_simple_map = False
    fold_arbitrary = False
    has_agg_step = False
    has_distinct = False
    fold_names: list[str] = []
    ret_type = shell.ret_type

    if shell_ok:
        try:
            from verus_transpiler.column_projection import (
                project_multi_schema_for_query,
                project_schema_for_query,
            )
            from verus_transpiler.parse_sql import normalize_schema
            from verus_transpiler import transpile_sql_to_verus

            from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec

            flat, multi = normalize_schema(schema)
            if multi:
                projected = project_multi_schema_for_query(sql, multi)
            else:
                projected = project_schema_for_query(sql, flat)
            spec_rs = transpile_sql_to_verus(sql, projected)
            ret_type = resolve_ret_type_from_method_spec(spec_rs)
            visible = _agent_visible_surface(spec_rs, ret_type)
            has_agg_step = _has_agg_step(visible)
            has_distinct = _has_distinct_set(visible)
            fold_names = fold_helper_names(spec_rs)
            fold_arbitrary = fold_has_arbitrary(spec_rs)
            count_distinct, multi_agg, is_scalar, is_simple_map = _sql_shape_flags(
                sql, schema
            )
        except Exception as exc:
            return CapabilityResult(
                source=source,
                id=qid,
                shell_ok=False,
                shell_status="shell_fail",
                has_agg_step=False,
                has_distinct_set=False,
                fold_arbitrary=False,
                capability_guess="shell_fail",
                ret_type=ret_type,
                reason=str(exc),
                sql_preview=preview,
            )

    capability = guess_capability(
        shell_ok=shell_ok,
        shell_status=shell.status,
        fold_arbitrary=fold_arbitrary,
        has_agg_step=has_agg_step,
        sql_has_count_distinct=count_distinct,
        sql_is_multi_agg=multi_agg,
        sql_is_scalar=is_scalar,
        sql_is_simple_map=is_simple_map,
    )

    return CapabilityResult(
        source=source,
        id=qid,
        shell_ok=shell_ok,
        shell_status=shell.status,
        has_agg_step=has_agg_step,
        has_distinct_set=has_distinct,
        fold_arbitrary=fold_arbitrary,
        capability_guess=capability,
        ret_type=ret_type,
        sql_has_count_distinct=count_distinct,
        sql_is_multi_agg=multi_agg,
        sql_is_scalar=is_scalar,
        sql_is_simple_map=is_simple_map,
        fold_helpers=fold_names or None,
        reason=shell.reason,
        sql_preview=preview,
    )


def summarize(results: list[CapabilityResult]) -> dict[str, object]:
    total = len(results)
    guess_counts = Counter(r.capability_guess for r in results)
    shell_ok = sum(1 for r in results if r.shell_ok)
    fold_arb = sum(1 for r in results if r.fold_arbitrary)
    agg_step = sum(1 for r in results if r.has_agg_step)
    distinct_set = sum(1 for r in results if r.has_distinct_set)

    missing_patterns: Counter[str] = Counter()
    for r in results:
        if r.capability_guess == "needs_trusted":
            if r.fold_arbitrary:
                missing_patterns["fold_arbitrary"] += 1
            if (r.sql_has_count_distinct or r.sql_is_multi_agg) and not r.has_agg_step:
                missing_patterns["missing_agg_step"] += 1
            if r.sql_has_count_distinct and not r.has_distinct_set:
                missing_patterns["missing_distinct_set"] += 1
        elif r.capability_guess == "transpile_fail":
            missing_patterns[r.reason.splitlines()[0][:120] if r.reason else "transpile_fail"] += 1
        elif r.capability_guess == "shell_fail":
            missing_patterns[r.reason.splitlines()[0][:120] if r.reason else "shell_fail"] += 1

    by_source: dict[str, dict[str, object]] = {}
    for source in sorted({r.source for r in results}):
        subset = [r for r in results if r.source == source]
        sub_guess = Counter(x.capability_guess for x in subset)
        by_source[source] = {
            "total": len(subset),
            "shell_ok": sum(1 for x in subset if x.shell_ok),
            "capability_guess": dict(sub_guess),
            "ready_pct": 100.0 * sub_guess.get("ready", 0) / len(subset) if subset else 0.0,
        }

    return {
        "total": total,
        "shell_ok": shell_ok,
        "shell_ok_pct": 100.0 * shell_ok / total if total else 0.0,
        "fold_arbitrary": fold_arb,
        "has_agg_step": agg_step,
        "has_distinct_set": distinct_set,
        "capability_guess": dict(guess_counts),
        "ready_pct": 100.0 * guess_counts.get("ready", 0) / total if total else 0.0,
        "by_source": by_source,
        "top_missing_patterns": [
            {"pattern": pat, "count": cnt}
            for pat, cnt in missing_patterns.most_common(15)
        ],
    }


def print_summary(report: dict[str, object], output_path: Path) -> None:
    summary = report["summary"]
    print("\nTrusted capability scoreboard")
    print(
        f"  total={summary['total']} shell_ok={summary['shell_ok']} "
        f"({summary['shell_ok_pct']:.1f}%)"
    )
    guess = summary["capability_guess"]
    print(
        f"  capability_guess: ready={guess.get('ready', 0)} "
        f"needs_trusted={guess.get('needs_trusted', 0)} "
        f"transpile_fail={guess.get('transpile_fail', 0)} "
        f"shell_fail={guess.get('shell_fail', 0)} "
        f"(ready {summary['ready_pct']:.1f}%)"
    )
    print(
        f"  fold_arbitrary={summary['fold_arbitrary']} "
        f"has_agg_step={summary['has_agg_step']} "
        f"has_distinct_set={summary['has_distinct_set']}"
    )
    print("\n  by source:")
    for source, row in summary["by_source"].items():
        print(
            f"    {source}: total={row['total']} shell_ok={row['shell_ok']} "
            f"ready={row['capability_guess'].get('ready', 0)} "
            f"({row['ready_pct']:.1f}%)"
        )
    patterns = summary.get("top_missing_patterns") or []
    if patterns:
        print("\n  top gaps:")
        for row in patterns[:10]:
            print(f"    [{row['count']}] {row['pattern']}")
    print(f"\nWrote {output_path}")


def main(argv: list[str] | None = None) -> int:
    from research_loop.scripts.sqlsmith_trusted_coverage import (
        load_sec_schema,
        parse_sql_file,
    )

    parser = argparse.ArgumentParser(description="Host-side Trusted capability scorer")
    parser.add_argument(
        "--sql-files",
        type=Path,
        nargs="+",
        required=True,
        help="GenDB-style SQL files (-- Qn: labels or bare SELECTs)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="JSON output path",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max queries per file (0=all)")
    args = parser.parse_args(argv)

    schema = load_sec_schema()
    results: list[CapabilityResult] = []
    for sql_path in args.sql_files:
        if not sql_path.is_file():
            print(f"Skipping missing file: {sql_path}", file=sys.stderr)
            continue
        source = str(sql_path.resolve().relative_to(ROOT.resolve()))
        queries = parse_sql_file(sql_path)
        if args.limit > 0:
            queries = queries[: args.limit]
        for qid, sql in queries:
            results.append(
                score_query(source=source, qid=qid, sql=sql, schema=schema),
            )

    if not results:
        print("No queries scored.", file=sys.stderr)
        return 2

    summary = summarize(results)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": summary,
        "queries": [asdict(r) for r in results],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print_summary(report, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
