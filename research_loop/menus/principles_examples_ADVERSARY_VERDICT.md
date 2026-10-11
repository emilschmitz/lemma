# Adversary verdict: LEMMA_EXAMPLES=principles (commit 31fb465)

Scope: worktree `agent-a7263fc262d297db2`, `git diff 75f4303 31fb465`. Question: is "the agent is not handed a solution to a benchmark query" true?

## Verdict: PASS WITH FIXES

The claim holds for the mounted examples: none of the seven files is the body of a TPC-H or SSB query, none carries a benchmark name, measurement, literal or constant,
and every prompt I built under the flag (about 450 prompts and lemma indexes on the invented schema, 64 on the real TPC-H catalog) cites only the seven files and `INDEX.md`
and names no benchmark. The default mount and the default lemma index are byte-identical to 75f4303.
It is not yet airtight: two prompt sentences and one INDEX sentence route to the shape of Q3/Q18-class queries or point to files that do not exist,
a SEC table name (`pre`) and a SEC column name (`report`) remain in the principles prompt, the default-mode prompt text changed (it is not "unchanged"),
one inlined proof body (`_COUNT_SHAPE`) bypasses the flag, and the leakage tests have holes that would not have caught any of these.

What I ran: `uv run pytest tests/test_declarative_principles.py -k "not verifies and not rejected and not returns_the_rows"` (13 passed);
prompts and lemma indexes for 20 SQL shapes x {dict, plain} x {parallel on/off} x 3 dict-size settings (none, small, over budget) on the invented schema;
TPC-H Q1, Q3, Q4, Q6, Q9, Q12, Q14, Q18 on the real `tpch_sf1` catalog package x {dict, plain} x {parallel} x {dict_sizes}; a byte diff of default-mode prompts, lemma indexes and mounts
between 75f4303 (extracted with `git archive` into scratch) and 31fb465. Verus re-verification of the seven files: see the last section.

## Findings

1. MEDIUM, prompt text routes to the decomposition of Q3/Q4-class queries. `declarative_spec/principles.py:169` (INDEX.md): "a join plus a group-by plus a top-N is
   `join_unique_lookup.rs` + `group_by_dict_key.rs` + `top_n_with_ties.rs`". That is TPC-H Q3 (3-table join, GROUP BY, ORDER BY ... LIMIT 10) and SSB Q3.x/Q4.x spelled as a file recipe.
   Not a body, but it is a query-shaped routing. Fix: replace by a shape-free sentence ("a real query usually combines several of these techniques"), or give a combination that is not a benchmark shape.

2. MEDIUM, dangling pointer in principles mode. `declarative_spec/prompt.py:812` (projection recipe in dictionary mode): "the example below was proved with plain strings ... (the `dict_*.rs` examples in `INDEX.md`
   show the translation)". In principles mode there is no example below and no `dict_*.rs` file. I reproduced it with `SELECT ev_user, it_group FROM events, items WHERE ev_item = it_id` under dict mode.
   Fix: drop that block when `principles.principles_only()` (the same guard as the recipe branch at :827).

3. MEDIUM, default mode is not unchanged. `declarative_spec/prompt.py:1024,1036-1038` and the `_PROOF_HYGIENE` quicksort-trigger line (:`res@[q].amount`) rewrite four lines of the default prompt
   (`.total`->`.amount`, `key_at(pre, ..)`->`key_at(events, ..)`, `uom/pure`->`kind/abc`); 120 of 120 default prompts I diffed (old vs new) differ in exactly those lines, nothing else
   (mounts and lemma indexes are identical). This confounds any comparison against prior default-mode runs, and the test that claims "unchanged"
   (`tests/test_declarative_principles.py:344-352`) asserts two substrings, not equality. Fix: either leave `_PROOF_HYGIENE` byte-identical and scrub only under the flag
   (same pattern as `_SPEED_SCRUB`), or state that the default prompt changed and make the test compare against a stored golden prompt.

4. MEDIUM, SEC names still in the principles prompt. `prompt.py:1025`: `let w = key_at(pre, i0);` (SEC table `pre`; the line above it was scrubbed to `events`, so the two are now inconsistent).
   `prompt.py:943`: "`valid_cols` bounds `report` to its cap, so `report > 100000`" (SEC column name). Neither is a query, but the claim in the docstring is "names appear in no ... SEC" for the examples only;
   the prompt test (`test_principles_prompts_..._name_no_benchmark_query`) misses them because `_DISTINCTIVE` (:260) keeps only names containing `_` plus a hand list that omits `pre`, `report`, `fy`, `num`.
   Fix: scrub both (`key_at(events, i0)`, `report` -> `rank`), and test prompts against the full `benchmark_names()` minus an explicit allowlist of English words (`line`, `name`, `value`, `region`, `part`, `date`, `version`, `form`, `instance`, `accepted`, `report`).

