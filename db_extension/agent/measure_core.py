"""Host-side measure/validate library for Lemma agent MCP (schema-general Verus)."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from concurrent import futures
from dataclasses import dataclass, field
from pathlib import Path

from db_extension.agent.extract import admit_workspace_runquery, extract_marked_body, validate_runquery_body
from db_extension.agent.lease_measure import (
    fallback_measure_path,
    lease_measure_enabled,
    merge_lease_into_metrics,
)
from db_extension.dataset_config import effective_dataset_size
from db_extension.verus_bridge import (
    invoke_verus_custom_pipeline,
    resolve_schema_for_sql,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKSPACE = ROOT / "research_loop" / "agent_workspace"
RESULTS_DIR_NAME = "mcp_results"
RUNS_DIR_NAME = "runs"
DEFAULT_RUNQUERY = "runquery_agent.rs"
CONFIG_ENV = ROOT / "research_loop" / "config.env"


@dataclass
class MeasureContext:
    """Host measure context bound to a workspace and query id."""

    query_id: int
    workspace: Path | None = None
    sql: str | None = None
    schema: dict | None = field(default=None, repr=False)

    def workspace_path(self) -> Path:
        if self.workspace is not None:
            return self.workspace.resolve()
        return workspace()


def workspace() -> Path:
    raw = os.environ.get("LEMMA_AGENT_WORKSPACE", str(DEFAULT_WORKSPACE))
    return Path(raw).resolve()


def results_dir(ws: Path | None = None) -> Path:
    d = (ws or workspace()) / RESULTS_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def runs_dir(ws: Path | None = None) -> Path:
    d = results_dir(ws) / RUNS_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_under_workspace(path: str, ws: Path | None = None) -> Path:
    base = ws or workspace()
    candidate = Path(path)
    target = candidate if candidate.is_absolute() else (base / candidate)
    target = target.resolve()
    target.relative_to(base)
    return target


def _harness_timeout_sec() -> int:
    timeout = 90
    if CONFIG_ENV.is_file():
        for line in CONFIG_ENV.read_text().splitlines():
            line = line.strip()
            if line.startswith("COMPILE_TIMEOUT_SEC="):
                timeout = int(line.split("=", 1)[1].strip()) + 120
                break
    return timeout


def _read_workspace_sql_schema(ws: Path) -> tuple[str, dict]:
    ro = ws / "context" / "ro"
    sql_path = ro / "query.sql"
    schema_path = ro / "schema.json"
    sql = sql_path.read_text(encoding="utf-8").strip() if sql_path.is_file() else ""
    if not sql:
        raise FileNotFoundError(f"missing workspace SQL context: {sql_path}")
    if schema_path.is_file():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    else:
        schema = resolve_schema_for_sql(sql)
    return sql, schema


def _is_host_standin_runquery(text: str) -> bool:
    """Proved bench stand-in: full ``pub exec fn run_query`` without agent markers."""
    if "AGENT_BODY_START" in text or "AGENT_EDIT_START" in text:
        return False
    return bool(
        re.search(r"pub\s+(?:exec\s+)?fn\s+run_query\s*\(", text)
        and "method_spec" in text
        and "external_body" not in text
        and "unimplemented!" not in text
    )


def _read_body(*, path: str | None, body: str | None, ws: Path | None = None) -> tuple[str, Path]:
    if body is not None:
        source = (ws or workspace()) / DEFAULT_RUNQUERY
        return body, source
    if path is None:
        path = DEFAULT_RUNQUERY
    target = _resolve_under_workspace(path, ws)
    if not target.is_file():
        raise FileNotFoundError(f"file not found: {target}")
    text = target.read_text(encoding="utf-8")
    if "AGENT_EDIT_START" in text:
        spec_path = target.parent / "context" / "ro" / "spec.rs"
        if not spec_path.is_file():
            raise ValueError(f"missing spec.rs for AGENT_EDIT admission: {spec_path}")
        spec_rs = spec_path.read_text(encoding="utf-8")
        inner = admit_workspace_runquery(text, spec_rs=spec_rs, agent_path=target)
    elif "AGENT_BODY_START" in text:
        inner = extract_marked_body(text, agent_path=target)
    else:
        inner = text
    return inner, target


def _write_marked_runquery(body: str, ws: Path | None = None) -> Path:
    base = ws or workspace()
    rq = base / DEFAULT_RUNQUERY
    spec_path = base / "context" / "ro" / "spec.rs"
    if spec_path.is_file():
        from db_extension.verus_bridge import resolve_ret_type_for_spec

        ret_type = resolve_ret_type_for_spec(spec_path.read_text(encoding="utf-8"))
    else:
        sql, schema = _read_workspace_sql_schema(base)
        from db_extension.verus_bridge import resolve_ret_type_for_sql

        ret_type = resolve_ret_type_for_sql(sql, schema)
    from research_loop.assemble_runquery import write_runquery_agent_file

    write_runquery_agent_file(rq, ret_type=ret_type, body_inner=body)
    return rq


def _invoke_harness(
    *,
    query_id: int,
    dataset_size: int,
    ws: Path,
    sql: str | None = None,
    schema: dict | None = None,
) -> tuple[dict, int]:
    del query_id  # custom SQL pipeline is schema-driven; id kept for MCP API stability
    if sql is None or schema is None:
        sql, schema = _read_workspace_sql_schema(ws)
    timeout = _harness_timeout_sec()
    t0 = time.perf_counter()
    try:
        with futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                invoke_verus_custom_pipeline,
                sql=sql,
                schema=schema,
                runquery_path=ws / DEFAULT_RUNQUERY,
                dataset_size=dataset_size,
            )
            metrics = future.result(timeout=timeout)
        returncode = 0 if metrics.get("status") == "SUCCESS" else 1
    except futures.TimeoutError:
        wall_ms = int((time.perf_counter() - t0) * 1000)
        raise TimeoutError(f"harness timed out after {timeout}s") from None
    except Exception as exc:
        wall_ms = int((time.perf_counter() - t0) * 1000)
        return (
            {
                "status": "FAILURE",
                "proof_verified": False,
                "latency_us": -1,
                "compiler_error": str(exc),
                "wall_harness_ms": wall_ms,
            },
            1,
        )
    wall_ms = int((time.perf_counter() - t0) * 1000)
    metrics.setdefault("wall_harness_ms", wall_ms)
    return metrics, returncode


def _trusted_usage_payload(*, raw: str, spec_rs: str | None, ws: Path | None) -> dict:
    from research_loop.trusted_usage import (
        trusted_usage_report,
        write_trusted_usage_artifact,
    )

    if not spec_rs:
        spec_path = (ws or workspace()) / "context" / "ro" / "spec.rs"
        if spec_path.is_file():
            spec_rs = spec_path.read_text(encoding="utf-8")
    if not spec_rs:
        return {}
    report = trusted_usage_report(spec_rs, raw)
    write_trusted_usage_artifact(report)
    return {
        "trusted_menu": report["trusted_menu"],
        "trusted_used": report["trusted_used"],
        "trusted_unused": report["trusted_unused"],
        "trusted_menu_count": report["trusted_menu_count"],
        "trusted_used_count": report["trusted_used_count"],
        "trusted_unused_count": report["trusted_unused_count"],
    }


def validate_solution(
    *,
    path: str | None = None,
    body: str | None = None,
    ws: Path | None = None,
) -> dict:
    """Validate run_query body; on success write marked runquery file."""
    try:
        inner, source = _read_body(path=path, body=body, ws=ws)
    except FileNotFoundError as exc:
        return {"ok": False, "phase": "read", "errors": [str(exc)], "runquery_path": None}
    except ValueError as exc:
        return {"ok": False, "phase": "extract", "errors": [str(exc)], "runquery_path": None}

    raw = body if body is not None else source.read_text(encoding="utf-8")
    spec_path = (ws or workspace()) / "context" / "ro" / "spec.rs"
    spec_rs = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else None
    usage = _trusted_usage_payload(raw=raw, spec_rs=spec_rs, ws=ws)

    if _is_host_standin_runquery(raw):
        return {
            "ok": True,
            "phase": "host_standin",
            "errors": [],
            "runquery_path": str(source),
            "body_chars": len(raw),
            "source_path": str(source),
            **usage,
        }

    if "AGENT_EDIT_START" in raw:
        return {
            "ok": True,
            "phase": "validated",
            "errors": [],
            "runquery_path": str(source),
            "body_chars": len(inner),
            "source_path": str(source),
            **usage,
        }

    errors = validate_runquery_body(inner)
    if errors:
        return {
            "ok": False,
            "phase": "validate",
            "errors": errors,
            "runquery_path": None,
            "body_chars": len(inner),
            "source_path": str(source),
            **usage,
        }

    rq_path = _write_marked_runquery(inner, ws)
    return {
        "ok": True,
        "phase": "validated",
        "errors": [],
        "runquery_path": str(rq_path),
        "body_chars": len(inner),
        "source_path": str(source),
        **usage,
    }


def run_solution(
    *,
    path: str | None = None,
    body: str | None = None,
    query_id: int,
    dataset_size: int | None = None,
    ws: Path | None = None,
    sql: str | None = None,
    schema: dict | None = None,
) -> dict:
    """Validate, invoke Verus harness; store run record under mcp_results/runs/."""
    validated = validate_solution(path=path, body=body, ws=ws)
    if not validated.get("ok"):
        return {
            "ok": False,
            "phase": validated.get("phase", "validate"),
            "errors": validated.get("errors", []),
            "run_id": None,
            "metrics": None,
            "result_path": None,
            "latency_us": None,
        }

    base = ws or workspace()
    rq_path = Path(validated["runquery_path"])
    size = dataset_size if dataset_size is not None else effective_dataset_size()
    run_id = f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}_{uuid.uuid4().hex[:8]}"
    t0 = time.perf_counter()
    try:
        metrics, returncode = _invoke_harness(
            query_id=query_id,
            dataset_size=size,
            ws=base,
            sql=sql,
            schema=schema,
        )
    except TimeoutError:
        elapsed_us = int((time.perf_counter() - t0) * 1_000_000)
        out = {
            "ok": False,
            "run_id": run_id,
            "phase": "harness",
            "errors": [f"harness timed out after {_harness_timeout_sec()}s"],
            "metrics": {
                "status": "TIMEOUT",
                "proof_verified": False,
                "latency_us": -1,
                "compiler_error": "harness timeout",
            },
            "result_path": None,
            "latency_us": -1,
            "dataset_size": size,
            "query_id": query_id,
            "wall_run_us": elapsed_us,
            "harness_returncode": -1,
        }
        _store_run(out, ws=base)
        return out

    elapsed_us = int((time.perf_counter() - t0) * 1_000_000)
    ok = metrics.get("status") == "SUCCESS" and bool(metrics.get("proof_verified"))
    if ok and lease_measure_enabled():
        try:
            metrics = merge_lease_into_metrics(metrics)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            metrics = dict(metrics)
            metrics["lease_measure_error"] = str(exc)
    else:
        metrics = dict(metrics)
        metrics.setdefault("measure_path", fallback_measure_path())
    latency_us = int(metrics.get("latency_us", -1))
    run_path = runs_dir(base) / f"{run_id}.json"
    out = {
        "ok": ok,
        "run_id": run_id,
        "phase": "harness",
        "errors": [] if ok else [metrics.get("compiler_error") or "harness failed"],
        "metrics": metrics,
        "result_path": str(run_path),
        "latency_us": latency_us,
        "dataset_size": size,
        "query_id": query_id,
        "runquery_path": str(rq_path),
        "wall_run_us": elapsed_us,
        "harness_returncode": returncode,
    }
    _store_run(out, ws=base)
    return out


def _store_run(record: dict, *, ws: Path) -> None:
    run_id = record.get("run_id")
    if not run_id:
        return
    path = runs_dir(ws) / f"{run_id}.json"
    path.write_text(json.dumps(record, indent=2) + "\n")
    latest = results_dir(ws) / "latest_run.json"
    latest.write_text(json.dumps(record, indent=2) + "\n")


def list_runs(*, ws: Path | None = None) -> list[dict]:
    base = ws or workspace()
    rd = runs_dir(base)
    runs: list[dict] = []
    for p in sorted(rd.glob("*.json"), reverse=True):
        try:
            runs.append(json.loads(p.read_text()))
        except json.JSONDecodeError:
            continue
    return runs


def load_run(run_id: str, *, ws: Path | None = None) -> dict | None:
    base = ws or workspace()
    path = runs_dir(base) / f"{run_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def mark_submit(run_id: str, *, ws: Path | None = None) -> dict:
    """Mark a prior run_id as the official submission (does not run harness)."""
    base = ws or workspace()
    run = load_run(run_id, ws=base)
    if run is None:
        return {
            "ok": False,
            "error": f"unknown run_id: {run_id}",
            "run_id": run_id,
            "submitted_path": None,
        }
    submitted = {
        "run_id": run_id,
        "marked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_path": str(runs_dir(base) / f"{run_id}.json"),
        "run": run,
        "metrics": run.get("metrics"),
        "latency_us": run.get("latency_us"),
        "ok": bool(run.get("ok")),
    }
    out_path = results_dir(base) / "submitted.json"
    out_path.write_text(json.dumps(submitted, indent=2) + "\n")
    return {
        "ok": True,
        "run_id": run_id,
        "submitted_path": str(out_path),
        "latency_us": run.get("latency_us"),
        "metrics": run.get("metrics"),
        "note": "Marked run as official submit; harness not re-run.",
    }


def get_submitted(*, ws: Path | None = None) -> dict | None:
    base = ws or workspace()
    path = results_dir(base) / "submitted.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def mcp_health(*, ws: Path | None = None) -> dict:
    base = ws or workspace()
    return {
        "ok": True,
        "workspace": str(base),
        "results_dir": str(results_dir(base)),
        "root": str(ROOT),
    }
