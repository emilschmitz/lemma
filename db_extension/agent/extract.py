"""Extract and validate RunQuery body from marked agent workspace file."""
from __future__ import annotations


MARKER_START = "// <<<LEMMA_RUNQUERY_BODY>>>"
MARKER_END = "// <<<END_LEMMA_RUNQUERY_BODY>>>"

_FORBIDDEN_IN_BODY = (
    "method ",
    "function ",
    "lemma ",
    "predicate ",
    "class ",
    "module ",
    "{:verify false}",
    "axiom",
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
    """Return validation errors; empty list means OK."""
    errors: list[str] = []
    if not body.strip():
        errors.append("RunQuery body is empty")
        return errors
    clean = _strip_comments_and_strings(body)
    if not clean.strip():
        errors.append("RunQuery body has no executable statements (comments only)")
        return errors
    for kw in _FORBIDDEN_IN_BODY:
        if kw in clean:
            errors.append(f"forbidden construct in body: {kw.strip()!r}")
    depth = 0
    for ch in clean:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                errors.append("unbalanced braces in body")
                return errors
    if depth != 0:
        errors.append("unbalanced braces in body")
    return errors


def extract_runquery_body_text(raw: str) -> str:
    """Extract inner body; file may be `{ ... }` or raw statements."""
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


def _extract_between_markers(text: str) -> str | None:
    start = text.find(MARKER_START)
    end = text.find(MARKER_END)
    if start == -1 or end == -1 or end <= start:
        return None
    inner = text[start + len(MARKER_START) : end]
    # Strip optional wrapping braces inside markers.
    inner = inner.strip()
    if inner.startswith("{"):
        return extract_runquery_body_text(inner)
    return inner.strip()


def extract_marked_body(text: str) -> str:
    """Extract body between markers, else fall back to brace/raw extraction."""
    marked = _extract_between_markers(text)
    if marked is not None:
        body = marked
    else:
        try:
            from research_loop.dafny_legacy.assemble_runquery import extract_runquery_body_text as _fallback

            body = _fallback(text)
        except ImportError:
            body = extract_runquery_body_text(text)
    errors = validate_runquery_body(body)
    if errors:
        raise ValueError("; ".join(errors))
    return body


def wrap_body_with_markers(body_inner: str) -> str:
    """Produce template file content with marker comments."""
    inner = body_inner.strip()
    if not inner.startswith("{"):
        inner = "{\n" + inner + "\n}"
    header = """// Agent workspace — edit ONLY between the markers below.
// Do not add method, function, lemma, class, or module declarations.
// Do not change requires/ensures (the host injects ValidCols + ensures).
//
// Engine is schema-general: use cols.Get<COL> / EqAt<COL> from the transpiled spec only.
// Never assume a fixed dataset in patterns you invent for reusable bodies.
"""
    return f"{header}{MARKER_START}\n{inner}\n{MARKER_END}\n"
