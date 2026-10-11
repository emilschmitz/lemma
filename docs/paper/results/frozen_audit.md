# Audit of the frozen Lemma container run (Sonnet 5.5, TPC-H SF1 + SSB SF1, 19 queries)

Read-only audit. Nothing under `research_loop/generated` or `research_loop/runs` was modified. Scratch scripts live in the session scratchpad.

## 0. Scope, sources, caveats

- Frozen commit: `75f4303` (`FROZEN_SHA.txt`; every run manifest says `git_sha=75f4303`, `git_dirty=true`). The audit worktree HEAD is `31fb465` (LEMMA_EXAMPLES=principles, a later commit); I did **not** use it. All 74 `.rs` files mounted under `workspace/context/ro/examples/` in a run are byte-identical to `tests/fixtures/declarative_proofs/` at `75f4303` (checked with `git show | cmp`), and the same 74 files are mounted in all 19 runs.
- Runs: `research_loop/generated/container_runs/sonnet_{ssb,tpch}_q*.log`; each `RESULT` line gives `run_dir` under `research_loop/runs/`. Config from the manifests: model `claude-sonnet-5-5`, `LEMMA_STRING_ENCODING=dict`, `LEMMA_JOIN_CHAIN=1`, `LEMMA_ENABLE_PARALLEL=0`, `LEMMA_FAST_TRUSTEDS=0`, `LEMMA_SPEED_BAR_MULT=1.0`, `AGENT_TIMEOUT_SEC=750`, `max_iterations=2`, Docker CLI.
- "Submitted body" = `workspace/mcp_results/submitted.json` `runquery_body`. Its `AGENT_HELPERS` + `AGENT_EDIT` regions are what is compared. For all 19 the assembled `workspace/declarative_build/declarative_query.rs` carries the identical regions (token-for-token) and its `verify_full.log` shows the same `N verified, 0 errors` as `submitted.json`, so the assembled program audited in Q2 is the submitted one.
- **No thinking text exists.** In `agent_stream.jsonl` and `claude_raw.jsonl` every `thinking` block has an empty `thinking` field and only an encrypted `signature` (19 runs, 0 chars except 244 chars in ssb_q2_1 that carry no example talk). The requested "thinking snippet" is replaced by the agent's visible assistant messages, quoted where they exist.
- **Unversioned input:** the TPC-H runs used `LEMMA_ASSUMPTION_PACKAGE=/home/emil/projects/lemma-db/research_loop/assumption_packages/registry/tpch_sf1.json`. That file is untracked (git status of the main checkout: `?? research_loop/assumption_packages/registry/`; mtime 2026-10-09 22:27, so after the 10-08 `.md`). It is not part of `75f4303`. It declares `unique_keys` for all 8 tables (e.g. `c_custkey`, `o_orderkey`, `p_partkey`, `(l_orderkey,l_linenumber)`), which `LEMMA_JOIN_CHAIN` consumes. A reader of the frozen SHA cannot reproduce the TPC-H specs without that file. The SSB runs used the tracked `ssb_sf1.json`.

## 1. Q1: copying

Method: regions (`AGENT_HELPERS_START..END` + `AGENT_EDIT_START..END`) of the submitted body vs the same regions of each of the 74 mounted examples (whole file when an example has no markers); comments (`//...`) stripped, whitespace collapsed, empty lines dropped. `ratio` = `difflib.SequenceMatcher(autojunk=False).ratio()` over line lists. `cov` = matched-block lines / submitted lines (immune to the example being much longer than the body). `verbatim` = fraction of submitted lines that occur as a line in the example, over all lines and over lines of >= 15 characters (excludes `}`, `{` and similar). Verdict by `ratio` (>0.8 copied, 0.4-0.8 adapted, <0.4 own).

