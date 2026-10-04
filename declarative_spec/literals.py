"""SQL string literals travel through the emitter as opaque tokens.

The emitter rewrites expression text with word-boundary regexes (column names, subquery
names). A raw literal in that text would be rewritten too (``WHERE s = 'a'`` with a column
named ``a``). ``string_token`` hides the literal's characters; ``resolve_string_tokens``
turns each token into a Rust string literal once, on the finished source.

DuckDB plain literals have no escape processing: the SQL text between the quotes (with
``''`` already folded to ``'``) is the value. The Rust literal below spells that value.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"__STR_([0-9a-f]*)__")


def string_token(value: str) -> str:
    return f"__STR_{value.encode('utf-8').hex()}__"


def rust_string_literal(value: str) -> str:
    out: list[str] = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{{{ord(ch):x}}}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def resolve_string_tokens(text: str) -> str:
    def literal(m: re.Match[str]) -> str:
        return rust_string_literal(bytes.fromhex(m.group(1)).decode("utf-8")) + "@"

    return _TOKEN.sub(literal, text)
