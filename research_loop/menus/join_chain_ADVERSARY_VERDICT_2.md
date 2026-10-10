# LEMMA_JOIN_CHAIN review, round 2 (adversary, Sonnet subagent)

Target: `git diff 4bb67f1..c59009e` (branch chain-dev) plus the four new fixtures. Soundness only. No container runs, no network.

## Verdict: merge as opt-in flag (default off): **yes**. No unsound path found. F1 of round 1 is fixed. One low note (N1) and two process notes.

## Checked

1. `_group_close_text` for a string ORDER BY without LIMIT (flag on). The lemma statements are not new text: `group_close_lemma` is unchanged and its lemmas
   (`rows`, `distinct`, `present`) ensure exactly the matching `run_query` postcondition from hypotheses about `gk/sel`; they never mention the order. A string ORDER BY
   with LIMIT still gets none (test). `run_query` signature + requires/ensures, including the `seq_le` order line, are byte-identical to the 4bb67f1 emit
   (diffed on SSB Q2.1, Q4.1, Q4.2 with dict + chain: the only other differences are the `chain_term_` rename and the three added lemmas).
   Verus, empty body, via verus_guarded: Q2.1 26 verified, 1 error; Q4.1 31/1; Q4.2 31/1; each exactly one `postcondition not satisfied` (run_query). The lemmas verify.
2. `chain_term_<fold>` rename: F1 (alias `total_t` vs term fn) no longer collides (the round-1 test now passes). Only residual: an alias literally named
   `chain_term_<other alias>` would still collide (loud build error, flag-on only; not worth a fix).
3. Fixtures (`dict_star_join_group_sum_sorted`, `dict_parallel_star_join_group_sum_sorted`, `..._two_keys_revenue_order`, `..._two_keys_string_order`): no
   `assume/admit/external_body/axiom/unimplemented/arbitrary`; `admit_declarative_body` and `admit_helpers` accept all four against the emitted SSB spec;
   `pytest tests/test_declarative_hard_fixtures.py -k "star or two_keys"`: the four star fixtures verify (9 passed, 1 failed, see N1).
   Soundness of how they use the host lemma: array-by-key+offset, unique keys and "value 0 = absent" are all proved by Verus, not assumed. They rest on
   `valid_cols` only: key range (c_custkey in [-32767, 32767] etc., so the offset index is in range), uniqueness (`!(k[i]==k[j])`, asserted in `main` for each
   chained table, round 1 (c)), `d_year` in [-2047, 2047] so `d_year+2048` is never the absent value 0, dictionary distinctness / `<=128` codes (checked at load).
   A dataset with a duplicate or out-of-range key is rejected by the loader/`main`, so no accepted data gives a result different from the spec. I could not
   build a counter-shape. I did not re-measure rows against DuckDB (allowed to skip); the run-time gate is `_apply_speed_bar`.
4. `verdict_error`: only the RESULT line changes. The SUCCESS status itself comes from `drive.py` only when `metrics.status == SUCCESS and proof_verified`, and
   `pipeline._apply_speed_bar` turns a row mismatch or `latency*mult >= duck_us` into FAILURE first, so an empty error on SUCCESS hides nothing in the
   declarative style. `SUCCESS_UNVERIFIED` still shows its error. Imperative style: SUCCESS carries no error anyway.

## Notes

* N1 (not in the delta): `-k two_keys` also selects the old `dict_group_two_keys_count_distinct_avg.rs` which FAILED here (Verus trigger error at the generated
  `assert forall ... seen@[t]`). File and flag-off emit are untouched by the delta (flag off: `_group_close_text` is unchanged for it), so I believe it is pre-existing
  or load/rlimit related; I did not bisect it. Check it on 4bb67f1 before calling the fixture suite green.
* N2 (process): `scripts/ram/heavy.sh` plus `verus_guarded.sh` can deadlock across sessions. A pytest in another worktree held slot-0 and waited for the SHARED heavy
  lock while my `heavy.sh` job held it exclusively and waited for the slot (load average 0, 17 minutes, my Q2.1 run timed out at 900 s as "VERIFY TIMEOUT").
  Running Verus only through `verus_guarded.sh` (no `heavy.sh`) avoided it. Not an engine soundness issue.
* N3 (pre-existing, not in the delta): when `speed_bar` is None `run_declarative_metrics` reports SUCCESS without a row comparison. Container runs always pass a bar.

## Tests added (append only)

`tests/test_join_chain_adversary.py` (16 pass): string ORDER BY keeps the `seq_le` ensures and the close lemmas do not mention it, string ORDER BY + LIMIT gets no
close lemmas with the flag, `verdict_error` is empty only for SUCCESS, and SUCCESS needs `proof_verified` in `drive.py`. No confirmed hole, so no failing tests.