| query | submitted lines | top example | ratio | cov | verbatim (all / >=15ch) | 2nd | verdict |
|---|---|---|---|---|---|---|---|
| ssb_q1_1 | 387 | `parallel_ungrouped_product_sum.rs` | 0.58 | 0.51 | 0.57 / 0.39 | `parallel_ungrouped_sum.rs` 0.57 | **adapted** |
| ssb_q1_2 | 390 | `parallel_ungrouped_sum.rs` | 0.60 | 0.51 | 0.57 / 0.37 | `parallel_ungrouped_product_sum.rs` 0.59 | **adapted** |
| ssb_q1_3 | 516 | `parallel_ungrouped_product_sum.rs` | 0.50 | 0.40 | 0.54 / 0.33 | `parallel_ungrouped_sum.rs` 0.49 | **adapted** |
| ssb_q2_1 | 1162 | `hard/dict_parallel_star_join_group_sum_sorted.rs` | 0.59 | 0.57 | 0.64 / 0.51 | `hard/dict_parallel_star_join_two_keys_string_order.rs` 0.50 | **adapted** |
| ssb_q2_3 | 678 | `hard/dict_parallel_star_join_group_sum_sorted.rs` | 0.50 | 0.64 | 0.65 / 0.53 | `hard/dict_parallel_star_join_two_keys_revenue_order.rs` 0.49 | **adapted** |
| ssb_q3_1 | 930 | `hard/dict_parallel_star_join_two_keys_revenue_order.rs` | 1.00 | 1.00 | 1.00 / 1.00 | `hard/dict_parallel_star_join_two_keys_string_order.rs` 0.52 | **copied** |
| ssb_q3_2 | 930 | `hard/dict_parallel_star_join_two_keys_revenue_order.rs` | 0.93 | 0.93 | 0.93 / 0.90 | `hard/dict_parallel_star_join_two_keys_string_order.rs` 0.51 | **copied** |
| ssb_q3_3 | 945 | `hard/dict_parallel_star_join_two_keys_revenue_order.rs` | 0.92 | 0.91 | 0.92 / 0.89 | `hard/dict_parallel_star_join_two_keys_string_order.rs` 0.51 | **copied** |
| ssb_q3_4 | 953 | `hard/dict_parallel_star_join_two_keys_revenue_order.rs` | 0.78 | 0.77 | 0.80 / 0.73 | `hard/dict_parallel_star_join_two_keys_string_order.rs` 0.48 | **adapted** |
| ssb_q4_1 | 1071 | `hard/dict_parallel_star_join_group_sum_sorted.rs` | 1.00 | 1.00 | 1.00 / 1.00 | `hard/dict_star_join_group_sum_sorted.rs` 0.78 | **copied** |
| ssb_q4_2 | 1212 | `hard/dict_parallel_star_join_two_keys_string_order.rs` | 1.00 | 1.00 | 1.00 / 1.00 | `hard/dict_parallel_star_join_group_sum_sorted.rs` 0.65 | **copied** |
| ssb_q4_3 | 1254 | `hard/dict_parallel_star_join_two_keys_string_order.rs` | 0.79 | 0.78 | 0.81 / 0.75 | `hard/dict_parallel_star_join_group_sum_sorted.rs` 0.59 | **adapted** |
| tpch_q01 | 1686 | `hard/dict_parallel_q1.rs` | 0.89 | 0.84 | 0.86 / 0.81 | `hard/group_decimal_sums_string_keys_sorted.rs` 0.25 | **copied** |
| tpch_q03 | 1347 | `tpch_q3_join_group_topk.rs` | 0.37 | 0.28 | 0.46 / 0.25 | `float_group_sum_order_limit.rs` 0.20 | **own** |
| tpch_q06 | 304 | `parallel_ungrouped_product_sum.rs` | 0.93 | 0.93 | 0.93 / 0.89 | `parallel_ungrouped_product_sum_slices.rs` 0.74 | **copied** |
| tpch_q09 | 1654 | `hard/dict_parallel_star_join_group_sum_sorted.rs` | 0.35 | 0.29 | 0.43 / 0.23 | `hard/dict_parallel_star_join_two_keys_string_order.rs` 0.31 | **own** |
| tpch_q12 | 444 | `hard/dict_parallel_q12.rs` | 0.18 | 0.45 | 0.56 / 0.40 | `hard/string_tuple_count_distinct_sorted.rs` 0.15 | **own** |
| tpch_q14 | 335 | `tpch_q14_promo_ratio.rs` | 0.43 | 0.39 | 0.53 / 0.38 | `dict_join_probe_sum.rs` 0.16 | **adapted** |
| tpch_q18 | 1124 | `dict_join_probe_sum.rs` | 0.10 | 0.07 | 0.30 / 0.01 | `hard/dict_anti_join_group_topk.rs` 0.09 | **own** |