5. LOW/MEDIUM, benchmark-derived technique hints remain in the _SPEED/_PROOF_HYGIENE text under the flag. They name no query and no file, but each is the hint of one benchmark:
   `prompt.py:1030` "`price * (100 - disc) <= 2e30` from the cell cap 1e15" (the Q1/Q6/Q14 revenue expression),
   `prompt.py:1032` "Short string keys (1 or 2 characters) ... as_bytes" (Q1 `l_returnflag`/`l_linestatus`),
   `prompt.py:956-957` "`a == 1 && b == code && c > 3`" block-skip flag (Q12), "`(q as i128) * 40000i128`" / "`q < 70000`" narrow-cell paragraph (SEC),
   `prompt.py` _SPEED "MIN or MAX over a join ... `!(any && d >= lo)`" (SEC). Acceptable as technique text; if the claim is "no benchmark hint at all", scrub or generalise the examples (`a * (b - c)`, "a 1-character key").

6. LOW, un-gated inlined body. `prompt.py:815-826`: for `recipe == "dense_map"` the 60-line `_COUNT_SHAPE` proof body (`SELECT k, COUNT(*) GROUP BY k` into dense counters) is inlined without checking the flag.
   None of my 24 SQL shapes routed there (declarative emit does not seem to produce the `int_map` result type), so it is latent; but it is exactly the pattern the flag exists to stop.
   Fix: `elif principles.principles_only()` before `dense_map`, or delete the branch if unreachable.

7. LOW, contradictory/misleading routing sentences under the flag. `prompt.py:997` (_DO_NOT): "find the nearest shape in INDEX.md, read that example and copy its loop structure" contradicts "None is the shape of your query" (:_SHAPE_LIST_PRINCIPLES); say "read the technique your spec needs".
   The group-close section (`prompt.py:611-615`) says "For a selection loop with a LIMIT ... call `_omitted` first" and points to `star_join_group_by.rs`, but that file builds `sel = identity`, `used = all true`, and never calls `lemma_group_close_omitted`;
   the sorted/limited grouped path (SSB Q2-Q4, TPC-H Q1/Q3 ORDER BY) therefore has no worked example at all (honest, but the sentence over-promises). In plain mode the section still cites `star_join_group_by.rs` ("dense slots over the codes of a dimension's dictionary") for a spec with no dictionary (I saw this for TPC-H Q1 and Q18 plain, parallel off).

8. MEDIUM (unverified), the flag is read from the environment in more than one process. `mount_examples`/prompt run in the launcher (flag forwarded by `container_batch.py:25`), but the speed hint
   (`pipeline.py:371`, `PARALLEL_HINT` vs `_PRINCIPLES`) is chosen in whichever process executes `run_runquery`; for the stdio MCP the env is `{LEMMA_AGENT_WORKSPACE, PYTHONPATH}` (`research_loop/agent_sandbox.py:904-908`) plus whatever the CLI inherits.
   If that process lacks `LEMMA_EXAMPLES`, the tool result would name `parallel_ungrouped_sum.rs` and `dict_group_count_sum_parallel.rs`, files that are not mounted. I did not run a container, so this is a risk, not a proof.
   `run_artifacts.py:187` records the launcher's value only, so such a mismatch would be invisible. Fix: derive the mode from the workspace (`examples/INDEX.md` header) inside `_apply_speed_bar`, or have the MCP env carry `LEMMA_EXAMPLES` explicitly, and record the mounted file list in the run manifest.

9. LOW, mode parsing. `principles.py:134-139` strips but is case-sensitive; `Principles`, `principle`, `1` all raise `ValueError` (good, loud, no silent fallback). `mount()` (:176-187) raises on stale files instead of cleaning (good). Unset means `full` by design. I found no path where principles silently falls back to the full set in the launcher;
   the risk is item 8 only.

