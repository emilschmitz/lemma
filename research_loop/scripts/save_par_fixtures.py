"""Save adversary-produced parallel candidates (JSON with run_query_body and helpers) as example fixture files.

``save_par_fixtures.py``: parallel_ungrouped_{min,max,count}.rs from research_loop/generated/adversary_par/*.json.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "research_loop" / "generated" / "adversary_par"
DST = ROOT / "tests" / "fixtures" / "declarative_proofs"

CASES = {
    "parallel_ungrouped_min.rs": ("par_min_n17", "ungrouped MIN under a filter: each worker returns (value, any) for its range; the merge keeps the smaller of two witnessed values (`lemma_merge`)"),
    "parallel_ungrouped_max.rs": ("par_max_n17", "ungrouped MAX under a filter (mirror of the MIN example)"),
    "parallel_ungrouped_count.rs": ("cnt_n16", "ungrouped COUNT(*) under a filter in a u64 accumulator (additive partials, as for SUM)"),
}


def main() -> None:
    for name, (cand, what) in CASES.items():
        d = json.loads((SRC / f"{cand}.json").read_text())
        header = (
            f"// Worked example (parallel scan, LEMMA_PARALLEL_VSTD=1): {what}.\n"
            f"//   {d['sql']}\n"
            "// Same design as `parallel_ungrouped_sum.rs`: 8 vstd worker threads over row ranges of the shared Arc, partials combined in\n"
            "// order. Found by the manual adversary of the parallel path (60 judged runs against DuckDB, no hole) and kept verified here.\n"
        )
        helpers = d.get("helpers", "").strip()
        text = header + "// AGENT_HELPERS_START\n" + helpers + "\n// AGENT_HELPERS_END\n// AGENT_EDIT_START\n" + d["run_query_body"].rstrip() + "\n// AGENT_EDIT_END\n"
        (DST / name).write_text(text)
        print("wrote", name, d["sql"])


if __name__ == "__main__":
    main()
