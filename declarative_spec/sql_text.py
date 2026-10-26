"""Pure SQL-text helpers shared by the template lifter (lift.py) and the in-DuckDB executor cache in research_loop, which re-exports them.

No DuckDB or other engine dependency (tests/test_declarative_emit.py::test_package_has_no_forbidden_imports_or_names): the cache-key
normalization and the literal-token scanner, mirrored byte for byte by the extension (``lemma::NormalizeSql`` / ``lemma::LiteralAt``).
"""

from __future__ import annotations

_WS = " \t\n\r\f\v"


def normalize_sql(sql: str, keep_dollar: bool = False) -> str:
    """The cache-key form of ``sql`` (module docstring). Mirrored byte for byte by the extension's ``NormalizeSql``.

    ``keep_dollar``: a ``$`` is an ordinary character and the whitespace is collapsed as everywhere else (a query template's body,
    whose ``$name`` placeholders the template matcher compares; :func:`template_skeleton`)."""
    out: list[str] = []
    i, n = 0, len(sql)
    pending_space = False
    while i < n:
        c = sql[i]
        if c in _WS:
            pending_space = True
            i += 1
            continue
        if pending_space and out:
            out.append(" ")
        pending_space = False
        if c in "'\"":
            j = sql.find(c, i + 1)
            j = n if j == -1 else j + 1  # an unterminated quote runs to the end (DuckDB rejects it anyway)
            out.append(sql[i:j])
            i = j
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j == -1 else j + 1
            out.append(sql[i:j])
            i = j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append(sql[i:j])
            i = j
        elif c == "$" and not keep_dollar:
            return _strip_end(sql)
        else:
            out.append(c)
            i += 1
    return _strip_end("".join(out))


def _strip_end(text: str) -> str:
    text = text.strip(_WS)
    while text.endswith(";"):
        text = text[:-1].rstrip(_WS)
    return text


def _ident_char(c: str) -> bool:
    return c.isascii() and (c.isalnum() or c == "_") or not c.isascii()


def _string_end(s: str, i: int) -> int | None:
    j = i + 1
    while j < len(s):
        if s[j] == "'":
            if j + 1 < len(s) and s[j + 1] == "'":
                j += 2
                continue
            return j + 1
        j += 1
    return None


def literal_at(s: str, i: int) -> tuple[str, int] | None:
    """``(kind, end)`` of the literal token starting at ``i`` (``number`` ``[0-9]+(.[0-9]+)?``, ``string`` ``'...'``, ``date``
    ``DATE '...'`` with at most one space, any case), or None. It must start a token: the character before is not an identifier
    character, ``.``, ``$`` or a quote; a number is not followed by an identifier character or ``.``. Mirror of ``lemma::LiteralAt``."""
    n = len(s)
    if i >= n or (i > 0 and (_ident_char(s[i - 1]) or s[i - 1] in ".$'\"")):
        return None
    if "0" <= s[i] <= "9":
        j = i
        while j < n and "0" <= s[j] <= "9":
            j += 1
        if j + 1 < n and s[j] == "." and "0" <= s[j + 1] <= "9":
            j += 1
            while j < n and "0" <= s[j] <= "9":
                j += 1
        if j < n and (_ident_char(s[j]) or s[j] == "."):
            return None
        return "number", j
    if s[i] == "'":
        end = _string_end(s, i)
        return None if end is None else ("string", end)
    if s[i : i + 4].casefold() == "date":
        q = i + 4
        if q < n and s[q] == " ":
            q += 1
        if q < n and s[q] == "'":
            end = _string_end(s, q)
            if end is not None:
                return "date", end
    return None


def _opaque_end(s: str, i: int) -> int:
    c = s[i]
    if c in "'\"":
        j = s.find(c, i + 1)
        return len(s) if j == -1 else j + 1
    if s.startswith("--", i):
        j = s.find("\n", i)
        return len(s) if j == -1 else j + 1
    if s.startswith("/*", i):
        j = s.find("*/", i + 2)
        return len(s) if j == -1 else j + 2
    return i
