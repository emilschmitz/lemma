"""The two regions of an agent file that the host keeps: the `run_query` body and the helpers.

The host rebuilds the program from these two regions and the host spec. Everything else in the
agent file is discarded.
"""

from __future__ import annotations

EDIT_START = "// AGENT_EDIT_START"
EDIT_END = "// AGENT_EDIT_END"
HELPERS_START = "// AGENT_HELPERS_START"
HELPERS_END = "// AGENT_HELPERS_END"


def _normalize(source: str) -> str:
    return source.replace("\r\n", "\n").replace("\r", "\n")


def _region(source: str, start_mark: str, end_mark: str) -> str:
    text = _normalize(source)
    start = text.index(start_mark) + len(start_mark)
    end = text.index(end_mark, start)
    return text[start:end].strip()


def extract_agent_edit(source: str) -> str:
    if EDIT_START not in source or EDIT_END not in source:
        raise ValueError("missing AGENT_EDIT markers")
    try:
        return _region(source, EDIT_START, EDIT_END)
    except ValueError as exc:
        raise ValueError("AGENT_EDIT_END comes before AGENT_EDIT_START") from exc


def extract_agent_helpers(source: str) -> str:
    """The helper region, or empty when the file has no helper markers at all."""
    has_start, has_end = HELPERS_START in source, HELPERS_END in source
    if not has_start and not has_end:
        return ""
    if not (has_start and has_end):
        raise ValueError("only one of the AGENT_HELPERS markers is present")
    try:
        return _region(source, HELPERS_START, HELPERS_END)
    except ValueError as exc:
        raise ValueError("AGENT_HELPERS_END comes before AGENT_HELPERS_START") from exc
