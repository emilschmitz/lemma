"""Schema-driven Verus harness glue for db_extension (not SSB/Dafny-specific)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from db_extension.catalog import DatabaseCatalog

ROOT = Path(__file__).resolve().parents[1]
RUNQUERY_TEMPLATE = ROOT / "research_loop" / "templates" / "runquery_agent.rs"
HARNESS_SCRIPT = ROOT / "research_loop" / "harness.py"

_FROM_RE = re.compile(r"\bfrom\s+([`\"']?)(\w+)\1", re.IGNORECASE)
_JOIN_RE = re.compile(r"\bjoin\s+([`\"']?)(\w+)\1", re.IGNORECASE)
_TRUSTED_RUN_QUERY_RE = re.compile(
    r"(//[^\n]*TRUSTED[^\n]*\n)?#\[verifier::external_body\]\s*"
    r"pub\s+exec\s+fn\s+run_query[\s\S]*?\n\}",
    re.MULTILINE,
)
_EXEC_RUN_QUERY_RE = re.compile(
    r"pub\s+exec\s+fn\s+run_query[\s\S]*?\n\}",
    re.MULTILINE,
)


def _normalize_col_type(raw: str) -> str:
    t = raw.strip().lower()
    if t in ("int", "integer", "bigint", "smallint", "tinyint", "hugeint"):
        return "int"
    if t in ("string", "varchar", "text", "char"):
        return "string"
    if t == "int":
        return "int"
    return t


def _normalize_schema_dict(schema: dict) -> dict:
    """Normalize catalog/transpiler schema values to verus kinds (int/string)."""
    if not schema:
        return schema
    sample = next(iter(schema.values()))
    if isinstance(sample, dict):
        return {
            table: {col: _normalize_col_type(t) for col, t in cols.items()}
            for table, cols in schema.items()
        }
    return {col: _normalize_col_type(t) for col, t in schema.items()}


def extract_tables_from_sql(sql: str) -> list[str]:
    tables: list[str] = []
    seen: set[str] = set()
    for pat in (_FROM_RE, _JOIN_RE):
        for m in pat.finditer(sql):
            name = m.group(2).lower()
            if name not in seen and name not in ("select", "where", "group", "order"):
                seen.add(name)
                tables.append(name)
    return tables


def looks_like_ssb_sql(sql: str) -> bool:
    norm = re.sub(r"\s+", " ", sql).strip().lower()
    if "lineorder_flat" in norm:
        return True
    ssb_markers = (
        "lo_orderdate",
        "lo_quantity",
        "lo_discount",
        "lo_extendedprice",
        "d_year",
        "p_brand",
        "c_nation",
        "s_nation",
    )
    return sum(1 for m in ssb_markers if m in norm) >= 2


def resolve_schema_for_sql(
    sql: str,
    schema: dict | None = None,
    *,
    catalog: DatabaseCatalog | None = None,
) -> dict:
    """Resolve flat or multi-table schema for SQL (explicit > env > catalog > SSB fallback)."""
    if schema is not None:
        return _normalize_schema_dict(schema)

    env_path = os.environ.get("LEMMA_SCHEMA_JSON", "").strip()
    if env_path:
        with open(env_path, encoding="utf-8") as f:
            return _normalize_schema_dict(json.load(f))

    tables = extract_tables_from_sql(sql)
    if not tables:
        raise ValueError(
            "Cannot resolve schema: no tables found in SQL. "
            "Pass schema= to run_optimization_loop or set LEMMA_SCHEMA_JSON."
        )

    cat = catalog or DatabaseCatalog()
    if len(tables) == 1:
        table_schema = cat.get_table_schema(tables[0])
        if table_schema:
            return _normalize_schema_dict(table_schema)

    multi: dict[str, dict[str, str]] = {}
    for table in tables:
        table_schema = cat.get_table_schema(table)
        if table_schema:
            multi[table] = _normalize_schema_dict(table_schema)

    if multi:
        if len(tables) == 1:
            return multi[tables[0]]
        return multi

    if looks_like_ssb_sql(sql):
        from research_loop.ssb_workload import schema as ssb_schema

        return _normalize_schema_dict(dict(ssb_schema))

    raise ValueError(
        f"Cannot resolve schema for table(s) {tables!r}. "
        "Pass schema= explicitly, set LEMMA_SCHEMA_JSON, or load tables into DuckDB catalog."
    )


def match_query_index(sql_query: str) -> int | None:
    """Optional SSB convenience: 1-based index when SQL matches a known SSB query."""
    try:
        from research_loop.ssb_workload import queries
    except ImportError:
        return None

    def normalize(s: str) -> str:
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s.replace('"', "").replace("'", "")

    norm_input = normalize(sql_query)
    for idx, q_sql in enumerate(queries):
        nq = normalize(q_sql)
        if nq == norm_input or nq in norm_input or norm_input in nq:
            return idx + 1

    if not looks_like_ssb_sql(sql_query):
        return None

    norm_input = normalize(sql_query)
    if "group by" in norm_input:
        if "d_year" in norm_input and "p_brand" in norm_input:
            if "mfgr#12" in norm_input or "p_category" in norm_input:
                return 4
            if "mfgr#2221" in norm_input:
                return 5 if "asia" in norm_input else 6
            return 4
        if "c_nation" in norm_input and "s_nation" in norm_input:
            return 7
        if "c_city" in norm_input and "s_city" in norm_input:
            if "united states" in norm_input:
                return 8
            if "19971201" in norm_input or "19971231" in norm_input:
                return 10
            return 9
        if "c_nation" in norm_input and "d_year" in norm_input:
            return 12 if "19970101" in norm_input else 11
        if "s_nation" in norm_input and "p_category" in norm_input:
            return 13
        if "lo_orderpriority" in norm_input:
            return 15

    if "lo_quantity" in norm_input:
        if "19940101" in norm_input or "19941231" in norm_input:
            return 14
        if "19930101" in norm_input:
            return 1
        if "1994" in norm_input:
            return 2
        return 1
    if "d_weeknuminyear" in norm_input:
        return 3
    return None


def resolve_query_id(sql_query: str) -> int:
    """Harness id: optional SSB match, else stable hash bucket (never silently default to Q1)."""
    matched = match_query_index(sql_query)
    if matched is not None:
        return matched
    return abs(hash(sql_query.strip())) % 1_000_000


def extract_trusted_run_query(spec_rs: str) -> str | None:
    """Do not treat vacuous TRUSTED run_query as a verified agent body."""
    m = _TRUSTED_RUN_QUERY_RE.search(spec_rs)
    if m:
        return None
    m = _EXEC_RUN_QUERY_RE.search(spec_rs)
    if m and "RunQuery skeleton" not in spec_rs and "AGENT" not in spec_rs:
        body = m.group(0).strip()
        if "external_body" in body or "unimplemented!" in body:
            return None
        return body
    return None


def agent_file_to_run_query_body(agent_raw: str, spec_rs: str) -> str:
    """Convert agent workspace file to harness run_query_body (full pub exec fn).

    Always re-wrap with host ``requires`` / ``ensures``. Never accept an agent-provided
    ``pub exec fn run_query`` that omits the method_spec postcondition (that would
    "verify" without proving equivalence).
    """
    _ = spec_rs
    from research_loop.assemble_runquery import extract_agent_body, validate_runquery_body

    inner = extract_agent_body(agent_raw)
    if not inner.strip():
        raise ValueError(
            "agent run_query body is empty; TRUSTED/unimplemented transpile stubs are not accepted"
        )
    errors = validate_runquery_body(inner)
    if errors:
        raise ValueError("; ".join(errors))
    indented = "\n".join(f"    {line}" if line.strip() else "" for line in inner.splitlines())
    return f"""pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{{
{indented}
}}
"""


def copy_runquery_template(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if RUNQUERY_TEMPLATE.is_file():
        dest.write_text(RUNQUERY_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        dest.write_text(
            "// AGENT_BODY_START\npub fn run_query(cols: &Cols) -> u64 {\n    unimplemented!()\n}\n// AGENT_BODY_END\n",
            encoding="utf-8",
        )


def write_mock_agent_body(
    spec_rs: str,
    workspace_path: str | Path,
    *,
    stream_demo: bool = False,
) -> None:
    """Write mock runquery_agent.rs — skeleton only; never vacuous TRUSTED run_query."""
    from research_loop.pipeline_demo import demo_enabled, stream_mock_agent_output

    _ = spec_rs
    dest = Path(workspace_path)
    if stream_demo and demo_enabled():
        stream_mock_agent_output(
            workspace_path=str(dest),
            body_inner="// TODO: agent fills run_query body",
        )
    copy_runquery_template(dest)


def resolve_tbl_path(sql: str, schema: dict, workload_tables: dict[str, Path] | None = None) -> str:
    """Best-effort tbl path for benchmark (env > workload > SSB/holdout heuristics)."""
    raw = os.environ.get("LEMMA_BENCH_TBL", "").strip()
    if raw:
        return raw
    raw = os.environ.get("LEMMA_SSB_FLAT_TBL", "").strip()
    if raw:
        return raw

    if workload_tables:
        tables = extract_tables_from_sql(sql)
        for t in tables:
            p = workload_tables.get(t)
            if p is not None and Path(p).is_file():
                return str(p)
        primary = next(iter(workload_tables.values()), None)
        if primary is not None and Path(primary).is_file():
            return str(primary)

    tables = extract_tables_from_sql(sql)
    if any(t == "scan_skew" for t in tables) or any(t == "scan_skew_1m" for t in tables):
        try:
            from db_extension.workload_config import holdout_data_dir, holdout_table_path

            for t in tables:
                p = holdout_table_path(t)
                if p is not None and p.is_file():
                    return str(p)
            skew = holdout_data_dir() / "scan_skew.tbl"
            if skew.is_file():
                return str(skew)
        except ImportError:
            pass

    if any(t == "lineorder_flat" for t in tables) or looks_like_ssb_sql(sql):
        try:
            from db_extension.dataset_config import tbl_path

            return str(tbl_path())
        except ImportError:
            pass
        default = ROOT / "ssb-dbgen" / "lineorder_flat.tbl"
        if default.is_file():
            return str(default)
    return ""


def invoke_verus_custom_pipeline(
    *,
    sql: str,
    schema: dict,
    runquery_path: Path | None = None,
    run_query_body: str | None = None,
    dataset_size: int = 50_000,
    tbl: str | None = None,
    workload_tables: dict[str, Path] | None = None,
) -> dict:
    """Run research_loop Verus custom SQL pipeline; normalize metrics for optimizer/MCP."""
    from research_loop.harness import run_custom_sql_pipeline

    body = (run_query_body or "").strip()
    if not body and runquery_path is not None and runquery_path.is_file():
        agent_raw = runquery_path.read_text(encoding="utf-8")
        spec_path = runquery_path.parent / "context" / "ro" / "spec.rs"
        spec_rs = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else ""
        if not spec_rs:
            from verus_transpiler import transpile_sql_to_verus

            spec_rs = transpile_sql_to_verus(sql, schema)
        body = agent_file_to_run_query_body(agent_raw, spec_rs)

    tbl_path = tbl if tbl is not None else resolve_tbl_path(sql, schema, workload_tables)
    res = run_custom_sql_pipeline(
        sql,
        schema,
        run_query_body=body,
        tbl=tbl_path or None,
        limit=dataset_size,
    )
    return normalize_harness_metrics(res)


def enrich_agent_error_message(
    error: str,
    *,
    verify_msg: str = "",
    max_chars: int = 2000,
) -> str:
    """Append verify/compile log excerpt when error only points at a log file."""
    err = (error or "").strip()
    if not err:
        return err
    extra = (verify_msg or "").strip()
    if not extra:
        m = re.search(r"see\s+(\S+\.log)\b", err)
        if m:
            log_path = Path(m.group(1))
            if log_path.is_file():
                try:
                    extra = log_path.read_text(encoding="utf-8", errors="replace").strip()
                except OSError:
                    pass
    if extra and extra not in err:
        return f"{err}\n\n--- log excerpt ---\n{extra[:max_chars]}"
    return err


def normalize_harness_metrics(res: dict) -> dict:
    status = res.get("status", "FAILURE")
    proof_verified = bool(res.get("proof_verified"))
    ok_status = status in ("SUCCESS", "SUCCESS_UNVERIFIED")
    compiler_error = res.get("error") or res.get("bench_error") or res.get("verify_msg") or ""
    compiler_error = enrich_agent_error_message(
        str(compiler_error),
        verify_msg=str(res.get("verify_msg") or ""),
    )
    return {
        "status": "SUCCESS" if ok_status and proof_verified else "FAILURE",
        "proof_verified": proof_verified,
        "latency_us": int(res.get("latency_us", -1)),
        "compiler_error": compiler_error,
        "raw_status": status,
        "bench_skipped": bool(res.get("bench_skipped")),
    }
