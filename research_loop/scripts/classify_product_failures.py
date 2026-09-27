"""Classify optimizer / experiment log tails by product-path step (AGENTS.md).

Loud remaining classes (not host leftover bugs):

- step 7 execute: official full-table 600s → proved + lat=-1 / lemma_ok=false.
  Iterate µs is not a fake official time.
- step 3 agent: no marked submit is a prove miss, unless leftover shows host
  E0425 tN / E0308 case_when (those stay assemble/transpile).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

STEP_NAMES = (
    "sql",
    "transpile",
    "agent",
    "assemble",
    "verify",
    "compile",
    "execute",
)

CLASSES = (
    "transpiler coverage",
    "assemble",
    "agent stupidity",
    "failed to execute",
    "infra",
)

_HARNESS_TIMEOUT = re.compile(r"TIMEOUT\s+after\s+\d+s", re.I)
_BINDER_PIN = re.compile(
    r"Binder Error|does not have a column",
    re.I,
)
_BROKEN_PIPE = re.compile(r"BrokenPipe|EPIPE", re.I)
_AGENT_TIMEOUT = re.compile(
    r"timed_out=True|TimeoutExpired|AGENT_TIMEOUT",
    re.I,
)
_AGENT_DOCKER_CTX = re.compile(
    r"agent_docker|run_agent_docker|docker_agent",
    re.I,
)
_AGENT_DOCKER_SIGKILL = re.compile(
    r"agent_docker_end:\s*exit=-9\b|agent_docker_end:\s*exit=137\b",
)
_RESOURCE_EXHAUSTED = re.compile(
    r"agent_resource_exhausted|RetriableError:\s*\[resource_exhausted\]|\[resource_exhausted\]",
    re.I,
)
_E0308 = re.compile(r"error\[E0308\]|E0308:", re.I)
_E0425 = re.compile(r"error\[E0425\]|cannot find value `t\d+`", re.I)
_NO_MARKED = re.compile(r"no marked submit", re.I)
_LEFTOVER_MISSING = re.compile(r"LEFTOVER_VERIFY_MISSING", re.I)
_VERUS_ERR = re.compile(
    r"error:\s|verification failed|Verus errors",
    re.I,
)
_AGENT_EDIT = re.compile(r"AGENT_EDIT|runquery_agent\.rs", re.I)
_RUN_QUERY = re.compile(r"run_query", re.I)
_SPEC_RS = re.compile(r"spec\.rs|context/ro/spec", re.I)
_ASSEMBLE_HOST = re.compile(
    r"custom_query\.rs|loaders/|assemble_verified|generated.*loader",
    re.I,
)
_VERIFY_FAIL = re.compile(
    r"verify_fails|verification and compilation|CUSTOM_PIPELINE_FAILED|No iteration succeeded",
    re.I,
)
_VERUS_RESULT_ERRORS = re.compile(
    r"verification results::\s*\d+\s+verified,\s*([1-9]\d*)\s+errors",
    re.I,
)
_RUN_QUERY_LINE = re.compile(r"LEMMA_TRACE_RUN_QUERY_LINE=(\d+)")
_ERROR_AT_LINE = re.compile(
    r"^error(?:\[[^\]]+\])?:[^\n]*\n(?:[^\n]*\n){0,8}?[^\n]*custom_query\.rs:(\d+):",
    re.MULTILINE,
)
_DIRTY = re.compile(
    r"Dirty files|LEMMA_EXPERIMENT=1 requires a clean git working tree",
    re.I,
)
_IN_INNER_GB = re.compile(
    r"IN inner GROUP BY|Transpilation failed",
    re.I,
)
_COUNT_ADDEND = re.compile(r"count_addend", re.I)
_E0252 = re.compile(r"error\[E0252\]", re.I)
_HASHSET_VIEW = re.compile(r"HashSetWithView", re.I)
_UNBALANCED_RUN_QUERY = re.compile(
    r"ValueError: unbalanced braces in run_query",
    re.I,
)
_OFFICIAL_MEASURE = re.compile(
    r"official_measure_error|official full-table measure timed out",
    re.I,
)


_STUB_TODO = re.compile(r"TODO:\s*implement hot path", re.I)
_STUB_RETURN = re.compile(
    r"(Vec::new\(\)|HashMapWithView::new\(\)|StringHashMap::new\(\)|HashMap::new\(\))",
)


def _is_unedited_agent_stub(text: str) -> bool:
    """True when AGENT_EDIT block still contains the host default TODO stub."""
    if "AGENT_EDIT_START" not in text:
        return False
    start = text.find("AGENT_EDIT_START")
    end = text.find("AGENT_EDIT_END", start)
    if end < 0:
        return False
    block = text[start:end]
    return bool(_STUB_TODO.search(block)) and bool(_STUB_RETURN.search(block))


def classify_run_dir(run_dir: Path) -> dict[str, Any] | None:
    """Classify infra when agent Docker timed out but CLI never started.

    Returns ``{step, class, detail}`` when the run dir shows no MCP submit and an
    unedited host stub; otherwise ``None`` (caller should use log classification).
    """
    ws = run_dir / "workspace" if (run_dir / "workspace").is_dir() else run_dir
    mcp = ws / "mcp_results"
    runs_dir = mcp / "runs"
    has_run_json = runs_dir.is_dir() and any(runs_dir.glob("*.json"))
    has_submitted = (mcp / "submitted.json").is_file()
    if has_run_json or has_submitted:
        return None

    agent_path = ws / "runquery_agent.rs"
    if not agent_path.is_file():
        return None
    agent_text = agent_path.read_text(encoding="utf-8", errors="replace")
    if not _is_unedited_agent_stub(agent_text):
        return None

    stream_path = ws / "logs" / "agent_stream.jsonl"
    stream_empty = (
        not stream_path.is_file()
        or stream_path.stat().st_size == 0
        or not stream_path.read_text(encoding="utf-8", errors="replace").strip()
    )
    if not stream_empty:
        return None

    return _result(3, "infra", detail="cli never started")


def _result(step: int, cls: str, *, detail: str = "") -> dict[str, Any]:
    if step < 1 or step > 7:
        raise ValueError(f"step must be 1-7, got {step}")
    if cls not in CLASSES:
        raise ValueError(f"unknown class: {cls}")
    out: dict[str, Any] = {"step": step, "class": cls}
    if detail:
        out["detail"] = detail
    return out


def _has_verify_diagnostic(text: str) -> bool:
    return bool(
        _VERUS_ERR.search(text)
        or _E0308.search(text)
        or _E0425.search(text)
        or _VERUS_RESULT_ERRORS.search(text)
    )


def _classify_errors_against_run_query(text: str) -> dict[str, Any] | None:
    """Host lemma lines sit above ``run_query``. Agent lines sit at or below it.

    The marker is injected from the harvested ``custom_query.rs`` when the
    driver log is classified. Without it, return None and use the other rules.
    """
    marker = _RUN_QUERY_LINE.search(text)
    if marker is None:
        return None
    run_query_line = int(marker.group(1))
    error_lines = [int(n) for n in _ERROR_AT_LINE.findall(text)]
    if not error_lines:
        return None
    if any(line < run_query_line for line in error_lines):
        return _result(4, "assemble", detail="host lemma before run_query")
    return _result(3, "agent stupidity", detail="run_query AGENT_EDIT")


def classify_optimizer_log(text: str) -> dict[str, Any]:
    """Return ``{step, class[, detail]}`` for optimizer stdout/stderr (first match wins)."""
    if not text:
        return _result(5, "infra", detail="unclassified_empty_log_open_traces")

    # Step 3 infra — bind-mounted entrypoint not executable (docker exit 126).
    if "entrypoint.sh" in text and "permission denied" in text.lower():
        return _result(3, "infra", detail="entrypoint permission denied")

    # Step 7 — harness verify/compile wall timeout (not agent docker).
    if _HARNESS_TIMEOUT.search(text):
        return _result(7, "failed to execute", detail="harness timeout")

    # Step 7 — official full-table measure timeout (no harness TIMEOUT after Ns).
    if _OFFICIAL_MEASURE.search(text):
        return _result(7, "failed to execute", detail="official measure")

    # Step 1 — experiment git cleanliness / preflight dirty tree.
    if _DIRTY.search(text):
        return _result(1, "infra", detail="dirty")

    # Step 2 — transpiler loud-fail (IN inner GROUP BY, etc.).
    if _IN_INNER_GB.search(text):
        detail = "IN inner GROUP BY" if "IN inner GROUP BY" in text else "transpile"
        return _result(2, "transpiler coverage", detail=detail)

    # Step 4 — host fold emit AssertionError on count_addend resolution.
    if "AssertionError" in text and _COUNT_ADDEND.search(text):
        return _result(4, "assemble", detail="count_addend")

    # Step 4 — duplicate HashSetWithView import at assemble.
    if _E0252.search(text) and _HASHSET_VIEW.search(text):
        return _result(4, "assemble", detail="E0252 HashSet")

    # Step 4 — agent run_query brace extraction during assemble.
    if _UNBALANCED_RUN_QUERY.search(text):
        return _result(4, "assemble", detail="brace")

    # Step 7 — DuckDB pin after proof.
    if _BINDER_PIN.search(text) and (
        "Executed in" in text
        or "proof" in text.lower()
        or "SUCCESS" in text
        or "pin" in text.lower()
    ):
        return _result(7, "failed to execute", detail="pin")

    # Step 3 — MCP / sandbox infra (BrokenPipe during agent docker).
    if _BROKEN_PIPE.search(text) and (
        _AGENT_DOCKER_CTX.search(text) or _AGENT_TIMEOUT.search(text)
    ):
        return _result(3, "infra", detail="sandbox/MCP")

    # Step 3 — Cursor API quota (RetriableError resource_exhausted), not agent timeout.
    if _RESOURCE_EXHAUSTED.search(text):
        return _result(3, "infra", detail="resource_exhausted")

    # A Verus/rustc diagnostic is the failure. Docker exit -9 after that is the
    # session wall, not a timeout that hid the diagnostic (r31 driver logs).
    located = _classify_errors_against_run_query(text)
    if located is not None:
        return located
    if not _has_verify_diagnostic(text):
        # Step 3 — agent docker timeout (before harness verify).
        if _AGENT_TIMEOUT.search(text) and _AGENT_DOCKER_CTX.search(text):
            return _result(3, "infra", detail="agent timeout")

        # GNU timeout --signal=KILL → exit -9/137 even when timed_out=False.
        if _AGENT_DOCKER_SIGKILL.search(text):
            return _result(3, "infra", detail="agent timeout")

        # Standalone TimeoutExpired / timed_out without harness "after Ns" — agent path.
        if re.search(r"TimeoutExpired", text) and not _HARNESS_TIMEOUT.search(text):
            return _result(3, "infra", detail="agent timeout")

    # Step 4 — leftover rustc E0425 host temps (tN) in custom_query.rs, not AGENT_EDIT.
    if _E0425.search(text) and _ASSEMBLE_HOST.search(text) and not _AGENT_EDIT.search(text):
        return _result(4, "assemble", detail="E0425 host tN")

    if _E0425.search(text) and not _AGENT_EDIT.search(text):
        return _result(4, "assemble", detail="E0425")

    # Step 2 / 4 — host codegen (E0308 outside AGENT_EDIT).
    if _E0308.search(text) and not _AGENT_EDIT.search(text):
        if _SPEC_RS.search(text):
            return _result(2, "transpiler coverage", detail="spec.rs E0308")
        return _result(4, "assemble", detail="E0308")

    if _E0308.search(text) and _SPEC_RS.search(text):
        return _result(2, "transpiler coverage", detail="spec.rs E0308")

    # Step 3 — Verus errors confined to agent run_query on typed spec.
    if _VERUS_ERR.search(text) and _AGENT_EDIT.search(text):
        edit_tail = text.split("AGENT_EDIT")[-1][:2000] if "AGENT_EDIT" in text else text
        if not _SPEC_RS.search(edit_tail):
            return _result(3, "agent stupidity", detail="run_query AGENT_EDIT")

    # Host markers in verify output → assemble or transpile, not agent.
    if _VERUS_ERR.search(text) or _VERIFY_FAIL.search(text):
        if _SPEC_RS.search(text) and not _AGENT_EDIT.search(text):
            return _result(2, "transpiler coverage", detail="spec verify")
        if _ASSEMBLE_HOST.search(text) and not _AGENT_EDIT.search(text):
            return _result(4, "assemble", detail="host scaffold")
        if _RUN_QUERY.search(text) and _AGENT_EDIT.search(text):
            return _result(3, "agent stupidity", detail="run_query verify")
        return _result(5, "infra", detail="unclassified_verify_open_traces")

    # Step 3 — agent never marked a verified submit. That is a prove miss.
    # Host leftover tN (E0425) / case_when E0308 already matched above as assemble/transpile.
    if _NO_MARKED.search(text):
        if _LEFTOVER_MISSING.search(text):
            return _result(3, "agent stupidity", detail="no marked submit (leftover missing)")
        return _result(3, "agent stupidity", detail="no marked submit")

    return _result(5, "infra", detail="unclassified_open_traces")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify optimizer log by product-path step.")
    parser.add_argument("--log", required=True, help="Path to log file (stdout+stderr tail)")
    args = parser.parse_args(argv)
    text = open(args.log, encoding="utf-8", errors="replace").read()
    print(json.dumps(classify_optimizer_log(text), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
