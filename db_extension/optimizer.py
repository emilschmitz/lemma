import json
import os
import subprocess
import sys
import time
from pathlib import Path

from verus_transpiler.column_projection import (
    project_multi_schema_for_query,
    project_schema_for_query,
)
from verus_transpiler.parse_sql import normalize_schema, parse_sql
from verus_transpiler.query_tables import uses_multi_table_program

from db_extension.verus_bridge import (
    invoke_verus_custom_pipeline,
    match_query_index,
    resolve_query_id,
    resolve_ret_type_for_spec,
    resolve_schema_for_sql,
    write_mock_agent_body,
)
from db_extension.workload_config import catalog_assumptions_for_workload
from research_loop.assemble_verified_program import prepare_agent_visible_spec
from research_loop.lemma_flags import lemma_research_log
from research_loop.pipeline_demo import (
    demo_banner,
    demo_enabled,
    demo_iteration,
    demo_live_step,
    demo_note,
    demo_step_pass_fail,
    format_demo_seconds_from_us,
    verbose_enabled,
)
from research_loop.pipeline_log import log_debug, log_info, log_trace
from research_loop.run_artifacts import RunArtifacts, begin_run, end_run
from verus_transpiler import transpile_sql_to_verus

COMPONENT = "optimizer"

# ANSI Color Codes
COLOR_GREEN = "\033[92m"
COLOR_RED = "\033[91m"
COLOR_YELLOW = "\033[93m"
COLOR_BLUE = "\033[94m"
COLOR_CYAN = "\033[96m"
COLOR_RESET = "\033[0m"


def _vprint(*args, **kwargs) -> None:
    if verbose_enabled() or not demo_enabled():
        print(*args, **kwargs)

_HARNESS_METRICS_PREFIX = "LEMMA_METRICS_JSON:"


def _parse_harness_metrics(stderr: str) -> dict:
    for line in (stderr or "").splitlines():
        if line.startswith(_HARNESS_METRICS_PREFIX):
            return json.loads(line[len(_HARNESS_METRICS_PREFIX):])
    return {}


def _maybe_harvest_verified_submit(workspace: Path) -> dict | None:
    """Honor verified MCP runs when agent exited without submit_runquery."""
    from db_extension.agent.measure_core import get_submitted, harvest_verified_submit

    if get_submitted(ws=workspace) is not None:
        return agent_meta_from_workspace_submit(workspace)
    if harvest_verified_submit(ws=workspace) is None:
        return None
    return agent_meta_from_workspace_submit(workspace)


def _has_verified_submit(agent_meta: dict | None) -> bool:
    return bool(agent_meta and agent_meta.get("ok") and agent_meta.get("submitted"))


def agent_meta_from_workspace_submit(workspace: Path) -> dict | None:
    """CLI Docker path has no OpenRouter meta; honor mcp_results/submitted.json."""
    from db_extension.agent.measure_core import get_submitted

    submitted = get_submitted(ws=workspace)
    if submitted is None:
        return None
    metrics = submitted.get("metrics") or {}
    lat = submitted.get("latency_us", metrics.get("latency_us", -1))
    try:
        latency_us = int(lat)
    except (TypeError, ValueError):
        latency_us = -1
    return {
        "ok": bool(submitted.get("ok")),
        "submitted": True,
        "submitted_run_id": submitted.get("run_id"),
        "submitted_metrics": metrics,
        "submitted_record": submitted,
        "runquery_body": submitted.get("runquery_body"),
        "iterate_dataset_size": submitted.get("iterate_dataset_size"),
        "latency_us": latency_us,
        "error": "" if submitted.get("ok") else (
            metrics.get("compiler_error")
            or "marked run failed verification"
        ),
    }


_SUBMITTED_RUNQUERY_SNAPSHOT = ".submitted_runquery_snapshot.rs"
_LEFTOVER_VERIFY_MAX_CHARS = 4000
_OFFICIAL_MEASURE_TIMEOUT_CACHE: dict[str, dict] = {}


def _official_measure_submit_keys(
    *,
    submitted: dict | None,
    agent_meta: dict,
) -> list[str]:
    keys: list[str] = []
    run_id = (submitted or {}).get("run_id") or agent_meta.get("submitted_run_id")
    if run_id:
        keys.append(f"run_id:{run_id}")
    body_hash = (submitted or {}).get("runquery_sha256")
    if body_hash:
        keys.append(f"runquery_sha256:{body_hash}")
    return keys


def _cached_official_measure_timeout(
    *,
    submitted: dict | None,
    agent_meta: dict,
) -> dict | None:
    for key in _official_measure_submit_keys(submitted=submitted, agent_meta=agent_meta):
        cached = _OFFICIAL_MEASURE_TIMEOUT_CACHE.get(key)
        if cached is None:
            continue
        err = cached.get("official_measure_error") or ""
        if "timed out" in err:
            return dict(cached)
    return None


def _remember_official_measure_timeout(
    *,
    metrics: dict,
    submitted: dict | None,
    agent_meta: dict,
) -> None:
    err = metrics.get("official_measure_error") or ""
    if "timed out" not in err:
        return
    snapshot = dict(metrics)
    for key in _official_measure_submit_keys(submitted=submitted, agent_meta=agent_meta):
        _OFFICIAL_MEASURE_TIMEOUT_CACHE[key] = snapshot


def clear_official_measure_timeout_cache() -> None:
    """Test helper: reset per-process official-measure timeout memo."""
    _OFFICIAL_MEASURE_TIMEOUT_CACHE.clear()


def leftover_verify_excerpt(workspace: Path, *, max_chars: int = _LEFTOVER_VERIFY_MAX_CHARS) -> str:
    """Leftover Verus/rustc log after a session. Not an agent verdict (AGENTS.md traces).

    Missing file is a loud empty string so harvest can say LEFTOVER_VERIFY_MISSING.
    """
    path = Path(workspace) / "verify_error_custom.log"
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    text = text.strip()
    if not text:
        return ""
    if len(text) > max_chars:
        return text[:max_chars] + "\n... [leftover verify truncated]"
    return text


