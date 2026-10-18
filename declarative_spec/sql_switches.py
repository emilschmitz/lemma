"""The [sql] switches of lemma.toml: one function per new SQL shape. Off (the default) means the emitter refuses the shape as before."""

from __future__ import annotations

import lemma_config


def agg_times_constant() -> bool:
    return bool(lemma_config.get("agg_times_constant"))


def derived_agg_expr() -> bool:
    return bool(lemma_config.get("derived_agg_expr"))


def cte_reuse() -> bool:
    return bool(lemma_config.get("cte_reuse"))


def left_join_count() -> bool:
    return bool(lemma_config.get("left_join_count"))


def templates() -> bool:
    return bool(lemma_config.get("templates"))


def exact_division() -> bool:
    """AVG and `/` as exact rationals, no float idealization; a FLOAT/DOUBLE operand is refused (see ``declarative_spec/exact_rational.py``)."""
    return bool(lemma_config.get("exact_division"))
