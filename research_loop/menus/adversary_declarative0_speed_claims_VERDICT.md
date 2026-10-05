# Adversary verdict: speed claims of the declarative path (SEC selective scan, TPC-H Q6, one-shot cost)

Reviewer: separate manual-adversary Sonnet subagent, 2026-10-05. Box: 8 logical cores (`nproc` = 8), DuckDB 1.5.4, `SELECT current_setting('threads')` = 8, MemAvailable ~6.9 GB at start.
All timed runs: `flock /tmp/lemma_timing.lock systemd-run --user --scope -p MemoryMax=8G -p MemorySwapMax=0 uv run python <script>`; scripts live in the session scratchpad
(`adv.py`, `adv_q6.py`, `viol.py`, `export_time.py`). The provers of the claimed numbers were manual Sonnet subagents, not a model agent; none of these numbers is a model-agent result.

## Verdicts

| Claim | Verdict |
|---|---|
| SEC scan: 9.5 ms vs 22.9 ms, 2.4x (narrow, profiled package) | **HOLDS WITH CONDITION** (kernel-only, margin-1 approved package, 8-core box; I measure 2.58x vs the in-place reference, but 1.84x vs a better reference) |
| SEC scan: 1.38x with wide cells; 0.69x before | **HOLDS** as stated; I did not re-measure (needs a wide-cell rebuild). The jsonl rows agree with one another. |
| TPC-H Q6 variant SF10: 20-25 ms vs 58 ms, 2.4-2.9x | **HOLDS WITH CONDITION** for 2.4x-2.5x (I measure 22.9 vs 57.3 = 2.50x); the **2.9x end is BIASED** (see below). Better reference: 2.07x. |
| One-shot cost: pin + encode ~1.0 s, load 0.2-0.5 s, break-even 50-1400 | **BIASED / UNSUPPORTED as a description of the shipped code.** The 1.0 s is a vectorized numpy proxy the repo does not run; the exporter that actually produces the column files costs about 35x more (below). Break-even for the real path is about 2600 queries, not 91. |

## What I measured (numbers, with commands)

### M1. SEC scan, same window, alternating, 11 rounds, medians (script `adv.py 11`)
Reference variants rotate their order per round; the binary (`nc_Bm1/declarative_build/declarative_query`, started fresh each round, its own 9 timed runs, median) runs once per round.

| Side | median us | best | worst |
|---|---|---|---|
| A. DuckDB, file DB, default settings (what the bar uses) | 23344 | 22605 | 27670 |
| B. DuckDB, file DB, `SET preserve_insertion_order=false` | 23168 | 22618 | 26972 |
| C. DuckDB, in-memory pre-narrowed copy (`ddate INTEGER, qtrs SMALLINT, uom ENUM`, 0.5 s to build with `CREATE TABLE ... AS`) | 16699 | 16340 | 21062 |
| D. same as C with `preserve_insertion_order=false` | 16609 | 16414 | 23293 |
| Binary kernel (median of its 9 runs) | 9065 | 8175 | 11525 |
| Binary LOAD_US (outside the timer) | 221984 | 184049 | 322338 |
| `SELECT 1` through the same Python client (fixed per-call overhead) | 634 | 566 | 730 |

Speedup of the binary: 2.58x vs A, 2.56x vs B, **1.84x vs C**, 1.83x vs D. Result row from DuckDB: (346584, 20250331), identical to the expected row.
The reference thread count is not the problem: it uses all 8 cores like the binary. `preserve_insertion_order` changes nothing here (23.3 vs 23.2 ms).
What closes a third of the gap is data layout: a reference allowed to scan the same narrow in-memory vectors we scan runs at 16.7 ms. The headline compares our prepared narrow vectors with the reference scanning compressed, wide on-disk columns (INTEGER qtrs, VARCHAR uom).
The reference time includes 0.6 ms of Python/plan overhead the binary's timer does not (about 2.5 percent of 23 ms); ignoring it gives 2.5x, still within the claim.

### M2. TPC-H Q6 variant, SF10 (59,986,052 rows), same method (script `adv_q6.py 11`)

| Side | median us | best | worst |
|---|---|---|---|
| A. file DB default | 57308 | 56592 | 60898 |
| B. file DB, pio false | 57298 | 56358 | 62085 |
| C. in-memory narrow copy (`DECIMAL(4,2)` discount and quantity, `DECIMAL(9,2)` price; 0.7 s to build) | 47401 | 46800 | 50635 |
| D. C with pio false | 47137 | 46554 | 49321 |
| Binary kernel | 22949 | 20852 | 24132 |
| Binary LOAD_US | 484146 | 418119 | 634700 |

Speedup: 2.50x vs A, 2.50x vs B, **2.07x vs C**, 2.05x vs D. The in-memory reference was given only caps the package states (price < 2^24 at scale 2 fits DECIMAL(9,2) with room), so this is the same assumption set, not a free lunch.
Bar numbers recorded in `decl_data/bar.json` and `last_check.json` for the same workspace: `duck_us` 58854, `speedup` 2.86 (kernel 20586). My same-window reference is 57.3 ms.

