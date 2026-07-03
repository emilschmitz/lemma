import os
import re
import sys
import json
import subprocess
import time
from sql_transpiler import transpile_sql_to_dafny_columnar
from research_loop.ssb_workload import queries, schema
from research_loop.pipeline_log import log_debug, log_info, log_trace, log_warn
from research_loop.pipeline_demo import (
    demo_enabled,
    demo_iteration,
    demo_note,
    demo_step_pass_fail,
    demo_banner,
    demo_live_step,
    format_demo_seconds_from_us,
    verbose_enabled,
)

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


def match_query_index(sql_query: str) -> int:
    """
    Normalizes the input SQL query and matches it against the 15 standard queries.
    Returns 1-based query index, or 1 if no match.
    """
    def normalize(s: str) -> str:
        s = re.sub(r"\s+", " ", s).strip().lower()
        # Remove table aliases or quotes
        s = s.replace('"', '').replace("'", "")
        return s

    norm_input = normalize(sql_query)
    for idx, q_sql in enumerate(queries):
        if normalize(q_sql) == norm_input or normalize(q_sql) in norm_input or norm_input in normalize(q_sql):
            return idx + 1
            
    # Substring matching heuristics
    # Group By queries
    if "group by" in norm_input:
        if "d_year" in norm_input and "p_brand" in norm_input:
            if "mfgr#12" in norm_input or "p_category" in norm_input:
                return 4
            elif "mfgr#2221" in norm_input:
                if "asia" in norm_input:
                    return 5
                return 6
            return 4
        elif "c_nation" in norm_input and "s_nation" in norm_input:
            return 7
        elif "c_city" in norm_input and "s_city" in norm_input:
            if "united states" in norm_input:
                return 8
            elif "19971201" in norm_input or "19971231" in norm_input:
                return 10
            return 9
        elif "c_nation" in norm_input and "d_year" in norm_input:
            if "19970101" in norm_input:
                return 12
            return 11
        elif "s_nation" in norm_input and "p_category" in norm_input:
            return 13
        elif "lo_orderpriority" in norm_input:
            return 15

    # Scalar queries
    if "lo_quantity < 24" in norm_input or "lo_quantity < 25" in norm_input or "lo_quantity" in norm_input:
        if "19940101" in norm_input or "19941231" in norm_input:
            return 14
        if "19930101" in norm_input:
            return 1
        if "1994" in norm_input:
            return 2
        return 1
    if "d_weeknuminyear" in norm_input:
        return 3

    return 1

def write_mock_agent_body(query_id: int, workspace_path: str) -> None:
    """Write verified columnar RunQuery body for mock mode (from benchmark fixtures)."""
    from research_loop.benchmark_runqueries import RUNQUERIES

    if query_id not in RUNQUERIES:
        raise ValueError(f"No mock RunQuery fixture for query {query_id}")
    full = RUNQUERIES[query_id].strip()
    m = re.search(r"method\s+RunQuery[^{]+\{", full, re.DOTALL)
    if not m:
        raise ValueError(f"Could not parse RunQuery method for query {query_id}")
    start = m.end()
    depth, i = 1, start
    while i < len(full) and depth:
        if full[i] == "{":
            depth += 1
        elif full[i] == "}":
            depth -= 1
        i += 1
    body = full[start : i - 1].strip()
    body = re.sub(
        r"MulU64U32\(ep,\s*disc\)",
        "MulU64U32(ep as NativeU64, disc)",
        body,
    )
    os.makedirs(os.path.dirname(workspace_path), exist_ok=True)
    with open(workspace_path, "w") as f:
        f.write("{\n" + body + "\n}\n")


