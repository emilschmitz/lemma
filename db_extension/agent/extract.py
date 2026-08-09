"""Extract and validate Verus run_query body from marked agent workspace file."""
from __future__ import annotations

import re
from pathlib import Path

from research_loop.assemble_runquery import (
    AGENT_END,
    AGENT_START,
    build_runquery_agent_source,
    extract_agent_body,
    extract_agent_body_checked,
    read_shell_fingerprint,
    validate_runquery_body as validate_rust_runquery_body,
    write_runquery_agent_file,
)

# Legacy Dafny markers (fallback during transition)
MARKER_START = "// <<<LEMMA_RUNQUERY_BODY>>>"
MARKER_END = "// <<<END_LEMMA_RUNQUERY_BODY>>>"


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


def extract_runquery_body_text(raw: str) -> str:
    """Extract inner body from braced block."""
    text = raw.strip()
    if text.startswith("{"):
        depth, i = 0, 0
        start = None
        while i < len(text):
            if text[i] == "{":
                if depth == 0:
                    start = i + 1
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    return text[start:i].strip()
            i += 1
    return text


def _extract_between_markers(text: str, start_marker: str, end_marker: str) -> str | None:
    start = text.find(start_marker)
    end = text.find(end_marker)
    if start == -1 or end == -1 or end <= start:
        return None
    inner = text[start + len(start_marker) : end].strip()
    if inner.startswith("{"):
        return extract_runquery_body_text(inner)
    return inner


def extract_marked_body(text: str, *, agent_path: Path | None = None) -> str:
    """Extract body between AGENT_BODY or LEMMA markers; verify shell fingerprint."""
    expected_fp: str | None = None
    if agent_path is not None:
        expected_fp = read_shell_fingerprint(agent_path)
    if AGENT_START in text and AGENT_END in text:
        if expected_fp is not None:
            return extract_agent_body_checked(text, expected_fingerprint=expected_fp)
        body = extract_agent_body(text)
        errors = validate_runquery_body(body)
        if errors:
            raise ValueError("; ".join(errors))
        return body
    try:
        marked = _extract_between_markers(text, AGENT_START, AGENT_END)
        if marked is None:
            marked = _extract_between_markers(text, MARKER_START, MARKER_END)
        if marked is not None:
            body = marked
        else:
            body = extract_runquery_body_text(text)
    except Exception:
        body = extract_runquery_body_text(text)
    errors = validate_runquery_body(body)
    if errors:
        raise ValueError("; ".join(errors))
    return body


def wrap_body_with_markers(body_inner: str, *, ret_type: str = "u64") -> str:
    """Produce natural Verus agent shell with AGENT_BODY markers."""
    return build_runquery_agent_source(ret_type=ret_type, body_inner=body_inner)


def write_marked_runquery(
    dest: Path,
    body_inner: str,
    *,
    ret_type: str = "u64",
) -> None:
    """Write shell + fingerprint sibling for ``runquery_agent.rs``."""
    write_runquery_agent_file(dest, ret_type=ret_type, body_inner=body_inner)
