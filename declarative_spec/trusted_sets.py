"""Selectable declarative trusted sets: the host lemma block and its lemma index, from ONE entry.

``declarative_default`` is exactly the block that used to be hardcoded (``lemmas.py`` float
error lemmas (the integer fit lemmas were removed by the audit: Verus knows them natively), and ``lemma_index.py``). The emitter, assembler, admission and the workspace builder
all ask ``current()``, which follows the active menu profile's ``trusted_set`` key
(``research_loop/menu_profile.py``); with no profile active it is ``declarative_default``. A key a profile names
that is not registered here fails loudly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class TrustedSet:
    name: str
    lemmas_rs: Callable[[], str]  # pasted between HOST_LEMMAS_START / END
    index_markdown: Callable[[], str]  # agent-visible lemma index; describes the same lemmas


def _default_lemmas_rs() -> str:
    from declarative_spec.lemmas import host_float_lemmas_rs

    return host_float_lemmas_rs().rstrip()


def _default_index_markdown() -> str:
    from declarative_spec.lemma_index import lemma_index_markdown

    return lemma_index_markdown()


TRUSTED_SETS: dict[str, TrustedSet] = {
    "declarative_default": TrustedSet("declarative_default", _default_lemmas_rs, _default_index_markdown),
}


def get(key: str) -> TrustedSet:
    if key not in TRUSTED_SETS:
        raise KeyError(f"unknown declarative trusted_set {key!r}; known: {sorted(TRUSTED_SETS)}")
    return TRUSTED_SETS[key]


def current() -> TrustedSet:
    """The active profile's trusted set, or ``declarative_default`` when no menu profile is active."""
    from research_loop.menu_profile import active_menu

    profile = active_menu()
    return get("declarative_default" if profile is None else profile.trusted_set)
