"""Classify optimizer / experiment log tails by product-path step (AGENTS.md)."""
from __future__ import annotations

import argparse
import json
import re
import sys
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
_E0308 = re.compile(r"error\[E0308\]|E0308:", re.I)
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


def _result(step: int, cls: str, *, detail: str = "") -> dict[str, Any]:
    if step < 1 or step > 7:
        raise ValueError(f"step must be 1-7, got {step}")
    if cls not in CLASSES:
        raise ValueError(f"unknown class: {cls}")
    out: dict[str, Any] = {"step": step, "class": cls}
    if detail:
        out["detail"] = detail
    return out


def classify_optimizer_log(text: str) -> dict[str, Any]:
    """Return ``{step, class[, detail]}`` for optimizer stdout/stderr (first match wins)."""
    if not text:
        return _result(5, "agent stupidity", detail="empty log")

    # Step 7 — harness verify/compile wall timeout (not agent docker).
    if _HARNESS_TIMEOUT.search(text):
        return _result(7, "failed to execute", detail="harness timeout")

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

    # Step 3 — agent docker timeout (before harness verify).
    if _AGENT_TIMEOUT.search(text) and _AGENT_DOCKER_CTX.search(text):
        return _result(3, "infra", detail="agent timeout")

    # Standalone TimeoutExpired / timed_out without harness "after Ns" — agent path.
    if re.search(r"TimeoutExpired", text) and not _HARNESS_TIMEOUT.search(text):
        return _result(3, "infra", detail="agent timeout")

    # Step 2 / 4 — host codegen (E0308 outside AGENT_EDIT).
    if _E0308.search(text) and not _AGENT_EDIT.search(text):
        if _SPEC_RS.search(text):
            return _result(2, "transpiler coverage", detail="spec.rs E0308")
        return _result(4, "assemble", detail="E0308")

    if _E0308.search(text) and _SPEC_RS.search(text):
        return _result(2, "transpiler coverage", detail="spec.rs E0308")

    # Step 3 — Verus errors confined to agent run_query on typed spec.
    if (
        _VERUS_ERR.search(text)
        and _AGENT_EDIT.search(text)
        and _RUN_QUERY.search(text)
        and not _SPEC_RS.search(text.split("AGENT_EDIT")[-1][:2000] if "AGENT_EDIT" in text else text)
    ):
        return _result(3, "agent stupidity", detail="run_query AGENT_EDIT")

    # Host markers in verify output → assemble or transpile, not agent.
    if _VERUS_ERR.search(text) or _VERIFY_FAIL.search(text):
        if _SPEC_RS.search(text) and not _AGENT_EDIT.search(text):
            return _result(2, "transpiler coverage", detail="spec verify")
        if _ASSEMBLE_HOST.search(text) and not _AGENT_EDIT.search(text):
            return _result(4, "assemble", detail="host scaffold")
        if _RUN_QUERY.search(text) and _AGENT_EDIT.search(text):
            return _result(3, "agent stupidity", detail="run_query verify")
        return _result(5, "agent stupidity", detail="verify")

    return _result(5, "agent stupidity", detail="default verify")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify optimizer log by product-path step.")
    parser.add_argument("--log", required=True, help="Path to log file (stdout+stderr tail)")
    args = parser.parse_args(argv)
    text = open(args.log, encoding="utf-8", errors="replace").read()
    print(json.dumps(classify_optimizer_log(text), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
