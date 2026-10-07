# Zero-copy lease: reliability gate (LEMMA_ZERO_COPY=1)

The zero-copy path is an OPTIONAL path. It is switched on only by `LEMMA_ZERO_COPY=1`, never chosen silently, and has no fallback in either direction:
a query it cannot run is refused at assemble time with the exact reason (`ZeroCopyUnsupported`), a run whose stored types or data differ from the spec aborts loudly.
This file lists the criteria under which Emil should switch it on, and which are met TODAY. Updated 2026-10-05 (branch `worktree-agent-a53c2a0e21969b179`, see the SHA in the last line).

Measurements: SEC `num` (39,401,761 rows) and TPC-H SF1 `lineitem`, DuckDB 1.5.4 (the python wheel's own C API, prototype link), median of 9 binary starts, kernel = each
binary's own median of 9, three load paths per shape with a Verus-proved body each: **shipped** = the streaming bulk exporter on main + file read + checks; **copy** = native
C-API pin + memcpy into Vecs; **zero** = native pin + borrowed chunks. Taken in a quiet window (1-minute load below 3 before, CPU used by other processes during the window
below 1.5 cores, both recorded in `research_loop/generated/pin_work/r_*.json`); windows that failed this were discarded and redone.

| shape | DuckDB in place | shipped one-shot | copy one-shot (kernel) | zero one-shot (kernel) | zero vs copy, one-shot | zero vs copy, kernel |
|---|---|---|---|---|---|---|
| `SUM(DECIMAL(38,4)) WHERE`, sequential | 238 ms | 37.41 s | 1,279 ms (29 ms) | 1,164 ms (78 ms) | 9% faster | 2.6x SLOWER |
| same, parallel (8 threads) | 243 ms | 37.77 s | 1,293 ms (19 ms) | 1,092 ms (20 ms) | 16% faster | 1.08x (tie) |
| `COUNT(*) WHERE qtrs = 3` (INTEGER, i32) | 14.7 ms | 964 ms | 288 ms (5.3 ms) | 263 ms (29.6 ms) | 8% faster | 5.5x SLOWER |
| `SUM(DECIMAL(15,2)) WHERE` over two columns (TPC-H, i64) | 6.6 ms | 474 ms | 151 ms (5.0 ms) | 114 ms (8.5 ms) | 24% faster | 1.7x SLOWER |

## Criteria

| # | Criterion | Today | Evidence |
|---|---|---|---|
| G1 | Adversary verdict SOUND on the hardened version, no open silent-wrong-answer finding | **MET** (fixes landed, not re-reviewed) | round 1: SOUND after fixes (F1 F2 F3 F7, fixed); round 2 (`zero_copy_lease_ADVERSARY_VERDICT_2.md`): SOUND after fixes: finding 1 (spec not bound to the schema model: silent NULL) fixed by the `IN_TYPES` binding, findings 2 (DATE infinity), 3 (version assert), 4 (escaping), 5 (order test), 7 (docs) fixed, each with tests; no hole in the verified library, none on DuckDB 1.5.4 |
| G2 | Every shape is supported or refused loudly, with the reason; refusals are counted | **MET** (mechanism) / unmeasured on arena rounds | `tests/test_zero_copy.py` (22 tests: strings, dictionaries, validity masks, floats, two tables, wrong width/type/scale, names), `zero_copy_round.py classify` reports supported / refused / no_spec per query; no arena round was available yet |
| G3 | No new trusted code beyond ZC-1 | **MET** | `tests/test_zero_copy_trust.py`: no `external_body`/`assume`/`admit` in the verified library, the `unsafe` code is the plain-Rust C-API pin (`zero_copy_ffi.rs`) and the slice borrow in the generated `main`; none is in verified code |
| G4 | Strictly opt-in, default off, no fallback either way | **MET** | tests: flag only `1` means on, assembly refuses without it, no code path chooses the other path |
| G5 | 0 differences in a randomized differential run against the copy path and DuckDB | **MET** (permutation-invariant bodies) + order check | `tests/test_zero_copy_differential.py`: 4 proved shapes x {uniform, constant, sorted, extreme, nothing-matches} x sizes {0, 1, 2, 2047, 2048, 2049, 4103, 20000, 123000, 250001} x seeds = 328 generated tables, zero == copy == DuckDB on every one. The proved bodies are SUM/COUNT (permutation-invariant), so `tests/test_zero_copy_order.py` also compares the pin's cell sequence with DuckDB's row order after DELETE/UPDATE/INSERT growth, several storage types, constant vectors and views |
| G6 | Works on DuckDB 1.5.x | **PARTIAL** | the four shapes run on the real 1.5.4 databases through the python wheel's C API; the repo's `build/libduckdb` is 1.2.2 and cannot open them. A production build must link a libduckdb 1.5.x release (not present on this machine; the release zip is about 32 MB, I did not download it) |
| G7 | One-shot (pin + checks + kernel) at least 2x faster than the shipped exporter + copy | **MET, but not because of zero-copy** | zero 3.7x / 4.2x / 32x / 34x vs shipped; the native copy loader gets 3.4x / 3.1x / 29x / 29x. Zero-copy adds 8 to 24 percent over the copy loader |
| G8 | Not slower than the native copy loader on the kernel (25 percent tie band) | **UNMET** | 2.6x, 5.5x, 1.7x slower on memory-bound scans; tie only on the 8-thread parallel DECIMAL(38,4) |
| G9 | Break-even against DuckDB in place is finite | **UNMET on 2 of 4** | `COUNT` over i32 and the two-column i64 sum: the borrowed kernel is slower than DuckDB's all-core scan, break-even `never` (copy: 31 and 90 queries) |
| G10 | Consistent on unseen queries (supported/6, correct/supported, faster than copy/supported over at least 3 arena rounds) | **UNMET (not measured)** | the arena had no round when this was written |
| G11 | Production link (a libduckdb 1.5.x release, not the python-wheel prototype link) | **UNMET** | `research_loop/scripts/zero_copy_oneshot.py::python_wheel_link` is a prototype hack (it also needs libpython) |

## Why G8 and G9 fail (the general cause)

The kernel loop is not the problem: the same chunk loop over ONE contiguous allocation split into the same chunks runs at flat-Vec speed (9.2 to 12.4 ms vs 10.3 to 15.0 ms flat, `count` over 39.4M i32),
and over per-chunk Vecs of my own at 15.3 ms. Over the buffers DuckDB hands out it takes 28 to 37 ms. Consecutive chunks' column buffers sit 16,384 bytes apart for 8,192 bytes of data
(round 2 confirmed 14,626 of 14,648 steps), at irregular strides in the Arrow export of the same result (24.0 ms vs 11.0 ms flat). Round 2 showed the 16,384 number itself is not the cause: a synthetic 16 KiB or 12 KiB
stride, and even a dense layout visited in shuffled chunk order, reproduce the slowdown, so the cost is non-adjacent chunks (no streaming across chunk boundaries). Software prefetch results disagree: in my runs
next-chunk prefetch did not help (37 ms vs 37 ms, also 2 and 4 chunks ahead and same-offset), in the adversary's run (load 0.8 to 1.0) same-offset next-chunk prefetch took 24 ms to 14 ms; treat prefetch as
unproven. A memory-bound scan over borrowed DuckDB chunks therefore runs about 2 to 2.5x slower than over a compacted copy, which is why the copy that zero-copy avoids (53 to 265 ms) is paid back by the first repeated
query. Compute-bound kernels (the 8-thread i128 sum) hide it.

## Recommendation

**Do not switch it on today.** Use the native C-API loader (copy mode) for the one-shot win over the shipped exporter (3x on INTEGER-width columns, 29x on DECIMAL(38,4), where the
shipped exporter spends 36 s): it needs no new trusted statement beyond the pin code. Zero-copy is worth enabling only for a single-use query on a wide fixed-width column where the 100 to
270 ms memcpy and the second resident copy matter and the kernel is compute-bound or parallel, and only after G1, G10 and G11.


# Cold stream path (LEMMA_COLD_STREAM=1): the proved fold as a DuckDB aggregate

A second OPTIONAL path (same rules: opt-in, no fallback, loud refusals) that removes the load step instead of shortening it: DuckDB's own parallel scan calls the proved fold once per vector
(`declarative_spec/cold_stream.py`, `cold_lib.rs`, `tests/fixtures/declarative_proofs/cold_*.rs`, design and numbers in `cold_path_feasibility.md`). Trusted statement ZC-2 (stated there).

| shape | DuckDB in place | cold e2e | ratio |
|---|---|---|---|
| `SUM(DECIMAL(38,4)) WHERE` (39.4M rows) | 282 ms | 258 ms | 0.91x |
| `COUNT(*) WHERE qtrs = 3` (39.4M rows) | 14.4 ms | 20.2 ms | 1.40x |
| two-column `SUM(DECIMAL(15,2)) WHERE` (TPC-H 6M rows) | 6.3 ms | 9.4 ms | 1.48x |

| # | Criterion | Today | Evidence |
|---|---|---|---|
| C1 | Cold e2e within about 1.5x of DuckDB in place on the shapes | **MET** | table above, quiet windows recorded in `pin_work/v2_*.json` (load before, other-process CPU during) |
| C2 | Adversary verdict SOUND, no open silent-wrong-answer finding | **PENDING** | `cold_stream_ADVERSARY_VERDICT.md` |
| C3 | Loud refusal of everything outside the shape | **MET** | `tests/test_cold_stream.py`: parallel spec, result shape, strings/dictionaries/validity/floats/two tables, stored type, declared-vs-spec type, missing markers |
| C4 | Differential against DuckDB | **MET** | `test_cold_fold_equals_duckdb_on_generated_tables` (three shapes, uniform / constant / sorted / extreme / nothing-matches data, sizes 0 to 250,001), delete/update/insert/constant/dictionary storage, aborts on NULL, wrong stored type, cell outside the cap |
| C5 | New trusted statement small and reviewed | **PENDING review** | ZC-2 (five items); no new `external_body`/`assume` in Verus code (test) |
| C6 | Order independence proved, not assumed | **MET** | `lemma_sum_by_perm` (multiset equality gives equal sums), mutation tests: dropping the permutation lemma, a wrong predicate, a merge that drops a partial, no cap check all fail to verify |
| C7 | Works on DuckDB 1.5.x | **PARTIAL** | python-wheel C API (v1.5.4), version asserted; the aggregate C API needs DuckDB 1.3+ (the repo's libduckdb 1.2.2 has none) |
| C8 | Production link (libduckdb 1.5.x release) | **UNMET** | prototype link only |
| C9 | Shapes covered | **PARTIAL** | ungrouped SUM/COUNT of per-row terms over fixed-width native columns, no NULL; GROUP BY, MIN/MAX, AVG, joins, strings not built (refused) |


## Revision 3 of the cold stream path (2026-10-07): measured with the x86-64-v3 build, scalar mode

The table above was measured on a baseline-SSE2 build (the cold/zero-copy compile helper omitted `LEMMA_TARGET_CPU`, default `x86-64-v3` on main). With the fix and the scalar-function mode (details and trusted statement ZC-2s in `cold_path_feasibility.md`, revision 3):

| shape | DuckDB in place | cold e2e (scalar mode) | ratio |
|---|---|---|---|
| `SUM(DECIMAL(38,4)) WHERE` (SEC `num`, 39.4M rows) | 235 ms | 204 ms | 0.87x |
| `COUNT(*) WHERE qtrs = 3` (SEC `num`, 39.4M rows) | 12.2 ms | 7.9 ms | 0.65x |
| two-column `SUM(DECIMAL(15,2)) WHERE`, TPC-H SF1 (6.0M rows) | 5.4 ms | 4.7 ms | 0.87x |
| the same, TPC-H SF10 (60.0M rows) | 34.9 ms | 27.7 ms | 0.79x |

C1 (within 1.5x of in place): **MET, and below 1.0x on every shape** (aggregate mode is 0.91 / 1.16 / 1.18 / 1.11). C2 (adversary): round 1 verdict `cold_stream_ADVERSARY_VERDICT.md` SOUND after fixes (rows-seen check, case-insensitive DESCRIBE, DISTINCT/GROUP BY/OVER/FILTER/JOIN refused: landed);
round 2 on the scalar mode, the cap-free proofs and the build flags: `cold_stream_ADVERSARY_VERDICT_2.md`. The proofs for the i64 / i32 shapes no longer assume catalog caps (stronger theorem). C8 (production link) is unchanged: UNMET.