### M3. Bar numbers measured at prepare time vs the same window
`nc_Bm1/decl_data/expect.json` `duck_us` = **27062** (median of 5, taken right after the export); same-window medians were 23344 (mine) and 22926 (`decl_oneshot.jsonl`, `B_fast_slices`). The reference is 16 percent slower in the prepare-time number. The `speedup` field in `nc_Bm1/last_check.json` is therefore **2.91x** (27062 / 9286), against 2.4x-2.58x in a same-window comparison. The 2.9x end of the Q6 range comes from the same mechanism and is not re-found in a same window (2.50x). The pipeline reports whichever `duck_us` was frozen at prepare time, and a quoted range that mixes `last_check.json` speedups with same-window ones mixes two measurements.

### M4. Violating the profiled caps (script `viol.py`; 20,000-row DuckDB copies of `num`, real package `sec_real_m1_pkg.json`, real `write_query_measure`)

| Mutation | Outcome |
|---|---|
| baseline | accepted |
| one `qtrs = 5000` (package cap 4096, fits i16) | **accepted silently** |
| one `ddate = 2000000000` (package cap 2^25, fits i32) | **accepted silently** |
| one `qtrs = 40000` (does not fit i16) | refused: `ValueError: cannot pack 40000 as i16` |
| 400 distinct `uom` (package says 256, u8 codes) | refused: `ValueError: cannot pack 256 as u8` |

So the refusal is loud only when a cell leaves the machine width. A cap violated inside the width is accepted; this is already the open Finding A of `adversary_declarative0_narrow_cells_VERDICT.md` (integer caps are only a claim `check.py` measures). For this particular body the answer cannot change from a cap violation inside the width (cells are read as ints), but any sum bound derived from the cap would rest on an unchecked claim.

### M5. What the real exporter costs (script `export_time.py`)
`write_query_measure` (the code that writes `cols_num.bin`: `fetchmany` plus a Python `struct.pack` per cell) on 2,000,000 rows of `num`: 1.8 s total (including the 7 DuckDB timing runs on the small table). Linear extrapolation to 39.4M rows: **about 36 s**. `declarative_oneshot.py` reports `pin_encode_us` of 0.99 s for the same table, because it times a different thing: one DuckDB projection with SQL `CAST`s and `enum_code`, materialized as numpy arrays. That path is not used to make the column files and does not write a file.

## Findings, in the order asked

1. **Outside the timer.** The timer in `assemble._timed_runs` wraps only `run_query(...)` (thread spawn and the result Vec are inside; `println` is outside). Outside it: reading the 275 MB column file, the byte-by-byte decode into Vecs, the cell/requirement checks (`LOAD_US`, 0.18-0.32 s on SEC, 0.42-0.63 s on Q6), the export itself (Python pack, about 36 s extrapolated), the DuckDB pin, process start and page cache. `load_us` is returned by the pipeline in the metrics but `speedup` is `duck_us / latency_us` only, and the speed-bar failure/success text says "x faster than DuckDB" without saying it is kernel-only. The one-shot numbers exist only in a separate script and a jsonl file. In `declarative_spec/prompt.py` the kernel-only numbers are quoted without any qualifier ("12.8x faster than the all-core reference engine", "13x on the real 39.4M-row table", "TPC-H Q1 at 3.95x", "20.8 ms to 9.3 ms"). The 13x example's own row in `decl_oneshot.jsonl` (`SUM_value_filter_SEC`) has `pin_encode_us` = 22.4 s and `one_shot_speedup` 0.01.
   In `decl_oneshot.jsonl` every row has `one_shot_speedup` between 0.01 and 0.03: a first query on freshly pinned data is 30 to 100 times slower than the reference answering in place.
