"""Copy the two agent regions (body and helpers) of one workspace's runquery_agent.rs into another's.

``declarative_transplant.py SRC_WS DST_WS``: used to re-measure an already proved body for the SAME SQL at a larger data size
(the DST workspace was prepared on the bigger database; its host spec and caps are the DST ones). The body is not trusted
because of the copy: ``declarative_manual.py check`` re-verifies it against the DST spec.
"""

from __future__ import annotations

import sys
from pathlib import Path

from declarative_spec.regions import (
    EDIT_END,
    EDIT_START,
    HELPERS_END,
    HELPERS_START,
    extract_agent_edit,
    extract_agent_helpers,
)


def transplant(src_rs: str, dst_rs: str) -> str:
    body = extract_agent_edit(src_rs)
    helpers = extract_agent_helpers(src_rs)
    a = dst_rs.index(EDIT_START) + len(EDIT_START)
    b = dst_rs.index(EDIT_END)
    out = dst_rs[:a] + "\n" + body + "\n" + dst_rs[b:]
    a = out.index(HELPERS_START) + len(HELPERS_START)
    b = out.index(HELPERS_END)
    return out[:a] + "\n" + helpers + "\n" + out[b:]


def main() -> int:
    src, dst = (Path(p).expanduser().resolve() / "runquery_agent.rs" for p in sys.argv[1:3])
    dst.write_text(transplant(src.read_text(), dst.read_text()))
    print(f"transplanted {src} -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
