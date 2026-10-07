"""The vstd modules, and the broadcast groups in them, read from the pinned Verus install.

The spec preamble imports every vstd module by glob so the proving agent needs no imports of
its own. The module list and the group list come from the vstd source, not from a hand-kept list.
Fails loudly when the source tree is missing or a module file cannot be found.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

VERUS_HOME = Path.home() / "tools" / "verus"
VSTD = VERUS_HOME / "vstd"

# Modules that have their own submodules we also import.
_RECURSE = ("std_specs", "arithmetic")
# `prelude` is imported separately. The infinite `ISet`/`IMap` libraries define the same free
# function names as `Set`/`Map` (`lemma_len_union`, ...), so a glob of both makes every such
# name ambiguous. The emitted specs use finite `Set`, `Map` and `Seq`, so the infinite ones go.
EXCLUDED = ("prelude", "imap", "imap_lib", "iset", "iset_lib")

_PUB_MOD = re.compile(r"^pub mod (\w+);", re.M)
_GROUP = re.compile(r"^pub broadcast group (group_\w+)\s*\{([^}]*)\}", re.M)


def _submodules(path: Path) -> list[str]:
    return _PUB_MOD.findall(path.read_text())


@lru_cache(maxsize=1)
def vstd_modules() -> tuple[str, ...]:
    """Module paths below ``vstd::``, e.g. ``seq_lib`` or ``std_specs::hash``."""
    found: list[str] = []
    for top in _submodules(VSTD / "vstd.rs"):
        if top in EXCLUDED:
            continue
        if top in _RECURSE:
            found.extend(f"{top}::{sub}" for sub in _submodules(VSTD / top / "mod.rs"))
        else:
            found.append(top)
    return tuple(found)


def preamble_uses() -> str:
    """``use vstd::...::*;`` for the prelude and every vstd module."""
    lines = ["use vstd::prelude::*;"] + [f"use vstd::{m}::*;" for m in vstd_modules()]
    return "\n".join(lines)


def _module_file(module: str) -> Path:
    base = VSTD / module.replace("::", "/")
    flat = base.with_suffix(".rs")
    return flat if flat.is_file() else base / "mod.rs"


@lru_cache(maxsize=1)
def broadcast_groups() -> tuple[tuple[str, str], ...]:
    """``(module, group_name)`` for every top-level ``pub broadcast group group_*`` in those modules.

    Every group is allowed, including one that lists an ``axiom_*`` item: those axioms are part of vstd's own trusted core,
    which every proof here already depends on (thread spawn/join, Vec/String/HashMap specs, float predicates), so switching one on
    adds no trust beyond vstd. What stays banned is naming an axiom (or anything else) outside a ``broadcast use`` of such a group,
    any path not starting with ``vstd::``, and any axiom the agent writes (see ``admit``).
    """
    out: dict[tuple[str, str], None] = {}
    for module in vstd_modules():
        for name, members in _GROUP.findall(_module_file(module).read_text()):
            out[(module, name)] = None
    return tuple(out)


def group_paths() -> frozenset[str]:
    return frozenset(f"vstd::{m}::{n}" for m, n in broadcast_groups())


def groups_markdown() -> str:
    lines = [f"- `broadcast use vstd::{m}::{n};`" for m, n in broadcast_groups()]
    return "\n".join(lines)
