# adversary_declarative0 log

Menu: `research_loop/trust_configs/adversary_declarative0.py` (declarative spec path; no fast, parallel, vector-scan,
spill-hash or fold-slot trusteds; vstd threads and hash maps are allowed on every menu).
Speed bar: `LEMMA_SPEED_BAR_MULT` (default 1.0 = merely faster; target 5.0x SEC, 2.8x TPC-H = GenDB over DuckDB,
`docs/paper/article_draft.md`). Reported per query: speedup over DuckDB at all 8 threads and at 1 thread.

Data used (14 GB box, 8 threads): SEC = the local 1M-row `num` slice
(`holdout/gendb_sec_edgar/duckdb/sec_edgar_local.duckdb`: num 1,000,000; pre 250,000; sub 40,000; tag 5 rows; the full
SEC set of 39.4M rows is not on this machine). TPC-H = SF1 generated with the DuckDB tpch extension
(`lineitem` 6,001,215 rows), native DECIMAL/DATE, honest catalog (row caps = measured counts). Larger SF does not fit
beside the other agents. Attainment against 5.0x / 2.8x is therefore indicative only.

Credentials: none of ANTHROPIC_API_KEY / LEMMA_CLAUDE_CONFIG_DIR was set in the launching shell, so the Claude runner
fails loudly (`claude agent selected but neither ANTHROPIC_API_KEY nor LEMMA_CLAUDE_CONFIG_DIR is set`).
ALL results below are **manual prover (Sonnet subagent), not a model-agent result**.

Memory rules (after the 2026-10-04 12:27 OOM): Verus only through `scripts/ram/verus_guarded.sh` (the manual harness sets
`LEMMA_VERUS_BIN` to it), one heavy job at a time, one manual prover at a time, TPC-H at most SF1.

## Setup changes (commits on `worktree-agent-a53c2a0e21969b179`)

| Fix | Why | Tests |
|---|---|---|
| menu `adversary_declarative0`, registered | round 0 | `tests/test_trust_configs.py` (resolves, applies flags, restores; no `LEMMA_EXACT_SUM`) |
| `LEMMA_SPEED_BAR_MULT`, `speedup`, `speedup_1t`, `duck1_us` | bar is configurable; attainment per query | `tests/test_declarative_measure.py`, `tests/test_decl_query_measure.py` |
| manual harness: absolute paths, `check` reads kind and `context/ro/query.sql` from the workspace | check failed on relative paths | `tests/test_declarative_manual.py` |
| `write_query_measure` writes `expect.json` | in-session `run_runquery` had no official columns, bar or expected rows on the measure path | `tests/test_declarative_manual.py` |
| (REMOVED, see the last line) emitter refused float ordering, equality, MIN, MAX (`declarative_spec/float_order.py`) | no proved bridge from f64 `<` to real `<` (see Q24); coverage item, not an agent failure | `tests/test_declarative_float_order.py` (7 refused forms, 4 allowed forms) |
| prompt rewrite: what you get, regions and rules, SQL, the ONE recipe for this spec's result type with the verified fixture inlined, hard-shape warning, speed, hygiene, one lemma index | prompt was 420 lines, repetitive, count recipe only fit `HashMapWithView` + `KEY_CAP` | `tests/test_declarative_prompt.py` (10 tests); stale prompt tests in `tests/test_spec_style.py` removed (they asserted text the integration prompt no longer had) |
| measure export streams in 500k-row chunks | SF1 `lineitem` export peaked at 6 GB of Python tuples | chunked == one chunk byte for byte; NULL in a later chunk still fails |
| `LEMMA_VERUS_BIN` override | run Verus through the memory guard | `tests/test_declarative_manual.py` |

Pre-existing failures on `integration/declarative-1`, not mine: `tests/test_spec_style.py::test_declarative_success_does_not_run_lease`,
`::test_unset_success_still_runs_lease` (RuntimeError).

