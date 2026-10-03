from __future__ import annotations

import os

import pytest

from research_loop.trust_configs import apply_trust_config, get_config


def test_unknown_config_raises() -> None:
    with pytest.raises(ValueError, match="unknown trust config"):
        get_config("nope")


def test_product_apply_restores_fast_trusteds() -> None:
    os.environ["LEMMA_FAST_TRUSTEDS"] = "1"
    with apply_trust_config("product"):
        assert os.environ["LEMMA_FAST_TRUSTEDS"] == "0"
    assert os.environ["LEMMA_FAST_TRUSTEDS"] == "1"


def test_fast_apply_sets_and_restores() -> None:
    prev = os.environ.pop("LEMMA_FAST_TRUSTEDS", None)
    try:
        with apply_trust_config("fast"):
            assert os.environ["LEMMA_FAST_TRUSTEDS"] == "1"
        assert "LEMMA_FAST_TRUSTEDS" not in os.environ
    finally:
        if prev is not None:
            os.environ["LEMMA_FAST_TRUSTEDS"] = prev


def test_hardware_is_product_transpiler_not_fast() -> None:
    hw = get_config("hardware")
    assert hw.transpiler == "product"
    assert hw.env["LEMMA_FAST_TRUSTEDS"] == "0"
    assert hw.name == "hardware"
    assert "hardware" in hw.note.lower()
    assert hw.name != "fast"
