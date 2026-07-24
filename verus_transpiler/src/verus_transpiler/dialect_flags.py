"""Modular TRUSTED-feature flags for Lemma Basic SQL dialect."""

from __future__ import annotations

# Features that rely on TRUSTED axioms/bridges. Set False to reject at parse/transpile.
TRUSTED_FEATURES: dict[str, bool] = {
    "window": True,
    "full_join": True,
    "cross_join": True,
    "semi_anti_join": True,
    "nway_join": True,
    "hash_join_exec": True,
    "recursive_cte": True,
    "intersect_except": True,
    "correlated_subquery": True,
    "ilike": True,
    "like_underscore": True,
    "grouped_derived": True,
    "case_when": True,
    "null_3vl": True,
}


def require_trusted(name: str) -> None:
    from .parse_sql import UnsupportedContractError

    if not TRUSTED_FEATURES.get(name, False):
        raise UnsupportedContractError(f"{name} disabled (TRUSTED feature flag off)")
