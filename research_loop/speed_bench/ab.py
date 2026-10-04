"""A/B timing of compiled proved binaries: interleaved rounds, min / p10 / median."""

from __future__ import annotations

import os
import re
import subprocess
import sys


def main(rows: int, rounds: int, runs: int, bins: list[str]) -> None:
    env = {**os.environ, "SPEED_ROWS": str(rows), "SPEED_WARMUP": "3", "SPEED_RUNS": str(runs)}
    samples: dict[str, list[int]] = {b: [] for b in bins}
    results: dict[str, str] = {}
    for _ in range(rounds):
        for b in bins:
            out = subprocess.run([b], capture_output=True, text=True, env=env, check=True).stdout
            samples[b] += [int(x) for x in re.search(r"SAMPLES_US:\[(.+)\]", out).group(1).split(",")]
            results[b] = re.search(r"RESULT:(.+)", out).group(1)[:60]
    print(f"load {os.getloadavg()[0]:.1f}")
    for b in bins:
        s = sorted(samples[b])
        print(f"{b.split('/')[-1]:<24} min {s[0]:>7} p10 {s[len(s) // 10]:>7} med {s[len(s) // 2]:>7}  {results[b]}")


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4:])
