"""Unit tests for overnight harvest failure classifier."""
from __future__ import annotations

from pathlib import Path

from research_loop.scripts.classify_product_failures import (
    classify_optimizer_log,
    classify_run_dir,
)

_HARNESS_90S = """
2026-09-07T02:33:45.211Z [INFO] agent_sandbox agent_docker_end: exit=0 timed_out=False
 OK (537 s)
  - Verifying and compiling Verus program... TIMEOUT after 90s

--- Optimization Finished ---
No iteration succeeded in verification and compilation.
CUSTOM_PIPELINE_FAILED: FAILED
"""

_BINDER_PIN = """
Executed in 3183362 us
Binder Error: Referenced column "missing_col" not found in FROM clause
Table 'num' does not have a column named 'missing_col'
proof=True SUCCESS
"""

_BROKEN_PIPE = """
[INFO] agent_sandbox agent_docker_start: docker run lemma-agent:cli
BrokenPipeError: [Errno 32] Broken pipe
agent_docker_end: exit=-1 timed_out=True
"""

_AGENT_INVARIANT = """
// AGENT_EDIT_START
pub exec fn run_query(num: &Cols_num, sub: &Cols_sub) -> (res: StringHashMap<u64>)
error: invariant not satisfied at end of loop body
verification failed: 1 errors
runquery_agent.rs:42:5
CUSTOM_PIPELINE_FAILED: FAILED
"""


def test_classify_harness_90s_timeout() -> None:
    out = classify_optimizer_log(_HARNESS_90S)
    assert out["step"] == 7
    assert out["class"] == "failed to execute"
    assert "harness" in out.get("detail", "")


def test_classify_binder_pin() -> None:
    out = classify_optimizer_log(_BINDER_PIN)
    assert out["step"] == 7
    assert out["class"] == "failed to execute"
    assert "pin" in out.get("detail", "")


def test_classify_broken_pipe_agent_infra() -> None:
    out = classify_optimizer_log(_BROKEN_PIPE)
    assert out["step"] == 3
    assert out["class"] == "infra"


def test_classify_resource_exhausted_agent_infra() -> None:
    text = """
agent_docker_end: exit=1 timed_out=False
RetriableError: [resource_exhausted] Error
agent_resource_exhausted: retry 1/8 iter=1 wait_s=30 (Cursor API quota; not consuming iteration)
"""
    out = classify_optimizer_log(text)
    assert out["step"] == 3
    assert out["class"] == "infra"
    assert out.get("detail") == "resource_exhausted"


def test_classify_docker_exit_minus9_timed_out_false_is_agent_timeout() -> None:
    text = """
CUSTOM_PIPELINE_FAILED [verify]: verus verify failed
error: invariant not satisfied
// AGENT_EDIT_START
agent_docker_end: exit=-9 timed_out=False
"""
    out = classify_optimizer_log(text)
    assert out["step"] == 3
    assert out["class"] == "infra"
    assert out.get("detail") == "agent timeout"


def test_classify_agent_invariant_fail() -> None:
    out = classify_optimizer_log(_AGENT_INVARIANT)
    assert out["step"] == 3
    assert out["class"] == "agent stupidity"


_DIRTY_TREE = """
LEMMA_EXPERIMENT=1 requires a clean git working tree.
Commit or stash changes, or set LEMMA_EXPERIMENT_ALLOW_DIRTY=1 to override.
Dirty files (2):
 M research_loop/foo.py
?? scratch.txt
"""

_IN_INNER_GB = """
Transpilation failed: IN inner GROUP BY is not supported in MethodSpec semi-join fold
CUSTOM_PIPELINE_FAILED: FAILED
"""

_COUNT_ADDEND_ASSERT = """
Traceback (most recent call last):
  File "multi_agg_step_bridge.py", line 2565, in multi_agg_step_trusted_rs
    count_addend = _resolve_count_addend(...)
AssertionError: count_addend unresolved for slot 3
"""

_E0252_HASHSET = """
error[E0252]: the name `HashSetWithView` is defined multiple times
    --> custom_query.rs:2839:5
2146 | use vstd::hash_set::HashSetWithView;
2839 | use vstd::hash_set::HashSetWithView;
"""

_UNBALANCED_BRACES = """
ValueError: unbalanced braces in run_query
  at admit_or_extract_legacy / agent_file_to_run_query_body
"""

