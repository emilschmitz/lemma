"""adversary_declarative0 menu: the declarative spec path (``declarative_spec``), no fast or parallel trusteds.

Sibling of adversary_imperativespec0 (product transpiler). Same flag philosophy: every speed
trusted is off and the semantics are exact (integer SUM is i128, no u64 wrap). Anything straight
from vstd (``vstd::thread::spawn``/``join``, ``HashMapWithView``, ``StringHashMap``) is allowed on
every menu; nothing we implement as trusted is.
"""

from __future__ import annotations

from research_loop.trust_configs._types import TrustConfig

CONFIG = TrustConfig(
    name="adversary_declarative0",
    transpiler="declarative",
    note=(
        "adversary_declarative0 menu on the declarative spec emitter (LEMMA_SPEC_STYLE=declarative). "
        "No fast trusteds, no parallel trusteds, no vector-scan or spill-hash trusteds, no fold-slot "
        "axioms. Integer SUM is the exact i128 mathematical sum. The agent writes the run_query body "
        "and a helper region; the host spec, lemmas and loaders are fixed. The speed bar is "
        "LEMMA_SPEED_BAR_MULT times faster than DuckDB (default 1.0, merely faster)."
    ),
    env={
        "LEMMA_SPEC_STYLE": "declarative",
        "LEMMA_FAST_TRUSTEDS": "0",
        "LEMMA_ENABLE_PARALLEL": "0",
        "LEMMA_ENABLE_VECTOR_SCAN": "0",
        "LEMMA_ENABLE_SPILL_HASH": "0",
        "LEMMA_FOLD_SLOT_AXIOMATIC": "0",
    },
    assumption_package=None,
)