2. **Reference side.** Threads: 8 = nproc, fair. Warmth: reference warmed (2 warmups, in-process file buffers), binary data fully resident: fair. Materialization: both materialize a one-row result; the reference additionally pays 0.6 ms of client and parse overhead: negligible. `preserve_insertion_order=false`: no effect (M1, M2). **Layout is the bias**: a reference that scans pre-narrowed in-memory copies of the same columns is 1.84x (SEC) and 2.07x (Q6) behind us, not 2.4x-2.6x. The reference is slower than it could be mostly because it scans wide compressed columns while we scan vectors prepared from them.
3. **Correctness side.** `_apply_speed_bar` compares the binary's printed rows with `expect.json` rows (computed by DuckDB on the full table), for kinds `int`/`float`/`str`, by position, exact for ints, relative 1e-9 for floats, with count mismatch refused. It reads the stdout of the run, and the printing happens only in the **last** (9th) timed run (`if s == TIMED_RUNS - 1`); runs 1-8, the ones that set the median, are not compared. A body that skipped rows would fail on a result that depends on them, but for an aggregate whose value it happens to reproduce (or a hard-coded constant) the row check alone cannot tell; only the Verus proof rules that out. So the check is a sanity check on the official table, not a second line of defence, and a fast-but-skipping body is stopped by the proof, not by the comparison. I did not find a gap in the proof path (not in scope).
4. **Caps tuned to our data.** The package `sec_real_m1_pkg.json` was measured on this table at margin 1 (uom 201 distinct rounded to 256, qtrs max 3604 rounded to 4096, ddate < 2^25). The default-margin package `sec_real_pkg.json` (margin 4) says `uom` max_distinct **1024**, which selects **u16** dictionary codes (`string_encoding.code_type`: u8 only up to 256). So the 2.4x is a margin-1 result: a default profiler run would load uom as u16 and scan more bytes (not re-measured: it needs a rebuilt body). Data that breaks the width is refused loudly (M4); data that breaks the cap inside the width is accepted. The speedup is available only because of assumptions the user has to approve (width of every touched column; they are claims about all future data), and a refreshed table with more than 256 distinct `uom` or `qtrs` beyond 32767 makes the export fail until the package is re-approved.
5. **Selection effects.** Quoted numbers are medians (binary: median of 9 runs, median of 3 starts in `declarative_oneshot.py`; reference median of 9 in the same window). `kernel_best_us` is stored but not used for headlines. The jsonl rows include the failures to improve (1.04x unsliced, 1.38x wide), so I found no best-of cherry-picking. The spread is real: binary 8.2-11.5 ms, reference 22.6-27.7 ms on one box with other processes (about 30 percent worst/best). The weakness is the mixture: ranges combine `duck_us` frozen at prepare time with same-window values (finding M3).
6. **Provenance.** All the cited numbers were produced by manual Sonnet provers who wrote the bodies with the sliced-loop recipe, knew the numbers, and iterated on the timing. Not a model-agent result, not blind. The prompt in the repo now teaches the sliced recipe, so a later model-agent result may differ either way.
7. **Other biases.** (a) The jsonl `break_even_queries` assumes the reference rescans on every repeat; a result cache or a pre-materialized in-memory table in the reference (C/D above) shifts it. (b) The oneshot script measures encoding with a SQL projection (1 s) that the repo does not use for the real export (M5); that understates the one-shot cost by about 35x. (c) The speedups are single-query, single-user: the binary spawns 8 threads per call and the reference is also parallel, so concurrent clients would divide both, not scale ours. (d) 1-thread reference (`duck1_us`, `speedup_1t` 10.4x) is also stored by the pipeline; it is not a fair headline but is not quoted in the claims.

## Conditions that must accompany any quoted speedup
1. "Kernel only: excludes the one-shot cost." Next to it, the one-shot number: about 1.2-1.7 s with the numpy proxy path (not the shipped exporter), about 36 s for the shipped Python exporter on 39.4M rows, plus 0.2-0.5 s load. First-query one-shot speedup is 0.01-0.03x.
2. "Break-even N repeated queries, prep amortized, on the same pinned data": recompute with the shipped exporter (about 2600 on SEC sliced, not 91).
3. "Measured against the reference scanning its own compressed wide columns in place; against an in-memory pre-narrowed copy the speedup is 1.8x (SEC scan) and 2.1x (Q6)."
4. "Same window, median of at least 9, 8 threads on both sides (8-core machine), kernel median of the binary's own 9 runs." Do not use `duck_us` from `expect.json` (prepare time, 16 percent high on SEC).
5. "Under a user-approved assumption package measured on this data at margin 1 (u8 `uom` codes need at most 256 distinct values; i16 `qtrs`; i32 `ddate`; Q6: i8/i16/i32 scaled cells). A default-margin package gives u16 codes and a smaller speedup. Cap violations that stay inside the machine width are not refused (Finding A)."
6. "Manual prover, not a model-agent result."

## Required fixes
1. `declarative_spec/pipeline._apply_speed_bar`: put `load_us` and an explicit `kernel_only: true` next to `speedup` in the result and in the failure text; stop describing the bar as "x faster than DuckDB" without "kernel-only".
2. Measure the reference in the same window as the binary at check time, not at prepare time (or re-time it inside `check`); store both and quote the same-window value. Today the stored `duck_us` can be 16 percent off.
3. Add the better reference to `decl_query_measure` (an in-memory pre-narrowed copy of the touched columns, and `preserve_insertion_order=false`) as a stored `duck_mem_us`, and report the speedup against both. The in-memory copy is a one-statement `CREATE TABLE AS` (0.5-0.7 s).
4. `declarative_oneshot.py`: time the real exporter (`write_query_measure` / `_export_table`) as `export_us`, or make the exporter vectorized and then say so. Do not label the numpy projection `pin_encode_us` as the cost of the pipeline.
5. `assemble._timed_runs`: compare the printed result on every timed run (or at least the first and last), not only the last.
6. `declarative_spec/prompt.py`: add "kernel only" to the quoted multipliers (12.8x, 13x, 3.95x, 9.3 ms) or drop them; the 13x example costs 22 s to pin and encode.
7. Report the package margin and the code widths chosen next to a narrow-cell speedup; refuse or flag a package whose `max_distinct` selects a wider code than the measured data needs only if the user asks for the smaller width; at minimum print the width that was picked.
8. Finding A of the narrow-cells verdict (emit and assert the integer cap conjunct) still stands; M4 shows `qtrs=5000` and `ddate=2e9` loading under caps 4096 and 2^25.
