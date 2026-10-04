#!/bin/sh
# Thread spawn+join cost: tiny table (16k rows), so the median is almost pure overhead.
# Needs the 2M-row binaries built by `par_measure.py --rows 2000000` first.
cd "$(dirname "$0")"
for q in q01_par q04_par; do
  for t in 1 2 4 8; do
    printf '%s threads=%s rows=16000 ' "$q" "$t"
    SPEED_ROWS=16000 SPEED_THREADS=$t SPEED_WARMUP=20 SPEED_RUNS=201 ".cache/2000000/$q" | grep MEDIAN
  done
done