def generate_mock_dafny_code(dafny_spec: str) -> str:
    """
    Parses the transpiled Dafny spec and automatically generates a backward-loop
    RunQuery implementation that Z3 can verify statically and instantly.
    """
    # 1. Determine the return type from MethodSpec definition
    ret_type_match = re.search(r"function MethodSpec\(data: seq<Row>\):\s*([^\n{]+)", dafny_spec)
    if not ret_type_match:
        raise ValueError("Could not find MethodSpec return type in spec.")
    ret_type = ret_type_match.group(1).strip()

    is_map = "map" in ret_type

    # 2. Extract the body of MethodSpec
    body_match = re.search(r"function MethodSpec\(data: seq<Row>\):[^{]+\{([\s\S]*?)\n\}", dafny_spec)
    if not body_match:
        raise ValueError("Could not find MethodSpec body in spec.")
    spec_body = body_match.group(1)

    loop_body = ""

    if is_map:
        # Map-returning query (GROUP BY)
        # We need to extract:
        # - The condition (optional): `if (condition) then`
        # - The key expression: `var key := (expression);`
        # - The term expression: `tailMap[key := val + (expression)]`
        cond_match = re.search(r"if\s+\(([^)]+)\)\s+then", spec_body)
        key_match = re.search(r"var key\s*:=\s*([^;]+);", spec_body)
        term_match = re.search(r"tailMap\[key\s*:=\s*val\s*\+\s*([^\]]+)\]", spec_body)

        if not key_match or not term_match:
            raise ValueError("Could not parse GROUP BY expressions in MethodSpec.")

        key_expr = key_match.group(1).strip()
        term_expr = term_match.group(1).strip()

        if cond_match:
            condition = cond_match.group(1).strip()
            loop_body = f"""    if ({condition}) {{
      var key := {key_expr};
      res := res[key := (if key in res then res[key] else 0) + {term_expr}];
    }}"""
        else:
            loop_body = f"""    var key := {key_expr};
    res := res[key := (if key in res then res[key] else 0) + {term_expr}];"""

        code = f"""method RunQuery(data: seq<Row>) returns (res: {ret_type})
  ensures res == MethodSpec(data)
{{
  res := map[];
  var i := |data|;
  while i > 0
    invariant 0 <= i <= |data|
    invariant res == MethodSpec(data[i..])
  {{
    i := i - 1;
    var row := data[i];
{loop_body}
  }}
}}"""
    else:
        # Scalar-returning query (SUM/COUNT)
        # Check if we have `var term := if (condition) then term_expr else 0;`
        term_def_match = re.search(r"var term\s*:=\s*(if[\s\S]*?else\s*0);", spec_body)
        if term_def_match:
            term_expr = term_def_match.group(1).strip()
            loop_body = f"""    var term := {term_expr};
    res := term + res;"""
        else:
            # Maybe it is directly `some_expr + MethodSpec(tail)`
            direct_match = re.search(r"([\s\S]*?)\s*\+\s*MethodSpec\(tail\)", spec_body)
            if direct_match:
                term_expr = direct_match.group(1).strip()
                # Clean up row definition
                term_expr = re.sub(r"var row\s*:=\s*data\[0\];\s*var tail\s*:=\s*data\[1..\];", "", term_expr).strip()
                loop_body = f"    res := ({term_expr}) + res;"
            else:
                raise ValueError("Could not parse scalar aggregation in MethodSpec.")

        code = f"""method RunQuery(data: seq<Row>) returns (res: {ret_type})
  ensures res == MethodSpec(data)
{{
  res := 0;
  var i := |data|;
  while i > 0
    invariant 0 <= i <= |data|
    invariant res == MethodSpec(data[i..])
  {{
    i := i - 1;
    var row := data[i];
{loop_body}
  }}
}}"""

    # Fix formatting/brackets inside string insertion
    code = code.replace("{室内}", "{")
    return code

