# Cold path feasibility: streaming chunk fold (checkpoint, 2026-10-05) — verdict: GO on hook (a), the aggregate UDF

Question (Emil): make a single, already-proved query competitive with DuckDB answering in place, by never materializing the column: let DuckDB's own parallel scan hand our proved fold its
vectors. Goal: cold end to end within about 1.5x of DuckDB in place, or a measured reason why not.

Prototype: `/tmp/claude-1000/zc/cold.rs` (plain Rust, DuckDB 1.5.4 through the python wheel's C API, real `sec_edgar_dec.duckdb`, `cold_tpch.rs` for TPC-H SF1). All numbers: median of 9 after one
warm-up, same process and connection, DuckDB's own `SUM`/`COUNT` as the in-place reference, machine load 0.5 to 3.9 (my own 8 threads included; the final measurement will be redone in a recorded quiet window). "first" is the first execution (cold buffer).

| hook | what it needs | sum DECIMAL(38,4) (39.4M rows) | count INTEGER (39.4M) | two-col DECIMAL(15,2) (6M) |
|---|---|---|---|---|
| DuckDB in place (builtin SUM/COUNT with WHERE) | nothing | 235 ms (first 551) | 14.1 ms (first 47.7) | 7.6 ms (first 52) |
| **(a) C-API aggregate UDF** (`duckdb_create_aggregate_function`, `SELECT f(col) FROM t`) | the aggregate-function C API (in the python wheel's `_duckdb.so`, 1.5.4) | **222 ms = 0.95x** (first 607) | **15.6 ms = 1.11x** (first 26.6) | **14.1 ms = 1.87x** (first 33.6) |
| (c) N connections, each streaming `WHERE rowid >= lo AND rowid < hi`, own fold, 8 / 4 / 16 threads | `duckdb_prepare`, `duckdb_execute_prepared_streaming`, `duckdb_fetch_chunk` | 379 / 343 / 397 ms = 1.6 / 1.5 / 1.7x | 53 / 46 / 79 ms = 3.8 / 3.2 / 5.6x | not run |
| (b) `lemma_storage` (`DataTable::ScanTableSegment`) | `duckdb.hpp` and the matching static library of the SAME version as the database | **NO-GO**: the repo ships duckdb.hpp / libduckdb_static.a of v1.2.2 (`build/libduckdb`), the databases are 1.5.4 files; DuckDB's C++ internals are not an API, and no 1.5.x headers or library are on this machine (a 1.5.x release zip is about 32 MB; not downloaded) | | |
| (d) the existing pin (materialize, then fold chunks in parallel) | `duckdb_query` + `duckdb_result_get_chunk` | 0.9 s pin before any fold (4x in place) | 0.19 s (14x) | 87 ms (12x) | 

Results are the same as DuckDB's on every run (sum 16240211051726890907327 scaled = 1624021105172689090.7327, count 3,118,445, two-column 49,660,095,033.50).

## Recommendation: GO, hook (a)

* DuckDB drives its own multi-threaded scan and calls our `update` once per vector (cache-hot, no copy, no pin, no file), `combine` across threads, `finalize` once. The kernel is already parallel, so the
  hand-written 8-thread proof is not needed any more: only a chunk fold and a merge are proved.
* Cold (data still in DuckDB's storage/buffer): 0.95x, 1.11x, 1.87x of in place. The two-column sum is 1.87x (6M rows, 14 ms): above the 1.5x goal, below 3x; the UDF path goes through DuckDB's hash-aggregate
  machinery with a constant group, and our per-vector fold adds an i128 accumulation, so the floor is a few ms. I will try to close it (i64 partial sums per vector, overflow-checked); if it cannot be closed the
  report states 1.9x.
* (c) is worse and not needed (single-threaded streaming per connection, DataChunk allocation per fetch); not pursued.

## What hook (a) needs and the trusted layout facts it adds

Nothing new is trusted in Verus code. The proved program is plain Rust with Verus: verified `cold_update(state, chunk slices)`, `cold_combine`, `cold_finish`; the glue that registers the C callbacks and
reads the vectors is plain untrusted Rust, as `main` is today. The statement the glue relies on (call it **ZC-2**; to be adversary-reviewed, small):

> **ZC-2.** The host registers one aggregate function `f` with exactly the declared parameter types of columns `c1..ck` of table `t`, with special NULL handling (NULL rows are delivered, not skipped), and runs
> `SELECT f(c1, ..., ck) FROM t` on the read-only database: NO `WHERE`, NO other operator, so every filter lives inside the proved fold. Then:
> 1. **layout:** in every `update` call, column `j` of the input chunk is a flat vector of native-width values of the declared type (the host checks the validity mask and the type, and aborts via `duckdb_aggregate_function_set_error` otherwise);
> 2. **alignment of rows:** index `i` of the `k` vectors of one `update` call is one row of `t`;
> 3. **exactly once:** over the whole query every row of `t` is delivered in exactly one `update` call into some state, and every state is combined into the final state exactly once before the single `finalize`
>    (so the multiset of delivered rows is the multiset of the rows of `t`; order is arbitrary);
> 4. **state memory:** DuckDB gives `state_size` bytes at ANY alignment (measured: the first prototype crashed with an `i128` field in the state: Rust's 16-byte alignment is not guaranteed), so the state is plain `u64` words.
>
> What Verus proves from these (the part that is NOT trusted): the fold is correct for every arrival order, because the spec of an unordered aggregate (SUM, COUNT, MIN, MAX) is invariant under permutation of the rows;
> the proved `cold_finish` has `requires seen is a permutation of the column` and `ensures` the unchanged declarative `ensures` of `run_query`.
> Not covered (refused loudly): GROUP BY, joins, strings, nullable columns, order-sensitive results, floats, anything with a `WHERE` that would run outside the proof.

What could be false (for the adversary): an engine that delivers a row twice or drops one (a DuckDB bug, or a rewrite such as a top-N / limit pushdown that does not apply to `f(...)` of a bare scan); a non-flat vector
(constant, dictionary) delivered to `update` (the C API aggregate wrapper flattens the chunk; to be tested on constant / dictionary-compressed columns); implicit casts: DuckDB casts a column to the declared
parameter type, a DECIMAL(38,2) column under a DECIMAL(38,4) parameter would be rescaled value-preservingly, but the spec literals are tied to the declared type, so the stored types are still checked by the
assembler (the F1/IN_TYPES machinery of the zero-copy path is reused); a second concurrent query on the same connection.

## Plan if GO (done in this order, behind `LEMMA_COLD_STREAM=1`, default off, no fallback, loud refusals)

1. `declarative_spec/cold_stream.py`: assemble a verified program per query: the spec with a spec-only column type, the proved `update/combine/finish`, plain-Rust glue registering `f` and running `SELECT f(...)`.
2. Worked proofs for the shapes: SUM DECIMAL(38,4) with filter, COUNT over INTEGER, two-column DECIMAL(15,2) sum (a "parallel" shape is the same program: DuckDB parallelizes).
3. Randomized differential test against DuckDB (sizes, constant / sorted / extreme / dictionary-compressed / deleted-rows tables), refusal tests, trust-surface test.
4. Measurement in a recorded quiet window on the four shapes; SEPARATE manual-adversary review with a verdict file; update `arena/FINDINGS.md` and `zero_copy_gate.md`.

## Result of the full implementation (same day): the goal is met on all three shapes

Verified programs (Verus, `declarative_spec/cold_lib.rs` + `tests/fixtures/declarative_proofs/cold_*.rs`): SUM over DECIMAL(38,4) with a filter (22 verified, 0 errors), COUNT over INTEGER (17/0), two-column
DECIMAL(15,2) sum (24/0). The "parallel" shape is the same program: DuckDB parallelizes the scan, so no thread proof exists any more. Quiet window (1-minute load below 3 before, other processes below 1.5 cores
during, both recorded; `research_loop/generated/pin_work/v2_*.json`), median of 9 binary starts, each binary's own median of 9 runs of `SELECT f(cols) FROM t` next to DuckDB's own answer to the original SQL
in the same process and connection:

| shape | DuckDB in place | proved fold as aggregate (cold, data in DuckDB's buffer) | ratio |
|---|---|---|---|
| `SUM(DECIMAL(38,4)) WHERE`, 39.4M rows, 8 threads (DuckDB's) | 282 ms | 258 ms | **0.91x** |
| `COUNT(*) WHERE qtrs = 3` (INTEGER), 39.4M rows | 14.4 ms | 20.2 ms | **1.40x** |
| `SUM(DECIMAL(15,2)) WHERE` over two columns, TPC-H 6M rows | 6.3 ms | 9.4 ms | **1.48x** |

Against the previous paths on the same shapes (one-shot, from `zero_copy_gate.md`): shipped exporter 37.4 s / 0.96 s / 0.47 s, native copy 1.28 s / 0.29 s / 0.15 s, zero-copy 1.16 s / 0.26 s / 0.11 s.
The first execution (cold buffer, `COLD_FIRST_US`) is 390 / 34 / 33 ms.

What it took (general causes, found by measurement):
* A data-dependent branch in the fold is the cost: on random data the branchy two-column sum was 2.1x (14 ms), the same loop with an arithmetic mask (`p & -(hit as i64)`) and the cap check fused into one pass
  is 1.48x; touching the memory alone is 1.3x. The Verus bodies are written branch-free (bool as integer, no `||` on bools: Verus has no non-short-circuit bool OR, so the violation count is an integer).
* DuckDB gives aggregate state memory at ANY alignment: a state with an `i128` field crashed the first prototype (`movaps`). The state is plain `u64` words.
* The framework itself costs nothing: a no-op aggregate takes as long as DuckDB's own SUM (5.1 vs 5.2 ms on the two-column table).


## Revision 3 (2026-10-07): every shape below 1.0x, in the scalar-function mode, at two scales

What changed since the table above (which was measured on a baseline-SSE2 build and with sequential reference timing):

1. **The build was not x86-64-v3.** `zero_copy_oneshot._compile` (used by the zero-copy and cold paths) did not pass `LEMMA_TARGET_CPU` (the shipped pipeline defaults to `x86-64-v3`, AVX2). The verified fold ran 7.3 us per 2048-row vector
   baseline and 1.9 us with AVX2 (instrumented per-call timers, SF10 two-column sum). Fixed (`declarative_spec.pipeline.target_cpu_rustc_args`). Every earlier cold ratio in this file (0.91 / 1.40 / 1.48) and in `zero_copy_gate.md` predates the fix.
2. **Interleaved reference.** The reference (DuckDB answering the original SQL on the same connection) is timed run for run with the fold, not in a later phase.
3. **No catalog cap in the i64 / i32 proofs.** `cold_sum_two_cols.rs` and `cold_count_int.rs` assume nothing about the cells: an `i64` cell is at most 2^63 in magnitude, so fewer than 2^62 of them sum into an `i128` whatever the data is (a theorem stronger than the
   declarative one, which also required `|cell| < 10^15`); the per-cell cap compare (4 compares and 4 adds per row) is gone. `cold_sum_filter.rs` (`i128` cells) keeps its cap check: without it the sum can overflow.
4. **Scalar mode** (`LEMMA_COLD_STREAM_MODE=scalar`, default `aggregate`). The C-API aggregate goes through DuckDB's hash-aggregate machinery even for an ungrouped query (a vector of 2048 state pointers per call, group lookup);
   a scalar function is called once per vector inside a projection, returns a CONSTANT vector (`duckdb_vector_reference_value`: no per-row write) that `COALESCE(MAX(...), 0)` consumes, and folds into a per-worker-thread state; after the query the host merges the thread states with
   the verified `cold_combine` and finishes with the verified `cold_finish`. Profile (39.4M-row INTEGER column, same connection, 3 GB / 8 threads): builtin `COUNT WHERE` 11.0 ms; aggregate no-op 11.4-13.0 ms (the framework alone is as slow as DuckDB's own filtered count);
   scalar no-op 6.1 ms; scalar fold 7.1 ms. The verified program is byte-identical in both modes (test); only the plain-Rust glue differs.
5. **Settings.** Every connection (fold and reference alike): `PRAGMA memory_limit='3GB'`, `PRAGMA threads=8`, `PRAGMA temp_directory`; recorded in the result rows.

Measured (heavy.sh slot, load below 3 before and other processes below 1.5 cores during, recorded in `research_loop/generated/pin_work/s4*_*.json`; median of 9 binary starts, each the median of its 9 interleaved runs; results equal DuckDB's: `matches_duckdb: true`):

| shape | rows | DuckDB in place | scalar mode | ratio | aggregate mode | ratio |
|---|---|---|---|---|---|---|
| `SUM(DECIMAL(38,4)) WHERE value > 5000` (SEC `num`) | 39.4M | 235 ms | 204 ms | **0.87** | 214 ms | 0.91 |
| `COUNT(*) WHERE qtrs = 3` (SEC `num`, INTEGER) | 39.4M | 12.2 ms | 7.9 ms | **0.65** | 13.8 ms | 1.16 |
| two-column `SUM(DECIMAL(15,2)) WHERE`, TPC-H SF1 | 6.0M | 5.4 ms | 4.7 ms | **0.87** | 6.4 ms | 1.18 |
| the same, TPC-H SF10 | 60.0M | 34.9 ms | 27.7 ms | **0.79** | 37.5 ms | 1.11 |

Notes: the fold reads EVERY row (the rows-seen check against `SELECT COUNT(*)` passes after every execution), while DuckDB's filtered query can prune row groups with its statistics; on the INTEGER column the reference's filtered count (11-12 ms) is slower than DuckDB's own unfiltered `SUM(qtrs)` (6.5-8 ms), so no row group was pruned there.
The comparison is buffer-hot for both sides (`COLD_FIRST_US`, the first execution, is 1.1-2x slower for both), "cold" meaning no export, no pin, no copy, not an empty buffer pool. The ~0.87 on the two DECIMAL shapes is the scan floor: the scalar no-op takes 70-90 percent of the fold's time.

Candidate structures evaluated and NOT built (measured upside or trust cost): letting DuckDB apply the WHERE (a superset filter before the fold: `WHERE l_quantity < 24`) would put DuckDB's filter in the trusted base ("DuckDB is not a second engine"); the experiment `pin_work/push_exp` was compiled but not pursued
because the fold alone already beats the in-place reference. Zone-map skipping inside the fold would need trusted row-group statistics; explicit SIMD intrinsics are not needed (AVX2 auto-vectorization of the branch-free fold is enough: 1.9 us per 2048 rows).

### Trusted statement for the scalar mode (ZC-2s), for adversary review

> **ZC-2s.** The host registers one scalar function `f` with the declared parameter types of the columns, special NULL handling, and runs `SELECT COALESCE(MAX(f(c1, ..., ck)), 0) FROM t` (no WHERE, nothing else). Then (1) every row of `t` is passed to exactly one call of `f`
> in a vector whose `k` column vectors are row-aligned, flat and of the declared native type; (2) calls may run on any thread in any order; each thread folds into its own state (a thread-local slot); (3) nothing else calls `f`; (4) the value `f` returns is ignored (the carrier query must return 0, checked).
> The host merges the thread slots after the query (verified `cold_combine`), finishes (verified `cold_finish`) and checks that the rows the merged state saw equal the engine's own `SELECT COUNT(*)` (a count, not a proof of exactness).
> Same shape and same verified program as ZC-2; what changes is the call pattern (per vector inside a projection) and that state memory is owned by the host (no DuckDB-allocated state, no alignment issue).
