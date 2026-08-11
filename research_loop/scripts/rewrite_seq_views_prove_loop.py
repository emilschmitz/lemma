#!/usr/bin/env python3
"""Rewrite prove_loop seq runqueries to use vec_*_view(out@) invariants."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research_loop.scripts.inject_fold_bound_proofs import (
    _load_spec,
    _rewrite_seq_views,
    _vec_view_for_ret,
)
from research_loop.method_spec_ret_type import (
    parse_method_spec_return_type,
    resolve_ret_type_from_method_spec,
)
from research_loop.trusted_ret_bridge import bridge_from_method_spec_type, get_bridge


def main() -> int:
    root = ROOT / "research_loop/generated/prove_loop"
    n = 0
    for rnd in ("r11", "r12"):
        for d in sorted(root.glob(f"{rnd}_q*")):
            agent = d / "runquery_agent.rs"
            if not agent.is_file():
                continue
            spec = _load_spec(d)
            ret = resolve_ret_type_from_method_spec(spec)
            bridge = get_bridge(ret) or bridge_from_method_spec_type(
                parse_method_spec_return_type(spec)
            )
            view = bridge.view_spec if bridge and bridge.view_spec else _vec_view_for_ret(ret)
            if not view or not view.startswith("vec_"):
                continue
            src = agent.read_text(encoding="utf-8")
            new = _rewrite_seq_views(src, view)
            if new != src:
                agent.write_text(new, encoding="utf-8")
                n += 1
                print("rewrote", d.name)
    print("done", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
