"""Prelude scalar helpers whose bodies Verus checks (no `external_body`)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from verus_transpiler.value_bounds import emit_trusted_prelude

from research_loop.harness import resolve_verus_bin, run_verus_verify

PROVED = [
    "add_u64",
    "mul_u64_u32",
    "sub_u64_to_i64",
    "add_i64",
    "case_when_u64_exec",
    "abs_u64_exec",
]

# Still trusted: the string exec helpers (no vstd spec for starts_with / ends_with /
# contains / to_ascii_lowercase) and nothing else in the scalar prelude.
STILL_TRUSTED = [
    "str_like_prefix_exec",
    "str_like_suffix_exec",
    "str_like_contains_exec",
    "str_ilike_match_exec",
    "str_like_underscore_match_exec",
    "str_lower_exec",
    "str_upper_exec",
]


@pytest.mark.parametrize("name", PROVED)
def test_scalar_prelude_helper_is_not_external_body(name: str) -> None:
    prelude = emit_trusted_prelude(include_left_join_miss=False)
    assert f"pub exec fn {name}(" in prelude
    assert not re.search(rf"external_body\]\s*pub exec fn {name}\b", prelude)


def test_prelude_external_body_set_is_exactly_the_string_helpers() -> None:
    prelude = emit_trusted_prelude(include_left_join_miss=False)
    trusted = re.findall(r"external_body\]\s*pub (?:exec|open spec) fn (\w+)", prelude)
    assert sorted(trusted) == sorted(STILL_TRUSTED)


def test_prelude_verifies_with_proved_arithmetic(tmp_path: Path) -> None:
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    prelude = emit_trusted_prelude(include_left_join_miss=False)
    rs = tmp_path / "prelude.rs"
    rs.write_text(
        "use vstd::prelude::*;\nverus! {\n" + prelude + "\nfn main() {}\n} // verus!\n"
    )
    ok, log = run_verus_verify(str(rs), timeout=300)
    assert ok, log[-3000:]
    assert " 0 errors" in log
