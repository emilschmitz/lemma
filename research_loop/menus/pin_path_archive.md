# Pin path (zero-copy and cold streaming): archived 2026-10-07

Status: **shelved** (Emil's decision, 2026-10-07). The paper concentrates on the resident path: proved, instance-specialized programs on
data prepared once, for queries that run many times (the GenDB protocol: hot runs, database in RAM, custom layout built once).
Nothing from this path is on `main` as code. The code is preserved on branch `worktree-agent-a2100078f58b32fa3`, tag
`archive/pin-path-2026-10-07` (commit 19a9d24). The documents are on `main` in this folder.

## What it was

Two ideas for running a proved query without copying the data into our own arrays.

1. **Zero-copy (`LEMMA_ZERO_COPY=1`).** Read DuckDB's pinned result chunks in place through a verified `PinnedCol` (a view that concatenates chunk slices).
   Trusted statement ZC-1 (one `unsafe from_raw_parts` in the plain-Rust main). Documents: `zero_copy_lease_PROPOSAL.md`, `zero_copy_lease_ADVERSARY_VERDICT.md`
   and `_2`, `zero_copy_gate.md`.
2. **Cold streaming (`LEMMA_COLD_STREAM=1`).** Register the proved fold with DuckDB (C API, `_duckdb.so` from the python wheel exports the full 1.5.4 API)
   so DuckDB's own parallel scan hands the fold each 2,048-value vector: no export, no pin, no copy. Two modes: `aggregate` (a UDF aggregate)
   and `scalar` (a scalar function inside `SELECT COALESCE(MAX(f(cols)),0) FROM t`, thread states merged by the verified `cold_combine` and `cold_finish`).
   Documents: `cold_path_feasibility.md`, `cold_stream_ADVERSARY_VERDICT.md`.

## Results

**Zero-copy: sound, not worth enabling.** One-shot only 8 to 24 percent faster than a native copy loader, and the kernel is 1.7 to 5.5x slower on three of
four shapes, because DuckDB's result-chunk buffers are not adjacent in memory (16 KB stride for 8 KB of data). A native C-API copy loader gets the one-shot win
with no new trust. Gate criteria 5 met, 3 unmet, 3 partial (see `zero_copy_gate.md`).

**Cold streaming (revision 3, 2026-10-07), real SEC `num` and TPC-H, DuckDB 1.5.4, buffer-hot on both sides, median of 9, all results equal DuckDB's:**

| shape | rows | DuckDB in place | scalar mode | ratio | aggregate mode | ratio |
|---|---|---|---|---|---|---|
| `SUM(DECIMAL(38,4)) WHERE value > 5000` (SEC `num`) | 39.4M | 235 ms | 204 ms | 0.87 | 214 ms | 0.91 |
| `COUNT(*) WHERE qtrs = 3` (SEC `num`, INTEGER) | 39.4M | 12.2 ms | 7.9 ms | 0.65 | 13.8 ms | 1.16 |
| two-column `SUM(DECIMAL(15,2)) WHERE`, TPC-H SF1 | 6.0M | 5.4 ms | 4.7 ms | 0.87 | 6.4 ms | 1.18 |
| same, TPC-H SF10 | 60.0M | 34.9 ms | 27.7 ms | 0.79 | 37.5 ms | 1.11 |

Reading: ratio below 1 means faster than DuckDB answering in place. The gains are 13 to 35 percent and come from a branch-free fold (up to 2x vs a branchy one),
an AVX2 build (an earlier cold ratio of 1.4 to 1.5 was a missing `LEMMA_TARGET_CPU`: baseline SSE2), and the scalar mode skipping DuckDB's hash-aggregate machinery.
The scan itself (DuckDB's) is 70 to 90 percent of the time, so there is little headroom: **DuckDB does the performance-critical part (storage reads,
decompression, parallel scheduling); we implement only the per-vector fold.** Covered shapes: ungrouped SUM/COUNT of per-row terms on fixed-width columns; no joins, no group-by.

## Trust and review status

- ZC-1 (zero-copy): adversary SOUND after fixes (two reviews).
- ZC-2 / ZC-2s (cold streaming): statement "the aggregate (or scalar function) sees every row exactly once, in some order" for the fixed query template.
  The first adversary review (aggregate mode) found a **silent wrong answer when the SQL adds `DISTINCT`** (DuckDB deduplicates before the callback), plus a liveness
  bug; the same class applies to FILTER, ORDER BY in the aggregate, WHERE, GROUP BY, window frames. Fix: the glue builds the SQL from the template and refuses
  every modifier (a rows-seen check against `SELECT COUNT(*)` was added for scalar mode). **The revision-3 scalar mode (ZC-2s) was NOT adversary-reviewed.**
- Nothing here was merged to `main` as code.

## Why shelved

The paper's practical claim is speed for repeated queries on resident data, where our execution replaces DuckDB's. The cold path gives parity to a modest edge for
a narrow shape class by reusing DuckDB's scan; it is a useful side result ("a proved fold can run inside DuckDB's scan at 0.65 to 0.87x") but not the main story.
The zero-copy idea does not pay off because of chunk layout.

## If resumed

1. Re-review ZC-2s (scalar mode) with a separate adversary; land the DISTINCT and modifier refusals with tests; confirm the rows-seen check.
2. Re-measure after merging `main`'s x86-64-v3 default (the branch already passes the target).
3. Extend beyond ungrouped sums only if there is a reason: grouped and join shapes would need DuckDB to do the join and give us groups, which changes the trust story.
4. Other findings in `research_loop/generated/arena/FINDINGS.md` (F-PIN-1 to 3, F-COLD-1 to 3): the shipped exporter was 29x slower than a native C-API load on DECIMAL(38,4)
   (this fed the exporter-v3 task, which is separate and still open); a data-dependent branch in a Verus-compiled fold costs up to 2x (write folds branch-free); DuckDB aggregate state
   memory has no alignment guarantee.
