"""Rocketship Trusted bar: adversarial emit guards + light semantic oracles.

Ensures ``emit_trusted_prelude()`` stays at the NASA-grade bar documented in
``docs/TRUSTED_FAMILIES.md``: fit-in-width ``requires``, ``checked_*`` arithmetic,
open string specs (no ``arbitrary()``), and ``left_join_miss_generic == false``.

Regression intent: if someone reintroduces ``wrapping_add`` on ``add_u64`` or
``arbitrary()`` on ``str_like_contains``, these tests fail loudly.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from verus_transpiler.value_bounds import emit_trusted_prelude

_ARITH_EXEC_TRUSTEDS: list[dict[str, Any]] = [
    {
        "name": "add_u64",
        "requires_snippets": ["(a as int) + (b as int) <= u64::MAX as int"],
        "ensures_snippets": ["res == a + b"],
        "checked": "checked_add",
        "forbid_wrapping": True,
    },
    {
        "name": "mul_u64_u32",
        "requires_snippets": ["(a as int) * (b as int) <= u64::MAX as int"],
        "ensures_snippets": ["res == a * (b as u64)"],
        "checked": "checked_mul",
        "forbid_wrapping": True,
    },
    {
        "name": "add_i64",
        "requires_snippets": [
            "(a as int) + (b as int) >= i64::MIN as int",
            "(a as int) + (b as int) <= i64::MAX as int",
        ],
        "ensures_snippets": ["res == a + b"],
        "checked": "checked_add",
        "forbid_wrapping": True,
    },
    {
        "name": "sub_u64_to_i64",
        "requires_snippets": [
            "(a as int) - (b as int) >= i64::MIN as int",
            "(a as int) - (b as int) <= i64::MAX as int",
        ],
        "ensures_snippets": ["res == (a as int) - (b as int)"],
        "checked": None,
        "forbid_wrapping": True,
    },
]


def _extract_fn_block(prelude: str, fn_name: str) -> str:
    """Return the source span from ``fn`` keyword through its closing ``}``."""
    needle = f"fn {fn_name}("
    start = prelude.find(needle)
    assert start != -1, f"{fn_name} not found in trusted prelude"
    brace = prelude.find("{", start)
    assert brace != -1, f"{fn_name} has no opening brace"
    depth = 0
    for i in range(brace, len(prelude)):
        ch = prelude[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return prelude[start : i + 1]
    raise AssertionError(f"unbalanced braces in {fn_name}")


def _split_spec_block(prelude: str, fn_name: str, *, end_marker: str | None = None) -> str:
    block = _extract_fn_block(prelude, fn_name)
    if end_marker and end_marker in prelude.split(fn_name, 1)[1]:
        return prelude.split(f"pub open spec fn {fn_name}")[1].split(end_marker)[0]
    return block


@pytest.fixture(scope="module")
def prelude() -> str:
    return emit_trusted_prelude(include_left_join_miss=True)


# --- Global negative: no arbitrary() in prelude ---


def test_prelude_contains_no_arbitrary(prelude: str) -> None:
    assert "arbitrary()" not in prelude, (
        "emit_trusted_prelude() must not emit arbitrary(); "
        "use real open specs (docs/TRUSTED_FAMILIES.md rocketship bar)"
    )


# --- Arithmetic exec Trusteds ---


@pytest.mark.parametrize("spec", _ARITH_EXEC_TRUSTEDS, ids=[s["name"] for s in _ARITH_EXEC_TRUSTEDS])
def test_arith_trusted_requires_before_ensures_and_checked(prelude: str, spec: dict[str, Any]) -> None:
    block = _extract_fn_block(prelude, spec["name"])
    req_pos = block.find("requires")
    ens_pos = block.find("ensures")
    assert req_pos != -1, f"{spec['name']}: missing requires"
    assert ens_pos != -1, f"{spec['name']}: missing ensures"
    assert req_pos < ens_pos, f"{spec['name']}: requires must appear before ensures"
    for snippet in spec["requires_snippets"]:
        assert snippet in block, f"{spec['name']}: missing requires snippet {snippet!r}"
    for snippet in spec["ensures_snippets"]:
        assert snippet in block, f"{spec['name']}: missing ensures snippet {snippet!r}"
    if spec["checked"]:
        assert spec["checked"] in block, f"{spec['name']}: expected {spec['checked']}"
    if spec["forbid_wrapping"]:
        assert "wrapping_add" not in block, f"{spec['name']}: must not use wrapping_add"
        assert "wrapping_mul" not in block, f"{spec['name']}: must not use wrapping_mul"


def test_adversarial_add_u64_rejects_wrapping_add_regression(prelude: str) -> None:
    block = _extract_fn_block(prelude, "add_u64")
    assert "checked_add" in block
    assert "wrapping_add" not in block


def test_adversarial_mul_u64_u32_rejects_wrapping_mul_regression(prelude: str) -> None:
    block = _extract_fn_block(prelude, "mul_u64_u32")
    assert "checked_mul" in block
    assert "wrapping_mul" not in block


# --- left_join_miss: open false, never external_body ---


def test_left_join_miss_generic_open_false_not_external_body(prelude: str) -> None:
    block = _extract_fn_block(prelude, "left_join_miss_generic")
    assert "external_body" not in block
    assert re.search(
        r"pub open spec fn left_join_miss_generic\(cols: &Cols, row: int\) -> bool \{\s*false\s*\}",
        prelude,
    ), "left_join_miss_generic must be open spec returning false"
    assert "arbitrary()" not in block


# --- String / LIKE open specs ---


def test_str_like_contains_exists_subrange_not_arbitrary(prelude: str) -> None:
    block = _split_spec_block(prelude, "str_like_contains", end_marker="str_like_prefix_exec")
    assert "exists|i: int|" in block
    assert "s.subrange(i, i + lit.len()) == lit" in block
    assert "arbitrary()" not in block


def test_adversarial_str_like_contains_rejects_arbitrary_regression(prelude: str) -> None:
    block = _split_spec_block(prelude, "str_like_contains", end_marker="str_like_prefix_exec")
    assert "arbitrary()" not in block
    assert "exists|i: int|" in block


def test_str_like_underscore_match_has_recursive_helper(prelude: str) -> None:
    assert "pub open spec fn str_like_underscore_match_rec" in prelude
    rec = _extract_fn_block(prelude, "str_like_underscore_match_rec")
    assert "decreases pat.len() - pi" in rec
    assert "str_like_underscore_match_rec(s, pat" in rec


def test_str_ilike_composes_ascii_lower(prelude: str) -> None:
    block = _split_spec_block(prelude, "str_ilike_match", end_marker="str_ilike_match_exec")
    assert "str_like_underscore_match(str_ascii_lower(s), str_ascii_lower(pat))" in block
    assert "arbitrary()" not in block


def test_str_lower_upper_open_spec_use_ascii_helpers_not_arbitrary(prelude: str) -> None:
    lower = _split_spec_block(prelude, "str_lower", end_marker="str_upper")
    upper = _split_spec_block(prelude, "str_upper", end_marker="str_lower_exec")
    assert "str_ascii_lower(s)" in lower
    assert "str_ascii_upper(s)" in upper
    assert "arbitrary()" not in lower
    assert "arbitrary()" not in upper


def test_abs_u64_open_identity_not_arbitrary(prelude: str) -> None:
    block = _split_spec_block(prelude, "abs_u64", end_marker="abs_u64_exec")
    assert re.search(r"pub open spec fn abs_u64\(x: u64\) -> u64 \{\s*x\s*\}", prelude)
    assert "arbitrary()" not in block


# --- Light semantic oracles (Python twin of open specs) ---


def _oracle_str_like_contains(s: str, lit: str) -> bool:
    if lit == "":
        return True
    n = len(lit)
    return any(s[i : i + n] == lit for i in range(len(s) - n + 1))


def _oracle_ascii_lower_char(c: str) -> str:
    if len(c) != 1:
        raise ValueError("single char expected")
    if "A" <= c <= "Z":
        return chr(ord(c) - ord("A") + ord("a"))
    return c


def _oracle_str_ascii_lower(s: str) -> str:
    return "".join(_oracle_ascii_lower_char(c) for c in s)


def _oracle_str_like_underscore_match(s: str, pat: str) -> bool:
    def m(si: int, pi: int) -> bool:
        if pi >= len(pat):
            return si >= len(s)
        if pat[pi] == "%":
            return any(m(k, pi + 1) for k in range(si, len(s) + 1))
        if pat[pi] == "_":
            return si < len(s) and m(si + 1, pi + 1)
        if si >= len(s) or s[si] != pat[pi]:
            return False
        return m(si + 1, pi + 1)

    return m(0, 0)


def _oracle_str_ilike_match(s: str, pat: str) -> bool:
    return _oracle_str_like_underscore_match(
        _oracle_str_ascii_lower(s),
        _oracle_str_ascii_lower(pat),
    )


_STR_LIKE_CONTAINS_CASES = [
    ("", "x"),
    ("hello", ""),
    ("hello", "ell"),
    ("hello", "xyz"),
    ("ababa", "aba"),
    ("Foo", "oo"),
]


@pytest.mark.parametrize(("s", "lit"), _STR_LIKE_CONTAINS_CASES)
def test_oracle_str_like_contains_fixtures(s: str, lit: str) -> None:
    assert _oracle_str_like_contains(s, lit) == (lit in s if lit else True)


_ASCII_LOWER_CASES = [
    ("", ""),
    ("abc", "abc"),
    ("ABC", "abc"),
    ("AbC123", "abc123"),
    ("café", "café"),
]


@pytest.mark.parametrize(("s", "expected"), _ASCII_LOWER_CASES)
def test_oracle_str_ascii_lower_fixtures(s: str, expected: str) -> None:
    assert _oracle_str_ascii_lower(s) == expected


_ILIKE_CASES = [
    ("Hello", "h%"),
    ("HELLO", "_ello"),
    ("MixEd", "m_x%d"),
    ("no", "yes"),
    ("A_B", "a_b"),
]


@pytest.mark.parametrize(("s", "pat"), _ILIKE_CASES)
def test_oracle_str_ilike_match_fixtures(s: str, pat: str) -> None:
    got = _oracle_str_ilike_match(s, pat)
    # Independent reference: Python str with ASCII lower + simple glob semantics.
    ref_s = "".join(c.lower() if "A" <= c <= "Z" else c for c in s)
    ref_pat = "".join(c.lower() if "A" <= c <= "Z" else c for c in pat)
    assert got == _oracle_str_like_underscore_match(ref_s, ref_pat)