Finding: the SEC `value` column is DOUBLE, so with float ordering refused the majority of GenDB-shaped SEC queries
(anything `ORDER BY SUM(value)`, `HAVING SUM(value) > ...`, `MAX(value)`) is out of scope until Emil decides on a float
comparison bridge. In the seed-7102 draw 4 of the first 7 shuffled queries were refused for this reason (Q9, Q14, Q17,
Q18; Q14: HAVING float SUM vs scalar AVG; Q9: ORDER BY total_value).

## Round 1 (seed 7101) - manual prover (Sonnet subagent), not a model-agent result

Prompt: the old 420-line prompt. Draw saved in `research_loop/generated/decl_rounds/draw_7101_first.json`
(the shuffle generator is not deterministic for a fixed seed; always read the saved draw).

| Query | SQL shape | step / blame | Trace quote | Speed |
|---|---|---|---|---|
| SEC Q20 | `num` JOIN `tag`, COUNT(DISTINCT adsh), CASE sums over `value > 0`, HAVING, LIMIT 200 | step 3 (agent), **setup didn't give the ability** (prompt and lemma gaps) | prover: no real attempt, judged infeasible: many-to-many join, COUNT DISTINCT via a double-indexed existential, nested string-tuple key, top-200 selection, "no helper lemmas/examples". (Now also emitter-refused: `n.value > 0` is a float comparison.) | none (DuckDB 139.4 ms / 234.9 ms at 8 / 1 threads) |
| SEC Q24 | `num` JOIN `sub`, correlated `MAX(n2.value)`, ORDER BY value DESC, LIMIT 1000 | step 3 (agent) / step 2 (spec): **host spec has no proved float comparison bridge** (setup didn't give the ability) | `last_check.json`: `verification results:: 17 verified, 1 errors`; `error: assertion failed ... assert((a as real) < (b as real));` and `postcondition not satisfied ... hit_count(n, s, 0) <= 1000`. Prover probe `if a < b { assert((a as real) < (b as real)); }` fails: vstd's `f64` `< <= > >=` are uninterpreted `lt_ensures` predicates. Not fixable without a trusted comparison bridge. Not added; question is with Emil. | none (DuckDB 82.4 / 121.4 ms) |
| TPC-H Q18-shape | `lineitem` GROUP BY `l_orderkey` HAVING `sum(l_quantity) > 304` ORDER BY LIMIT 100 | step 5 (verify) / step 3 (agent): known-hard shape (HAVING + top-K); **setup didn't give the ability** (no worked example; Z3 rlimit settings still coming) | `last_check.json`: `verification results:: 38 verified, 2 errors`; `error: while loop: Resource limit (rlimit) exceeded` at `declarative_query.rs:820` (`while i > 0`) and `:996` (`while c < ks.len()`); also `warning: using ==> in assert forall does not currently assume the antecedent` x3. The prover got a long way (38 of 40 obligations). | none (DuckDB 109.6 / 277.1 ms) |

Prove rate round 1: 0/3 (Q20 and Q24 are setup/spec gaps, not agent stupidity; Q18 is rlimit on a known-hard shape).
Not a single result is a model-agent result.

Fixes triggered by round 1: float refusal, prompt restructure with worked examples and the known-hard list,
`expect.json`, absolute paths, chunked export (see table above).

## Bandwidth-bound single-thread losers (data for scoping a vstd-thread parallel loader; nothing built)

Emil's decision (relayed): anything straight from vstd, including `vstd::thread::spawn/join`, may be used on any menu.
We do not build a parallel loader here; this table is the data for scoping one.

| Query (round) | rows scanned | proved | binary | DuckDB 8 threads | DuckDB 1 thread | vs 8 threads | vs 1 thread |
|---|---|---|---|---|---|---|---|
| TPC-H Q6 variant (r2), manual prover | 6,001,215 `lineitem`, 4 columns, about 168 MB | yes, 15 verified, 0 errors | 21,874 us | 11,490 us | 26,722 us | 0.53x (loss) | 1.22x (win) |

The scan is memory-bandwidth-bound for one core; the bar (all-core engine) is not winnable single-threaded at this size.
Note the DuckDB median moves between prepares (Q6: 11.5 ms, then 8.9 ms on re-prepare), so single bar numbers carry about
25 percent noise on this shared box.

Prompt and examples changes from this result (generic): the bar is stated to be the all-core engine with `speedup_1t`
reported separately; branch-free accumulate (`if hit { v } else { 0 }`, about 1.7x faster than a branchy add on an
unpredictable filter) and `&&` not `&`; the `mul_small` `nonlinear_arith` helper is a verified worked example
(`tests/fixtures/declarative_proofs/ungrouped_decimal_product_sum.rs`, verified by a test through the guarded Verus).

## Round 2 results so far (manual prover, not a model-agent result)

| Query | step / blame | trace quote | speed |
|---|---|---|---|
| TPC-H Q6 variant | step 7 (execute): **proved and then below the bar** (not a proof fail); bandwidth-bound, see table above | `verification results:: 15 verified, 0 errors`; `proved but below the speed bar: query 21874 us, DuckDB 11490 us (0.53x; the bar is 1x faster than DuckDB)` | 0.53x (8 thr), 1.22x (1 thr) |
| SEC Q2 (tuple-of-strings GROUP BY, COUNT DISTINCT, AVG, ORDER BY cnt) | step 3 (agent), AVG part only: **setup didn't give the ability** (f64 division / int-to-f64 lemmas missing; owned by the float-idealization agent) | `verification results:: 41 verified, 1 errors`; the prover set `avg` to `0.0` as a DIAGNOSTIC (its own comment: "f64 div has an unsatisfiable precondition; 0.0 is NOT the true AVG"), so that body is NOT a result | none |

Everything but AVG verified for Q2 (grouping, tuple key, COUNT DISTINCT, sorted result). The AVG-free variant of that body is
now the verified fixture `tests/fixtures/declarative_proofs/hard/string_tuple_count_distinct_sorted.rs` (see fixes below).
Speed note from the prover: that design scans once per group, O(groups x rows), and would lose to the reference engine
on many groups. A single-pass hash-aggregate recipe for grouped COUNT DISTINCT is NOT written yet (open item; needs a
per-group seen-map proof).

Fixes from Q2 (generic, tested):
- helper-region parser (`declarative_spec/admit.py`): a signature or `ensures` with `if ... { } else { }` or a block
  expression no longer splits into fake items (`helper region holds only ... not: else`); braces in parentheses are
  expression braces; a block followed by `else`, `ensures`/`requires`..., an operator or `{` continues the item.
  Tests: 6 block-signature forms accepted (also with a following item), bad item / reused name / duplicate after such a
  signature still rejected, unbalanced parentheses reported.
- prompt: rlimit recipe (opaque spec fns for invariant bundles, one proof fn per property with `reveal`; the misleading
  `invariant not satisfied before loop` symptom), the ground-term / `choose` rule, and a pointer to the hard worked
  example with its header comment (not the 550-line body) when the spec is a grouped COUNT DISTINCT.
- verified hard fixture (test verifies it through the guarded Verus, and a mutated sorted-insert must fail):
  tuple-of-strings group key, per-group distinct set as a backward scan with a `StringHashMap` seen-map, `Vec::insert`
  into a sorted vector (`lemma_ins_*`), opaque invariant bundles, the ground-term pattern.

| SEC Q19 (NOT EXISTS, SUM(value) DOUBLE, HAVING COUNT, ORDER BY cnt LIMIT 1000), DOUBLE schema | step 3 (agent) / step 2 (spec): **setup didn't give the ability**: the f64 eps precondition is unsatisfiable at the host caps | prover (2 of 8 checks, then stopped): `verification results:: 17 verified, 2 errors`. `out_row_ok` needs `|total - sum| <= FLOAT_ABS_EPS` (1e20) but `lemma_f64_sum_within_eps` needs `n_terms^2 * mag_cap / 2^52 <= eps`; `valid_cols` gives group size <= ROW_CAP_num = 2^31 and `|value| < 2^62`, worst case 2^72 ~ 4.7e21 > 1e20, so the lemma's precondition cannot be discharged for a plain left fold. Prompt gaps: no worked float example, no NOT EXISTS / top-K example. NOTE: the prover made only 2 checks and stopped on a hand-arithmetic argument, so this is a weak trace (the Z3 probe was inconclusive); treat as 'prover gave up early', not as a proof of impossibility. This is the DOUBLE variant; the DECIMAL variant (round 3 on) has no eps. | none |

## Results table (tiered; manual prover (Sonnet subagent), not a model-agent result; SEC data is SYNTHETIC)

Tiers: T1 single-table filter + aggregate, T2 single-table GROUP BY, T3 two-table join, T4 EXISTS/IN/scalar subquery/COUNT DISTINCT,
T5 three tables / derived tables / the rest. Held-out shapes (30 percent of shape keys by hash) are drawn only with `--heldout`
and never used for recipes, fixtures or prompt text; tuned and held-out are reported separately. Registry:
`research_loop/generated/decl_rounds/seen_queries.jsonl`.
Prover rules from round 4: at least 6 of 10 checks on real attempts; stop early only with a Verus-confirmed blocker (quoted).

| query | tier | set | prover | proved? | us | duck 8t | duck 1t | speedup (8t / 1t) |
|---|---|---|---|---|---|---|---|---|
| r1 Q20 (pre-tier) | T4 | tuned | manual, old prompt | no (gave up, no attempt) | - | 139,403 | 234,892 | - |
| r1 Q24 | T4 | tuned | manual | no (float bridge) | - | 82,354 | 121,364 | - |
| r1 TPC-H Q18-shape | T2/T4 | tuned | manual | no: 38 verified, 2 rlimit | - | 109,636 | 277,071 | - |
| r2 TPC-H Q6 variant | T1 | tuned (fixture) | manual | yes, 15 verified | 21,874 | 11,490 | 26,722 | 0.53x / 1.22x |
| r2 SEC Q2 | T4 | tuned (fixture) | manual | no: 41 verified, 1 error (AVG) | - | 24,183 | 21,275 | - |
| r2b SEC Q19 (DOUBLE) | T4 | tuned | manual, gave up after 2 checks | no (gave up; eps precondition argument not Verus-confirmed) | - | 31,622 | 38,070 | - |
| r3 SEC Q11 (correlated MAX, top-100, DECIMAL) | T4 | tuned | manual, 10 real checks | no: 59 verified, 1 error | - | 49,171 | 128,903 | - |

| **r4 SEC T1 `SELECT MIN(ddate), MAX(ddate) FROM num WHERE uom='pure' AND qtrs=3`** (synthetic, 1M rows) | T1 | tuned (now a fixture) | manual, 4 checks | **YES, 11 verified, 0 errors** | **320** | 1,227 | 1,830 | **3.83x / 5.72x** |

| **r4 TPC-H T2 (Q1 variant, 6.0M lineitem rows)** | T2 | tuned (now a hard fixture) | manual, 8 checks | **YES, 63 verified, 0 errors** | **32,457** | 37,214 | 110,465 | **1.15x / 3.40x** |

(r4 T2: beats the all-core engine by 1.15x, short of the 2.8x TPC-H target; one backward pass, 1-character string keys as byte codes
into a slot table, groups kept sorted by insertion. Fixture `hard/group_decimal_sums_string_keys_sorted.rs`, verified by a test
against the generated SF1 catalog; prompt lessons added: no exec helper fns, backward pass with suffix invariants, product bounds,
`as_bytes` byte codes, rlimit budget.)

First proved-and-faster result (manual prover (Sonnet subagent), not a model-agent result; official full-table measure with the
row-count check; the target multipliers are 5.0x SEC / 2.8x TPC-H over the multi-threaded engine, so this one clears 2.8x but
not 5.0x on the 8-thread engine). The three failed checks were all one thing: `&str ==` has no spec tying it to `@`
(`assert(e <==> (s@ == "pure"@))` failed, also with `reveal_strlit`). Fix found by the prover from vstd `string.rs`:
`String::from_str("pure")` hoisted out of the loop, `pure@ == "pure"@` in the invariant, compare with `String ==`
(no vstd lemma needed). Now the verified fixture `tests/fixtures/declarative_proofs/ungrouped_minmax_string_filter.rs`
(verified by a guarded-Verus test; a wrong comparison must fail), recipe `ungrouped_minmax`, and a prompt tip. Blame for the three
failed checks: setup didn't give the ability (no string-literal or MIN/MAX example).

| **r3b SEC Q11 re-run after the projection `out_row_ok` fix** (join + correlated MAX + top-100, DECIMAL, synthetic) | T4 | tuned (now a hard fixture) | manual, 10 of 12 checks | **YES proof: 31 verified, 0 errors; speed bar MISSED** | 71,750 | 46,232 | 116,645 | **0.64x / 1.63x** |

| r4 SEC T3 `SELECT s.fy, SUM(n.value) FROM num n JOIN sub s ON n.adsh = s.adsh WHERE n.uom = 'shares' GROUP BY s.fy` (DECIMAL, synthetic) | T3 | tuned | manual, 6 checks | **no: Verus-CONFIRMED spec blocker** | - | 21,886 | 61,915 | - |

r4 T3 (blocker confirmed by Verus, sent to the transpiler agent addcd33571290f391): step 2 (transpile) / step 5 (verify), blame
**host spec**: the emitted `valid_cols_num` bounds the DECIMAL(38,4) `value` cell by its TYPE (`n.value@[i] as int >= -99999999999999999999999999999999999999 &&
... <= 99999999999999999999999999999999999999`), not by the package's `max_value_exclusive = 2^62 * 10^4`; the ensures is an exact `int`
sum over pairs stored in an i128, so two valid cells of 1e38-1 on one adsh already exceed `i128::MAX`. Trace: `verification results::
19 verified, 1 errors`; `possible arithmetic underflow/overflow` at `res.set(j, OutRow { fy: k, total: c + cell })`; the prover's diagnostic
`assert(c as int + cell as int <= i128::MAX as int)` fails. Everything else (the string literal filter after `String::from_str`) proved.
Fix requested: honor the column cap in `valid_cols` for DECIMAL cells and check that `ROW_CAP_num * ROW_CAP_sub * cap < 2^127`
(2^31 * 2^20 * 2^75.3 = 2^126.3) or refuse the class. Re-run after the merge.

r3b Q11 (confirms the projection fix): first monolithic attempt hit `RLIMIT ... --rlimit 3` with the misleading `invariant not
satisfied before loop`; opaque `tk` bundle fixed it; the O(n^2) rescan then timed out (`binary timed out`); replaced by "next
same-key row" chains over `StringHashMap` (proved by an opaque bundle `ch`) -> 111,802 us, then tuned to 71,750 us (value compare
before the tag compare; pre-filter on the sub map; a last-lookup cache and `with_capacity` did not help: data is not clustered by
adsh). Remaining cost: per-row String hashing of 1M rows. Classification for the speed miss: step 7 (execute), blame **agent too
stupid to write something fast? no: setup didn't give the ability** (no provable cheap byte-fingerprint/hash-prefilter idiom; no
dense-array recipe for string keys). Fixture `hard/projection_join_correlated_max_topk.rs` (a proof template, not a speed template).

