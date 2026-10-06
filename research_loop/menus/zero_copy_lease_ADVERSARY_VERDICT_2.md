# Adversary verdict 2: zero-copy lease, hardened version (ZC-1, `LEMMA_ZERO_COPY=1`)

Manual adversary (Sonnet subagent, separate from the author and from the round-1 adversary). Protocol: `TRUSTED_ADDITION_PROTOCOL.md`. Date 2026-10-05.
Library under test: the python `duckdb` wheel's C API, DuckDB v1.5.4 (the prototype link, `python_wheel_link`), so the real 1.5.x behaviour was tested this time.
No timing lock was taken; the only timings below are an uncontrolled structural experiment (load average 0.8 to 1.0 on 8 cores, `uptime` before and after) and are stated as such.
Scratch files (not part of the repo): `/tmp/claude-1000/adv2/` (`probe.rs`, `drive.py`, `res.py`, `e2e.py`, `e2e2.py`, `stride.rs`, `rss.rs`, `lib_attack.py`, `q2.py`).

## Verdict: SOUND after fixes (finding 1 must land first; findings 2 to 4 are cheap and recommended)

I found no input on which ZC-1 is false on DuckDB 1.5.4, no hole in `zero_copy_lib.rs`, and no way to get a proved body over `PinnedCol` to differ from DuckDB when the
(spec, schema model, database) triple is consistent. I found one silent wrong answer reachable through the assembler's API when the schema model and the spec disagree about the
scale (finding 1: the round-1 F1 failure is closed against the database, not against the spec). The round-1 findings F1, F2, F3, F7 are fixed and I re-checked each.

## Findings

### 1. The spec is not bound to the schema model: a model whose scale differs from the scale baked into the spec literals verifies, runs, and returns a wrong answer. Class (a) plus (c) in the assembler. Severity: medium (silent wrong answer, precondition is a caller inconsistency).

`resolve` (`zero_copy.py:132-165`) compares the MODEL's declared type with the database's stored type, and `main` re-checks the stored type against the model's type. Neither compares the
model with the SPEC. The spec has no record of its input scales (only `// OUT_SCALES`), and the catalog scale is baked into literals (`value@[i0] > 50000000` means `> 5000` at scale 4).
Reproduction (`/tmp/claude-1000/adv2/e2e2.py`): spec generated for DECIMAL(38,4) (`zero_copy_sum_filter.spec.rs`), model AND stored types DECIMAL(38,2), a DECIMAL(38,2) database:

```
verification results:: 14 verified, 0 errors
rc 0 ['ROW\x1fNULL'] duckdb 14962698837.00 scaled2 1496269883700
```

Exit code 0, the binary prints NULL, DuckDB prints 1.4962698837e10. All three checks the hardening added pass (model == stored, expect_type == stored, width i128). The drivers
(`zero_copy_oneshot.schema_and_stored`, `zero_copy_prove._model`, `zero_copy_round.classify_one`) rebuild the model independently of `regenerate_spec`, so nothing ties the two together
except that both read the same catalog today. The copy path has the same plumbing assumption (the exporter scales by the model), so this is not new to zero-copy, but round 1's
F1 argument ("an accepted result must not rest on the harness") applies.
Fix (a): make the emitter write the input types into the spec (`// IN_TYPES: num.value=decimal(38,4) ...`, next to `// OUT_SCALES`) and have `resolve` refuse any difference
between that line and the model's `info.sql_type`; or derive `Resolved.expect` from the spec line instead of the model. Regression test: the e2e2 reproduction must raise
`ZeroCopyUnsupported` at assemble time.

### 2. DATE infinity passes every check and is read as the raw integer. Class (a), low; also an inconsistency between the two paths that the differential cannot see.

DuckDB stores `'infinity'::DATE` as `2147483647` (and `-infinity` as `-2147483647`). No catalog cap bounds a DATE cell (`emit_surface.py:1783` returns no cap for dates; the spec has no value conjunct),
so the pin delivers it. Evidence (`drive.py` scenario `dates`, probe of the pinned chunk vs python): pinned cell `2147483647`, python export `2932896` (`datetime.date.max`, the python client
maps infinity to 9999-12-31). DuckDB itself: `SELECT d - DATE '1970-01-01'` gives `2147483647` (so the borrowed value matches DuckDB for date differences and the copy path's
exporter is the wrong one), `d + 1` stays infinity, `date_diff('day', DATE '1970-01-01', d)` is NULL, `epoch(d)` is NULL. A spec that does `as int` arithmetic on the cell can therefore differ from DuckDB
on a table that contains an infinite date, and zero == copy fails there. Fix (a): in `main`, for a DATE column assert no cell equals `i32::MAX` or `-i32::MAX` (one scan, like the cap checks);
test: a table with one `'infinity'` row aborts. (Until then: accepted limitation (b), "DATE infinity is read as a raw integer".)

