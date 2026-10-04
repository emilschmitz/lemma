"""The two spec style names, in ONE place. The profile layer and the launcher import them from here.

``imperative`` is the loop-and-invariant path (``verus_transpiler`` spec, agent writes ``run_query``);
``declarative`` is ``declarative_spec``. Flag values are exactly these two; anything else is rejected.

``ENV_VALUE`` is what is written to ``LEMMA_SPEC_STYLE``. The existing reader
(``db_extension/optimizer.py::_read_lemma_spec_style``) still spells the imperative style
``recursive``, so that is its value here until the reader is renamed; then this mapping becomes the
identity (one line) and ``recursive`` is rejected everywhere through ``style_from_env``.
"""

from __future__ import annotations

DECLARATIVE = "declarative"
IMPERATIVE = "imperative"
STYLES = (IMPERATIVE, DECLARATIVE)

ENV_VALUE = {DECLARATIVE: "declarative", IMPERATIVE: "recursive"}  # <- the one line to change on rename
_FROM_ENV = {v: k for k, v in ENV_VALUE.items()}


def check_style(style: str) -> str:
    if style == "recursive" and "recursive" not in STYLES:
        raise ValueError("style 'recursive' was renamed to 'imperative'")
    if style not in STYLES:
        raise ValueError(f"unknown style {style!r}; known: {STYLES}")
    return style


def style_from_env(value: str) -> str:
    """The style named by a ``LEMMA_SPEC_STYLE`` value."""
    value = value.strip().lower()
    if value not in _FROM_ENV:
        if value == "recursive":
            raise ValueError("style 'recursive' was renamed to 'imperative'")
        raise ValueError(f"unknown LEMMA_SPEC_STYLE {value!r}; known: {sorted(_FROM_ENV)}")
    return _FROM_ENV[value]
