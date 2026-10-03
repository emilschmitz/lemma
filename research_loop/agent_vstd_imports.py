"""Which ``use`` lines an agent may add.

A vstd lemma or a proved broadcast group is an import. A name containing
``axiom``, or a glob that can pull one in, is an assume and is rejected.
``vstd::prelude::*`` and ``vstd::arithmetic::<module>::*`` are host or
proof-library imports and stay.
"""

from __future__ import annotations

import re

_USE_START = re.compile(r"^(?:pub\s+)?(?:broadcast\s+)?use\b")
_PRELUDE_GLOB = re.compile(r"use\s+vstd::prelude::\*")
_ARITH_GLOB = re.compile(r"use\s+vstd::arithmetic::[A-Za-z0-9_]+::\*")


def use_is_an_assume(line: str) -> bool:
    """True when this import would bring an axiom into scope."""
    stripped = line.strip()
    if not _USE_START.match(stripped):
        return False
    if "axiom" in stripped.lower():
        return True
    compact = re.sub(r"\s+", "", stripped)
    if "::*" not in compact:
        return False
    return not (_PRELUDE_GLOB.search(stripped) or _ARITH_GLOB.search(stripped))
