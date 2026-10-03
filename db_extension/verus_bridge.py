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
    """Resolve flat or multi-table schema for SQL (explicit > env > catalog)."""
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

    cat = catalog or DatabaseCatalog(
        (os.environ.get("LEMMA_DUCKDB_PATH") or "").strip() or None
    )
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


def resolve_ret_type_for_spec(verus_spec: str) -> str:
    """Map MethodSpec text to assembler RET_TYPE_CONFIG key (source of truth)."""
    from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec

    return resolve_ret_type_from_method_spec(verus_spec)


def resolve_ret_type_for_sql(sql: str, schema: dict | None) -> str:
    """Map SQL + schema to assembler RET_TYPE_CONFIG key.

    Fallback only when MethodSpec text is not available yet; prefer
    ``resolve_ret_type_for_spec`` when transpiled spec exists.
    Fail loud on parse/shape errors (do not invent ``u64``).
    """
    if not sql.strip():
        raise ValueError("cannot resolve ret_type: empty SQL")
    from verus_transpiler.parse_sql import normalize_schema, parse_sql

    from research_loop.harness import _resolve_custom_ret_type
    from verus_transpiler.column_projection import (
        project_multi_schema_for_query,
        project_schema_for_query,
    )

    flat, multi = normalize_schema(schema or {})
    query = parse_sql(sql, schema or {})
    if multi:
        projected = project_multi_schema_for_query(sql, multi)
    else:
        projected = project_schema_for_query(sql, flat)
    return _resolve_custom_ret_type(query, projected, multi=bool(multi))


def agent_file_to_run_query_body(
    agent_raw: str,
    spec_rs: str,
    *,
    ret_type: str | None = None,
    agent_path: Path | None = None,
) -> str:
    """Convert agent workspace file to harness run_query_body (full pub exec fn).

    AGENT_EDIT: admit full fn with contract checks. AGENT_BODY: legacy body extract + host wrap.
    Never accept a vacuous TRUSTED run_query without method_spec postcondition.
    """
    from research_loop.admit_agent_runquery import admit_or_extract_legacy, read_expected_fingerprint
    from research_loop.assemble_runquery import AGENT_EDIT_START, AGENT_START

    # Host-injected proved stand-ins (bench_standins) ship a full pub exec fn with proof.
    if (
        AGENT_EDIT_START not in agent_raw
        and AGENT_START not in agent_raw
        and _EXEC_RUN_QUERY_RE.search(agent_raw)
    ):
        body = agent_raw.strip()
        if "method_spec" in body and "external_body" not in body and "unimplemented!" not in body:
            return body

    ret = ret_type
    if ret is None:
        if not spec_rs.strip():
            raise ValueError("cannot resolve ret_type: missing MethodSpec and ret_type")
        from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec

        ret = resolve_ret_type_from_method_spec(spec_rs)
    expected_fp = read_expected_fingerprint(agent_path) if agent_path is not None else None
    fn_text = admit_or_extract_legacy(
        agent_raw,
        method_spec_rs=spec_rs,
        ret_type=ret,
        expected_fingerprint=expected_fp,
    )
    if not fn_text.strip():
        raise ValueError(
            "agent run_query body is empty; TRUSTED/unimplemented transpile stubs are not accepted"
        )
    return fn_text


def copy_runquery_template(
    dest: Path,
    *,
    ret_type: str = "u64",
    sql_query: str | None = None,
    method_spec_rs: str | None = None,
) -> None:
    from research_loop.assemble_runquery import write_runquery_agent_file

    write_runquery_agent_file(
        dest,
        ret_type=ret_type,
        sql_query=sql_query,
        method_spec_rs=method_spec_rs,
    )


def write_mock_agent_body(
    spec_rs: str,
    workspace_path: str | Path,
    *,
    stream_demo: bool = False,
    sql_query: str = "",
    schema: dict | None = None,
) -> None:
    """Write mock runquery_agent.rs — skeleton only; never vacuous TRUSTED run_query."""
    from research_loop.pipeline_demo import demo_enabled, stream_mock_agent_output

    dest = Path(workspace_path)
    if stream_demo and demo_enabled():
        stream_mock_agent_output(
            workspace_path=str(dest),
            body_inner="// TODO: agent fills run_query body",
        )
    ret = resolve_ret_type_for_spec(spec_rs) if spec_rs.strip() else resolve_ret_type_for_sql(sql_query, schema)
    copy_runquery_template(
        dest,
        ret_type=ret,
        sql_query=sql_query or None,
        method_spec_rs=spec_rs if spec_rs.strip() else None,
    )


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


def read_workspace_bench_hints(runquery_path: Path | None) -> dict[str, str]:
    """Optional hot-path bench overrides from ``context/ro/bench_hints.json``."""
    if runquery_path is None:
        return {}
    hints_path = runquery_path.parent / "context" / "ro" / "bench_hints.json"
    if not hints_path.is_file():
        return {}
    try:
        raw = json.loads(hints_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}
    keys = (
        "hot_path_rs",
        "bench_exec",
        "bench_timing_body",
        "bench_post_timing",
        "bench_main_prefix",
    )
    return {k: str(raw[k]) for k in keys if k in raw and raw[k]}


