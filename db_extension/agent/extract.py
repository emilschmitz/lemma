"""Extract and validate Verus run_query from marked agent workspace file."""
from __future__ import annotations

import re
from pathlib import Path

from research_loop.admit_agent_runquery import admit_or_extract_legacy
from research_loop.assemble_runquery import (
    AGENT_EDIT_START,
    AGENT_END,
    AGENT_START,
    build_runquery_agent_source,
    build_runquery_agent_source_legacy,
    extract_agent_body,
    extract_agent_body_checked,
    read_edit_fingerprint,
    validate_runquery_body as validate_rust_runquery_body,
    write_runquery_agent_file,
)


def _strip_comments_and_strings(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith("//", i):
            i = text.find("\n", i)
            if i == -1:
                break
            out.append("\n")
            i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end == -1:
                break
            out.append(" " * (end + 2 - i))
            i = end + 2
        elif text[i] in "\"'":
            q = text[i]
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == q:
                    j += 1
                    break
                j += 1
            out.append(" " * (j - i))
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def validate_runquery_body(body: str) -> list[str]:
    """Return validation errors; empty list means OK (Verus/Rust agent body)."""
    errors = validate_rust_runquery_body(body)
    if not body.strip():
        return errors
    clean = _strip_comments_and_strings(body)
    stripped = re.sub(r"[{}\s;]+", "", clean)
    if not stripped:
        errors.append("RunQuery body has no executable statements (comments only)")
    return errors


def admit_workspace_runquery(
    agent_text: str,
    *,
    spec_rs: str,
    agent_path: Path | None = None,
) -> str:
    """Admit agent file; return full ``pub exec fn run_query`` for assembly."""
    expected_fp = read_edit_fingerprint(agent_path) if agent_path is not None else None
    return admit_or_extract_legacy(
        agent_text,
        method_spec_rs=spec_rs,
        expected_fingerprint=expected_fp,
    )


def extract_marked_body(
    text: str,
    *,
    agent_path: Path | None = None,
    spec_rs: str | None = None,
) -> str:
    """Extract admitted run_query (AGENT_EDIT) or legacy body (AGENT_BODY)."""
    if AGENT_EDIT_START in text:
        if not spec_rs:
            raise ValueError("AGENT_EDIT admission requires spec_rs")
        return admit_workspace_runquery(text, spec_rs=spec_rs, agent_path=agent_path)

    if AGENT_START not in text or AGENT_END not in text:
        raise ValueError(
            "runquery_agent.rs missing AGENT_EDIT_START/END or AGENT_BODY_START/END markers; "
            "only marked agent files are accepted"
        )
    expected_fp = read_edit_fingerprint(agent_path) if agent_path is not None else None
    if expected_fp is not None:
        return extract_agent_body_checked(text, expected_fingerprint=expected_fp)
    body = extract_agent_body(text)
    errors = validate_runquery_body(body)
    if errors:
        raise ValueError("; ".join(errors))
    return body


def wrap_body_with_markers(body_inner: str, *, ret_type: str = "u64") -> str:
    """Produce Verus agent shell with AGENT_EDIT around full run_query."""
    return build_runquery_agent_source(ret_type=ret_type, body_inner=body_inner)


def wrap_body_with_markers_legacy(body_inner: str, *, ret_type: str = "u64") -> str:
    """Legacy AGENT_BODY shell for old tests."""
    return build_runquery_agent_source_legacy(ret_type=ret_type, body_inner=body_inner)


def write_marked_runquery(
    dest: Path,
    body_inner: str,
    *,
    ret_type: str = "u64",
    use_body_markers: bool = False,
) -> None:
    """Write shell + fingerprint sibling for ``runquery_agent.rs``."""
    write_runquery_agent_file(
        dest,
        ret_type=ret_type,
        body_inner=body_inner,
        use_body_markers=use_body_markers,
    )
