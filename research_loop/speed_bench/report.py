"""Print a table from measure.py JSON files."""

from __future__ import annotations

import json
import sys


def main(paths: list[str]) -> None:
    for p in paths:
        data = json.load(open(p))
        print(f"## {p}")
        print("| query | rows | verus | match | proved us (med/min) | duck8 us | duck1 us | x vs duck8 | x vs duck1 | idle | noisy |")
        print("|---|---|---|---|---|---|---|---|---|---|---|")
        for e in data:
            d = e["duckdb_us"]
            ts = sorted(d, key=int, reverse=True)
            hi, lo = ts[0], ts[-1]
            print(
                f"| {e['id']} | {e['rows']} | {e['verus']} | {all(e['match'].values())} "
                f"| {e['proved_us']['median']:.0f}/{e['proved_us']['min']:.0f} "
                f"| {d[hi]['median']:.0f} | {d[lo]['median']:.0f} "
                f"| {e['speedup_median'][hi]:.2f} | {e['speedup_median'][lo]:.2f} | {e.get('idle_before_blocks')} | {e.get('noisy')} |"
            )


if __name__ == "__main__":
    main(sys.argv[1:])
