"""Assemble trusted RunQuery from agent body-only file."""
from __future__ import annotations

import re

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


def runquery_shell_from_spec(dafny_spec: str) -> str:
    """Build trusted RunQuery header + opening brace from transpiled spec."""
    col_match = re.search(
        r"function\s+(?:\{[^}]*\}\s+)?MethodSpec\(cols:\s*Cols\)\s*:\s*([^\n{]+)",
        dafny_spec,
    )
    if col_match:
        ret_type = col_match.group(1).strip()
        return (
            f"method RunQuery(cols: Cols) returns (res: {ret_type})\n"
            f"  requires ValidCols(cols)\n"
            f"  ensures res == MethodSpec(cols)\n"
            "{\n"
        )
    ret_match = re.search(
        r"function\s+(?:\{[^}]*\}\s+)?MethodSpec\(data:\s*seq<Row>\)\s*:\s*([^\n{]+)",
        dafny_spec,
    )
    if not ret_match:
        raise ValueError("Could not find MethodSpec(cols: Cols) or MethodSpec(data: seq<Row>) in spec")
    ret_type = ret_match.group(1).strip()
    return (
        f"method RunQuery(data: seq<Row>) returns (res: {ret_type})\n"
        f"  ensures res == MethodSpec(data)\n"
        "{\n"
    )


def assemble_runquery_from_body(dafny_spec: str, body_raw: str) -> str:
    """Splice validated agent body into trusted RunQuery shell."""
    body = extract_runquery_body_text(body_raw)
    errors = validate_runquery_body(body)
    if errors:
        raise ValueError("; ".join(errors))
    shell = runquery_shell_from_spec(dafny_spec)
    indented = body
    if indented and not indented.endswith("\n"):
        indented += "\n"
    return shell + indented + "}\n"