def _invoke_declarative_pipeline(
    *,
    sql: str,
    schema: dict,
    runquery_path: Path | None,
    run_query_body: str | None,
    workload: str | None,
) -> dict:
    """Declarative flag: assemble the agent edit, compile, and run. Not the recursive pipeline."""
    from db_extension.workload_config import catalog_assumptions_for_workload
    from declarative_spec.emit import emit_declarative_spec
    from declarative_spec.pipeline import run_declarative_metrics

    spec_rs = ""
    agent_source = (run_query_body or "").strip()
    work_dir: Path | None = None
    if runquery_path is not None:
        spec_path = runquery_path.parent / "context" / "ro" / "spec.rs"
        if spec_path.is_file():
            spec_rs = spec_path.read_text(encoding="utf-8")
        if not agent_source and runquery_path.is_file():
            agent_source = runquery_path.read_text(encoding="utf-8")
        work_dir = runquery_path.parent / "declarative_build"
    if not spec_rs:
        spec_rs = emit_declarative_spec(
            sql,
            schema,
            catalog_assumptions_for_workload(workload),
            float_abs_eps=os.environ.get("LEMMA_FLOAT_ABS_EPS"),
        )
    if not agent_source:
        agent_source = spec_rs
    column_bins = None
    speed_bar = None
    if runquery_path is not None:
        from declarative_spec.bench import load_speed_bar

        loaded = load_speed_bar(runquery_path.parent / "decl_data")
        if loaded is not None:
            column_bins, speed_bar = loaded
    metrics = run_declarative_metrics(
        spec_rs=spec_rs,
        agent_source=agent_source,
        work_dir=work_dir,
        column_bins=column_bins,
        speed_bar=speed_bar,
    )
    return normalize_harness_metrics(metrics)


def invoke_verus_custom_pipeline(
    *,
    sql: str,
    schema: dict,
    runquery_path: Path | None = None,
    run_query_body: str | None = None,
    dataset_size: int = 50_000,
    tbl: str | None = None,
    workload_tables: dict[str, Path] | None = None,
    workload: str | None = None,
) -> dict:
    """Run research_loop Verus custom SQL pipeline; normalize metrics for optimizer/MCP."""
    from db_extension.optimizer import _read_lemma_spec_style

    if _read_lemma_spec_style() == "declarative":
        return _invoke_declarative_pipeline(
            sql=sql,
            schema=schema,
            runquery_path=runquery_path,
            run_query_body=run_query_body,
            workload=workload,
        )

    from research_loop.harness import run_custom_sql_pipeline

    bench_hints = read_workspace_bench_hints(runquery_path)
    body = (run_query_body or "").strip()
    if not body and runquery_path is not None and runquery_path.is_file():
        agent_raw = runquery_path.read_text(encoding="utf-8")
        spec_path = runquery_path.parent / "context" / "ro" / "spec.rs"
        spec_rs = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else ""
        if not spec_rs:
            from db_extension.workload_config import catalog_assumptions_for_workload
            from verus_transpiler import transpile_sql_to_verus

            spec_rs = transpile_sql_to_verus(
                sql,
                schema,
                catalog_assumptions=catalog_assumptions_for_workload(workload),
            )
        ret_type = resolve_ret_type_for_spec(spec_rs)
        body = agent_file_to_run_query_body(
            agent_raw,
            spec_rs,
            ret_type=ret_type,
            agent_path=runquery_path,
        )
        from research_loop.assemble_verified_program import rust_ret_from_run_query_fn

        admitted_rust_ret = rust_ret_from_run_query_fn(body)
    else:
        admitted_rust_ret = None

    tbl_path = tbl if tbl is not None else resolve_tbl_path(sql, schema, workload_tables)
    tbls = None
    if workload_tables:
        tbls = {k: str(v) for k, v in workload_tables.items() if Path(v).is_file()}
        if not tbls:
            tbls = None
    duckdb_path: str | None = None
    raw_duck = (os.environ.get("LEMMA_DUCKDB_PATH") or "").strip()
    if raw_duck and raw_duck not in (":memory:",) and Path(raw_duck).is_file():
        duckdb_path = str(Path(raw_duck).resolve())
    if workload == "sec" and duckdb_path is None:
        try:
            from db_extension.workload_config import resolve_workload

            spec = resolve_workload(sql, workload="sec")
            if Path(spec.db_path).is_file():
                duckdb_path = str(Path(spec.db_path).resolve())
        except (FileNotFoundError, ValueError):
            pass
    res = run_custom_sql_pipeline(
        sql,
        schema,
        run_query_body=body,
        tbl=tbl_path or None,
        tbls=tbls,
        limit=dataset_size,
        rust_ret=admitted_rust_ret,
        workload=workload,
        duckdb_path=duckdb_path,
        **bench_hints,
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
