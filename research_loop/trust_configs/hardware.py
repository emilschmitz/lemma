"""Hardware-close kernels / adversary bench config (not rocketship, not fast menu).

Uses the product transpiler (``verus_transpiler``), not ``declarative_spec``; a
declarative emitter would need its own trust config file.
"""

from __future__ import annotations

from research_loop.trust_configs._types import TrustConfig

CONFIG = TrustConfig(
    name="hardware",
    transpiler="product",
    note=(
        "Adversary and speed_bench select this config. Same env as product "
        "(fast trusteds off). Not rocketship and not the fast menu; new axioms "
        "for hardware-close experiments go here rather than changing product "
        "defaults. trust_configs is only a switch over existing flags."
    ),
    env={
        "LEMMA_FAST_TRUSTEDS": "0",
        "LEMMA_ENABLE_PARALLEL": "0",
        "LEMMA_ENABLE_VECTOR_SCAN": "0",
        "LEMMA_ENABLE_SPILL_HASH": "0",
        "LEMMA_FOLD_SLOT_AXIOMATIC": "0",
    },
    assumption_package=None,
)
