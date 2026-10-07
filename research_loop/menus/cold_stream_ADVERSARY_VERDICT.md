VERDICT: SOUND after fixes (no silent wrong answer found inside the stated conditions; finding 1 should be added before the path is switched on, finding 3 is a liveness bug)

Reviewer: manual adversary 3 (Sonnet), 2026-10-06. Tree reviewed: worktree agent-a2100078f58b32fa3, HEAD f4795c8 plus the author's UNCOMMITTED edits to declarative_spec/cold_stream.py (XOR state check, interleaved reference timing) and cold_stream_oneshot.py. My binaries were built from the tree as it stood when each build got the machine lock; the author was editing while I worked, so re-run the three builds after the final commit. DuckDB 1.5.4 (python wheel). No timing claims taken. All scratch in /tmp/claude-1000/adv3 (scripts exp_count.py, exp_sum.py, variant.py, run_variants.py, mut.py, exp_cap.py); heavy builds went through scripts/ram/heavy.sh, Verus through verus_guarded.sh, max table 6.0M rows.

## Findings

1. (a) ZC-2 item 3 (every row exactly once) is not checked by anything. Nothing in the glue compares the rows the fold saw with the table. I could not make DuckDB 1.5.4 drop or duplicate a row (findings below), but the one unproved leg of the chain has a free runtime check. Add: in `zc_final` store `st.rows` into a static AtomicU64; in `main`, after the first query, run `SELECT count(*) FROM "t"` (answered from table metadata) and abort loudly if it differs. This catches dropped/duplicated rows (not a swap of contents) and also catches a vector-count bug. File: declarative_spec/cold_stream.py `_glue` (zc_final, main). Needs two tests (missing rows via a deliberately lying callback, and the normal case).

2. (b) The proof is only about `SELECT zc_cold(cols) FROM t`. If anyone edits the generated SQL the glue does not stop it. variant.py + run_variants.py on a 1M-row table (want 199374):
   - `zc_cold(DISTINCT "qtrs")` returns 1 (SILENT WRONG; DuckDB dedups before update).
   - `GROUP BY x / 100000` and `zc_cold(..) OVER ()` abort with "the chunk's rows belong to different aggregate states". This guard is only a pointer comparison: a GROUP BY whose groups are each aligned to whole vectors would pass it and give per-group results computed as if the group were the whole table (not run; reasoned from the code, cold_stream.py zc_update).
   Not reachable today (the SQL string is generated and a test pins it, tests/test_cold_stream.py line 95). Accepted limitation; keep the "no GROUP BY/DISTINCT/FILTER/window" sentence in ZC-2 and keep the pinned-SQL test.

3. (c) Host bug, loud refusal of a legal table: the DESCRIBE guard in `main` compares column names case-sensitively (`r[0].as_deref() == Some(col)`, cold_stream.py about line 380) while DuckDB identifiers are case-insensitive. Table with column "Value" and spec column `value`: exe_abort rc 101 "column value is not in the table" (exp_sum.py "column named Value (case)", the only FAIL of ~70). Fix: compare with `eq_ignore_ascii_case`. Liveness only, never wrong.

4. (b) Test-suite blind spots (none produces a wrong answer):
   - tests/test_cold_stream.py line 239 compares `int(want * 10**scale)` with python Decimal in the default 28-digit context; DECIMAL(38,4) sums of extreme cells (up to about 1e32 scaled) can be silently rounded by that multiplication. My comparison used exact strings (`SUM(..)::VARCHAR` with the dot removed) and passed, so no bug, but fix the test.
   - `cold_stream_oneshot._measure` checks `rows_agree` only across cold runs; it never compares the cold ROW with DuckDB's own answer to the reference SQL. The differential test does, the measurement run does not. Add the comparison to the measurement script.
   - All three proved bodies are sums/counts. By construction no order-sensitive result can be "proved wrongly": `cold_finish` only requires `seen.to_multiset() =~= cold_rows(num).to_multiset()`, so a body can use nothing but the multiset; a fixture that needs order simply fails to verify. I found no accepted shape that breaks this. (Combine order: `cold_combine` ensures `a + b` for target-then-source, DuckDB may do either, which is why ZC-2 says "some order"; harmless because only the multiset is used.)

5. (b) `res[0]` in the generated `zc_final` panics (process abort through extern "C", loud) if a future spec's ensures allows an empty result. Not a silent error.

6. (b) Input vectors are required aligned to align_of::<T>() (16 for i128); a sliced vector with an odd offset would be a spurious loud abort. Never seen.

## Attacks that did not break it (count_int, sum_filter, sum_two_cols; each compared with DuckDB's answer to the original SQL)

