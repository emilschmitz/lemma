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
from verus_transpiler.parse_sql import normalize_schema

from db_extension.verus_bridge import (
    invoke_verus_custom_pipeline,
    match_query_index,
    resolve_query_id,
    resolve_ret_type_for_spec,
    resolve_schema_for_sql,
    write_mock_agent_body,
)
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


def run_optimization_loop(
    sql_query: str,
    dataset_size: int = 50000,
    max_iterations: int = 3,
    use_mock: bool = True,
    model: str = None,
    schema: dict | None = None,
    workload_tables: dict | None = None,
) -> dict:
    """
    Runs the query optimization loop (schema-driven Verus). Prints step-by-step colored output.
    """
    try:
        catalog_schema = resolve_schema_for_sql(sql_query, schema)
        # Same projection the harness uses — agent must see the Cols/MethodSpec that assemble verifies.
        try:
            _flat, multi = normalize_schema(catalog_schema)
            if multi is not None:
                resolved_schema = project_multi_schema_for_query(sql_query, multi)
            else:
                resolved_schema = project_schema_for_query(sql_query, _flat)
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
        try:
            if demo_enabled():
                with demo_live_step("🏗", "SQL → Verus spec", pass_fail=True) as transpile_step:
                    verus_spec = transpile_sql_to_verus(sql_query, resolved_schema)
                    transpile_step.set_passed(True)
            else:
                t_start = time.perf_counter()
                verus_spec = transpile_sql_to_verus(sql_query, resolved_schema)
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
        agent_spec = prepare_agent_visible_spec(verus_spec, ret_type)
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

                last_error = enrich_agent_error_message(last_error)
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
                    )
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
            try:
                if demo_enabled():
                    with demo_live_step("🦾", "Generating RunQuery", pass_fail=True) as gen_step:
                        body, proc = _run_agent()
                        log_trace(COMPONENT, "agent_body_preview", body[:200])
                        has_marked = bool(
                            agent_meta and agent_meta.get("submitted_metrics") is not None
                        )
                        gen_step.set_passed(proc.returncode == 0 or has_marked)
                        if proc.returncode != 0 and not has_marked:
                            err = (proc.stderr or proc.stdout or "agent exited non-zero").strip()
                            if not demo_enabled():
                                _vprint(f" {COLOR_RED}FAILED{COLOR_RESET}")
                                _vprint(f"    {err[:500]}")
                            history.append(_history_entry(
                                iteration=iteration,
                                status="FAILURE",
                                proof_verified=False,
                                latency=-1,
                                error=f"Agent failed: {err}",
                                wall_s=time.perf_counter() - a_start,
                                agent_gen_wall_s=agent_gen_wall_s + (time.perf_counter() - a_start),
                            ))
                            _snapshot_history()
                            continue
                else:
                    body, proc = _run_agent()
                    log_trace(COMPONENT, "agent_body_preview", body[:200])
                    # Marked submit (even failed verify) still has metrics — do not drop them.
                    has_marked = bool(
                        agent_meta and agent_meta.get("submitted_metrics") is not None
                    )
                    if proc.returncode != 0 and not has_marked:
                        err = (proc.stderr or proc.stdout or "agent exited non-zero").strip()
                        _vprint(f" {COLOR_RED}FAILED{COLOR_RESET}")
                        _vprint(f"    {err[:500]}")
                        history.append(_history_entry(
                            iteration=iteration,
                            status="FAILURE",
                            proof_verified=False,
                            latency=-1,
                            error=f"Agent failed: {err}",
                            wall_s=time.perf_counter() - a_start,
                            agent_gen_wall_s=agent_gen_wall_s + (time.perf_counter() - a_start),
                        ))
                        _snapshot_history()
                        continue
                    write_ms = int((time.perf_counter() - a_start) * 1000)
                    if has_marked and proc.returncode != 0:
                        _vprint(f" {COLOR_GREEN}OK{COLOR_RESET} (marked run; verify failed)")
                    else:
                        _vprint(f" {COLOR_GREEN}OK{COLOR_RESET} ({write_ms // 1000} s)")
            except subprocess.TimeoutExpired:
                iter_agent_wall_s = time.perf_counter() - a_start
                agent_gen_wall_s += iter_agent_wall_s
                if demo_enabled():
                    demo_step_pass_fail("🦾", "Generating RunQuery", int(iter_agent_wall_s * 1000), False)
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
        use_marked_metrics = (
            not use_mock
            and agent_meta is not None
            and agent_meta.get("submitted_metrics") is not None
        )
        if use_marked_metrics:
            metrics = dict(agent_meta["submitted_metrics"])
            metrics.setdefault("status", "SUCCESS" if agent_meta.get("ok") else "FAILURE")
            metrics.setdefault("proof_verified", bool(agent_meta.get("ok")))
            metrics.setdefault("latency_us", agent_meta.get("latency_us", -1))
            log_info(
                COMPONENT,
                "harness_skip",
                "using marked submit metrics from agent",
                run_id=agent_meta.get("submitted_run_id"),
                latency_us=metrics.get("latency_us"),
            )
            _vprint("  - Using marked submit metrics (skipping duplicate harness)...", end="", flush=True)
            h_time = 0.0
            status = metrics["status"]
            proof_verified = metrics["proof_verified"]
            latency = metrics["latency_us"]
            _vprint(f" {COLOR_GREEN}OK{COLOR_RESET} (marked run)")
            if status == "SUCCESS" and proof_verified:
                if best_latency == -1 or latency < best_latency:
                    best_latency = latency
                    best_iteration = iteration
            history.append(_history_entry(
                iteration=iteration,
                status=status,
                proof_verified=proof_verified,
                latency=latency,
                error=metrics.get("compiler_error", ""),
                metrics=metrics,
                agent_meta=agent_meta,
                wall_s=iter_agent_wall_s or None,
                agent_gen_wall_s=agent_gen_wall_s,
                extra={"submitted_run_id": agent_meta.get("submitted_run_id")},
            ))
            _save_harness_metrics(iteration, metrics)
            _snapshot_history()
            continue

        log_debug(COMPONENT, "harness_start", f"custom sql query_id={query_id}", dataset_size=dataset_size)
        _vprint("  - Verifying and compiling Verus program...", end="", flush=True)
        h_start = time.perf_counter()
        harness_timeout = 90
        cfg_path = os.path.join(root_dir, "research_loop", "config.env")
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                for line in f:
                    if line.strip().startswith("COMPILE_TIMEOUT_SEC="):
                        harness_timeout = int(line.split("=", 1)[1].strip()) + 120
                        break

        def _run_verus_harness() -> dict:
            return invoke_verus_custom_pipeline(
                sql=sql_query,
                schema=resolved_schema,
                runquery_path=agent_body_path,
                dataset_size=dataset_size,
                workload_tables=workload_tables,
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

            if status == "SUCCESS" and proof_verified:
                if best_latency == -1 or latency < best_latency:
                    best_latency = latency
                    best_iteration = iteration

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
            ))
            _save_harness_metrics(iteration, metrics)
            _snapshot_history()

        except subprocess.TimeoutExpired:
            if demo_enabled():
                demo_step_pass_fail("✅", "Verifying against spec", int(harness_timeout * 1000), False)
            _vprint(f" {COLOR_RED}TIMEOUT{COLOR_RESET} after 90s")
            history.append(_history_entry(
                iteration=iteration,
                status="TIMEOUT",
                proof_verified=False,
                latency=-1,
                error="Harness timed out",
                wall_s=iter_agent_wall_s or None,
                agent_gen_wall_s=agent_gen_wall_s,
            ))
            _snapshot_history()

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
            _vprint(f"{COLOR_RED}No iteration succeeded in verification and compilation.{COLOR_RESET}")

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
