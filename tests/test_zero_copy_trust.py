"""The zero-copy path adds no trusted Verus code: gate criterion 'no new trusted beyond ZC-1' (research_loop/menus/zero_copy_gate.md)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = (ROOT / "declarative_spec" / "zero_copy_lib.rs").read_text()
FFI = (ROOT / "declarative_spec" / "zero_copy_ffi.rs").read_text()


def _code(text: str) -> str:
    return re.sub(r"//[^\n]*", "", text)


def test_the_verified_library_has_no_trusted_escape():
    code = _code(LIB)
    for word in ("external_body", "external_fn_specification", "assume(", "admit(", "assume_specification", "#[verifier::external"):
        assert word not in code, word


def test_unsafe_exists_only_in_the_plain_rust_ffi_and_the_generated_main():
    assert "unsafe" not in _code(LIB)
    assert _code(FFI).count("from_raw_parts") == 0  # the borrow itself is written in the generated main, once per column
    from declarative_spec import zero_copy

    src = (ROOT / "declarative_spec" / "zero_copy.py").read_text()
    assert src.count("from_raw_parts") == 2  # zero-copy borrow and the copy-control memcpy, both in generated main text
    assert zero_copy.lib_rs() == LIB