### 3. No check of the library version. Class (a), low.

ZC-1's fidelity rests on a deprecated API (round-1 F5: `duckdb_result_get_chunk` and `duckdb_result_chunk_count` are "scheduled for removal"). `grep library_version` finds nothing in `zero_copy_ffi.rs` or `zero_copy.py`.
I verified the behaviour on 1.5.4 only (finding 8). A production link to another libduckdb (gate G11) changes the premise silently. Fix: `duckdb_library_version()` in `main`, asserted against the validated set (1.5.4 now),
and the version printed in the run output; the gate's SHA record should include it.

### 4. A real column or table name containing `"` or `{` or `}` produces generated Rust that does not compile (loud, not silent). Class (c), low.

`zero_copy.py:283, 285-286, 291` interpolate `real` raw into string literals: with the F2 test's own column `my"col` the generated line is
`assert!(pin.cols[0].elem_bytes == ..., "my"col: pinned width differs from i128");` (`/tmp/claude-1000/adv2/q2.py`). The `expect_type` call and the SELECT are escaped correctly (`_rust_str`), and `test_f2_...`
only asserts strings, never compiles. `zc_duck::count` (`zero_copy_ffi.rs:79`) also wraps the name in `\"{}\"` without doubling an inner quote (a parse error, loud). Fix: use `_rust_str(real)` for the message
(or pass the name as a `{}` argument) and double quotes in `count`; test: compile the F2 case.

### 5. The differential test cannot see a row-order or chunk-placement error, and covers none of the storage states that matter. Class (a) (add tests), no hole found.

`tests/test_zero_copy_differential.py` runs SUM and COUNT with per-row predicates. Both are permutation invariant, so a pin that returned the right cells in the wrong order, or chunks placed at the wrong offsets, would
pass; zero and copy go through the same C-API pin, so they share any misread, and the only independent reference is a scalar. Tables are always fresh CTAS in a new process (checkpointed on close). Not covered:
DELETE or UPDATE, INSERT-grown tables, views, WAL-resident data, DATE / HUGEINT / DECIMAL(4,.) / DECIMAL(9,.) / TINYINT columns, a NULL (run-time abort), a value above the cap (abort), a stored-type mismatch other than one scale.
I re-ran the file (`LEMMA_ZC_DIFF_SEEDS=1`: `4 passed in 48.74s`; the default 3 seeds gives 82 tables per case, 328 in all, I verified that arithmetic). I then covered the gaps by hand, order-sensitively
(`probe.rs` prints every pinned cell in chunk order, `drive.py` compares the whole sequence with `SELECT` through the python client, DuckDB 1.5.4):

```
base 300000 rows DECIMAL(38,4)           EQUAL      del (DELETE 1/7, UPDATE 1/11, DECIMAL(18,3)+BIGINT)   EQUAL
del_nockpt (same + INSERT, no checkpoint) EQUAL     inserts (40 INSERT statements, INTEGER)               EQUAL
hugeint 5000 rows                         EQUAL      dec4 (i16)  EQUAL    dec9 (i32) EQUAL    tiny (i8,i16) EQUAL
constant column 100000                    EQUAL      view with a constant column, view over a join, ORDER BY views (asc, desc)   EQUAL
two-column select incl. v+1               EQUAL      dates: DIFFERENT only for infinity (finding 2)       NULL at row 70000: pin aborts "column 0 has NULLs"
```