Notes on borderline cases:
- ssb_q3_4 (0.78) and ssb_q4_3 (0.79) are one step below the "copied" line; 73-75% of their non-trivial lines are verbatim from the Q3.1 / Q4.2 example. Treat them as near-copies with the filter predicates and dictionary sizes edited.
- tpch_q12 is "own" only because its body is 444 lines against a 1844-line parallel example (ratio is size-penalised); `cov`=0.45, 56% of its lines occur verbatim in `hard/dict_parallel_q12.rs`. The agent's own summary: "My own helper lemmas ... (adapted from the TPC-H Q12 example)". It is a sequential body (no `spawn`) that reuses the example's lemma blocks.
- tpch_q03 (0.37, verbatim 0.46) and tpch_q09 (0.35, verbatim 0.43) are below 0.4 but share a lot of structure with their top example (Q3: the TPC-H Q3 reference body, then rewritten parallel; Q9: the SSB star-join example). Only tpch_q18 (0.10, 0.01 non-trivial verbatim) is clearly independent.
- Counts: copied 7 (ssb_q3_1, q3_2, q3_3, q4_1, q4_2, tpch_q01, tpch_q06), adapted 8, own 4. Three of the copies are exact: ssb_q3_1, ssb_q4_1, ssb_q4_2 have ratio 1.00 and equal line counts to the example (the example **is** that query's earlier solution, see Q4(C)).
- INDEX.md in the mounted examples labels these files by benchmark query name ("SSB Q4.1", "SSB Q3.1", "SSB Q4.2", "TPC-H Q1", "TPC-H Q12", "TPC-H Q3", "TPC-H Q14", "TPC-H Q6 shape"), so the agent was told which file solves its query.

### 1(a) Example files opened, in order of first reference

Detected from tool calls (Read paths and shell commands: cat/sed/head/open/grep/ls) that mention `examples` or an example basename. `#n` is the tool-call index (0-based) in `agent_stream.jsonl`. Edits are not listed; the remaining calls are `runquery_agent.rs` edits, `run_runquery`/`submit_runquery` and unrelated shell.

- **ssb_q1_1** (20 tool calls): #15 sh:parallel_ungrouped_product_sum.rs
- **ssb_q1_2** (19 tool calls): #9 sh:parallel_ungrouped_product_sum.rs; #10 sh:<dir>; #11 sh:parallel_ungrouped_product_sum.rs
- **ssb_q1_3** (32 tool calls): #10 sh:parallel_ungrouped_product_sum.rs; #11 sh:`cd /workspace/context/ro; grep -rn "Arc::new\|Arc<Vec" examp`; #12 sh:h/dict_parallel_q12.rs, h/dict_parallel_star_join_group_sum_sorted.rs; #13 sh:parallel_ungrouped_product_sum.rs
- **ssb_q2_1** (50 tool calls): #2 Read:INDEX.md; #3 Read:h/dict_star_join_group_sum_sorted.rs; #6 sh:h/dict_star_join_group_sum_sorted.rs; #7 sh:h/dict_star_join_group_sum_sorted.rs; #13 sh:h/dict_parallel_star_join_group_sum_sorted.rs; #14 Read:h/dict_parallel_star_join_group_sum_sorted.rs; #15 Read:h/dict_parallel_star_join_group_sum_sorted.rs; #16 Read:h/dict_parallel_star_join_group_sum_sorted.rs; #18 Read:h/dict_parallel_star_join_group_sum_sorted.rs
- **ssb_q2_3** (10 tool calls): #2 Read:h/dict_parallel_star_join_group_sum_sorted.rs; #3 Read:h/dict_parallel_star_join_group_sum_sorted.rs
- **ssb_q3_1** (10 tool calls): #2 Read:INDEX.md; #3 Read:h/dict_parallel_star_join_two_keys_revenue_order.rs; #4 Read:h/dict_parallel_star_join_two_keys_revenue_order.rs; #5 sh:h/dict_parallel_star_join_two_keys_revenue_order.rs
- **ssb_q3_2** (9 tool calls): #2 Read:h/dict_parallel_star_join_two_keys_revenue_order.rs; #3 Read:h/dict_parallel_star_join_two_keys_revenue_order.rs; #4 sh:h/dict_parallel_star_join_two_keys_revenue_order.rs
- **ssb_q3_3** (13 tool calls): #2 Read:`/workspace/context/ro/examples/hard/INDEX.md`; #3 sh:h/dict_parallel_star_join_two_keys_revenue_order.rs, h/dict_star_join_group_sum_sorted.rs; #4 Read:h/dict_parallel_star_join_two_keys_revenue_order.rs; #5 Read:h/dict_parallel_star_join_two_keys_revenue_order.rs; #6 sh:h/dict_parallel_star_join_two_keys_revenue_order.rs
- **ssb_q3_4** (11 tool calls): #1 Read:h/dict_parallel_star_join_two_keys_revenue_order.rs; #3 Read:h/dict_parallel_star_join_two_keys_revenue_order.rs
- **ssb_q4_1** (10 tool calls): #2 Read:h/dict_parallel_star_join_group_sum_sorted.rs; #3 grepToolCall:h/dict_parallel_star_join_group_sum_sorted.rs; #4 sh:h/dict_parallel_star_join_group_sum_sorted.rs
- **ssb_q4_2** (7 tool calls): #2 Read:h/dict_parallel_star_join_two_keys_string_order.rs; #3 sh:h/dict_parallel_star_join_two_keys_string_order.rs
- **ssb_q4_3** (47 tool calls): #2 Read:INDEX.md; #3 Read:h/dict_parallel_star_join_two_keys_string_order.rs; #4 Read:h/dict_parallel_star_join_two_keys_string_order.rs; #5 sh:h/dict_parallel_star_join_two_keys_string_order.rs; #6 sh:h/dict_parallel_star_join_two_keys_string_order.rs
- **tpch_q01** (21 tool calls): #2 Read:INDEX.md; #3 sh:h/dict_parallel_q1.rs; #4 sh:h/dict_parallel_q1.rs; #5 Read:h/dict_parallel_q1.rs; #6 Read:h/dict_parallel_q1.rs; #7 Read:h/dict_parallel_q1.rs; #8 sh:float_group_avg_decimal.rs; #9 sh:h/dict_parallel_q1.rs
- **tpch_q03** (107 tool calls): #2 Read:INDEX.md; #3 Read:tpch_q3_join_group_topk.rs; #4 sh:dict_string_filter_minmax.rs; #6 sh:h/dict_parallel_star_join_group_sum_sorted.rs; #11 sh:tpch_q3_join_group_topk.rs; #12 sh:tpch_q3_join_group_topk.rs; #13 sh:tpch_q3_join_group_topk.rs; #42 sh:parallel_ungrouped_sum.rs; #43 sh:h/dict_parallel_star_join_group_sum_sorted.rs; #44 sh:h/dict_parallel_star_join_group_sum_sorted.rs; #55 sh:h/dict_parallel_star_join_group_sum_sorted.rs; #56 Read:h/dict_parallel_star_join_group_sum_sorted.rs; #57 Read:h/dict_parallel_star_join_group_sum_sorted.rs; #58 sh:h/dict_parallel_star_join_group_sum_sorted.rs
- **tpch_q06** (7 tool calls): #2 Read:parallel_ungrouped_product_sum.rs; #3 sh:parallel_ungrouped_product_sum.rs
- **tpch_q09** (54 tool calls): #2 sh:h/dict_parallel_star_join_two_keys_string_order.rs, h/dict_star_join_group_sum_sorted.rs; #3 Read:h/dict_star_join_group_sum_sorted.rs; #4 sh:tpch_q14_promo_ratio.rs; #5 Read:tpch_q14_promo_ratio.rs; #6 sh:`cd /workspace/context/ro/verus; cat INDEX.md | head -60; gre`; #9 sh:h/dict_parallel_star_join_group_sum_sorted.rs; #10 sh:`cd /workspace/context/ro/verus/vstd; sed -n 1,140p string.rs`; #11 sh:h/dict_parallel_star_join_group_sum_sorted.rs; #29 sh:h/dict_parallel_star_join_group_sum_sorted.rs; #34 sh:h/dict_parallel_star_join_group_sum_sorted.rs; #40 sh:h/dict_parallel_star_join_group_sum_sorted.rs; #41 Read:h/dict_parallel_star_join_group_sum_sorted.rs; #42 Read:h/dict_parallel_star_join_group_sum_sorted.rs
- **tpch_q12** (12 tool calls): #2 sh:h/dict_parallel_star_join_group_sum_sorted.rs, h/dict_star_join_group_sum_sorted.rs; #3 Read:h/dict_parallel_q12.rs; #4 sh:h/dict_star_join_group_sum_sorted.rs; #5 Read:h/dict_parallel_q12.rs; #6 sh:h/dict_parallel_q12.rs
- **tpch_q14** (7 tool calls): #2 sh:<dir>; #3 Read:tpch_q14_promo_ratio.rs; #4 sh:tpch_q14_promo_ratio.rs
- **tpch_q18** (74 tool calls): #2 sh:<dir>; #3 sh:h/dict_join3_group_topk.rs; #4 sh:h/dict_group_two_keys_count_distinct_avg.rs, h/dict_having_scalar_subquery.rs, h/dict_parallel_q1.rs; #5 sh:h/dict_having_scalar_subquery.rs, h/dict_parallel_q1.rs

Reading of the order: SSB Q3.1-3.4, Q4.1, Q4.2, Q4.3 and TPC-H Q1/Q6/Q14 open exactly the top-matching file within the first 2-5 tool calls (ssb_q4_1: 10 calls total, ssb_q4_2: 7, ssb_q3_1: 10, tpch_q06: 7, tpch_q14: 7). ssb_q1_1 first wrote its own sequential body, was refused below the bar, then `cat`ed `parallel_ungrouped_product_sum.rs` at call #15. ssb_q1_1..q1_3, q2_1, q2_3 and tpch_q12 were routed to the nearest-shape example and adapted. tpch_q18 browsed several unrelated SEC examples and wrote its own.

### 1(c) Decision snippets (assistant text; thinking is empty)

- ssb_q3_1: "I copied that example's helpers and body into `runquery_agent.rs` and changed nothing." (also: "The query is the same as the worked example ... (SSB Q3.1) and the spec matches it.")
- ssb_q4_1: "Markers are in the example. Splice it into the agent file with a script."; later "I copied the helpers and `run_query` body of the verified parallel SSB Q4.1 example ... so I made no changes to it."
- ssb_q4_2: "The worked example `hard/dict_parallel_star_join_two_keys_string_order.rs` is this exact query, SSB Q4.2." ... "I copied its helper region and `run_query` body".
- ssb_q3_2: "taken from the closest worked example (`dict_parallel_star_join_two_keys_revenue_order.rs`) and adapted." ssb_q3_3: "I adapted the verified parallel SSB Q3.1 example ... the filters become `c_city`/`s_city` ..., and the dictionary-size bounds go from 128 to 1024."
- ssb_q2_3: "The correctness proof is adapted from the SSB Q4.1 parallel example, simplified".
- tpch_q01: "I built it by adapting the verified TPC-H Q1 example (`hard/dict_parallel_q1.rs`)". tpch_q06: "The body is the parallel product-sum template ... I changed the template's constants to this query's".
- tpch_q12: "adapted from the TPC-H Q12 example". tpch_q14: "the same division as the TPC-H Q14 example".
- ssb_q1_1/q1_2/q1_3, q2_1, q3_4, q4_1.., tpch_q03/q09/q18: no visible statement about examples.

## 2. Q2: trusted items in the assembled, Verus-verified program

Method: grep of `workspace/declarative_build/declarative_query.rs` (the verified file) for `#[verifier::external_body]`, `#[verifier::external*]`, `assume_specification`, `admit(`, `assume(`, `axiom_`, `broadcast use`. Result: **no** `assume_specification`, `#[verifier::external]`, `#[verifier::external_fn_specification]`, `admit(` or `assume(` in any of the 19 programs; no trusted item inside the agent regions (admission rejects them; confirmed 0 in region).

| query | `external_body` (all host, `HOST_LEMMAS` block from `declarative_spec/lemmas.py`) | vstd axiom broadcast (host prelude, line 81) | host-proved chain lemmas | threads (vstd `spawn`/`join`) | verified |
|---|---|---|---|---|---|
| ssb_q1_1 | 0 | 0 | `lemma_chain_hit_unique` + 4 zero/single + `_row` = proved | yes | 31/0 |
| ssb_q1_2 | 0 | 0 | same | yes | 31/0 |
| ssb_q1_3 | 0 | 0 | same | yes | 38/0 |
| ssb_q2_1 | 0 | 1 | `lemma_chain_hit_unique` + 8 zero/single + rows = proved | yes | 89/0 |
| ssb_q2_3 | 0 | 1 | same | yes | 57/0 |
| ssb_q3_1 | 0 | 1 | same | yes | 76/0 |
| ssb_q3_2 | 0 | 1 | same | yes | 76/0 |
| ssb_q3_3 | 0 | 1 | same | yes | 76/0 |
| ssb_q3_4 | 0 | 1 | same | yes | 75/0 |
| ssb_q4_1 | 0 | 1 | `lemma_chain_hit_unique` + 10 zero/single + rows = proved | yes | 85/0 |
| ssb_q4_2 | 0 | 1 | same | yes | 95/0 |
| ssb_q4_3 | 0 | 1 | same | yes | 98/0 |
| tpch_q01 | **11** (float idealization) | 0 | none emitted | yes | 111/0 |
| tpch_q03 | 0 | 2 (i64, i32 key model) | `lemma_chain_hit_unique` + 6 zero/single + rows = proved | yes (2 spawn sites, 3 join) | 70/0 |
| tpch_q06 | 0 | 0 | none | yes | 21/0 |
| tpch_q09 | 0 | 1 | `lemma_chain_hit_unique` + 12 zero/single + rows = proved | yes | 109/0 |
| tpch_q12 | 0 | 0 | `lemma_chain_hit_unique` + 8 zero/single = proved | no (sequential) | 38/0 |
| tpch_q14 | **12** (float idealization + division by zero) | 0 | `lemma_chain_hit_unique` + 8 zero/single = proved | no | 36/0 |
| tpch_q18 | 0 | 2 (i64, i32) | none (`lemma_group_close_rows` only) | no | 75/0 |

Per-origin detail:
1. **Float idealization, `declarative_spec/lemmas.py` (HOST_LEMMAS block, labelled "TRUSTED (f64 idealization)")**: present only in tpch_q01 (11 items) and tpch_q14 (12 items). The 11 common items: `lemma_f64_add_real`, `lemma_f64_sub_real`, `lemma_f64_mul_real`, `lemma_f64_div_real`, `host_u64_to_f64`, `host_i128_to_f64`, `lemma_f64_lt_real`, `lemma_f64_le_real`, `lemma_f64_gt_real`, `lemma_f64_ge_real`, `lemma_f64_eq_real` (all `#[verifier::external_body]`; bodies empty `{ }` for the lemmas, plain casts for `host_*`). tpch_q14 adds `host_f64_div_by_zero` (IEEE division by +0.0; body `x / 0.0`). The header states that f64 add/sub/mul/div/cast are an idealization (rounding ignored), comparisons trusted only as the link from vstd predicates to `as real`. Of the 19 queries only these two touch f64.
2. **Chain lemmas (`declarative_spec/chain_lemmas.py`, `LEMMA_JOIN_CHAIN=1`)**: `lemma_chain_hit_unique`, `lemma_<fold>_zero_d<k>`, `lemma_<fold>_single_d<k>`, `lemma_<fold>_row`, `lemma_group_close_rows`, and the `chain_term_<fold>` spec fns are ordinary `proof fn` with bodies: **proved, not `external_body`** (0 `external_body` in all 17 programs that carry them, and `N verified, 0 errors`). They rely on the **assumption** that the chained dimension keys are unique, which is a `valid_cols_*` conjunct (`forall i<j ... !(key[i]==key[j])`, e.g. `valid_cols_date`) that `main` checks at run time.
3. **Loaders / `main`**: `load_cols_<table>` are inside `verus!` with `requires` (caps, ranges, unique keys) and `ensures valid_cols_...`; they are proved (body builds the struct). `fn main()` (file reader, `assert!` of row counts against the DuckDB pin, per-column length, `ROW_CAP`/value caps, dictionary relations, trailing bytes) is **outside `verus!`**: ordinary Rust, not verified, not `external_body`. The `requires` of the loaders are therefore backed by runtime `assert!`s only (23-66 asserts per program). Also outside `verus!`: any timing/bench harness (`std::time::Instant`), `std::fs::read`.
4. **Hash-key axioms (vstd, broadcast by the host prelude)**: `broadcast use vstd::std_specs::hash::axiom_i64_obeys_hash_table_key_model;` in 10 programs, plus `axiom_i32_obeys_hash_table_key_model` in tpch_q03 and tpch_q18 (count column above). They are vstd axioms (`broadcast proof fn axiom_*`, trusted by vstd). No program uses vstd `HashMapWithView`/`StringHashMap`/`HashSetWithView` (grep: 0), so the axiom is in scope but the generated bodies index arrays instead; the only `HashSet` text is in `main` (unverified std code).
5. **Agent regions**: 0 trusted items in all 19; `#[verifier::opaque]` appears in ssb_q1_3 (2), tpch_q01 (8), tpch_q09 (1), tpch_q18 (9); `opaque` hides a definition from the solver, it adds no trust.

vstd trust that the verified programs depend on (short note): `vstd::thread::spawn` and `JoinHandle::join` are `#[verifier::external_body]` (vstd/thread.rs) and carry the spec that the closure's return satisfies the predicate (used by 16 of 19; not tpch_q12, q14, q18); `Vec` specs (`push`, `len`, indexing, `with_capacity`, `std_specs/vec.rs` has 5 `external_body`), `std::sync::Arc::new` / deref via `assume_specification` in `std_specs/smart_ptrs.rs`, integer arithmetic/cast specs in `std_specs/num.rs`, `String`/`str` specs where dictionaries appear, and the f64 predicates in `vstd::float` (for the 2 float queries). Counts per query: host-emitted `external_body` = 0 for 17 queries, 11 for tpch_q01, 12 for tpch_q14; assume/admit/assume_specification = 0 for all 19.

## 3. Q3: beating DuckDB (official, `official_interleaved_medians`, K=5 rounds, 9 DuckDB reps, interleaved order alternating, `speed_bar_mult=1.0`)

Ratio = duck median / ours median (equals `official.speedup`). Band = `ratio_band` from the per-round ratios. "Entirely above 1.0" = band lower bound > 1.0. All 19 are `status SUCCESS`, `inconclusive=False`.

| query | ours ms | duck ms | ratio (medians) | band [lo, hi] | rounds >1.0 | band entirely >1.0 | inconclusive |
|---|---|---|---|---|---|---|---|
| ssb_q1_1 | 6.73 | 8.77 | 1.30 | [1.16, 1.47] | 5/5 | yes | False |
| ssb_q1_2 | 4.85 | 5.79 | 1.20 | [1.14, 1.53] | 5/5 | yes | False |
| ssb_q1_3 | 3.07 | 5.44 | 1.77 | [1.39, 1.88] | 5/5 | yes | False |
| ssb_q2_1 | 6.41 | 14.06 | 2.19 | [2.19, 2.75] | 5/5 | yes | False |
| ssb_q2_3 | 5.70 | 14.27 | 2.50 | [2.02, 2.93] | 5/5 | yes | False |
| ssb_q3_1 | 6.88 | 22.75 | 3.30 | [3.24, 3.81] | 5/5 | yes | False |
| ssb_q3_2 | 9.33 | 17.54 | 1.88 | [1.84, 2.20] | 5/5 | yes | False |
| ssb_q3_3 | 9.00 | 16.84 | 1.87 | [1.78, 2.39] | 5/5 | yes | False |
| ssb_q3_4 | 4.90 | 12.62 | 2.58 | [2.16, 2.99] | 5/5 | yes | False |
| ssb_q4_1 | 10.66 | 25.86 | 2.42 | [2.37, 2.57] | 5/5 | yes | False |
| ssb_q4_2 | 9.86 | 24.23 | 2.46 | [2.44, 3.01] | 5/5 | yes | False |
| ssb_q4_3 | 13.54 | 15.77 | 1.16 | [1.10, 1.31] | 5/5 | yes | False |
| tpch_q01 | 7.69 | 25.18 | 3.28 | [3.01, 3.44] | 5/5 | yes | False |
| tpch_q03 | 17.43 | 20.23 | 1.16 | [1.08, 1.20] | 5/5 | yes | False |
| tpch_q06 | 6.14 | 7.27 | 1.18 | [1.03, 1.32] | 5/5 | yes | False |
| tpch_q09 | 54.69 | 70.74 | 1.29 | [1.17, 1.42] | 5/5 | yes | False |
| tpch_q12 | 15.17 | 18.08 | 1.19 | [1.03, 1.21] | 5/5 | yes | False |
| tpch_q14 | 10.64 | 15.73 | 1.48 | [1.44, 1.51] | 5/5 | yes | False |
| tpch_q18 | 22.04 | 64.96 | 2.95 | [2.86, 3.36] | 5/5 | yes | False |

All 19 have all 5 rounds above 1.0 and a band lower bound above 1.0. Margins are thin for tpch_q06 (lo 1.03), tpch_q12 (lo 1.03; hi 1.21), tpch_q03 (lo 1.08), ssb_q4_3 (lo 1.10), ssb_q1_1/q1_2 (1.16/1.14), i.e. 6 of 19 have a lower bound under 1.2x. Machine in the manifests: 8 threads, `target_cpu=x86-64-v3`; the session in-run speedup reported by `run_runquery` was sometimes measured at the 50k iterate cap (tpch_q12, tpch_q14 and ssb_q3_4/q4_2 summaries say so); the table above is the host's official full-table measure. The queries that are copied from or equal to an own-solution example (ssb_q3_1 3.30x, q4_1 2.42x, q4_2 2.46x, tpch_q01 3.28x) are among the largest wins.

## 4. Q4: fit (what shaped the agent's inputs)

Range audited: merge base with `main` = `d3b40d5`; commits `d3b40d5..75f4303` (22 non-merge commits; 2 merges `0b65aba`, `3cfd839`). Motivation comes from commit messages and `research_loop/menus/iter_tpch_ssb_LOG.md` (failure table + causes C1-C6, round 1 results). Files `lemmas.py`, `numeric_rewrite.py`, `resolve.py`, `parse_query.py` (except `ee714d4`), `emit_agg/filter/join.py` were not changed in the range.

### (A) Transpiler / declarative_spec code that shapes the spec (affects what must be proved)
| commit | what it does | motivating query |
|---|---|---|
| `ee714d4` | comma-join rewrite in `parse_query.py` (+96 lines) and `emit.py`; SSB SF1 loader, 13 standard SSB queries, `ssb_sf1` assumption package | all 13 SSB (SSB uses `FROM a, b WHERE ...`) |
| `8476041` | `LEMMA_JOIN_CHAIN` (default off, on in this run): `join_chain.py`, `chain_lemmas.py`, `emit_surface.py`: fact-first fold order for unique-key join chains, unique-key requirements for chained tables, host-proved zero/single-support lemmas; `ssb_sf1.json` declares unique keys | cause C4: SSB Q2.1/Q3.1/Q4.x and TPC-H Q9 (and Q3 speed) failed at the 3-6 table joins |
| `6fb7c92` | `join_chain.py`: resolve a qualified column by exact alias first (self-joins) | adversary review of join_chain; no benchmark query named |
| `4bb67f1` | host-proved `lemma_chain_hit_unique` and `lemma_<fold>_row`; self-joins are not chains | C4 (star joins) |
| `0a716af` | `emit_surface.py`: `group_close` lemmas for a string ORDER BY without LIMIT under join_chain; also accidentally added `research_loop/generated` as a symlink | SSB Q2.1 / Q4.x (string ORDER BY, no LIMIT) |
| `d061001` | `chain_lemmas.py`: term fn renamed `chain_term_<fold>` (alias collision); adversary verdict | adversary finding F1, no query |

### (B) Everything else that shapes the agent (prompt, examples, assumption packages, harness/measure)
| commit | what it does | motivating query |
|---|---|---|
| `d67e0e0` | harness: `RUN TIMEOUT` (60 s) message for a verified binary that does not finish; MCP wait > inner limits (`pipeline.py`, `verus_limits.py`, `measure_core.py`) | SSB Q3.2 (lost 15 of 25 min to silent 300 s waits) |
| `a0572ae` | prompt names only example files mounted in the run's string mode; says `submit_runquery` refuses a run below the bar; failure log of 11 failures | TPC-H Q1 and Q12 (named non-mounted `dict_*` parallel examples), C1/C2/C5 |
| `b70439f` | `container_batch` forwards `LEMMA_JOIN_CHAIN`; manifest records it | infrastructure for the chain mode |
| `c4310f8` | **example** `hard/dict_star_join_group_sum_sorted.rs` (SSB Q4.1 sequential, 62 verified), recipe `dict_star_join`, prompt section | SSB Q4.1 (C4) |
| `0a3304b` | **example** `hard/dict_parallel_star_join_group_sum_sorted.rs` (SSB Q4.1 parallel, 85 verified, 2.7x), registry + prompt | SSB Q4.1 (C6) |
| `35c2cc1` | **example** `hard/dict_parallel_star_join_two_keys_revenue_order.rs` (SSB Q3.1, 76 verified, 2.4x) | SSB Q3.1 |
| `bd60b87` | **example** `hard/dict_parallel_star_join_two_keys_string_order.rs` (SSB Q4.2, 95 verified, 2.25x) | SSB Q4.2 |
| `c59009e` | RESULT error empty for a SUCCESS (`run_container_agent.py`) | SSB Q3.3 (stale timeout printed beside a 3.05x SUCCESS) |
| `c8e7112` | chain prompt section: why the SUM fits (one tuple per fact row) | SSB / TPC-H Q9 SUM-width failures |
| `a8925cb`, `d0235c1` | LOG: round 1 results, run id | docs |
| `4ad56d3` | second adversary verdict + tests for join_chain | docs/tests |
| `6bd91de` | official speed verdict: K interleaved rounds DuckDB vs ours, verdict on medians, bar unchanged; in-session measure labelled | measurement validity (not a query) |
| `114c815` | official measure: DuckDB per-round preamble, ratio band + inconclusive flag, no mixed-source speedups, spill cleanup | measurement validity |
| `c286322` | `ssb13.py` transpile+typecheck funnel for the 13 SSB queries | SSB |
| `0b65aba` | merge of main (egress bridge proxy tunnelling, `container_batch` env pass-through, COMPARABILITY.md, non-SEC catalog loading) | infrastructure |
| `3cfd839` | merge of main (`results_table.py`) | reporting |
| `75f4303` | untrack `research_loop/generated` (self-referencing symlink from `0a716af` wiped data twice) | infra fix |

### (C) Which mounted example solves which benchmark query (own-solution), and when it was written
Run set: TPC-H Q1, Q3, Q6, Q9, Q12, Q14, Q18; SSB Q1.1-Q1.3, Q2.1, Q2.3, Q3.1-Q3.4, Q4.1-Q4.3.

| example file | solves | written | during this iteration? |
|---|---|---|---|
| `hard/dict_parallel_star_join_group_sum_sorted.rs` | **SSB Q4.1** (header carries the exact SQL) | `0a3304b`, 10-10 04:29 | **yes** (from the earlier round of this very benchmark) |
| `hard/dict_star_join_group_sum_sorted.rs` | **SSB Q4.1** sequential | `c4310f8`, 10-10 04:19 | **yes** |
| `hard/dict_parallel_star_join_two_keys_revenue_order.rs` | **SSB Q3.1** (siblings Q3.2-Q3.4 differ only in WHERE) | `35c2cc1`, 10-10 04:39 | **yes** |
| `hard/dict_parallel_star_join_two_keys_string_order.rs` | **SSB Q4.2** (Q4.3 is a sibling) | `bd60b87`, 10-10 04:53 | **yes** |
| `hard/dict_parallel_q1.rs` | **TPC-H Q1** (SF3 3.95x) | `7adadff`, 10-04 19:49 | no (on main before the merge base) |
| `hard/dict_parallel_q12.rs` | **TPC-H Q12** | `1830ee0`, 10-05 07:30 | no |
| `tpch_q3_join_group_topk.rs` | **TPC-H Q3** (sequential reference body, plain strings) | `c4b4870`, 10-04 21:44 | no |
| `tpch_q14_promo_ratio.rs` | **TPC-H Q14** | `c4b4870`, 10-04 21:44 | no |
| `parallel_ungrouped_product_sum.rs`, `parallel_ungrouped_product_sum_slices.rs`, `ungrouped_decimal_product_sum.rs` | **TPC-H Q6 shape** (also SSB Q1.x shape: ungrouped SUM of a product under range filters) | `c1ac5c6` 10-04 17:58; `6b56db7` 10-05; `dbd8c74` 10-04 | no |
| `hard/group_decimal_sums_string_keys_sorted.rs` | TPC-H Q1 shape (plain strings) | `c52101a`, 10-04 | no |
| `tpch_q19_disjunction.rs` | TPC-H Q19 (not in this run) | `c4b4870` | no |
| no example | TPC-H Q9, TPC-H Q18, SSB Q1.x exact, Q2.1, Q2.3 (nearest shapes only) | - | - |
| all other 50-odd fixtures (float_*, projection_*, SEC `dict_*`, `parallel_dict_*`, `hard/dict_*topk`, ...) | SEC / GenDB-published shapes and technique demos, none a benchmark solution | 10-04 to 10-07 | no |

Observation for the paper: the four examples written during this iteration are, by their own headers, the verified solutions of SSB Q4.1, Q3.1 and Q4.2 from the previous round, and three of those queries were then submitted verbatim (ratio 1.00) in the frozen run; Q3.2-3.4 and Q4.3 are 0.78-0.93 near-copies of them. TPC-H Q1, Q6 (0.93), Q14 and Q12 were solved from older own-solution examples. Only tpch_q18 (and, by ratio, q09 and q03) is independent of any example that solves a benchmark query. The mounted set therefore leaks benchmark solutions into 15 of 19 runs (7 copied, 8 adapted); the later `LEMMA_EXAMPLES=principles` commit `31fb465` (not audited here) is the change that removes that.
