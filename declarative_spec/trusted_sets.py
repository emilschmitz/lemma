"""Selectable declarative trusted sets: the host lemma block and its lemma index, from ONE entry.

``declarative_default`` is exactly the block that used to be hardcoded (``lemmas.py`` float
error lemmas (the integer fit lemmas were removed by the audit: Verus knows them natively), and ``lemma_index.py``). The emitter, assembler, admission and the workspace builder
all ask ``current()``, which follows the active menu profile's ``trusted_set`` key
(``research_loop/menu_profile.py``); with no profile active it is ``declarative_default``. A key a profile names
that is not registered here fails loudly.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class TrustedSet:
    name: str
    # Both take the emitted spec (None: every block). The float (f64 idealization) block is part of the set only
    # when the spec involves a float value, so an integer / DECIMAL / string / date query carries no float lemma,
    # neither in the solver context nor in the trusted surface the prover is shown.
    lemmas_rs: Callable[[str | None], str]  # pasted between HOST_LEMMAS_START / END
    index_markdown: Callable[[str | None], str]  # agent-visible lemma index; describes the same lemmas


_REGION = re.compile(r"// HOST_LEMMAS_START.*?// HOST_LEMMAS_END", re.S)
_FLOAT_USE = re.compile(r"\bf64\b|\breal\b|\babs_real\b|\b\d+real\b|f64_literals_ok|FLOAT_|MAG_CAP_")


def spec_uses_floats(spec: str | None) -> bool:
    """True when the spec (outside the host lemma region) mentions a float value: f64, real, a float literal."""
    if spec is None:
        return True
    return _FLOAT_USE.search(_REGION.sub("", spec)) is not None


def _default_lemmas_rs(spec: str | None = None) -> str:
    from declarative_spec.lemmas import float_error_lemmas_rs

    return float_error_lemmas_rs().rstrip() if spec_uses_floats(spec) else ""


def _default_index_markdown(spec: str | None = None) -> str:
    from declarative_spec.lemma_index import lemma_index_markdown

    return lemma_index_markdown(floats=spec_uses_floats(spec))


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
