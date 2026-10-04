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


def test_float_error_lemmas_verus() -> None:
    rust = float_error_lemmas_rs()
    assert "lemma_f64_add_within" in rust
    assert "as real" in rust
    assert rust.count("external_body") == 11
    proc = _run_verus(rust)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "0 errors" in combined


# The six `*_fits` host lemmas were removed: Verus gives these facts for primitive `+` itself.
_REMOVED_FIT_LEMMAS = (
    "lemma_u64_add_fits",
    "lemma_i128_add_fits",
    "lemma_count_step_fits_u64",
    "lemma_count_step_fits_i128",
    "lemma_sum_step_fits_u64",
    "lemma_sum_step_fits_i128",
)


def test_integer_add_is_exact_in_verus_without_host_lemmas() -> None:
    proc = _run_verus(
        """
fn count_step(prev: u64, row_cap: u64) -> (r: u64)
    requires prev as int + 1 <= row_cap as int,
    ensures r as int == prev as int + 1,
{ prev + 1 }

fn sum_step(prev: i128, cell: i128, cap: i128) -> (r: i128)
    requires
        0 <= cap,
        -cap <= cell <= cap,
        -cap <= prev as int + cell as int <= cap,
    ensures r as int == prev as int + cell as int,
{ prev + cell }
"""
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "0 errors" in combined


def test_overflowing_add_is_still_rejected_by_verus() -> None:
    proc = _run_verus("fn bad(prev: u64) -> u64 { prev + 1 }")
    assert proc.returncode != 0


@pytest.mark.parametrize("name", _REMOVED_FIT_LEMMAS)
def test_float_lemma_source_and_host_names_omit_removed_fit_lemmas(name: str) -> None:
    from declarative_spec.admit import host_names

    assert name not in float_error_lemmas_rs()
    assert name not in host_names("")
