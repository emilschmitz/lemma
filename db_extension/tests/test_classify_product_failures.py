"""Unit tests for overnight harvest failure classifier."""
from __future__ import annotations

from research_loop.scripts.classify_product_failures import classify_optimizer_log

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


def test_classify_agent_invariant_fail() -> None:
    out = classify_optimizer_log(_AGENT_INVARIANT)
    assert out["step"] == 3
    assert out["class"] == "agent stupidity"