10. TEST HOLES (`tests/test_declarative_principles.py`):
    a. `:186-195` `_package_tables` falls back to `/home/emil/projects/lemma-db/...` (main checkout) when the registry is untracked; in a clean clone SSB names come from nowhere and `test_the_name_list_covers_all_three_benchmarks` fails loudly (good) but the test then cannot run anywhere except this machine. Track `ssb_sf1.json`/`tpch_sf1.json` or inline the SSB column list like the TPC-H literal.
    b. `:197-209` the SEC side reads `SCHEMA_SQL` or the `SEC_SCHEMA` fallback; both give table names `num pre sub tag` and columns, which are English words, so the test can only be satisfied by avoiding common words in comments, and it silently does not check benchmark VALUES (`'AMERICA'`, `'MFGR#12'`, `'BUILDING'`, `'MAIL'`, `'PROMO%'`, dates such as 19940101, `0.06`, `24`, `300`). I grepped the seven files for these: none present. Add a value list to the test.
    c. `:304-312` the dict-size probe uses sizes 6/4 only; the over-budget path (`dense_budget.message`, `_hash_pointer`) is untested. I exercised it with 100000-entry dictionaries: no file named. Add it.
    d. The prompt probes use only the invented schema; the real catalogs (TPC-H, SSB) reach more sections (dates, decimals, narrow cells). My 64 TPC-H prompts were clean for file citations and benchmark names; add one real-catalog probe set.
    e. `:344-352` default-unchanged test is two substrings (see item 3).

11. LOW, header claims. `join_unique_lookup.rs:7`: "999 is the key cap in `valid_cols_*`" is true here (`max_value_exclusive=1000`) but the array size `1999` and `keys@.len() < 1000` are also hard-coded; the header says "use YOUR spec's cap for the offset and the array size" (adequate). `parallel_scan_sum.rs:15`: "rows <= 2^31" is asserted as `assert(n <= 2147483648)` (:108, :229) and holds only because the catalog row cap is 16; say "from ROW_CAP". `group_by_dict_key.rs:2`: `ev_kind: Vec<u8>` codes is the width for `max_distinct=6`; a larger dictionary uses a wider cell (say so).
    `top_n_with_ties.rs:6`: "any of them is a correct answer" is right for the sort column (the invariant only constrains `ev_qty`); consistent with the DuckDB-parity test (four rows tie at 9). The tie rule text matches the invariant (`res[last].ev_qty >= k.0`). I found no false claim in the other headers.

## Per-file, per-benchmark paste analysis (renaming only)

Method: what would transfer unchanged, what needs real work. "Rename only" never verifies for any query below because every benchmark query changes the spec fold (different SUM expression/filters/keys) and the invariants name those folds.

### scan_filter_sum_count.rs (50 lines, filtered COUNT/SUM, DECIMAL)
- Q6: closest. Transfers: backward suffix scan, `i128` accumulators, `reveal_with_fuel`, `any`/NULL handling, DECIMAL scaled-integer comparison. Needs: product `price*discount` (nonlinear bound lemma), four range predicates (the file has two), date literal as int, bound constants. About 80% of the structure; the product bound is the real work. A technique demo, not the query.
- Q1: no (single group-free result). Q14: scalar part only. SSB Q1.x: the fact-side half only.