r3 Q11 trace (Sonnet manual prover, 10 checks): check 1 rejected before Verus (`broadcast use at the top of the helper region`);
2 `Could not automatically infer triggers for this quantifier`; 3 and 4 RLIMIT on `run_query` (`invariant not satisfied before loop`,
`precondition not satisfied`); 5 `run_query` verified (55 verified) with RLIMIT in a final-facts lemma; 6 to 10 `verification
results:: 58/59 verified, 1 errors`, always the first `ensures` clause `forall r. exists i0,i1. row_hit(i0,i1) && out_key(res@[r]) ==
proj_key(i0,i1)` (the output row `res@[r]` appears only inside the `exists`, so the forall has no ground term to fire on; four
workarounds tried: reveal + assert forall by, `let tr = t[r]`, a per-row lemma, a ground `row_hit` seed). Classification: step 3 (agent) /
5 (verify); blame **setup didn't give the ability** (no example for `forall r. exists hit`, only `forall hit. exists r`; no top-K with
multiplicity example). Hard but possible: untried ideas are ghost witness sequences `w0`/`w1` per output row, or a non-opaque
`h_keyhit`. Naive O(n^2) design (rescan per row), so also a speed loser even if it verified. Kept emitted, recorded as hard.
Helper-region note from this run: a module-level `broadcast use` in the helper region is rejected by design (put it inside a proof fn);
the prompt now says so. (Update below.)

