"""Named trust configs: modular switches over existing LEMMA_* flags."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from research_loop.trust_configs import fast as fast_mod
from research_loop.trust_configs import hardware as hardware_mod
from research_loop.trust_configs import product as product_mod
from research_loop.trust_configs._types import TrustConfig

CONFIGS: dict[str, TrustConfig] = {
    product_mod.CONFIG.name: product_mod.CONFIG,
    fast_mod.CONFIG.name: fast_mod.CONFIG,
    hardware_mod.CONFIG.name: hardware_mod.CONFIG,
}


def get_config(name: str) -> TrustConfig:
    if name not in CONFIGS:
        known = ", ".join(sorted(CONFIGS))
        raise ValueError(f"unknown trust config {name!r}; known: {known}")
    return CONFIGS[name]


def active_config_name() -> str:
    return os.environ.get("LEMMA_TRUST_CONFIG", "product")


@contextmanager
def apply_trust_config(name: str) -> Iterator[TrustConfig]:
    cfg = get_config(name)
    saved: dict[str, tuple[str | None, bool]] = {}
    for key, val in {**cfg.env, "LEMMA_TRUST_CONFIG": name}.items():
        was_set = key in os.environ
        saved[key] = (os.environ.get(key), was_set)
        os.environ[key] = val
    try:
        yield cfg
    finally:
        for key, (old, was_set) in saved.items():
            if was_set:
                assert old is not None
                os.environ[key] = old
            else:
                os.environ.pop(key, None)
