"""Which ``use`` lines an agent may add.

Any ``use vstd::...;`` is allowed, including globs (``use vstd::seq::*;``) and
``broadcast use`` of vstd's own broadcast groups. Those are vstd's trusted base.
A line is an assume, and rejected, when it names ``axiom``, ``arbitrary``,
``proof_from_false``, ``unreached`` or ``spec_affirm`` (this covers the host's
hash-key axiom), or when it is a ``broadcast use`` glob/list, which cannot be
audited by name.
"""

from __future__ import annotations

import re

_USE_START = re.compile(r"^(?:pub\s+)?(?:broadcast\s+)?use\b")
_BROADCAST = re.compile(r"^(?:pub\s+)?broadcast\s+use\b")
ASSUME_NAME = re.compile(r"(?i)(?:axiom|arbitrary|proof_from_false|unreached|spec_affirm)")


def use_is_an_assume(line: str) -> bool:
    """True when this import would bring an axiom or an assume-like item into scope."""
    stripped = line.strip()
    if not _USE_START.match(stripped):
        return False
    if ASSUME_NAME.search(stripped):
        return True
    return bool(_BROADCAST.match(stripped)) and ("*" in stripped or "{" in stripped)