_OFFICIAL_MEASURE = """
LEMMA_METRICS_JSON: {"status": "SUCCESS", "proof_verified": true,
  "official_measure_error": "official full-table measure timed out after 300s"}
lemma_ok=false
"""


def test_classify_dirty_experiment_tree() -> None:
    out = classify_optimizer_log(_DIRTY_TREE)
    assert out["step"] == 1
    assert out["class"] == "infra"
    assert "dirty" in out.get("detail", "")


def test_classify_in_inner_groupby_transpile() -> None:
    out = classify_optimizer_log(_IN_INNER_GB)
    assert out["step"] == 2
    assert out["class"] == "transpiler coverage"
    assert "IN" in out.get("detail", "") or "transpile" in out.get("detail", "")


def test_classify_count_addend_assertion_assemble() -> None:
    out = classify_optimizer_log(_COUNT_ADDEND_ASSERT)
    assert out["step"] == 4
    assert out["class"] == "assemble"
    assert "count_addend" in out.get("detail", "")


def test_classify_e0252_hashset_assemble() -> None:
    out = classify_optimizer_log(_E0252_HASHSET)
    assert out["step"] == 4
    assert out["class"] == "assemble"
    detail = out.get("detail", "")
    assert "E0252" in detail or "HashSet" in detail


def test_classify_unbalanced_run_query_braces() -> None:
    out = classify_optimizer_log(_UNBALANCED_BRACES)
    assert out["step"] == 4
    assert out["class"] == "assemble"
    assert "brace" in out.get("detail", "")


def test_classify_no_marked_submit_is_agent_prove_miss() -> None:
    out = classify_optimizer_log(
        "FAILED\n    no marked submit\n"
        'LEMMA_METRICS_JSON: {"compiler_error": "no marked submit"}\n'
    )
    assert out["step"] == 3
    assert out["class"] == "agent stupidity"
    assert "no marked submit" in out.get("detail", "")


def test_classify_empty_log_is_not_agent() -> None:
    out = classify_optimizer_log("")
    assert out["class"] == "infra"
    assert "unclassified" in out.get("detail", "")


def test_classify_e0425_tn_custom_query_is_assemble() -> None:
    text = """
error[E0425]: cannot find value `t5` in this scope
    --> custom_query.rs:412:17
LEFTOVER_VERIFY_BEGIN
error[E0425]: cannot find value `t1` in this scope
LEFTOVER_VERIFY_END
"""
    out = classify_optimizer_log(text)
    assert out["step"] == 4
    assert out["class"] == "assemble"
    assert "E0425" in out.get("detail", "")


def test_classify_e0425_without_agent_edit_is_assemble() -> None:
    text = "error[E0425]: cannot find value `t4` in this scope\n"
    out = classify_optimizer_log(text)
    assert out["step"] == 4
    assert out["class"] == "assemble"


def test_classify_e0308_custom_query_not_agent_edit() -> None:
    text = """
error[E0308]: mismatched types
    --> custom_query.rs:88:9
    expected `u64`, found `int`
"""
    out = classify_optimizer_log(text)
    assert out["step"] == 4
    assert out["class"] == "assemble"
    assert "E0308" in out.get("detail", "")


def test_classify_e0308_spec_rs_is_transpile() -> None:
    text = """
error[E0308]: mismatched types
    --> spec.rs:12:5
    expected u64 found int
"""
    out = classify_optimizer_log(text)
    assert out["step"] == 2
    assert out["class"] == "transpiler coverage"


def test_classify_no_marked_plus_e0425_prefers_assemble() -> None:
    text = """
FAILED
    no marked submit
LEFTOVER_VERIFY_BEGIN
error[E0425]: cannot find value `t2` in this scope
    --> custom_query.rs:200:9
LEFTOVER_VERIFY_END
"""
    out = classify_optimizer_log(text)
    assert out["step"] == 4
    assert out["class"] == "assemble"


def test_classify_leftover_missing_is_agent_prove_miss() -> None:
    text = """
FAILED
    no marked submit
    LEFTOVER_VERIFY_MISSING (no leftover verify_error_custom.log)
LEMMA_METRICS_JSON: {"compiler_error": "no marked submit"}
"""
    out = classify_optimizer_log(text)
    assert out["step"] == 3
    assert out["class"] == "agent stupidity"
    assert "leftover missing" in out.get("detail", "")