def run_optimization_loop(sql_query: str, dataset_size: int = 50000, max_iterations: int = 3, use_mock: bool = True, model: str = None) -> dict:
    """
    Runs the query optimization loop. Prints step-by-step colored output.
    """
    query_id = match_query_index(sql_query)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(current_dir)
    scratchpad_path = os.path.join(root_dir, "research_loop", "agent_scratchpad.md")

    if demo_enabled():
        demo_banner("Lemma Optimizer")
    else:
        _vprint(f"{COLOR_CYAN}--- Starting Lemma optimizer for Query {query_id} ---{COLOR_RESET}")
    
    best_latency = -1
    best_iteration = -1
    history = []

    log_info(COMPONENT, "loop_start", f"query_id={query_id}", dataset_size=dataset_size, mock=use_mock)

    for iteration in range(1, max_iterations + 1):
        log_info(COMPONENT, "iteration_start", f"iter={iteration}/{max_iterations}")
        if demo_enabled():
            demo_iteration(iteration, max_iterations)
        else:
            _vprint(f"\n{COLOR_BLUE}Iteration {iteration}:{COLOR_RESET}")

        # Step 1: Transpile SQL
        log_debug(COMPONENT, "transpile_start", "sql_transpiler")
        _vprint("  - Transpiling SQL query to formal Dafny spec...", end="", flush=True)
        try:
            if demo_enabled():
                with demo_live_step("🏗", "SQL → Dafny spec"):
                    dafny_spec = transpile_sql_to_dafny_columnar(sql_query, schema)
            else:
                t_start = time.perf_counter()
                dafny_spec = transpile_sql_to_dafny_columnar(sql_query, schema)
                ms = int((time.perf_counter() - t_start) * 1000)
                log_debug(COMPONENT, "transpile_done", f"{ms}ms", spec_bytes=len(dafny_spec))
                _vprint(f" {COLOR_GREEN}OK{COLOR_RESET} ({ms} ms)")
        except Exception as e:
            _vprint(f" {COLOR_RED}FAILED{COLOR_RESET}")
            _vprint(f"    Error: {e}")
            return {"status": "FAILED", "error": f"Transpilation failed: {e}"}
        if demo_enabled():
            log_debug(COMPONENT, "transpile_done", "ok", spec_bytes=len(dafny_spec))

        # Step 2: Write agent code
        _vprint("  - Writing optimized query in Dafny...", end="", flush=True)
        if use_mock:
            try:
                if demo_enabled():
                    with demo_live_step("🦾", "Generating RunQuery"):
                        agent_body_path = os.path.join(root_dir, "research_loop", "agent_workspace", "runquery_agent.dfy")
                        write_mock_agent_body(query_id, agent_body_path)
                else:
                    agent_body_path = os.path.join(root_dir, "research_loop", "agent_workspace", "runquery_agent.dfy")
                    write_mock_agent_body(query_id, agent_body_path)
                    _vprint(f" {COLOR_GREEN}OK{COLOR_RESET} (Mock Agent, columnar fixture Q{query_id})")
            except Exception as e:
                _vprint(f" {COLOR_RED}FAILED{COLOR_RESET} (Mock generation failed)")
                _vprint(f"    Error: {e}")
                return {"status": "FAILED", "error": f"Mock generation failed: {e}"}
        else:
            from pathlib import Path
            from research_loop.agent_sandbox import (
                build_docker_image,
                docker_image_built,
                load_agent_config,
                run_agent_iteration,
                use_docker,
            )

            cfg = load_agent_config()
            workspace = Path(root_dir) / "research_loop" / "agent_workspace"
            last_error = history[-1]["error"] if history else ""
            last_lat = history[-1]["latency_us"] if history and history[-1].get("proof_verified") else -1

            if use_docker(cfg):
                image = cfg.get("AGENT_IMAGE", "lemma-agent:latest")
                if not docker_image_built(image):
                    log_info(COMPONENT, "docker_build_start", f"building {image}")
                    _vprint(f"  - Building agent Docker image {image}...", end="", flush=True)
                    try:
                        build_docker_image(image)
                        _vprint(f" {COLOR_GREEN}OK{COLOR_RESET}")
                    except Exception as e:
                        _vprint(f" {COLOR_RED}FAILED{COLOR_RESET}")
                        return {"status": "FAILED", "error": f"Docker image build failed: {e}"}
                _vprint("  - Running agent in Docker sandbox...", end="", flush=True)
            else:
                log_info(COMPONENT, "agent_local", "subprocess AGENT_CMD", workspace=str(workspace))
                _vprint("  - Running agent (local subprocess)...", end="", flush=True)

            a_start = time.perf_counter()
            try:
                if demo_enabled():
                    with demo_live_step("🦾", "Generating RunQuery", pass_fail=True) as gen_step:
                        body, proc = run_agent_iteration(
                            query_id=query_id,
                            dafny_spec=dafny_spec,
                            iteration=iteration,
                            max_iterations=max_iterations,
                            last_error=last_error,
                            last_latency_us=last_lat,
                            workspace=workspace,
                            cfg=cfg,
                        )
                        log_trace(COMPONENT, "agent_body_preview", body[:200])
                        gen_step.set_passed(proc.returncode == 0)
                        if proc.returncode != 0:
                            err = (proc.stderr or proc.stdout or "agent exited non-zero").strip()
                            if not demo_enabled():
                                _vprint(f" {COLOR_RED}FAILED{COLOR_RESET}")
                                _vprint(f"    {err[:500]}")
                            history.append({
                                "iteration": iteration,
                                "status": "FAILURE",
                                "proof_verified": False,
                                "latency_us": -1,
                                "error": f"Agent failed: {err}",
                            })
                            continue
                else:
                    body, proc = run_agent_iteration(
                        query_id=query_id,
                        dafny_spec=dafny_spec,
                        iteration=iteration,
                        max_iterations=max_iterations,
                        last_error=last_error,
                        last_latency_us=last_lat,
                        workspace=workspace,
                        cfg=cfg,
                    )
                    log_trace(COMPONENT, "agent_body_preview", body[:200])
                    if proc.returncode != 0:
                        err = (proc.stderr or proc.stdout or "agent exited non-zero").strip()
                        _vprint(f" {COLOR_RED}FAILED{COLOR_RESET}")
                        _vprint(f"    {err[:500]}")
                        history.append({
                            "iteration": iteration,
                            "status": "FAILURE",
                            "proof_verified": False,
                            "latency_us": -1,
                            "error": f"Agent failed: {err}",
                        })
                        continue
                    write_ms = int((time.perf_counter() - a_start) * 1000)
                    _vprint(f" {COLOR_GREEN}OK{COLOR_RESET} ({write_ms // 1000} s)")
            except subprocess.TimeoutExpired:
                if demo_enabled():
                    demo_step_pass_fail("🦾", "Generating RunQuery", int((time.perf_counter() - a_start) * 1000), False)
                _vprint(f" {COLOR_RED}TIMEOUT{COLOR_RESET}")
                history.append({
                    "iteration": iteration,
                    "status": "TIMEOUT",
                    "proof_verified": False,
                    "latency_us": -1,
                    "error": "Agent timed out",
                })
                continue
            except Exception as e:
                _vprint(f" {COLOR_RED}FAILED{COLOR_RESET}")
                _vprint(f"    {e}")
                return {"status": "FAILED", "error": str(e)}

        # Step 3: Verify and compile and benchmark using harness.py
        log_debug(COMPONENT, "harness_start", f"q={query_id}", dataset_size=dataset_size)
        _vprint("  - Verifying and compiling Rust binaries...", end="", flush=True)
        h_start = time.perf_counter()
        harness_cmd = [
            "uv", "run", "python", "research_loop/harness.py",
            "-q", str(query_id),
            "--dataset-size", str(dataset_size)
        ]
        harness_timeout = 90
        cfg_path = os.path.join(root_dir, "research_loop", "config.env")
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                for line in f:
                    if line.strip().startswith("COMPILE_TIMEOUT_SEC="):
                        harness_timeout = int(line.split("=", 1)[1].strip()) + 120
                        break
        
        try:
            if demo_enabled():
                returncode, metrics = _run_harness_demo(
                    harness_cmd, cwd=root_dir, timeout=harness_timeout
                )
                if not metrics:
                    metrics = {
                        "status": "FAILURE",
                        "proof_verified": False,
                        "latency_us": -1,
                        "compiler_error": f"Harness crashed (exit {returncode})",
                    }
            else:
                harness_res = subprocess.run(
                    harness_cmd, cwd=root_dir, capture_output=True, text=True, timeout=harness_timeout
                )
                try:
                    metrics = json.loads(harness_res.stdout)
                except json.JSONDecodeError:
                    metrics = {
                        "status": "FAILURE",
                        "proof_verified": False,
                        "latency_us": -1,
                        "compiler_error": f"Harness crashed: {harness_res.stderr}"
                    }
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
                    if "compiler_error" in metrics and metrics["compiler_error"]:
                        _vprint(f"    Error: {metrics['compiler_error']}")
                else:
                    _vprint(f" {COLOR_RED}COMPILATION FAILED{COLOR_RESET}")
                    if "compiler_error" in metrics and metrics["compiler_error"]:
                        _vprint(f"    Error: {metrics['compiler_error']}")

            if status == "SUCCESS" and proof_verified:
                if best_latency == -1 or latency < best_latency:
                    best_latency = latency
                    best_iteration = iteration

            history.append({
                "iteration": iteration,
                "status": status,
                "proof_verified": proof_verified,
                "latency_us": latency,
                "error": metrics.get("compiler_error", "")
            })

        except subprocess.TimeoutExpired:
            if demo_enabled():
                demo_step_pass_fail("✅", "Verifying against spec", int(harness_timeout * 1000), False)
            _vprint(f" {COLOR_RED}TIMEOUT{COLOR_RESET} after 90s")
            history.append({
                "iteration": iteration,
                "status": "TIMEOUT",
                "proof_verified": False,
                "latency_us": -1,
                "error": "Harness timed out"
            })

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
        return {
            "status": "SUCCESS",
            "best_latency_us": best_latency,
            "best_iteration": best_iteration,
            "history": history,
        }
    return {
        "status": "FAILED",
        "best_latency_us": -1,
        "history": history,
    }