## Data note (every result line)

The SEC data on this machine is SYNTHETIC (`holdout/gendb_sec_edgar/synth_tiny.py`), not real EDGAR: `value = round(uniform(1.0, 1e6), 2)`, 1M `num` rows, `coreg`/`footnote` NULL on every row. From round 3 on, queries are drawn on the DECIMAL variant (`sec_edgar_local_dec.duckdb`, `value` DECIMAL(38,4) derived from the stored doubles, package `sec_margin_dec`; `research_loop/menus/sec_decimal_variant.md`). Speeds on 1M synthetic rows are not GenDB-scale.

## Audit of added helpers against vstd (Emil's rule: no junk)

`mul_small` (fixture `ungrouped_decimal_product_sum.rs`; a prover-written helper in a worked example, not a host lemma): grep
`LEMMAS.md` for `lemma_mul_upper_bound` / `lemma_mul_inequality` / `mul_le`: vstd has `lemma_mul_upper_bound(x, xbound, y, ybound)`
requiring `0 <= x`; the decimal cell here is signed (`-999999999999999 <= p`), so there is no exact equivalent. Kept as an
example only. Other fixtures added by me (`string_tuple_count_distinct_sorted.rs`) are example bodies; their helpers
(`seen_inv`, `lemma_ins_*`, `lemma_nf_*`) are specific to the host's `count_distinct_*` / `out_row_ok` spec functions and
have no vstd equivalent beyond `Seq::insert_ensures`-style lemmas, which they already call.

## Round 2 (seed 7102) - draw

Refused during the draw (coverage items): SEC Q18 and Q17 (`ORDER BY n.value DESC` over a float, correlated float MAX),
Q14 (HAVING SUM(float) > scalar subquery), Q9 (ORDER BY SUM(float)). All reason: `float comparison has no proved bridge to reals`.

Drawn: SEC Q2 (`pre` GROUP BY `(stmt, rfile)` with COUNT(DISTINCT adsh), AVG(line), ORDER BY cnt; string tuple key, known-hard),
SEC Q19 (`num` NOT EXISTS `pre`, float SUM, HAVING COUNT > 10, ORDER BY cnt LIMIT 1000; known-hard),
TPC-H Q6-variant (ungrouped decimal sum with date and discount filters; worked-example shape).

- Float shapes are back in scope, refusal removed (`declarative_spec/float_order.py` deleted; f64 idealization, `docs/TRUSTED_FAMILIES.md`): stored-column filters, MIN/MAX, ORDER BY, products and differences, grouped SUM/AVG with HAVING and top-K emit; refused: float equality on computed values, colliding float literals, AVG whose integer sum may exceed 2^53.
