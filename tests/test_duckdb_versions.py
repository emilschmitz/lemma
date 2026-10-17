"""Runs record the DuckDB Python package and native libduckdb versions and refuse a mismatch."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from research_loop import run_artifacts as ra

ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "build" / "libduckdb"
needs_lib = pytest.mark.skipif(not (LIB_DIR / "libduckdb.so").is_file(), reason="run scripts/fetch_libduckdb.sh")


@needs_lib
def test_matching_versions_are_recorded() -> None:
    v = ra.duckdb_versions(LIB_DIR)
    assert v == {"duckdb_python_version": duckdb.__version__, "duckdb_native_version": duckdb.__version__}


@needs_lib
def test_a_mismatch_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(duckdb, "__version__", "0.0.1")
    with pytest.raises(RuntimeError, match="version mismatch"):
        ra.duckdb_versions(LIB_DIR)


def test_the_pins_agree() -> None:
    assert f'"duckdb=={duckdb.__version__}"' in (ROOT / "pyproject.toml").read_text()
    assert f"VERSION={duckdb.__version__}" in (ROOT / "scripts" / "fetch_libduckdb.sh").read_text()
