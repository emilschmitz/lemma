"""Trusted helper menu mining for agent run_query bodies (research harvest)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from research_loop.assemble_runquery import (
    AGENT_EDIT_END,
    AGENT_EDIT_START,
    _strip_rust_comments_and_strings,
)

_EXEC_FN_RE = re.compile(r"pub\s+exec\s+fn\s+(\w+)\s*\(", re.MULTILINE)
_AGG_STATE_RE = re.compile(r"pub\s+struct\s+(AggStepState_\w+)", re.MULTILINE)
_VIEW_FN_RE = re.compile(r"pub\s+open\s+spec\s+fn\s+(\w+_view)\s*\(", re.MULTILINE)


def list_trusted_menu(spec_rs: str) -> list[str]:
    """Names of Trusted exec helpers (+ view bridges + AggStepState types) in agent-visible spec.

    Includes:
    - ``pub exec fn NAME`` (agg_*, set_*, seq_*, hashmap bridges used as calls)
    - ``pub struct AggStepState_*`` (exec state types agents may name in annotations)
    - ``pub open spec fn *_view`` (Trusted exec↔spec view bridges; agents reference these
      in ``ensures`` / loop invariants even though they are open spec, not exec)
    """
    names: set[str] = set()
    for pat in (_EXEC_FN_RE, _AGG_STATE_RE, _VIEW_FN_RE):
        names.update(pat.findall(spec_rs))
    return sorted(names)


def scan_trusted_used(body_or_fn: str, menu: list[str]) -> list[str]:
    """Return sorted unique menu names referenced as identifiers in ``body_or_fn``."""
    if not menu:
        return []
    clean = _strip_rust_comments_and_strings(body_or_fn)
    used: list[str] = []
    for name in menu:
        if re.search(rf"\b{re.escape(name)}\b", clean):
            used.append(name)
    return sorted(set(used))


def _function_body_inner(fn_text: str) -> str:
    brace_start = fn_text.find("{")
    if brace_start == -1:
        return fn_text
    depth, i = 1, brace_start + 1
    while i < len(fn_text) and depth:
        if fn_text[i] == "{":
            depth += 1
        elif fn_text[i] == "}":
            depth -= 1
        i += 1
    return fn_text[brace_start + 1 : i - 1]


def agent_scan_text(source: str) -> str:
    """Best-effort region to scan for Trusted identifier use (run_query body preferred)."""
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    if AGENT_EDIT_START in normalized and AGENT_EDIT_END in normalized:
        from research_loop.admit_agent_runquery import (
            extract_agent_edit_region,
            parse_run_query_fn,
        )

        try:
            edit = extract_agent_edit_region(normalized)
            fn = parse_run_query_fn(edit)
            return _function_body_inner(fn)
        except ValueError:
            try:
                return extract_agent_edit_region(normalized)
            except ValueError:
                pass
    if "pub exec fn run_query" in normalized:
        from research_loop.admit_agent_runquery import parse_run_query_fn

        try:
            return _function_body_inner(parse_run_query_fn(normalized))
        except ValueError:
            pass
    return normalized


def trusted_usage_report(spec_rs: str, agent_source_or_fn: str) -> dict:
    """Menu / used / unused lists plus counts for harvest JSON."""
    menu = list_trusted_menu(spec_rs)
    scan_target = agent_scan_text(agent_source_or_fn)
    used = scan_trusted_used(scan_target, menu)
    unused = sorted(set(menu) - set(used))
    return {
        "trusted_menu": menu,
        "trusted_used": used,
        "trusted_unused": unused,
        "trusted_menu_count": len(menu),
        "trusted_used_count": len(used),
        "trusted_unused_count": len(unused),
    }


def write_trusted_usage_artifact(
    report: dict,
    *,
    run: object | None = None,
) -> Path | None:
    """Write ``logs/trusted_usage.json`` on run dir and/or ``LEMMA_RUN_DIR``."""
    written: Path | None = None
    if run is not None:
        from research_loop.run_artifacts import RunArtifacts

        if isinstance(run, RunArtifacts):
            written = run.write_trusted_usage(report)
    run_dir = os.environ.get("LEMMA_RUN_DIR", "").strip()
    if run_dir:
        logs = Path(run_dir) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        dest = logs / "trusted_usage.json"
        dest.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written = dest
    return written
