"""Rust identifier escaping for schema column names."""

from __future__ import annotations

# Rust 2018/2021 strict, reserved, and weak keywords (lowercase).
_RUST_KEYWORDS: frozenset[str] = frozenset(
    {
        "as",
        "async",
        "await",
        "break",
        "box",
        "const",
        "continue",
        "crate",
        "do",
        "dyn",
        "else",
        "enum",
        "extern",
        "false",
        "fn",
        "for",
        "if",
        "impl",
        "in",
        "let",
        "loop",
        "match",
        "mod",
        "move",
        "mut",
        "pub",
        "ref",
        "return",
        "self",
        "static",
        "struct",
        "super",
        "trait",
        "true",
        "type",
        "unsafe",
        "use",
        "where",
        "while",
        "abstract",
        "become",
        "final",
        "macro",
        "override",
        "priv",
        "typeof",
        "unsized",
        "virtual",
        "yield",
        "try",
        "union",
    }
)


def rust_ident(name: str) -> str:
    """Lowercase schema column name to a Rust field identifier (raw if keyword)."""
    ident = name.lower()
    if ident in _RUST_KEYWORDS:
        return f"r#{ident}"
    return ident
