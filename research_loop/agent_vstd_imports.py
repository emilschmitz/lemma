"""Which ``use`` lines an agent may add.

A vstd lemma or a proved broadcast group is an import. A name containing
``axiom``, ``arbitrary``, or ``proof_from_false``, or a glob that can pull
an axiom in, is an assume and is rejected.
``vstd::prelude::*`` and ``vstd::arithmetic::<module>::*`` are host or
proof-library imports and stay.
"""

from __future__ import annotations

import re

_USE_START = re.compile(r"^(?:pub\s+)?(?:broadcast\s+)?use\b")
_PRELUDE_GLOB = re.compile(r"use\s+vstd::prelude::\*")
_ARITH_GLOB = re.compile(r"use\s+vstd::arithmetic::[A-Za-z0-9_]+::\*")
# Names that prove a fact from nothing, or that are vstd's own assumes.
# `proof_from_false` still needs `false`, but it is not a lemma the agent may import.
_ASSUME_NAME = re.compile(
    r"(?i)(?:axiom|arbitrary|proof_from_false|unreached|spec_affirm)"
)


def use_is_an_assume(line: str) -> bool:
    """True when this import would bring an axiom or an assume-like item into scope."""
    stripped = line.strip()
    if not _USE_START.match(stripped):
        return False
    if _ASSUME_NAME.search(stripped):
        return True
    compact = re.sub(r"\s+", "", stripped)
    if "::*" not in compact:
        return False
    return not (_PRELUDE_GLOB.search(stripped) or _ARITH_GLOB.search(stripped))
