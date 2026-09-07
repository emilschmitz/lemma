#!/usr/bin/env python3
"""Coverage harness for GenDB-style resampled SQL (SQLSmith stand-in).

For each query: transpile → resolve MethodSpec return type → agent shell → admission
→ stitch a full program (``assemble_verified_*``). **Does not run Verus
verify/compile** and does not prove ``run_query ≡ method_spec``.

Status taxonomy:

- ``ok_shell`` — transpile, ret-type resolution, host ``run_query`` shell template,
  admission lint, and program assembly all succeed (default stub body; no agent edit).
- ``transpile_fail`` — ``UnsupportedContractError`` or ``transpile_sql_to_verus`` failure
  (includes pre-transpile ``UnsupportedContractError`` from parse/projection).
- ``shell_fail`` — transpile OK but ret-type, shell build, admission, or assembly failed.
- ``other`` — pre-transpile parse/projection errors that are not ``UnsupportedContractError``.

``pass_rate`` / ``shell_pass_rate`` in the JSON report = ``ok_shell / total`` (shell
pipeline only; **not** end-to-end verified-query success).

Usage::

    uv run python research_loop/scripts/sqlsmith_trusted_coverage.py \\
        --sql-file holdout/gendb_sec_edgar/queries_all.sql

    uv run python research_loop/scripts/sqlsmith_trusted_coverage.py \\
        --regenerate --num-generate 200 --num-select 25
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_SQL = ROOT / "holdout" / "gendb_sec_edgar" / "queries_all.sql"
DEFAULT_OUTPUT = ROOT / "research_loop" / "generated" / "sqlsmith_coverage_baseline.json"
GENERATE_SCRIPT = ROOT / "holdout" / "gendb_sec_edgar" / "generate_queries.py"
SCHEMA_SQL = ROOT / "holdout" / "gendb_sec_edgar" / "schema.sql"

_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(\w+)\s*\((.*?)\);",
    re.DOTALL | re.IGNORECASE,
)
_SCHEMA_COL = re.compile(
    r"^\s*(\w+)\s+(VARCHAR|INTEGER|DOUBLE|TEXT)\b",
    re.MULTILINE | re.IGNORECASE,
)

_LABELED_QUERY = re.compile(
    r"--\s*Q(\d+):.*?\n(SELECT\b.*?;)",
    re.DOTALL | re.IGNORECASE,
)
_BARE_SELECT = re.compile(r"(SELECT\b.*?;)", re.DOTALL | re.IGNORECASE)


@dataclass
class QueryResult:
    id: str
    status: str
    reason: str = ""
    ret_type: str | None = None
    sql_preview: str = ""


def _strip_sql_line_comments(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if "--" in line:
            line = line[: line.index("--")]
        lines.append(line)
    return "\n".join(lines)


def load_sec_schema() -> dict[str, dict[str, str]]:
    """SEC EDGAR catalog: full ``schema.sql`` when present, else test holdout subset."""
    if SCHEMA_SQL.is_file():
        text = _strip_sql_line_comments(SCHEMA_SQL.read_text(encoding="utf-8"))
        out: dict[str, dict[str, str]] = {}
        for match in _CREATE_TABLE.finditer(text):
            table = match.group(1).lower()
            cols: dict[str, str] = {}
            for col_match in _SCHEMA_COL.finditer(match.group(2)):
                name = col_match.group(1).lower()
                sql_type = col_match.group(2).upper()
                if sql_type == "INTEGER":
                    cols[name] = "int"
                elif sql_type == "DOUBLE":
                    cols[name] = "double"
                else:
                    cols[name] = "string"
            if cols:
                out[table] = cols
        if out:
            return out

    from tests.test_sec_holdout_parse import SEC_SCHEMA

    return SEC_SCHEMA


def parse_sql_file(path: Path) -> list[tuple[str, str]]:
    """Return (query_id, sql) pairs from a GenDB-style SQL file."""
    text = path.read_text(encoding="utf-8")
    labeled = list(_LABELED_QUERY.finditer(text))
    if labeled:
        return [(f"Q{m.group(1)}", m.group(2).strip()) for m in labeled]

    out: list[tuple[str, str]] = []
    for i, m in enumerate(_BARE_SELECT.finditer(text), start=1):
        out.append((f"q{i}", m.group(1).strip()))
    return out


def normalize_failure_reason(reason: str) -> str:
    """Bucket key: first line, trimmed, capped."""
    line = reason.strip().splitlines()[0] if reason.strip() else "unknown"
    line = re.sub(r"\s+", " ", line)
    if len(line) > 160:
        line = line[:157] + "..."
    return line


def _assemble_program(
    *,
    sql: str,
    spec_rs: str,
    run_query_body: str,
    schema: dict,
    projected: dict,
    ret_type: str,
) -> str:
    import inspect

    from verus_transpiler.column_projection import project_schema_for_query
    from verus_transpiler.parse_sql import normalize_schema, parse_sql
    from verus_transpiler.query_tables import program_table_order

    from research_loop.assemble_verified_program import (
        assemble_verified_join_program,
        assemble_verified_nway_program,
        assemble_verified_program,
    )

    _flat, multi = normalize_schema(schema)
    query = parse_sql(sql, schema)
    multi_schema = projected if isinstance(projected, dict) else schema

    if query.joins and multi:
        tables = program_table_order(query, multi)
        if len(tables) >= 2:
            if len(tables) == 2:
                left_t, right_t = tables[0], tables[1]
                return assemble_verified_join_program(
                    spec_rs=spec_rs,
                    run_query_body=run_query_body,
                    multi_schema=multi_schema,
                    table_order=(left_t, right_t),
                    ret_type=ret_type,
                    default_tbls={left_t: "", right_t: ""},
                )
            return assemble_verified_nway_program(
                spec_rs=spec_rs,
                run_query_body=run_query_body,
                multi_schema=multi_schema,
                table_order=tables,
                ret_type=ret_type,
                default_tbls={t: "" for t in tables},
            )
        raise ValueError("join requires at least two tables")

    order = program_table_order(query, multi)
    if multi and order:
        primary = order[0]
        if (
            isinstance(projected, dict)
            and primary in projected
            and isinstance(projected[primary], dict)
        ):
            schema_dict = projected[primary]
        else:
            schema_dict = project_schema_for_query(sql, schema)
    elif multi:
        schema_dict = project_schema_for_query(sql, schema)
    else:
        schema_dict = projected if isinstance(projected, dict) else _flat

    assemble_kwargs: dict = {
        "spec_rs": spec_rs,
        "run_query_body": run_query_body,
        "schema_dict": schema_dict,
        "ret_type": ret_type,
        "default_tbl": "",
    }
    sig = inspect.signature(assemble_verified_program)
    if "support_tables" in sig.parameters and multi and order and isinstance(projected, dict):
        support_tables = {
            t: projected[t]
            for t in order[1:]
            if t in projected and isinstance(projected[t], dict)
        }
        if support_tables:
            assemble_kwargs["support_tables"] = support_tables

    return assemble_verified_program(**assemble_kwargs)


def classify_query(sql: str, qid: str, schema: dict) -> QueryResult:
    """Classify one query through the shell pipeline (no Verus prove/compile)."""
    preview = " ".join(sql.split())[:120]
    try:
        from verus_transpiler.column_projection import (
            project_multi_schema_for_query,
            project_schema_for_query,
        )
        from verus_transpiler.parse_sql import (
            UnsupportedContractError,
            normalize_schema,
            parse_sql,
        )

        flat, multi = normalize_schema(schema)
        parse_sql(sql, schema)
        if multi:
            projected = project_multi_schema_for_query(sql, multi)
        else:
            projected = project_schema_for_query(sql, flat)
    except (UnsupportedContractError, ValueError, KeyError, TypeError) as exc:
        return QueryResult(
            id=qid,
            status="transpile_fail" if isinstance(exc, UnsupportedContractError) else "other",
            reason=str(exc),
            sql_preview=preview,
        )

    try:
        from verus_transpiler import transpile_sql_to_verus

        spec_rs = transpile_sql_to_verus(sql, projected)
    except UnsupportedContractError as exc:
        return QueryResult(
            id=qid,
            status="transpile_fail",
            reason=str(exc),
            sql_preview=preview,
        )
    except (ValueError, RuntimeError, TypeError) as exc:
        return QueryResult(
            id=qid,
            status="transpile_fail",
            reason=str(exc),
            sql_preview=preview,
        )

    try:
        from research_loop.admit_agent_runquery import admit_agent_runquery
        from research_loop.assemble_runquery import build_runquery_agent_source
        from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec

        ret_type = resolve_ret_type_from_method_spec(spec_rs)
        shell = build_runquery_agent_source(
            ret_type=ret_type,
            method_spec_rs=spec_rs,
            sql_query=sql,
        )
        admit = admit_agent_runquery(shell, method_spec_rs=spec_rs)
        if not admit.ok:
            return QueryResult(
                id=qid,
                status="shell_fail",
                reason="; ".join(admit.violations),
                ret_type=ret_type,
                sql_preview=preview,
            )
        assert admit.run_query_fn is not None
        program = _assemble_program(
            sql=sql,
            spec_rs=spec_rs,
            run_query_body=admit.run_query_fn,
            schema=schema,
            projected=projected,
            ret_type=ret_type,
        )
        if "method_spec" not in program or "run_query" not in program:
            raise ValueError("assembled program missing method_spec or run_query")
    except (ValueError, RuntimeError, TypeError) as exc:
        return QueryResult(
            id=qid,
            status="shell_fail",
            reason=str(exc),
            ret_type=locals().get("ret_type"),
            sql_preview=preview,
        )

    return QueryResult(
        id=qid,
        status="ok_shell",
        ret_type=ret_type,
        sql_preview=preview,
    )


def run_coverage(
    queries: list[tuple[str, str]],
    schema: dict,
) -> tuple[list[QueryResult], dict[str, int], list[dict[str, object]]]:
    results: list[QueryResult] = []
    for qid, sql in queries:
        results.append(classify_query(sql, qid, schema))

    counts = Counter(r.status for r in results)
    total = len(results)
    ok = counts.get("ok_shell", 0)
    shell_pass_rate = ok / total if total else 0.0

    fail_reasons = Counter(
        normalize_failure_reason(r.reason)
        for r in results
        if r.status != "ok_shell" and r.reason
    )
    failure_buckets = [
        {"reason": reason, "count": count}
        for reason, count in fail_reasons.most_common()
    ]

    summary = {
        "total": total,
        "counts": {
            "ok_shell": counts.get("ok_shell", 0),
            "transpile_fail": counts.get("transpile_fail", 0),
            "shell_fail": counts.get("shell_fail", 0),
            "other": counts.get("other", 0),
        },
        "shell_pass_rate": shell_pass_rate,
        "failure_buckets": failure_buckets,
    }
    return results, summary, failure_buckets


def maybe_regenerate_pool(
    *,
    num_generate: int,
    num_select: int,
    output: Path,
    seed: int,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(GENERATE_SCRIPT),
        "--num-generate",
        str(num_generate),
        "--num-select",
        str(num_select),
        "--seed",
        str(seed),
        "--output",
        str(output),
    ]
    print(f"Regenerating query pool: {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)
    return output


def build_report(
    *,
    source: str,
    results: list[QueryResult],
    summary: dict[str, object],
) -> dict[str, object]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": source,
        **summary,
        "queries": [asdict(r) for r in results],
    }


def print_summary(report: dict[str, object], output_path: Path) -> None:
    counts = report["counts"]
    total = report["total"]
    ok = counts["ok_shell"]
    shell_pct = 100.0 * report["shell_pass_rate"]
    print(f"\nSQLSmith trusted shell coverage ({report['source']})")
    print(
        f"  total={total} ok_shell={ok} shell_pass_rate={shell_pct:.1f}% "
        "(transpile+shell+admission; not Verus verify)"
    )
    print(
        f"  transpile_fail={counts['transpile_fail']} "
        f"shell_fail={counts['shell_fail']} other={counts['other']}"
    )
    buckets = report.get("failure_buckets") or []
    if buckets:
        print("  top failures:")
        for row in buckets[:10]:
            print(f"    [{row['count']}] {row['reason']}")
    print(f"\nWrote {output_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure transpile + agent shell + admission coverage for GenDB-style SQL "
            "(no Verus verify/compile)"
        ),
    )
    parser.add_argument(
        "--sql-file",
        type=Path,
        default=DEFAULT_SQL,
        help="SQL file with -- Qn: labeled queries (default: queries_all.sql)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="JSON summary output path",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Run holdout/gendb_sec_edgar/generate_queries.py before measuring",
    )
    parser.add_argument("--num-generate", type=int, default=500)
    parser.add_argument("--num-select", type=int, default=25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--pool-output",
        type=Path,
        default=None,
        help="Output path when --regenerate (default: --sql-file)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max queries (0 = all)")
    args = parser.parse_args(argv)

    sql_path = args.sql_file
    if args.regenerate:
        pool_out = args.pool_output or sql_path
        sql_path = maybe_regenerate_pool(
            num_generate=args.num_generate,
            num_select=args.num_select,
            output=pool_out,
            seed=args.seed,
        )

    if not sql_path.is_file():
        print(f"SQL file not found: {sql_path}", file=sys.stderr)
        return 2

    queries = parse_sql_file(sql_path)
    if args.limit > 0:
        queries = queries[: args.limit]
    if not queries:
        print(f"No queries parsed from {sql_path}", file=sys.stderr)
        return 2

    schema = load_sec_schema()
    results, summary, _ = run_coverage(queries, schema)
    report = build_report(
        source=str(sql_path.resolve().relative_to(ROOT.resolve())),
        results=results,
        summary=summary,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print_summary(report, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
