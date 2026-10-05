# Parallel dense group-by / nullable scan / dict join probe / transplant: adversary review (manual adversary, Sonnet subagent)

Target: integration at `faa9620` (merged into my branch). Soundness only (float rounding accepted). Tests: `tests/test_parallel_dict_adversary.py`
(25 pass, 1 strict xfail; Verus through `verus_guarded.sh`, one job at a time).

## Verdict: merge: **yes**; safe to use for claimed results: **yes, with condition 1**

No unsound path found. Every fixture verifies, matches DuckDB at every tested data size, and the negative controls reject.

### Conditions

1. **Regenerate the spec in `declarative_manual.py check`** (open, strict xfail `test_check_regenerates_the_spec_...`). `check` verifies the body against
   `context/ro/spec.rs` as found in the workspace and never re-emits it from `query.sql` plus the catalog. The spec is the ground truth, so for a CLAIMED result
   re-emit it (or refuse a `spec.rs` that differs from the fresh emission). The transplant tool makes this sharper: it moves a body into a DST workspace whose
   `spec.rs` was produced earlier. Not a hole in the automated pipeline (the agent runs with `ro/` read-only), a hardening of the manual path.
2. Record in the paper's Limitations that the thread path trusts vstd's `thread::spawn`, `JoinHandle::join` and `Arc` specifications (already stated in `parallel.py`).

## (1) Parallel assembly

* `main` builds one `Arc::new(cols_<t>)` per table and calls `run_query(&*arc_a, &*arc_b, &arc_a, &arc_b)`: the plain struct and the Arc are the SAME object (pinned for
  one table with dictionary and validity vectors, which live inside the struct the Arc owns, and for a two-table join). The call never mentions the un-Arc'd struct.
  A self join (two parameters of one table) has no parallel variant (loud `DeclarativeUnsupported`); a non-`Vec<OutRow>` result is refused. Every parallel spec requires
  `**<t>_arc == *<t>` and keeps the sequential `ensures` byte for byte.
* Sizes: all 7 fixtures (SUM, MIN, MAX, COUNT, dense group-by, TPC-H Q1, nullable scan) were compiled once and run on n = 0, 1, 3, 7, 8, 9, 15, 16, 17, 100 rows (workers: 8; fewer rows
  than workers, not divisible, empty) against DuckDB on the same data: all equal. Overflow at `ROW_CAP`: the chunk arithmetic is proved for rows at most 2^31; the same
  body transplanted to a spec with cap 2^40 is rejected by Verus, and at caps 2^20 and 2^30 it re-verifies.
* **Worker panic:** an out-of-bounds index injected into the first spawned closure (unverified build, `--no-verify`) fires (`panicked` on stderr), `join()` returns `Err`,
  the inline recompute runs, and the printed rows equal DuckDB's at n = 0, 1, 8, 9, 100. The Err arm is also proved in the verified body (same step lemma).

## (2) Dense group-by merge

* Dense arrays are sized by the dictionary length; `valid_cols` requires every code below it, so no key code is outside the domain. The two-key flat slot `code1 * m2 + code2`
  is checked by Verus (Q1 fixture verified against the spec's `key_at`).
* Empty versus zero-count: in the Q1 test the `(N, F)` combination is in both dictionaries but every row is after the date cutoff; the result has no such group and equals DuckDB's.
  A group whose SUM is 0 (`EUR`, value 0 only) is present with count and sum 0 and equals DuckDB's. ORDER BY over merged groups equals DuckDB's (Q1 sorted by two keys).
* Not covered by any fixture: a NULL key group in the parallel dense path (no proof exists to attack; the sequential `key_at` for a nullable key is `(valid, value)`).
* Resource note, not unsoundness: the flat slot array has `m1 * m2` entries; with the SEC join-key dictionaries (about 10^5 values each) such a body would try to allocate
  tens of GB and abort loudly; it can never print a wrong row.

## (3) Transplant tool

`transplant` copies only the two agent regions; the rest of the DST file is preserved byte for byte, and a source without markers is loud. It does not verify. The gate is
`declarative_manual check` -> `run_declarative_metrics`: it re-runs admission on body and helpers (a transplanted `external_body` helper and `assume(false)` body are rejected as
FAILURE before Verus runs), re-assembles, and requires `N verified, 0 errors`. A body proved for `line > 5` transplanted into the `line > 6` spec fails verification.
Remaining weakness: condition 1 (the DST `spec.rs` is trusted as found).

## (4) Dict join probe

Build side `sub` with repeated `adsh`: **`valid_cols_sub` does not contain the declared unique key** (only when a join cap uses it), so the proof cannot rely on uniqueness; the
fixture keeps a per-code COUNT array, and with duplicated build keys the result equals DuckDB's (probe rows multiplied by the number of matching build rows). Probe keys absent from
the build side (`zz1`, `zz2`) contribute nothing, as in DuckDB. NULL join keys: the join columns are not nullable in the package (the exporter refuses a NULL), and a nullable key in a
`JOIN ... ON` is refused by the NULL pass.

## (5) Judge-style runs

Hand-proved bodies, mutation controls (the authors' per-fixture mutations in `test_declarative_parallel.py` / `test_declarative_string_dict.py` plus my transplant-negative controls), and
DuckDB comparison on small tables around the worker count, plus one 1M-row run on the local synthetic SEC database (dense group-by over `num` and the 1M x 40k dict join probe, both
`SUCCESS`, rows equal to DuckDB). The real 39M-row database was not used (a 39M DuckDB build was running).
