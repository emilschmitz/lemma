"""Pytest configuration: ensure repo root is importable."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import os  # noqa: E402

import pytest  # noqa: E402

# Also at import, for test modules that emit a spec while being collected (before any fixture runs); see the autouse fixture below.
os.environ.setdefault("LEMMA_ASSUMPTIONS", "1")


@pytest.fixture(autouse=True)
def _tests_do_not_depend_on_the_run_defaults_of_lemma_toml(monkeypatch: pytest.MonkeyPatch):
    """lemma.toml sets parallel_vstd = "auto" for container runs; the unit tests of the sequential spec pin "off" (a test that wants another value sets it)."""
    import lemma_config

    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "off")
    # The same for the two run defaults added later (string_encoding = "dict", join_chain = true): the older emitter/prompt tests describe the
    # plain, FROM-order form. A test of the new defaults deletes these variables (tests/test_speed_target.py); a test of a mode sets its own.
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "plain")
    monkeypatch.setenv("LEMMA_JOIN_CHAIN", "0")
    # assumptions = false is the run default since 2026-10-17; the existing tests and proved fixtures describe the (now UNMAINTAINED)
    # assumption-package path, which must stay byte-identical. Tests of the default delete this variable (tests/test_assumptions_flag.py).
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "1")
    lemma_config.clear_cli()  # CLI overrides are process-global: no test leaks its flags into the next
    yield
    lemma_config.clear_cli()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "slow: needs a big build or a full-size database (e.g. TPC-H SF1); minutes per test")
