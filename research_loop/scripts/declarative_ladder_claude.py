"""Claude Code ladder: Haiku 4.5 first, Sonnet 5.5 only when Haiku proves fewer than 4 of 6.

Usage: ``declarative_ladder_claude.py``. Needs ``ANTHROPIC_API_KEY`` or
``LEMMA_CLAUDE_CONFIG_DIR`` in the launching shell (see AGENT_SANDBOX.md).
A query counts as proved when the ladder record status is SUCCESS
(proof verified and the official measure ran).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_loop.scripts.declarative_ladder import run_ladder

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-5-5"
MIN_PROVED = 4


def proved(records: list[dict]) -> int:
    return sum(1 for r in records if r["status"] == "SUCCESS")


def main() -> int:
    haiku = proved(run_ladder(HAIKU))
    print(f"GATE {HAIKU} proved {haiku}/6", flush=True)
    if haiku >= MIN_PROVED:
        return 0
    sonnet = proved(run_ladder(SONNET))
    print(f"GATE {SONNET} proved {sonnet}/6", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