def post_agent_next_step(*, use_mock: bool, submitted: dict | None) -> str:
    """What the host may do after the agent process exits.

    ``assemble_leftover`` — mock only (legacy leftover file).
    ``official_measure`` — marked verified snapshot.
    ``no_submit_fail`` — non-mock with no verified submit; do not touch leftover.
    """
    if use_mock:
        return "assemble_leftover"
    if (
        submitted
        and submitted.get("ok")
        and submitted.get("runquery_body")
        and submitted.get("runquery_sha256")
    ):
        return "official_measure"
    return "no_submit_fail"


def should_assemble_leftover_after_agent(
    *,
    use_mock: bool,
    submitted: dict | None,
) -> bool:
    """True only for mock leftover assemble. Real agents never stitch leftover."""
    return post_agent_next_step(use_mock=use_mock, submitted=submitted) == "assemble_leftover"


def _submitted_runquery_snapshot_path(
    *,
    submitted: dict | None,
    agent_meta: dict,
    workspace: Path,
    fallback_path: Path,
) -> Path | None:
    """Write snapshotted runquery body to workspace; prefer snapshot over dirty leftover."""
    body = None
    if submitted:
        body = submitted.get("runquery_body")
    if not body:
        body = agent_meta.get("runquery_body")
    if body:
        snap = workspace / _SUBMITTED_RUNQUERY_SNAPSHOT
        snap.write_text(body, encoding="utf-8")
        return snap
    if fallback_path.is_file():
        return fallback_path
    return None


def official_full_measure_after_submit(
    *,
    submitted_metrics: dict,
    agent_meta: dict,
    submitted: dict | None,
    sql_query: str,
    resolved_schema: dict,
    dataset_size: int,
    workspace: Path,
    agent_body_path: Path,
    workload_tables: dict | None,
    workload: str | None,
    harness_timeout: int,
    invoke_fn=invoke_verus_custom_pipeline,
) -> dict:
    """After marked MCP submit: preserve submit proof; run official full-table execute."""
    iterate_latency_us = int(
        agent_meta.get("latency_us", submitted_metrics.get("latency_us", -1))
    )
    iterate_dataset_size = None
    if submitted:
        iterate_dataset_size = submitted.get("iterate_dataset_size")
    if iterate_dataset_size is None:
        run = (submitted or {}).get("run") or {}
        iterate_dataset_size = run.get("dataset_size")
    if iterate_dataset_size is None:
        iterate_dataset_size = agent_meta.get("iterate_dataset_size")

    submit_proof = bool(submitted_metrics.get("proof_verified")) or bool(agent_meta.get("ok"))

    metrics: dict = {
        **submitted_metrics,
        "iterate_latency_us": iterate_latency_us,
        "proof_verified": True if submit_proof else bool(submitted_metrics.get("proof_verified")),
    }
    if iterate_dataset_size is not None:
        metrics["iterate_dataset_size"] = iterate_dataset_size

    runquery_path = _submitted_runquery_snapshot_path(
        submitted=submitted,
        agent_meta=agent_meta,
        workspace=workspace,
        fallback_path=agent_body_path,
    )
    if runquery_path is None:
        metrics["official_measure_error"] = "no runquery snapshot or body file"
        metrics["latency_us"] = -1
        return metrics

    cached_timeout = _cached_official_measure_timeout(
        submitted=submitted,
        agent_meta=agent_meta,
    )
    if cached_timeout is not None:
        out = dict(cached_timeout)
        if submit_proof:
            out["proof_verified"] = True
        return out

    def _run_official() -> dict:
        return invoke_fn(
            sql=sql_query,
            schema=resolved_schema,
            runquery_path=runquery_path,
            dataset_size=dataset_size,
            workload_tables=workload_tables,
            workload=workload,
        )

    try:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run_official)
            official = future.result(timeout=harness_timeout)
    except (TimeoutError, concurrent.futures.TimeoutError):
        metrics["official_measure_error"] = (
            f"official full-table measure timed out after {harness_timeout}s"
        )
        metrics["latency_us"] = -1
        if submit_proof:
            metrics["proof_verified"] = True
        _remember_official_measure_timeout(
            metrics=metrics,
            submitted=submitted,
            agent_meta=agent_meta,
        )
        return metrics
    except Exception as exc:
        metrics["official_measure_error"] = str(exc)
        metrics["latency_us"] = -1
        if submit_proof:
            metrics["proof_verified"] = True
        return metrics

    official_ok = (
        official.get("status") == "SUCCESS"
        and official.get("proof_verified")
        and int(official.get("latency_us", -1)) >= 0
    )
    if official_ok:
        for key, val in official.items():
            if key != "proof_verified":
                metrics[key] = val
        metrics["proof_verified"] = True if submit_proof else bool(official.get("proof_verified"))
        metrics.setdefault("measure_path", "official_full")
        metrics["dataset_size"] = dataset_size
    else:
        metrics["official_measure_error"] = (
            official.get("compiler_error")
            or f"status={official.get('status')} proof={official.get('proof_verified')}"
        )
        metrics["latency_us"] = -1
        if submit_proof:
            metrics["proof_verified"] = True
        _remember_official_measure_timeout(
            metrics=metrics,
            submitted=submitted,
            agent_meta=agent_meta,
        )

    return metrics


def is_timed_verified_success(metrics: dict) -> bool:
    """True when harness/agent metrics are verified with a real timed bench."""
    if metrics.get("status") != "SUCCESS":
        return False
    if not metrics.get("proof_verified"):
        return False
    try:
        latency = int(metrics.get("latency_us", -1))
    except (TypeError, ValueError):
        return False
    # A zero clock is the timed call returning in under 1µs. That is not a scan.
    if latency <= 0:
        return False
    if metrics.get("official_measure_error"):
        return False
    return metrics.get("bench_skipped") is not True


