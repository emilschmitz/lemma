"""Tests for declarative_spec.lemmas host helpers and Verus snippets."""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
from pathlib import Path

import pytest

_LEMMAS_PATH = Path(__file__).resolve().parents[1] / "declarative_spec" / "lemmas.py"
_spec = importlib.util.spec_from_file_location("declarative_spec_lemmas", _LEMMAS_PATH)
assert _spec and _spec.loader
_lemmas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_lemmas)

FitRefusal = _lemmas.FitRefusal
choose_agg_slot = _lemmas.choose_agg_slot
float_error_lemmas_rs = _lemmas.float_error_lemmas_rs
integer_fit_lemmas_rs = _lemmas.integer_fit_lemmas_rs

VERUS = Path("/home/emil/tools/verus/verus")


def _run_verus(rust_body: str) -> subprocess.CompletedProcess[str]:
    src = f"""use vstd::prelude::*;

verus! {{
{rust_body}
}}

fn main() {{}}
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
        f.write(src)
        path = f.name
    try:
        return subprocess.run(
            [str(VERUS), path],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        Path(path).unlink(missing_ok=True)


def test_choose_agg_slot_u64_unsigned() -> None:
    assert choose_agg_slot(10, signed=False) == "u64"


def test_choose_agg_slot_i128_large_unsigned() -> None:
    assert choose_agg_slot(2**80, signed=False) == "i128"


def test_choose_agg_slot_i128_large_signed() -> None:
    assert choose_agg_slot(2**80, signed=True) == "i128"


def test_choose_agg_slot_refusal() -> None:
    with pytest.raises(FitRefusal):
        choose_agg_slot(2**140, signed=False)


def test_choose_agg_slot_signed_never_u64() -> None:
    assert choose_agg_slot(10, signed=True) == "i128"


def test_integer_fit_lemmas_verus() -> None:
    rust = integer_fit_lemmas_rs()
    assert "external_body" not in rust
    assert "assume(" not in rust
    proc = _run_verus(rust)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "0 errors" in combined


def test_float_error_lemmas_verus() -> None:
    rust = float_error_lemmas_rs()
    assert "lemma_f64_add_within" in rust
    assert "as real" in rust
    assert "f64_left_fold" not in rust and "host_f64_sum_error" not in rust
    proc = _run_verus(rust)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "0 errors" in combined
