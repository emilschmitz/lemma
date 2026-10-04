"""SQL ``LIKE`` as a spec function over ``Seq<char>``.

DuckDB LIKE: ``%`` matches any run of characters (including none), ``_`` matches exactly
one character, every other character matches itself, and there is no escape character
unless ESCAPE is written (refused). Matching is case sensitive.
"""

from __future__ import annotations

SPEC_LIKE_FN = """pub open spec fn spec_like(s: Seq<char>, p: Seq<char>) -> bool
    decreases s.len() + p.len()
{
    if p.len() == 0 {
        s.len() == 0
    } else if p[0] == '%' {
        spec_like(s, p.skip(1)) || (s.len() > 0 && spec_like(s.skip(1), p))
    } else if s.len() == 0 {
        false
    } else if p[0] == '_' || p[0] == s[0] {
        spec_like(s.skip(1), p.skip(1))
    } else {
        false
    }
}"""
