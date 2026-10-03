"""Existing speed menu B (fast trusteds on)."""

from __future__ import annotations

from research_loop.trust_configs._types import TrustConfig

CONFIG = TrustConfig(
    name="fast",
    transpiler="product",
    note="Existing speed menu B: LEMMA_FAST_TRUSTEDS=1.",
    env={
        "LEMMA_FAST_TRUSTEDS": "1",
        "LEMMA_ENABLE_PARALLEL": "0",
        "LEMMA_ENABLE_VECTOR_SCAN": "0",
        "LEMMA_ENABLE_SPILL_HASH": "0",
        "LEMMA_FOLD_SLOT_AXIOMATIC": "0",
    },
    assumption_package=None,
)
