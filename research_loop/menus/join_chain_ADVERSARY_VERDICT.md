# LEMMA_JOIN_CHAIN review (manual adversary, Sonnet subagent)

Target: `git diff a0572ae..4bb67f1` (reviewed from a `git archive` snapshot of 4bb67f1; the worktree was moving). Soundness only.
Tests: `tests/test_join_chain_adversary.py` (9 pass, 1 fails now = finding F1). Verus only through `verus_guarded.sh`.

## Verdict: merge as opt-in flag (default off): **yes**, no unsound path found. One low, loud finding (F1) to fix or document.

## What I checked

(a) Same spec, reordered. Emitted flag off vs on for the 13 SSB queries (Q2.2 is refused in both) and TPC-H Q3/Q9/Q12, plain and dict.
`row_hit`, `key_at` and every `*_val` body, with indexes renamed by table, are the same set of conjuncts (only the order of the range-guard
conjuncts differs). Q3 diffed in full: `out_row_ok`, `group_close_*` lemmas, ensures are the same with the argument order permuted. The
assembled `main` calls `run_query` in signature order (`structs_in_sig`), also in the parallel variant (`LEMMA_PARALLEL_VSTD=auto`, Arc args
in the same order); `dense_budget.key_dictionaries` maps `key_at` params to tables by name (order-free). Outer joins, subqueries, CTEs and
USING are refused before or by `find_chain`. Self-joins are now not chains (4bb67f1).
(b) Detection. Only `ident == ident` top-level conjuncts and AND-ed ON pairs count; OR, NOT, `<>`, arithmetic, same-table equalities, float
non-key equalities, partly covered composite keys give no chain (tests). Nullable key or equated column refuses the chain. Wrong detection
cannot make anything false: the only statement it adds is the catalog's declared unique key, a data assumption; the reorder is the
only semantic move and (a) covers it. A wrong detection can only make the host lemma `lemma_chain_hit_unique` fail to verify (loud).
(c) Runtime check. `_runtime_checks` asserts every unique conjunct in `main` before `run_query` (a conjunct it cannot parse raises at
assembly). Seen for: single int key, composite key (TPC-H partsupp), string key plain and dict (codes; sound because the dictionary is checked
distinct), all chained tables of SSB Q4.1 / TPC-H Q9. NULL keys are refused at export and the chain is refused for nullable keys, so
`check.py` (GROUP BY) and `main` (HashSet) agree. Real data: `check.violations` on ssb_sf1 and tpch_sf1 with the registry catalogs: `[]`. valid_cols is
satisfiable by any dataset the checks accept (empty table too), so it is not vacuous.
(d) Verus, empty body: SSB Q2.1 (23 verified, 1 error), Q3.1 (25/1), Q4.1 (28/1), TPC-H Q3 (21/1), Q9 (34/1), Q12 (20/1) plain; SSB Q3.4,
TPC-H Q9, Q12 dict. Each has exactly one error, `postcondition not satisfied` of `run_query`; none in the library (`lemma_chain_hit_unique`,
`lemma_<fold>_row`, zero/single lemmas). String-key chain (no hit-unique lemma, key not int) verifies plain and dict too. The lemmas are
proved from `valid_cols` and `row_hit`, so a proved body that uses them is as sound as `valid_cols` (loader-checked). No `_t` name use can
change a statement; the preconditions (`x <= bounds`) only restrict.
(e) No `assume`, `external_body`, axiom in `join_chain.py` / `chain_lemmas.py`; `admit.py` is unchanged by the diff.

## Findings

### F1 (low, loud): host names collide with aggregate aliases when the flag is on
Repro: `SELECT da.x, SUM(fact.v) AS total, SUM(fact.b_id) AS total_t FROM fact, da WHERE fact.a_id = da.id GROUP BY da.x ORDER BY da.x`
(tests toy schema). Flag off: no duplicate. Flag on: `sum_total_t` is the fold of alias `total_t` and also the new term fn of `total`;
Verus: "name `sum_total_t` is defined multiple times". Not unsound (a build error), but a flag-induced regression.
Fix: name the term fn with a reserved infix that no alias can produce (e.g. `chain_term_<name>`), or refuse the alias. Test:
`test_an_aggregate_alias_cannot_collide_with_the_host_term_function` (fails now). (`sum_x_d1` vs alias `x_d1` is the same pre-existing class.)

### Notes (no action needed for merge)
* Float / non-int / DECIMAL key: no `lemma_chain_hit_unique` (the agent proves its own); a float key does not compile in `main`'s HashSet (loud).
* `chain_hit_unique` verifying depends on the join equalities being derivable from `row_hit`; a type mismatch would fail the lemma loudly.
* The conjunct order inside `valid_cols` and the dict trigger text are unusual but accepted by Verus.

## Conditions
1. Fix or document F1.
2. Keep the flag default off until a container card runs with it and row-matches DuckDB (the unique checks in `main` are only exercised on the column-file path).