### group_by_dict_key.rs (190 lines, one dict key, COUNT+SUM)
- Q1: transfers the three-phase skeleton (zero slots, backward bump with the one-row unfolding `assert forall`, emit nonzero slots with ghost `idx`, `lemma_count_pos`). Needs: TWO string keys (flat `m1*m2` slots), four SUMs incl. products of decimals and `(1+tax)` (nonlinear bounds), AVG, ORDER BY on strings (sorted emission; the file emits in code order with no ORDER BY), group-close with order. Q1 is not here: the key arity, aggregate list and the sorted output are all missing. Not a leak.
- Q12: key is a fact-table dict column (this file's shape), but the two CASE sums read a dimension attribute, IN-list filter, ORDER BY. Needs join + CASE; skeleton transfers.
- SSB Q1-Q4: single key, no join, no order: partial.

### join_unique_lookup.rs (146 lines, unique-key probe, scalar COUNT/SUM)
- SSB Q1.1-Q1.3: the HIGHEST transfer. Same shape (fact scan, unique dimension probe, dimension filter, scalar SUM). Transfers: `build_index`, `idx_fwd`/`idx_bwd`, the three-way split (cell empty / dim filter fails / hit), the uniqueness argument. Needs: fact-side filters (`lo_discount`, `lo_quantity`) with their own "no tuple passes" arm (the file only has dimension-filter and missing-key arms), product `extendedprice*discount` bound, index size for `d_datekey` (~2M, not 1999), dimension predicate on `d_year`/`d_yearmonthnum`/`d_weeknuminyear`. Real work, roughly 20-30% of the body. Borderline but acceptable: it is the canonical technique and the rest is not given.
- TPC-H Q14: same pattern (lineitem scan, part probe, LIKE-prefix test on a dict string, ratio of two sums). Needs ratio/division lemmas, LIKE-on-dict, decimal products, a 200k-key index. Acceptable.
- Q12 (orders probe), Q3/Q18 (orders/customer probes), SSB Q2-Q4: provides the probe only.

### star_join_group_by.rs (309 lines, fact + 2 unique dims, GROUP BY a dim dict string, SUM)
- SSB Q2.x: the closest to a family shape (two of the three dimensions, a dictionary group key, a SUM, per-fact-row step lemmas, ghost `gk/gw/sel/used/pos`). Needs: third dimension and its step lemma, SECOND group key (`d_year`; flat `m1*m2` slots), ORDER BY year, brand (sorted emission via `used/pos/sel`, `_omitted`), 60% of the closing proof is the identity `sel` here. I judge ~50-60% transfers; compare 792 lines for the benchmark fixture `hard/dict_star_join_group_sum_sorted.rs`, which this file does not contain (no `val`-array encoding of filters, no sort).
- SSB Q3.x/Q4.x: two or three dimension group keys, sort by year asc and revenue desc, 3-4 dimensions: more missing than present.
- TPC-H Q3: chain (customer->orders->lineitem) and the group key is a FACT integer (`l_orderkey`), not a dimension dictionary string; no hash group table, no top-10 selection. Skeleton only.
- Q18: IN-subquery with HAVING, 5-key group, hash group table: nothing transfers beyond the probe.
- Q9: composite key `(ps_partkey, ps_suppkey)` into `partsupp`, 6 tables, `LIKE '%green%'`: not covered.
- Not a leak (no shape IS a benchmark query), but together with INDEX sentence (finding 1) it is the file most likely to be the base of an SSB Q2.x run. Keep it, and consider a header line "the output here is in code order; an ORDER BY needs the selection loop".

### top_n_with_ties.rs (153 lines, projection ORDER BY ... LIMIT 3, ties)
- Q3 (LIMIT 10), Q18 (LIMIT 100): the insertion/pop idea and the tie-rule invariant transfer; but both queries rank GROUPS (selection loop over group slots, two-column ORDER BY revenue desc, orderdate), whereas this file is a row projection with a multiset spec (`out_copies`, `hits_with`). Needs the group-close `_omitted` path (not exemplified anywhere in the seven). Acceptable.
- SSB: ORDER BY with no LIMIT: n/a.

### parallel_scan_sum.rs (308 lines, 8 workers, filtered SUM)
- Q6 (and SSB Q1.x after the join): transfers the entire parallel skeleton unchanged (`lo_of`, `part_ok`, `handle_ok`, spawn/join, telescoping, Err arm, nonlinear chunk bounds). Needs: the product term in the worker fold and in the partial's bound (the 2^63 bound is per cell, a product needs 2^126 per row), four predicates, the worker-count choice. This is a template by design (it is a trimmed `parallel_ungrouped_sum.rs`: same lemma set, same constant 268435457); the measurement comment and EDGAR table names were removed. Acceptable.
- Q1 (parallel group-by with per-worker dense arrays): the header says it, the file does not show it.

### null_skipping_aggregate.rs (57 lines)
- No TPC-H or SSB query has a nullable column in the shipped schemas; transfers nothing to Q1-Q18 or SSB. Pure technique.

### Summary table (what a rename-only paste gives)

| query | best base file | what it proves for the query | still real work |
|---|---|---|---|
| TPC-H Q1 | group_by_dict_key | skeleton of one-key dense group-by | 2nd key, 4 product SUMs + AVG, string ORDER BY |
| Q3 | star_join_group_by + top_n_with_ties | probe + closing for a dim-keyed group | chain join, fact-keyed hash group, ORDER BY 2 cols, top-10 selection |
| Q6 | scan_filter_sum_count / parallel_scan_sum | whole loop / whole parallel skeleton | product bound, predicates |
| Q9 | none | probes only | 6 tables, composite key, LIKE, year extraction |
| Q12 | join_unique_lookup + group_by_dict_key | probe, fact-dict group | CASE sums on dim attribute, IN-list, order |
| Q14 | join_unique_lookup | probe + unique argument | ratio, LIKE-on-dict, decimal products |
| Q18 | none | probes only | HAVING subquery, 5-key hash group, order, limit |
| SSB Q1.x | join_unique_lookup | probe + split | fact filters arm, product, index size |
| SSB Q2.x | star_join_group_by | ~half | 3rd dim, 2nd key, ORDER BY selection |
| SSB Q3.x/Q4.x | star_join_group_by | less than half | 3-4 dims, 2-3 keys, sort by two columns |

No cell in this table is "paste and rename"; the largest are SSB Q1.x (join_unique_lookup) and Q6 (scan_filter_sum_count, parallel_scan_sum). Strictly, SSB Q1.x and Q6 are the two where the agent receives the bulk of the proof structure.
If the bar is "no benchmark query shape as a worked body", these two are the places to look: consider making `join_unique_lookup.rs` COUNT-only with a string dimension filter (no scalar SUM(product) shape), and `parallel_scan_sum.rs` a COUNT or MIN.

## Comparison with the benchmark-shaped fixtures

grep -i for `tpc ssb edgar sec q[0-9] lineorder lineitem 39 SF1 ms x speedup duckdb benchmark fixture dict_ parallel_ungrouped hard/` over the seven files: no hit except the constants `999`, `1999`, `268435457`, `2147483648`, `999999`, which are catalog caps of the invented schema or the generic chunk bound of the original. The EDGAR measurement line ("39.4M num rows ... 12.8x"), the table names (`pre`, `num`), SSB Q4.1 text, row counts and ms figures are gone. `ev_cost` literals (`50.00`, `5000`) and filters (`ev_day >= 30/100`, `us_level >= 3`, `it_shelf < 20`, `ev_qty > 1/2`, LIMIT 3) match no benchmark literal.
Structure retained from the fixtures: `parallel_scan_sum.rs` ~ `parallel_ungrouped_sum.rs`; `top_n_with_ties.rs` ~ `projection_top_k.rs`; `group_by_dict_key.rs` ~ `dict_group_count_sum_dense.rs`; `star_join_group_by.rs` is a rebuild of the `hard/dict_star_join_group_sum_sorted.rs` idea at 309 vs 792 lines without its filter-array encoding and sorting.

## Other channels checked (principles mode)

Clean: `declarative_spec/feedback.py`, `bench.py`, `drive.py` text, `admit.py`, `dense_budget.message` (hash-pointer removed; over-budget case leaves no example, which is honest), `pipeline._apply_speed_bar` hint (`PARALLEL_HINT_PRINCIPLES`), `trusted_sets._dict_note`, emitted spec and assembled program for all seven principle specs (no `examples/`, benchmark, `Q\d`, `.rs` names), MCP tool specs (`db_extension/agent/*`: no example or benchmark text), `PROMPT.txt` equals `DECLARATIVE.md` in a real prior workspace, Verus docs mount (public vstd/Verus examples only), the Docker image copies only `db_extension/agent` and `assemble_runquery.py`.
Dangling/over-promising: items 2, 7. Env path: item 8.
`declarative_spec/shapes.py` names benchmark fixtures but is used by `emit.check_shapes` and tests, not shown to the agent.

## Default mode regression

`git diff 75f4303 31fb465 -- declarative_spec research_loop`: default mount (`mount_dict`, `mount_plain`) and default lemma index are byte-identical on 242 files compared; the only default-prompt change is item 3 (four lines). `example_registry.UNMOUNTED` gets the seven `principles/*` names (good: the registry-completeness test will not demand them). `container_batch.command` forwards the flag only when set; `run_artifacts.effective_settings` records `full` when unset. No silent fallback found in the launcher path (items 8, 9).

## Verus re-verification of the seven files

NOT re-run by me: my `heavy.sh` job queued behind another session's job on the machine-wide timing lock and I cancelled it rather than hold the queue. The repo's own `test_principle_verifies` / `test_a_wrong_body_is_rejected` / `test_principle_returns_the_rows_duckdb_returns` (Verus, mutations, DuckDB parity) are the authority; I did not verify that they pass at 31fb465. My review of the headers is by reading only (item 11).