def harness_timeout_sec(*, config_env_path: str | None = None) -> int:
    """Wall-clock budget for verify+compile harness (compile/verify max + buffer)."""
    compile_timeout = int(os.environ.get("COMPILE_TIMEOUT_SEC", "180"))
    verify_timeout = int(os.environ.get("VERUS_VERIFY_TIMEOUT_SEC", "120"))
    if config_env_path and os.path.isfile(config_env_path):
        with open(config_env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("COMPILE_TIMEOUT_SEC="):
                    compile_timeout = int(line.split("=", 1)[1].strip())
                elif line.startswith("VERUS_VERIFY_TIMEOUT_SEC="):
                    verify_timeout = int(line.split("=", 1)[1].strip())
    return max(compile_timeout, verify_timeout) + 120


def bench_timeout_sec() -> int:
    """Wall-clock budget for binary execute/bench runs (``LEMMA_BENCH_TIMEOUT_SEC``)."""
    raw = os.environ.get("LEMMA_BENCH_TIMEOUT_SEC", "120").strip()
    try:
        return max(30, int(raw))
    except ValueError:
        return 120


def official_measure_timeout_sec(*, config_env_path: str | None = None) -> int:
    """Post-submit full-table measure wall: verify+compile budget or bench, whichever is larger."""
    return max(harness_timeout_sec(config_env_path=config_env_path), bench_timeout_sec())


def _keep_optimizing() -> bool:
    raw = os.environ.get("LEMMA_KEEP_OPTIMIZING", "").strip().lower()
    return raw in ("1", "true", "yes")


def _stop_on_timed_success_enabled() -> bool:
    raw = os.environ.get("LEMMA_STOP_ON_TIMED_SUCCESS", "").strip().lower()
    return raw in ("1", "true", "yes")


def _maybe_stop_on_timed_success(*, metrics: dict, iteration: int) -> bool:
    if _keep_optimizing():
        return False
    if not _stop_on_timed_success_enabled():
        return False
    if is_timed_verified_success(metrics):
        log_info(COMPONENT, "stop_on_timed_success", f"iter={iteration}")
        return True
    return False


def _record_timed_best(
    *,
    metrics: dict,
    latency: int,
    iteration: int,
    official_full_bests: list[tuple[int, int]],
    official_bests: list[tuple[int, int]],
    fallback_bests: list[tuple[int, int]],
) -> None:
    """Track best latency; prefer official-full rows over iterate fallback at harvest."""
    if metrics.get("status") != "SUCCESS":
        return
    if not metrics.get("proof_verified"):
        return
    if latency < 0:
        return
    if metrics.get("official_measure_error"):
        return
    elif metrics.get("measure_path") == "official_full":
        official_full_bests.append((latency, iteration))
    else:
        official_bests.append((latency, iteration))


def _resolve_best_latency(
    official_full_bests: list[tuple[int, int]],
    official_bests: list[tuple[int, int]],
    fallback_bests: list[tuple[int, int]],
) -> tuple[int, int]:
    if official_full_bests:
        return min(official_full_bests, key=lambda pair: pair[0])
    if official_bests:
        return min(official_bests, key=lambda pair: pair[0])
    return -1, -1


def _history_entry(
    *,
    iteration: int,
    status: str,
    proof_verified: bool,
    latency: int,
    error: str = "",
    metrics: dict | None = None,
    agent_meta: dict | None = None,
    wall_s: float | None = None,
    agent_gen_wall_s: float | None = None,
    extra: dict | None = None,
) -> dict:
    entry: dict = {
        "iteration": iteration,
        "status": status,
        "proof_verified": proof_verified,
        "latency_us": latency,
        "error": error,
    }
    if wall_s is not None:
        entry["wall_s"] = round(wall_s, 3)
    if agent_gen_wall_s is not None:
        entry["agent_gen_wall_s"] = round(agent_gen_wall_s, 3)
    if agent_meta:
        for key in ("tokens_in", "tokens_out", "cost_usd"):
            if key in agent_meta:
                entry[key] = agent_meta[key]
    if metrics:
        for key in ("SESSION_HOT_US", "PREP_US", "OPEN_US", "COLD_QUERY_US", "measure_path"):
            if key in metrics:
                entry[key] = metrics[key]
    if extra:
        entry.update(extra)
    return entry


def _trusted_usage_extra(
    *,
    agent_body_path: Path,
    spec_rs: str,
    run: RunArtifacts | None,
) -> dict:
    """Harvest Trusted menu/usage for history + ``logs/trusted_usage.json``."""
    if not agent_body_path.is_file():
        return {}
    from research_loop.trusted_usage import (
        trusted_usage_report,
        write_trusted_usage_artifact,
    )

    report = trusted_usage_report(spec_rs, agent_body_path.read_text(encoding="utf-8"))
    write_trusted_usage_artifact(report, run=run)
    return {
        "trusted_menu": report["trusted_menu"],
        "trusted_used": report["trusted_used"],
        "trusted_unused": report["trusted_unused"],
    }


def _maybe_merge_lease_metrics(metrics: dict) -> dict:
    try:
        from db_extension.agent.lease_measure import (
            lease_measure_enabled,
            merge_lease_into_metrics,
        )

        if lease_measure_enabled() and metrics.get("status") == "SUCCESS" and metrics.get("proof_verified"):
            return merge_lease_into_metrics(metrics)
    except Exception as exc:
        out = dict(metrics)
        out["lease_measure_error"] = str(exc)
        return out
    return metrics


def _run_harness_demo(harness_cmd: list[str], *, cwd: str, timeout: int) -> tuple[int, dict]:
    """Run harness; stream demo UI on stderr live, parse metrics from the trailer line."""
    proc = subprocess.Popen(
        harness_cmd,
        cwd=cwd,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    metrics: dict = {}
    assert proc.stderr is not None
    try:
        for line in proc.stderr:
            if line.startswith(_HARNESS_METRICS_PREFIX):
                metrics = json.loads(line[len(_HARNESS_METRICS_PREFIX):].strip())
            else:
                sys.stderr.write(line)
                sys.stderr.flush()
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    return proc.returncode, metrics


# match_query_index, write_mock_agent_body, resolve_schema_for_sql live in verus_bridge

def _finish_run(run: RunArtifacts | None, result: dict) -> dict:
    if run is None:
        return result
    return end_run(run, result)


def _execute_agent_with_resource_exhausted_retries(
    *,
    run_agent_fn,
    workspace: Path,
    iteration: int,
    harvest_fn,
    has_verified_submit_fn,
    sleep_fn=time.sleep,
) -> tuple[str, object, dict | None, bool]:
    """Run agent; on Cursor resource_exhausted retry with backoff without advancing iteration.

    Returns ``(body, proc, agent_meta, resource_exhausted_exhausted)``.
    When ``resource_exhausted_exhausted`` is True, retries were bounded and failed.
    """
    from research_loop.agent_sandbox import (
        agent_run_resource_exhausted,
        max_agent_resource_exhausted_retries,
        resource_exhausted_backoff_sec,
    )

    max_retries = max_agent_resource_exhausted_retries()
    resource_retry = 0
    agent_meta: dict | None = None

    while True:
        body, proc = run_agent_fn()
        harvested = harvest_fn()
        if harvested is not None:
            agent_meta = harvested

        if has_verified_submit_fn(agent_meta):
            return body, proc, agent_meta, False

        if not agent_run_resource_exhausted(proc, workspace):
            return body, proc, agent_meta, False

        resource_retry += 1
        if resource_retry > max_retries:
            log_info(
                COMPONENT,
                "agent_resource_exhausted_exhausted",
                f"iter={iteration} retries={max_retries}",
                infra="resource_exhausted",
            )
            print(
                f"agent_resource_exhausted_exhausted: iter={iteration} "
                f"retries={max_retries} (infra failure after backoff)",
                flush=True,
            )
            return body, proc, agent_meta, True

        wait = resource_exhausted_backoff_sec(resource_retry)
        log_info(
            COMPONENT,
            "agent_resource_exhausted",
            f"retry={resource_retry}/{max_retries} iter={iteration} wait_s={wait:.0f}",
            infra="resource_exhausted",
        )
        print(
            f"agent_resource_exhausted: retry {resource_retry}/{max_retries} "
            f"iter={iteration} wait_s={wait:.0f} "
            f"(Cursor API quota; not consuming iteration)",
            flush=True,
        )
        sleep_fn(wait)


def run_optimization_loop(
    sql_query: str,
    dataset_size: int = 50000,
    max_iterations: int = 3,
    use_mock: bool = True,
    model: str = None,
    schema: dict | None = None,
    workload_tables: dict | None = None,
    workload: str | None = None,
) -> dict:
    """
    Runs the query optimization loop (schema-driven Verus). Prints step-by-step colored output.
    """
    try:
        catalog_schema = resolve_schema_for_sql(sql_query, schema)
        # Same projection the harness uses — agent must see the Cols/MethodSpec that assemble verifies.
        try:
            _flat, multi = normalize_schema(catalog_schema)
            parsed = parse_sql(sql_query, catalog_schema)
            if multi is not None and uses_multi_table_program(parsed, multi):
                resolved_schema = project_multi_schema_for_query(sql_query, multi)
            else:
                resolved_schema = project_schema_for_query(sql_query, catalog_schema)
        except Exception:
            resolved_schema = catalog_schema
    except ValueError as e:
        return {"status": "FAILED", "error": str(e), "history": []}

    query_id = resolve_query_id(sql_query)
    ssb_match = match_query_index(sql_query)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(current_dir)

    run: RunArtifacts | None = None
    if lemma_research_log():
        run = begin_run(
            query_id=query_id,
            sql_query=sql_query,
            root=root_dir,
            extra_manifest={
                "dataset_size": dataset_size,
                "max_iterations": max_iterations,
                "use_mock": use_mock,
                "model": model,
            },
        )
        workspace = run.workspace
    else:
        workspace = Path(root_dir) / "research_loop" / "agent_workspace"

    if demo_enabled():
        demo_banner("Lemma Optimizer")
    else:
        _vprint(f"{COLOR_CYAN}--- Starting Lemma optimizer (query_id={query_id}) ---{COLOR_RESET}")
        if ssb_match is not None:
            _vprint(f"    SSB harness match: Q{ssb_match} (optional convenience)")
    
    official_full_bests: list[tuple[int, int]] = []
    official_bests: list[tuple[int, int]] = []
    fallback_bests: list[tuple[int, int]] = []
    best_latency = -1
    best_iteration = -1
    history = []
    agent_gen_wall_s = 0.0

    log_info(
        COMPONENT,
        "loop_start",
        f"query_id={query_id}",
        dataset_size=dataset_size,
        mock=use_mock,
        run_dir=str(run.path) if run else "",
        research_log=bool(run),
    )

    def _snapshot_history() -> None:
        if run is not None:
            run.write_history(history)

    def _save_harness_metrics(iteration: int, metrics: dict) -> None:
        if run is not None and metrics:
            run.save_json(f"harness_iter{iteration}.json", metrics)

    for iteration in range(1, max_iterations + 1):
        log_info(COMPONENT, "iteration_start", f"iter={iteration}/{max_iterations}")
        iter_agent_wall_s = 0.0
        if demo_enabled():
            demo_iteration(iteration, max_iterations)
        else:
            _vprint(f"\n{COLOR_BLUE}Iteration {iteration}:{COLOR_RESET}")

        # Step 1: Transpile SQL
        log_debug(COMPONENT, "transpile_start", "verus_transpiler")
        _vprint("  - Transpiling SQL query to formal Verus spec...", end="", flush=True)
        catalog = catalog_assumptions_for_workload(workload)
        try:
            if demo_enabled():
                with demo_live_step("🏗", "SQL → Verus spec", pass_fail=True) as transpile_step:
                    verus_spec = transpile_sql_to_verus(
                        sql_query, resolved_schema, catalog_assumptions=catalog
                    )
                    transpile_step.set_passed(True)
            else:
                t_start = time.perf_counter()
                verus_spec = transpile_sql_to_verus(
                    sql_query, resolved_schema, catalog_assumptions=catalog
                )
                ms = int((time.perf_counter() - t_start) * 1000)
                log_debug(COMPONENT, "transpile_done", f"{ms}ms", spec_bytes=len(verus_spec))
                _vprint(f" {COLOR_GREEN}OK{COLOR_RESET} ({ms} ms)")
        except Exception as e:
            _vprint(f" {COLOR_RED}FAILED{COLOR_RESET}")
            _vprint(f"    Error: {e}")
            return _finish_run(run, {"status": "FAILED", "error": f"Transpilation failed: {e}", "history": history})
        if demo_enabled():
            log_debug(COMPONENT, "transpile_done", "ok", spec_bytes=len(verus_spec))
        schema_json_path = workspace / "context" / "ro" / "schema.json"
        schema_json_path.parent.mkdir(parents=True, exist_ok=True)
        schema_json_path.write_text(json.dumps(resolved_schema, indent=2) + "\n")
        ret_type = resolve_ret_type_for_spec(verus_spec)
        agent_spec = prepare_agent_visible_spec(
            verus_spec, ret_type, catalog_assumptions=catalog
        )
        view_raw = os.environ.get("LEMMA_DEMO_VIEW_DIR", "").strip()
        if view_raw:
            view_p = Path(view_raw)
            view_p.mkdir(parents=True, exist_ok=True)
            (view_p / "spec.rs").write_text(agent_spec)
            (view_p / "CURRENT").write_text("spec.rs (MethodSpec + TRUSTED agg API)\n")
        ro_spec = workspace / "context" / "ro" / "spec.rs"
        ro_spec.parent.mkdir(parents=True, exist_ok=True)
        ro_spec.write_text(agent_spec)
        (workspace / "context" / "ro" / "query.sql").write_text(sql_query.strip() + "\n")

        # Step 2: Write agent code
        _vprint("  - Writing optimized query in Verus...", end="", flush=True)
        agent_body_path = workspace / "runquery_agent.rs"
        agent_meta: dict | None = None
        if use_mock:
            try:
                if demo_enabled():
                    with demo_live_step("🦾", "Generating RunQuery", pass_fail=True) as gen_step:
                        write_mock_agent_body(
                            verus_spec,
                            agent_body_path,
                            sql_query=sql_query,
                            schema=resolved_schema,
                        )
                        gen_step.set_passed(True)
                else:
                    write_mock_agent_body(
                        verus_spec,
                        agent_body_path,
                        sql_query=sql_query,
                        schema=resolved_schema,
                    )
                    _vprint(f" {COLOR_GREEN}OK{COLOR_RESET} (Mock Agent, TRUSTED run_query from spec)")
            except Exception as e:
                _vprint(f" {COLOR_RED}FAILED{COLOR_RESET} (Mock generation failed)")
                _vprint(f"    Error: {e}")
                return _finish_run(run, {"status": "FAILED", "error": f"Mock generation failed: {e}", "history": history})
        else:
            from types import SimpleNamespace

            from db_extension.agent.config import load_agent_flags

            agent_flags = load_agent_flags()
            backend = agent_flags.backend.strip().lower()
            last_error = history[-1]["error"] if history else ""
            if last_error:
                from db_extension.verus_bridge import enrich_agent_error_message
                from research_loop.agent_sandbox import attach_workspace_verify_error

                last_error = enrich_agent_error_message(last_error)
                last_error = attach_workspace_verify_error(workspace, last_error)
            last_lat = history[-1]["latency_us"] if history and history[-1].get("proof_verified") else -1

            try:
                bench_raw = os.environ.get("LEMMA_BENCH_TBL", "").strip()
                if bench_raw:
                    data_path = Path(bench_raw)
                else:
                    from db_extension.dataset_config import tbl_path

                    data_path = tbl_path()
            except ImportError:
                data_path = None

            def _run_agent() -> tuple[str, SimpleNamespace]:
                nonlocal agent_meta
                if backend == "cli":
                    from research_loop.agent_sandbox import (
                        build_docker_image,
                        docker_image_built,
                        load_agent_config,
                        run_agent_iteration,
                        use_docker,
                    )

                    cfg = load_agent_config()
                    if use_docker(cfg):
                        image = cfg.get("AGENT_IMAGE", "lemma-agent:latest")
                        if not docker_image_built(image):
                            log_info(COMPONENT, "docker_build_start", f"building {image}")
                            _vprint(f"  - Building agent Docker image {image}...", end="", flush=True)
                            build_docker_image(image, install_agent_cli=True)
                            _vprint(f" {COLOR_GREEN}OK{COLOR_RESET}")
                        _vprint("  - Running agent in Docker sandbox...", end="", flush=True)
                    else:
                        log_info(COMPONENT, "agent_local", "subprocess AGENT_CMD", workspace=str(workspace))
                        _vprint("  - Running agent (local subprocess)...", end="", flush=True)
                    body, proc = run_agent_iteration(
                        query_id=query_id,
                        verus_spec=verus_spec,
                        sql_query=sql_query,
                        schema=resolved_schema,
                        data_path=data_path,
                        iteration=iteration,
                        max_iterations=max_iterations,
                        last_error=last_error,
                        last_latency_us=last_lat,
                        workspace=workspace,
                        cfg=cfg,
                        catalog_assumptions=catalog,
                    )
                    agent_meta = agent_meta_from_workspace_submit(workspace)
                    return body, proc

                from db_extension.agent import run_openrouter_agent_iteration
                from db_extension.agent.docker_runner import ensure_image

                log_info(COMPONENT, "agent_openrouter", "OpenRouter ReAct + Docker tools")
                _vprint("  - Running OpenRouter agent (Docker tools)...", end="", flush=True)
                ensure_image(agent_flags.agent_image)
                body, meta = run_openrouter_agent_iteration(
                    query_id=query_id,
                    sql_query=sql_query,
                    verus_spec=verus_spec,
                    schema=resolved_schema,
                    iteration=iteration,
                    max_iterations=max_iterations,
                    last_error=last_error,
                    last_latency_us=last_lat,
                    workspace=workspace,
                    data_path=data_path,
                    flags=agent_flags,
                    catalog_assumptions=catalog,
                )
                agent_meta = meta
                ok = bool(meta.get("ok"))
                err = meta.get("error", "") or ""
                proc = SimpleNamespace(
                    returncode=0 if ok else 1,
                    stdout=err,
                    stderr=err,
                )
                return body, proc

            a_start = time.perf_counter()
            resource_exhausted_exhausted = False
            try:
                def _agent_run_with_retries() -> tuple[str, object, dict | None, bool]:
                    return _execute_agent_with_resource_exhausted_retries(
                        run_agent_fn=_run_agent,
                        workspace=workspace,
                        iteration=iteration,
                        harvest_fn=lambda: _maybe_harvest_verified_submit(workspace),
                        has_verified_submit_fn=_has_verified_submit,
                    )

                if demo_enabled():
                    with demo_live_step("🦾", "Generating RunQuery", pass_fail=True) as gen_step:
                        body, proc, agent_meta, resource_exhausted_exhausted = (
                            _agent_run_with_retries()
                        )
                        log_trace(COMPONENT, "agent_body_preview", body[:200])
                        has_verified_submit = _has_verified_submit(agent_meta)
                        gen_step.set_passed(proc.returncode == 0 or has_verified_submit)
                else:
                    body, proc, agent_meta, resource_exhausted_exhausted = (
                        _agent_run_with_retries()
                    )
                    log_trace(COMPONENT, "agent_body_preview", body[:200])
                    has_verified_submit = _has_verified_submit(agent_meta)
                    if not resource_exhausted_exhausted:
                        write_ms = int((time.perf_counter() - a_start) * 1000)
                        if has_verified_submit and proc.returncode != 0:
                            _vprint(
                                f" {COLOR_YELLOW}HARVESTED{COLOR_RESET} "
                                f"(verified MCP submit; agent rc={proc.returncode}, "
                                f"{write_ms // 1000} s)"
                            )
                        elif proc.returncode == 0 or has_verified_submit:
                            _vprint(f" {COLOR_GREEN}OK{COLOR_RESET} ({write_ms // 1000} s)")

                if resource_exhausted_exhausted or (
                    proc.returncode != 0 and not _has_verified_submit(agent_meta)
                ):
                    if resource_exhausted_exhausted:
                        from research_loop.agent_sandbox import (
                            max_agent_resource_exhausted_retries,
                        )

                        err = (
                            f"Agent failed: Cursor resource_exhausted after "
                            f"{max_agent_resource_exhausted_retries()} retries"
                        )
                    else:
                        err = (
                            proc.stderr or proc.stdout or "agent exited non-zero"
                        ).strip()
                        err = f"Agent failed: {err}"
                    if not demo_enabled():
                        _vprint(f" {COLOR_RED}FAILED{COLOR_RESET}")
                        _vprint(f"    {err[:500]}")
                    history.append(_history_entry(
                        iteration=iteration,
                        status="FAILURE",
                        proof_verified=False,
                        latency=-1,
                        error=err,
                        wall_s=time.perf_counter() - a_start,
                        agent_gen_wall_s=agent_gen_wall_s + (time.perf_counter() - a_start),
                        extra=(
                            {"resource_exhausted": True}
                            if resource_exhausted_exhausted
                            else None
                        ),
                    ))
                    _snapshot_history()
                    continue
            except subprocess.TimeoutExpired:
                iter_agent_wall_s = time.perf_counter() - a_start
                agent_gen_wall_s += iter_agent_wall_s
                harvested = None
                if not use_mock:
                    harvested = _maybe_harvest_verified_submit(workspace)
                    if harvested is not None:
                        agent_meta = harvested
                has_verified_submit = _has_verified_submit(agent_meta)
                if demo_enabled():
                    demo_step_pass_fail(
                        "🦾",
                        "Generating RunQuery",
                        int(iter_agent_wall_s * 1000),
                        has_verified_submit,
                    )
                if has_verified_submit:
                    _vprint(
                        f" {COLOR_YELLOW}TIMEOUT{COLOR_RESET} "
                        "(harvested verified MCP submit; proceeding to official measure)"
                    )
                else:
                    _vprint(f" {COLOR_RED}TIMEOUT{COLOR_RESET}")
                    history.append(_history_entry(
                        iteration=iteration,
                        status="TIMEOUT",
                        proof_verified=False,
                        latency=-1,
                        error="Agent timed out",
                        wall_s=iter_agent_wall_s,
                        agent_gen_wall_s=agent_gen_wall_s,
                    ))
                    _snapshot_history()
                    continue
            except Exception as e:
                _vprint(f" {COLOR_RED}FAILED{COLOR_RESET}")
                _vprint(f"    {e}")
                return _finish_run(run, {"status": "FAILED", "error": str(e), "history": history})

            if not use_mock:
                iter_agent_wall_s = time.perf_counter() - a_start
                agent_gen_wall_s += iter_agent_wall_s

        # Step 3: Verify and compile and benchmark (skip if OpenRouter marked a run)
        usage_extra = _trusted_usage_extra(
            agent_body_path=agent_body_path,
            spec_rs=agent_spec,
            run=run,
        )
        from db_extension.agent.measure_core import get_submitted

        submitted_record = get_submitted(ws=workspace) if not use_mock else None
        post_step = post_agent_next_step(use_mock=use_mock, submitted=submitted_record)
        use_marked_metrics = post_step == "official_measure"
        if use_marked_metrics:
            if agent_meta is None or agent_meta.get("submitted_metrics") is None:
                agent_meta = agent_meta_from_workspace_submit(workspace) or {}
            submitted_metrics = dict(
                agent_meta.get("submitted_metrics")
                or (submitted_record or {}).get("metrics")
                or {}
            )
            iterate_latency = int(
                agent_meta.get("latency_us", submitted_metrics.get("latency_us", -1))
            )
            log_info(
                COMPONENT,
                "marked_submit_official",
                "running official full-table measure after marked submit",
                run_id=agent_meta.get("submitted_run_id"),
                iterate_latency_us=iterate_latency,
                dataset_size=dataset_size,
            )
            _vprint(
                "  - Official full-table measure after marked submit...",
                end="",
                flush=True,
            )
            h_start = time.perf_counter()
            cfg_path = os.path.join(root_dir, "research_loop", "config.env")
            measure_timeout = official_measure_timeout_sec(config_env_path=cfg_path)
            metrics = official_full_measure_after_submit(
                submitted_metrics=submitted_metrics,
                agent_meta=agent_meta,
                submitted=submitted_record,
                sql_query=sql_query,
                resolved_schema=resolved_schema,
                dataset_size=dataset_size,
                workspace=workspace,
                agent_body_path=agent_body_path,
                workload_tables=workload_tables,
                workload=workload,
                harness_timeout=measure_timeout,
            )
            h_time = time.perf_counter() - h_start
            metrics = _maybe_merge_lease_metrics(metrics)
            status = metrics.get("status", "SUCCESS" if metrics.get("proof_verified") else "FAILURE")
            proof_verified = bool(metrics.get("proof_verified"))
            try:
                latency = int(metrics.get("latency_us", -1))
            except (TypeError, ValueError):
                latency = -1
            if metrics.get("official_measure_error"):
                _vprint(
                    f" {COLOR_YELLOW}TIMEOUT{COLOR_RESET} (proved; official full-table timed out; "
                    f"lat=-1; iterate {iterate_latency} us is not official: "
                    f"{str(metrics['official_measure_error'])[:120]})"
                )
            elif status == "SUCCESS" and proof_verified and latency >= 0:
                _vprint(
                    f" {COLOR_GREEN}OK{COLOR_RESET} (official full-table, {latency} us, {h_time:.1f}s)"
                )
            else:
                _vprint(f" {COLOR_GREEN}OK{COLOR_RESET} (marked run)")
            # Overnight harvest greps these tokens; do not rely on harness JSON alone.
            print(
                f"proof_verified={bool(proof_verified)} latency_us={latency}",
                flush=True,
            )
            print(
                f"{_HARNESS_METRICS_PREFIX}{json.dumps(metrics)}",
                flush=True,
            )
            _record_timed_best(
                metrics=metrics,
                latency=latency,
                iteration=iteration,
                official_full_bests=official_full_bests,
                official_bests=official_bests,
                fallback_bests=fallback_bests,
            )
            history.append(_history_entry(
                iteration=iteration,
                status=status,
                proof_verified=proof_verified,
                latency=latency,
                error=metrics.get("compiler_error", "") or metrics.get("official_measure_error", ""),
                metrics=metrics,
                agent_meta=agent_meta,
                wall_s=iter_agent_wall_s or None,
                agent_gen_wall_s=agent_gen_wall_s,
                extra={"submitted_run_id": agent_meta.get("submitted_run_id"), **usage_extra},
            ))
            _save_harness_metrics(iteration, metrics)
            _snapshot_history()
            if _maybe_stop_on_timed_success(metrics=metrics, iteration=iteration):
                break
            continue

        if post_step == "no_submit_fail":
            from db_extension.agent.measure_core import loader_block_after_proof

            blocked = loader_block_after_proof(ws=workspace)
            if blocked:
                err = (
                    "step 7 (execute): the function was proved, then the column "
                    "loader rejected the file type. Not starting another prove. "
                    + blocked
                )
                _vprint(f" {COLOR_RED}FAILED{COLOR_RESET}")
                _vprint(f"    {err}")
                print(f"proof_verified={True} latency_us={-1}", flush=True)
                print(
                    f"{_HARNESS_METRICS_PREFIX}{json.dumps({'status': 'FAILURE', 'proof_verified': True, 'latency_us': -1, 'compiler_error': err})}",
                    flush=True,
                )
                history.append(_history_entry(
                    iteration=iteration,
                    status="FAILURE",
                    proof_verified=True,
                    latency=-1,
                    error=err,
                    agent_meta=agent_meta,
                    wall_s=iter_agent_wall_s or None,
                    agent_gen_wall_s=agent_gen_wall_s,
                    extra=usage_extra or None,
                ))
                _save_harness_metrics(iteration, {"status": "FAILURE", "proof_verified": True, "latency_us": -1, "compiler_error": err})
                _snapshot_history()
                return _finish_run(run, {"status": "FAILED", "error": err, "history": history})
            leftover = leftover_verify_excerpt(workspace)
            err = "no marked submit"
            if leftover:
                err = f"no marked submit; leftover verify:\n{leftover}"
            _vprint(f" {COLOR_RED}FAILED{COLOR_RESET}")
            _vprint("    no marked submit")
            if leftover:
                _vprint("    LEFTOVER_VERIFY_BEGIN")
                _vprint(leftover)
                _vprint("    LEFTOVER_VERIFY_END")
            else:
                _vprint("    LEFTOVER_VERIFY_MISSING (no leftover verify_error_custom.log)")
            print(f"proof_verified={False} latency_us={-1}", flush=True)
            print(
                f"{_HARNESS_METRICS_PREFIX}{json.dumps({'status': 'FAILURE', 'proof_verified': False, 'latency_us': -1, 'compiler_error': err, 'leftover_verify': leftover})}",
                flush=True,
            )
            history.append(_history_entry(
                iteration=iteration,
                status="FAILURE",
                proof_verified=False,
                latency=-1,
                error=err,
                agent_meta=agent_meta,
                wall_s=iter_agent_wall_s or None,
                agent_gen_wall_s=agent_gen_wall_s,
                extra=usage_extra or None,
            ))
            _snapshot_history()
            continue

        log_debug(COMPONENT, "harness_start", f"custom sql query_id={query_id}", dataset_size=dataset_size)
        _vprint("  - Verifying and compiling Verus program...", end="", flush=True)
        h_start = time.perf_counter()
        cfg_path = os.path.join(root_dir, "research_loop", "config.env")
        harness_timeout = harness_timeout_sec(config_env_path=cfg_path)

        def _run_verus_harness() -> dict:
            return invoke_verus_custom_pipeline(
                sql=sql_query,
                schema=resolved_schema,
                runquery_path=agent_body_path,
                dataset_size=dataset_size,
                workload_tables=workload_tables,
                workload=workload,
            )

        try:
            if demo_enabled():
                metrics = _run_verus_harness()
                if metrics:
                    print(
                        f"{_HARNESS_METRICS_PREFIX}{json.dumps(metrics)}",
                        file=sys.stderr,
                    )
            else:
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(_run_verus_harness)
                    metrics = future.result(timeout=harness_timeout)
            h_time = time.perf_counter() - h_start
            
            status = metrics["status"]
            proof_verified = metrics["proof_verified"]
            latency = metrics["latency_us"]
            log_info(
                COMPONENT,
                "harness_done",
                f"status={status} latency_us={latency}",
                proof_verified=proof_verified,
                ms=int(h_time * 1000),
            )

            if not demo_enabled():
                if status == "SUCCESS" and proof_verified:
                    _vprint(f" {COLOR_GREEN}VERIFIED & COMPILED{COLOR_RESET} in {h_time:.1f}s")
                    _vprint(f"    {COLOR_GREEN}Result:{COLOR_RESET} Executed in {COLOR_CYAN}{latency} us{COLOR_RESET}")
                elif not proof_verified:
                    _vprint(f" {COLOR_RED}VERIFICATION FAILED{COLOR_RESET}")
                    if metrics.get("compiler_error"):
                        _vprint(f"    Error: {metrics['compiler_error']}")
                else:
                    _vprint(f" {COLOR_RED}COMPILATION FAILED{COLOR_RESET}")
                    if metrics.get("compiler_error"):
                        _vprint(f"    Error: {metrics['compiler_error']}")

            metrics = _maybe_merge_lease_metrics(metrics)

            _record_timed_best(
                metrics=metrics,
                latency=latency,
                iteration=iteration,
                official_full_bests=official_full_bests,
                official_bests=official_bests,
                fallback_bests=fallback_bests,
            )

            history.append(_history_entry(
                iteration=iteration,
                status=status,
                proof_verified=proof_verified,
                latency=latency,
                error=metrics.get("compiler_error", ""),
                metrics=metrics,
                agent_meta=agent_meta if not use_mock else None,
                wall_s=iter_agent_wall_s or None,
                agent_gen_wall_s=agent_gen_wall_s,
                extra=usage_extra or None,
            ))
            _save_harness_metrics(iteration, metrics)
            _snapshot_history()
            if _maybe_stop_on_timed_success(metrics=metrics, iteration=iteration):
                break

        except (subprocess.TimeoutExpired, TimeoutError):
            if demo_enabled():
                demo_step_pass_fail("✅", "Verifying against spec", int(harness_timeout * 1000), False)
            _vprint(f" {COLOR_RED}TIMEOUT{COLOR_RESET} after {harness_timeout}s")
            history.append(_history_entry(
                iteration=iteration,
                status="TIMEOUT",
                proof_verified=False,
                latency=-1,
                error="Harness timed out",
                wall_s=iter_agent_wall_s or None,
                agent_gen_wall_s=agent_gen_wall_s,
                extra=usage_extra or None,
            ))
            _snapshot_history()

    best_latency, best_iteration = _resolve_best_latency(
        official_full_bests, official_bests, fallback_bests
    )

    if demo_enabled():
        if best_latency != -1:
            demo_note(
                f"Best: iteration {best_iteration} out of {max_iterations} at "
                f"{format_demo_seconds_from_us(best_latency)} s"
            )
    else:
        _vprint(f"\n{COLOR_CYAN}--- Optimization Finished ---{COLOR_RESET}")
        if best_latency != -1:
            _vprint(f"Best iteration: {COLOR_GREEN}{best_iteration}{COLOR_RESET} with latency: {COLOR_GREEN}{best_latency} us{COLOR_RESET}")
        else:
            proved = any(
                h.get("status") == "SUCCESS"
                and h.get("proof_verified")
                for h in history
            )
            if proved:
                _vprint(
                    f"{COLOR_RED}Iterations verified but none produced a timed bench "
                    f"(latency_us >= 0).{COLOR_RESET}"
                )
            else:
                _vprint(f"{COLOR_RED}No iteration succeeded in verification and compilation.{COLOR_RESET}")

    if best_latency != -1:
        print(f"best_latency_us={best_latency}", flush=True)

    if best_latency != -1:
        return _finish_run(run, {
            "status": "SUCCESS",
            "best_latency_us": best_latency,
            "best_iteration": best_iteration,
            "history": history,
        })
    return _finish_run(run, {
        "status": "FAILED",
        "best_latency_us": -1,
        "history": history,
    })
