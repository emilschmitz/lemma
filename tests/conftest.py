import pytest


@pytest.fixture(autouse=True)
def _named_prove_loop_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests here have no SEC DuckDB. Name the tiny profile; never reach it implicitly.

    Tests that exercise the measured catalog or another package set their own value.
    """
    monkeypatch.setenv("LEMMA_ASSUMPTION_PACKAGE", "prove_loop")
