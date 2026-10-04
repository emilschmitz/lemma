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


def test_adversary_imperativespec0_is_product_transpiler_not_fast() -> None:
    cfg = get_config("adversary_imperativespec0")
    assert cfg.transpiler == "product"
    assert cfg.name == "adversary_imperativespec0"
    assert cfg.name != "fast"
    assert "adversary_imperativespec0" in cfg.note.lower()


def test_adversary_imperativespec0_applies_product_flags_and_exact_sum() -> None:
    keys = {
        "LEMMA_FAST_TRUSTEDS": "0",
        "LEMMA_ENABLE_PARALLEL": "0",
        "LEMMA_ENABLE_VECTOR_SCAN": "0",
        "LEMMA_ENABLE_SPILL_HASH": "0",
        "LEMMA_FOLD_SLOT_AXIOMATIC": "0",
        "LEMMA_EXACT_SUM": "1",
    }
    saved = {k: os.environ.pop(k, None) for k in [*keys, "LEMMA_TRUST_CONFIG"]}
    try:
        with apply_trust_config("adversary_imperativespec0"):
            for k, v in keys.items():
                assert os.environ[k] == v
            assert os.environ["LEMMA_TRUST_CONFIG"] == "adversary_imperativespec0"
        assert "LEMMA_EXACT_SUM" not in os.environ
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_old_hardware_name_is_rejected_without_alias() -> None:
    with pytest.raises(ValueError, match="unknown trust config 'hardware'"):
        get_config("hardware")
    with pytest.raises(ValueError, match="unknown trust config 'hardware'"):
        with apply_trust_config("hardware"):
            pass
