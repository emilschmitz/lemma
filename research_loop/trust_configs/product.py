"""Product path trust menu (menu A defaults)."""

from __future__ import annotations

from research_loop.trust_configs._types import TrustConfig

CONFIG = TrustConfig(
    name="product",
    transpiler="product",
    note="Menu A defaults: rocketship product path flags unchanged.",
    env={
        "LEMMA_FAST_TRUSTEDS": "0",
        "LEMMA_ENABLE_PARALLEL": "0",
        "LEMMA_ENABLE_VECTOR_SCAN": "0",
        "LEMMA_ENABLE_SPILL_HASH": "0",
        "LEMMA_FOLD_SLOT_AXIOMATIC": "0",
    },
    assumption_package=None,
)