Whole generated programs (Verus, 14 verified, 0 errors, `e2e.py`, sum filter, table `num` and also quoted mixed-case `"Num"`, the generated SELECT is `SELECT "value" FROM "Num"`), run against the DuckDB answer:
base, DELETE+UPDATE, delete-all (NULL), DELETE of the whole first row group, a VIEW named `num`, 40 appended inserts, and the exact-cap boundary all EQUAL; a value above the cap, a NULL, a DECIMAL(38,3) column under a (38,4) spec,
and a table that exists only in another schema all ABORT loudly (the last one with DuckDB's own Catalog Error). Recommend turning `drive.py` into a test: it needs no Verus.

### 6. The pin is still not copy-free inside DuckDB on 1.5.4. Class (b), restates round-1 F4 with a 1.5.4 number.

`/tmp/claude-1000/adv2/rss.rs`, 30M-row INTEGER table (120 MB of cells): `VmRSS` after open 45 MB, after pin 360 MB (315 MB added, 2.6x the data), after the COUNT 362 MB. The program holds DuckDB's materialized collection and the
fetched chunks. The gate's last paragraph ("the second resident copy matters") should say that zero-copy removes our third copy and not DuckDB's second.

### 7. Documentation that is stale or inaccurate. Class (b), fix before the paper line is written.

* `zero_copy_gate.md` G3: "the only `unsafe` is the borrow in the generated `main`". `zero_copy_ffi.rs` is full of `unsafe` (every C-API call), plus `Box::leak`; the trusted plain-Rust surface is the whole `zc_duck` module, `zc_offsets` and `main` (they establish `wf` and "the slices are the column", which Verus takes as given). `test_zero_copy_trust.py` says this correctly, the gate text does not.
* `zero_copy_lease_PROPOSAL.md` section 4 last paragraph still says "the pin would be leaked ... Not in the prototype" (it is leaked now); section 7 first bullets still describe "`main` holds `Pin` to its end"; section 7 "Peak memory: the pin is the only copy" contradicts section 8 and round-1 F4; section 10 item 1 says 11 of 19,244 chunks, round-1 F6 measured 12.
* G4 says the flag is the only switch: the three scripts (`zero_copy_oneshot._env`, `zero_copy_prove._env`, `zero_copy_round.classify_one`) set `LEMMA_ZERO_COPY=1` (and `classify_one` also `LEMMA_NARROW_CELLS=1`) in their own process. Explicit by script name, no pipeline code does it (I grepped: only `declarative_spec/zero_copy.py`, three scripts and tests mention the flag), but "only `LEMMA_ZERO_COPY=1` in the environment" is not literally true.
* `zero_copy_prove.py check` returns exit code 0 and `proved: True` when `rows_error` is non-null (a wrong answer prints a field and exits 0). Make it exit non-zero.

### 8. Check of the author's kernel-slowdown explanation (gate section "Why G8 and G9 fail"). The description is right; the cause is narrower than stated and the prefetch claim is wrong as I measured it. Class (b).

Experiment: `/tmp/claude-1000/adv2/stride.rs`, 30M-row INTEGER column pinned from DuckDB 1.5.4, then the same cells laid out in other ways in my own memory, one kernel (`count(x == 3)`, chunked, 14,649 chunks), median of 9 runs inside one process, single thread, AMD Ryzen AI 5 330 (L3 8 MiB), load average 0.8 to 1.0 before and after (an uncontrolled box, so read the ratios, not the milliseconds):

```
pinned strides (ptr[k+1]-ptr[k]): 16384 for 14,626 of 14,648 steps               (claim confirmed: 8,192 B of data per 16,384 B)
duckdb pinned chunks             24.1 / 24.4 ms
dense, same chunk lengths        7.5 / 5.8 ms          per-chunk heap Vecs (back to back)  5.4 / 5.7 ms
synthetic stride 16384           24.6 / 27.6 ms        synthetic stride 12288               27.8 / 29.0 ms
dense but chunks visited in shuffled order   24.7 / 27.1 ms
duckdb pinned + software prefetch of the next chunk, same offset, dist 0:   14.3 ms  (dense with the same loop: 9.8 ms)
```

Reading: (a) the 16,384 stride is real, and a synthetic stride reproduces the 4x slowdown. (b) So does a perfectly dense layout visited out of order, and a 12,288 stride: the loss is "consecutive chunks are not adjacent in
memory" (the hardware stream prefetcher does not follow across a gap), not the 16,384 number in particular. (c) "Software prefetch of the next chunk does not help (36 ms)" did not reproduce: prefetching the next chunk's line at the same offset
while scanning the current one took the pinned scan from 24 to 14 ms in my loop (distance 256 and 1024 elements were worse, 16.4 and 24.7 ms; the loop shape itself costs the dense baseline 5.8 to 9.8 ms). One run on a
non-quiet box proves only that the claim "does not help" is not general; the author's version of the prefetch is not in the repo so I could not diff it. It does not change the recommendation (a proved Verus body cannot issue prefetches today), but the sentence should be softened.

### 9. Over-refusals (loud, accepted). Class (b).

DECIMAL(p<=9) is stored as i16/i32 but the emitter loads every DECIMAL up to 18 digits as i64, so those columns are refused with the exact reason (test exists); the shapes the path accepts are exactly: INTEGER/SMALLINT/TINYINT with
`LEMMA_NARROW_CELLS=1`, BIGINT, HUGEINT, DECIMAL(15..18,s) and DECIMAL(19..38,s), DATE. `info.sql_type` spellings `int2`, `int1`, `short`, `long`, `signed` are not in `by_sql` and are refused, not mis-mapped.

## `resolve` / assembler matrix I ran (`/tmp/claude-1000/adv2/res.py`, all as intended)

ACCEPT: NUMERIC(38,4) vs DECIMAL(38,4); bare DECIMAL vs DECIMAL(18,3); DECIMAL(38) vs (38,0); INT8 vs BIGINT; Integer vs int4 (narrow); mixed-case table and column names; stored column names in other case.
REFUSE with exact reason: DECIMAL(38,0) vs HUGEINT (both ways); BIGINT vs UBIGINT; BIGINT vs TIMESTAMP (`unsupported SQL type`); INT vs DATE and DATE vs INTEGER; DECIMAL(18,3) vs (18,2); (18,3) vs (19,3); (38,4) vs (37,4);
TINYINT vs SMALLINT; BIGINT vs DECIMAL(18,0); BOOLEAN, DOUBLE; DECIMAL(4,2) loaded as i64. `stored_types` is a required keyword argument; a lying caller (finding 1) is not caught, a stale or wrong database is (the run-time `expect_type`).
Two fields cannot map to one column (each field ident maps to the columns with that sanitized name; 0 or 2 is refused). Sanitized-name collisions between tables refuse even when only one is used (over-refusal, safe).

## What I tried that did not break it

* **Verus library** (`lib_attack.py`): added to the library `proof fn`s with `wf` as the only assumption. True and verified: `c@.len() == c.n`, `chunks.len() <= n` (via `lemma_chunk_count`), `c@[0] == chunks[0][0]`, equal `offs` implies equal view length. False and rejected (7 of 7): `len == n+1`, `chunks.len() < n`, `c@ == d@` for two wf columns with equal offs, `chunks[0].len() == n`, `ensures false`, a cell read one row late, `c.n == d.n` for two unrelated wf columns. (An eighth claim I wrote, chunk 0 has equal length in two columns with equal `offs`, failed only because I did not mention `offs@[1]`: the `wf` forall is triggered on `offs@[k+1]`, which agents must mention; it is an incompleteness, not a hole.) No `external_body` / `assume` / `admit`; `find_chunk` and `get` proofs and the cast arguments (`offs` are `usize` mirrored as `int`, `lemma_chunk_count` bounds the count by `n <= ROW_CAP`) check out; the `choose` is unique for `i < n` by `lemma_cell`.
* **ZC-1 on 1.5.4** (see finding 5 table): chunk lengths all 2048 except the last in every scenario, non-null 16-aligned buffers, flat vectors for constant, dictionary, sequence, view and ORDER BY inputs (an order-sensitive comparison of every cell), retained across DELETE/UPDATE/INSERT states of the table before the pin, validity-mask NULL detected at row 70000 (and round 1's 0/63/64/2047/2048/4095/4096/4999).
* **The F1/F2/F3/F7 fixes**: F1 abort at run time on a stored scale difference (e2e `temp-like: wrong scale` aborts, message names both types); F2 real names quoted, `Num` and `"num x"` reach the intended table, a table that exists only in a non-main schema is a DuckDB catalog error, never another table; F3 `!p.is_null()` asserted next to the alignment check, empty and delete-all tables run (n = 0, `offs = [0]`); F7 refused at assemble time.
* **Parallel chunk-range body**: it is in the differential (`sum_dec38_parallel`, passes) and Verus verifies it; I read the telescoping argument (`rl`, `lemma_end`, the worker-panic recompute branch uses the same proved loop) and found no gap. The 8 ranges cover `[0, m)` since `cs = m/8 + 1` gives `8*cs >= m`.
* **Spec shapes**: BOOLEAN, unsigned, float, string, dictionary, `__valid` columns, two tables are refused before Verus runs; a unique-key conjunct is refused; `valid_cols` conjuncts the checker cannot restate raise. A dropped cap conjunct cannot happen silently because `_runtime_checks` and `_loader_requires` read the same conjunct list and an unknown one raises.
* **Fallbacks**: none either way. `assemble_zero_copy_program` raises without the flag, `mode="copy"` is an explicit control argument, `assemble_declarative_program` never calls it.

## What I could not check

* Any performance number of the gate table (no timing lock, shared box); I only checked its internal arithmetic (shipped/zero ratios 3.7, 4.2, 32, 34 and the zero-vs-copy percentages 9, 16, 8.7, 24.5 recompute from the stated milliseconds; the 328 count recomputes; the 22-test count is right).
* The real 39.4M-row SEC database and a 630 MB pin (I used 30M-row and 300k-row generated 1.5.4 databases); `LEMMA_NARROW_CELLS` COUNT shape on the real `qtrs` (the differential builds it on a generated INTEGER table, passes).
* A DATE column through a full proved body (no fixture exists); a HUGEINT column through a full proved body (probe level only).
* Other DuckDB versions, a 1.5.x release libduckdb (not the python wheel + libpython hack), big-endian or non-x86 targets, a hostile concurrent thread.
* Read-only opening of a database with a live WAL written by another process.

## Opinion: nullable columns (`__valid`): keep refusing

Supporting the mask means a second trusted layout fact in ZC-1: "for a vector with `validity != null`, bit `r % 64` of word `r / 64` is 1 iff row `r` of the chunk is valid, the buffer holds at least `ceil(len/64)` words, a null pointer means every row valid,
and the bits past `len` are unspecified", plus a bit-mask view lemma (`(w[r/64] >> (r%64)) & 1`) and a `Seq<bool>` view of a chunked mask. It could be false if DuckDB changes `ValidityMask` (it was `uint64` words since 0.3 but the
C API only promises "uint64_t*" with the accessor, and `duckdb_vector_ensure_validity_writable` shows the pointer can be absent), if a vector shares a mask with another, or if 1.5+ result chunks hand out masks that alias the
collection's. It buys little: the gate shows zero-copy is already within 10 to 25 percent of the copy loader on one-shot and slower on the kernel, and a nullable column is exactly where a `bool` expansion pass (one byte per row, plain Rust,
no new trusted fact beyond the exporter's) costs 1/16 to 1/4 of the cell data. So: refuse now; if nullable columns are wanted, expand the mask into a `Vec<bool>` in `main` (a copy of the mask only, the values stay borrowed) rather than borrowing the bit mask.

## Which gate criteria are met today, from my own evidence

* G1: not yet. Verdict SOUND after fixes; closes when finding 1 lands with its test (2 to 4 recommended with it).
* G2: met (mechanism): I ran 25 declared/stored combinations through `resolve` and 11 whole-program scenarios; every mismatch is refused at assemble time or aborts at run time, none silent except finding 1's spec/model case. Arena counts: no round, unmeasured.
* G3: met (no new Verus trust; library re-read, grep clean), with the wording fix in finding 7. The unverified plain-Rust surface is `zc_duck`, `zc_offsets` and `main`.
* G4: met (the only pipeline-level references are in the new files; no fallback in either direction), with the finding-7 nit about the scripts setting the flag.
* G5: reproduced (4 passed), but the evidence is weaker than "0 differences" suggests (finding 5); my 19-scenario order-sensitive probe plus 11 whole-program scenarios supplement it. I consider it met for the four shapes and the data kinds it generates, not for DATE, DELETE/UPDATE states, or order errors until the tests of finding 5 exist.
* G6: partial, agree: the behaviour is confirmed on 1.5.4 in every scenario above, but there is no version assertion (finding 3) and no production libduckdb 1.5.x.
* G7: the table's ratios recompute; not re-measured. Agree "met but not because of zero-copy".
* G8, G9, G10, G11: unmet, agree. My experiment (finding 8) confirms the mechanism for G8 (non-adjacent chunks), says the cause is chunk adjacency in general, and says software prefetch is not ruled out as a mitigation.