Reproduce: `uv run python /tmp/claude-1000/adv3/exp_count.py`, `exp_sum.py`, `exp_cap.py` after `heavy.sh uv run python /tmp/claude-1000/adv3/build.py <shapes>` (builds verified 17/0, 22/0, 24/0).
- Vector kind reaching `update` (the flat-vector assumption, F-flat): constant column 500k rows (checkpointed, stats-constant), constant then random, RLE runs, few-distinct dictionary data, ALTER ADD COLUMN DEFAULT (constant-filled scan) with and without UPDATE, DELETE/UPDATE/CHECKPOINT, extra columns, generated virtual columns (constant `AS (3)` and `x % 4`), views: constant projection, filtered view (sliced vectors) over random and over constant column, LIMIT/OFFSET, UNION ALL, BIGINT->INTEGER cast view, DECIMAL(38,4) views, two-column filtered view, one constant + one random column. All equal DuckDB. DuckDB 1.5.4's C aggregate wrapper delivers flat vectors in every case.
- Sizes: 0 rows, 1 row, 500k, 6,001,215 rows (exactly the cap: correct) and 6,001,216 (aborts "more rows than the catalog row cap", loud).
- NULL: at positions 0, 63, 64, 2047, 2048, 122879, 122880, last, all-NULL, in either column of the two-column shape: always abort (rc 101). A view that filters the NULLs out passes correctly (no NULL reaches update).
- Caps: cell = cap and mixed +-cap on 400k rows (sum 1.8e28 and 1.2e28, exact equal to DuckDB); cap+1 and -cap-1 (even a single row) abort; DECIMAL(38,4) max value aborts.
- Declared vs stored type: DECIMAL(38,2), (18,4), (37,4), HUGEINT, DOUBLE, VARCHAR for the 38,4 column; DECIMAL(18,2) (same i64 width), (15,3), BIGINT for the two-column one: all refused by the DESCRIBE guard before any query. Thresholds 5000.0000 / 5000.0001 right.
- Threads (glue edited to `SET threads=1/3/32`, `preserve_insertion_order=false`; compiled with --no-verify, count_int only): all give 199374 = DuckDB. Combine paths with many/few states are exercised.
- Verus mutations (via the test's `_verus`): count: rows counter not advanced -> 16 verified 1 error; wrong predicate -> 1 error; two-column mask differs from hit predicate -> 1 error; harmless rewrite of the combine -> 17/0 (control). With the author's four this covers drop-partial, predicate, cap, permutation lemma.
- Library review (cold_lib.rs): no external_body/assume/admit; `lemma_sum_by_perm` has a real induction over remove/index_of; `sum_by` is the plain left fold; bound lemma used for the i128 no-overflow argument (2^31 rows times cap). `cold_update`'s requires are discharged by the glue's checks (rows+n <= cap, equal lengths because both slices use the same `n`, same state pointer). The glue's `Ghost::assume_new()` leaves the ghost sequences unconstrained exactly as the doc says; nothing else is unconstrained.

## Measurement review (no re-measurement)

- Reference runs the original SQL (with WHERE) on the same connection, same thread setting, same result-materialisation path (`query`), 2 warm-ups: fair, and conservative for the claim in one respect (DuckDB's filter pushdown/zone maps help the reference only; the fold always scans every row).
- "cold" is a misnomer: the reported medians are buffer-hot (2 warm-ups, median of 9). Only `COLD_FIRST_US` is cold and the reference has no first-run number, so the table's ratios must be read as "hot, one process". The old sequential layout ran the reference after the fold had warmed the buffer; the author's uncommitted interleaved version fixes that bias, so the table must be regenerated with it before it is quoted.
- The 0.91x on DECIMAL(38,4) is plausible because the fold replaces DuckDB's overflow-checked 128-bit add with a cap check fused into the same pass (a different, proved guarantee), not evidence DuckDB is slow.

## Not checked

DuckDB versions other than 1.5.4 (version assert refuses them); a persisted catalog object already named `zc_cold`; tables above 6M rows or a SEC-size (39.4M) table (memory rule; the 39.4M run is the author's); a GROUP BY with vector-aligned groups (finding 2, reasoned only); concurrent queries on the same connection; the production libduckdb link; timing.

## Opinion

ZC-2 is small (five items) and honest. Items 1, 2 and 4 are checked at run time (flat/aligned/NULL-free, equal lengths, state memory via unaligned words). Item 3 is the single unchecked assumption and finding 1 closes most of it for one cheap query. With finding 1 and 3 fixed I would switch it on (opt-in) for the three supported shapes.

Gate criteria from my own evidence: C2 (adversary verdict): this file, SOUND after fixes once finding 1 lands. C3 refusals: met (type/NULL/cap/row-cap/shape refusals all loud in my runs). C4 differential: met (reproduced ~70 scenarios, 0 differences). C5 small reviewed trusted statement: met subject to finding 1. C6 order independence proved: met (mutations fail, control passes; permutation lemma real). C7 DuckDB 1.5.x: partial, unchanged. C8 production link: unmet, not examined. C9 shapes: partial, unchanged. C1 (timing): not assessed; see measurement review for what must be redone.