def test_classify_no_marked_plus_agent_edit_leftover_is_agent() -> None:
    text = """
FAILED
    no marked submit
LEFTOVER_VERIFY_BEGIN
// AGENT_EDIT_START
pub exec fn run_query(cols: &Cols) -> (res: u64)
error: invariant not satisfied at end of loop body
verification failed: 1 errors
LEFTOVER_VERIFY_END
"""
    out = classify_optimizer_log(text)
    assert out["step"] == 3
    assert out["class"] == "agent stupidity"


def test_classify_default_unclassified_not_agent() -> None:
    out = classify_optimizer_log("something went sideways with no known tokens")
    assert out["class"] == "infra"
    assert "unclassified" in out.get("detail", "")


def test_classify_entrypoint_permission_denied_is_infra() -> None:
    text = (
        "exec: \"/app/entrypoint.sh\": permission denied\n"
        "agent_sandbox agent_docker_end: exit=126 timed_out=False\n"
    )
    out = classify_optimizer_log(text)
    assert out["step"] == 3
    assert out["class"] == "infra"
    assert "permission denied" in out.get("detail", "")


def test_classify_official_measure_timeout() -> None:
    out = classify_optimizer_log(_OFFICIAL_MEASURE)
    assert out["step"] == 7
    assert out["class"] == "failed to execute"
    assert "official measure" in out.get("detail", "")


def test_classify_run_dir_cli_never_started(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    ws = run_dir / "workspace"
    ws.mkdir(parents=True)
    (ws / "mcp_results" / "runs").mkdir(parents=True)
    (ws / "logs").mkdir()
    (ws / "runquery_agent.rs").write_text(
        "// AGENT_EDIT_START\n"
        "pub exec fn run_query(cols: &Cols) -> (res: Vec<u64>) {\n"
        "    // TODO: implement hot path to match method_spec (see context/ro/spec.rs)\n"
        "    Vec::new()\n"
        "}\n"
        "// AGENT_EDIT_END\n",
        encoding="utf-8",
    )
    out = classify_run_dir(run_dir)
    assert out is not None
    assert out["step"] == 3
    assert out["class"] == "infra"
    assert out["detail"] == "cli never started"


def test_classify_run_dir_with_mcp_submit_not_cli_never_started(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    ws = run_dir / "workspace"
    runs = ws / "mcp_results" / "runs"
    runs.mkdir(parents=True)
    (runs / "001.json").write_text("{}", encoding="utf-8")
    (ws / "runquery_agent.rs").write_text(
        "// AGENT_EDIT_START\n"
        "pub exec fn run_query(cols: &Cols) -> (res: u64) {\n"
        "    // TODO: implement hot path\n"
        "    Vec::new()\n"
        "}\n"
        "// AGENT_EDIT_END\n",
        encoding="utf-8",
    )
    assert classify_run_dir(run_dir) is None


def test_classify_run_dir_stub_with_agent_stream_not_cli_never_started(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    ws = run_dir / "workspace"
    (ws / "mcp_results" / "runs").mkdir(parents=True)
    (ws / "logs").mkdir()
    (ws / "logs" / "agent_stream.jsonl").write_text('{"type":"init"}\n', encoding="utf-8")
    (ws / "runquery_agent.rs").write_text(
        "// AGENT_EDIT_START\n"
        "pub exec fn run_query(cols: &Cols) -> (res: Vec<u64>) {\n"
        "    // TODO: implement hot path to match method_spec\n"
        "    Vec::new()\n"
        "}\n"
        "// AGENT_EDIT_END\n",
        encoding="utf-8",
    )
    assert classify_run_dir(run_dir) is None


def test_classify_official_full_table_600s_is_execute_not_fake_time() -> None:
    text = """
LEMMA_METRICS_JSON: {"status": "SUCCESS", "proof_verified": true,
  "latency_us": -1, "iterate_latency_us": 88,
  "official_measure_error": "official full-table measure timed out after 600s"}
lemma_ok=false
"""
    out = classify_optimizer_log(text)
    assert out["step"] == 7
    assert out["class"] == "failed to execute"
    assert "official measure" in out.get("detail", "")
