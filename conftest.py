"""Pytest configuration: ensure repo root is importable."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _tests_do_not_depend_on_the_run_defaults_of_lemma_toml(monkeypatch: pytest.MonkeyPatch):
    """lemma.toml sets parallel_vstd = "auto" for container runs; the unit tests of the sequential spec pin "off" (a test that wants another value sets it)."""
    import lemma_config

    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "off")
    # The same for the two run defaults added later (string_encoding = "dict", join_chain = true): the older emitter/prompt tests describe the
    # plain, FROM-order form. A test of the new defaults deletes these variables (tests/test_speed_target.py); a test of a mode sets its own.
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "plain")
    monkeypatch.setenv("LEMMA_JOIN_CHAIN", "0")
    lemma_config.clear_cli()  # CLI overrides are process-global: no test leaks its flags into the next
    yield
    lemma_config.clear_cli()


@pytest.fixture
def exact_division_off(monkeypatch: pytest.MonkeyPatch):
    """lemma.toml [sql] exact_division = false: the f64 idealization and the real-form AVG / ratio specs (byte-identical to before the flag).

    The modules that state or prove that form (`pytestmark = pytest.mark.usefixtures("exact_division_off")`) use it; the default (on) is
    tested in tests/test_declarative_exact_division.py."""
    monkeypatch.setenv("LEMMA_EXACT_DIVISION", "0")
