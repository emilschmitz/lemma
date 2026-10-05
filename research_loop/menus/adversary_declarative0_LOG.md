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

| **r5 SEC T1 HELD-OUT `SELECT MIN(value), SUM(value) FROM num WHERE value > 5000`** (DECIMAL, synthetic, 1M rows) | T1 | **held-out** | manual, 1 check (after the DECIMAL-cap host fix) | **YES, 9 verified, 0 errors** | **1,753** | 9,384 | 21,374 | **5.35x / 12.19x** |

r5 T1 held-out: the first prover run (before the transpiler's fix) stopped after 1 check with a Verus-confirmed, logically
explained blocker: `error: possible arithmetic underflow/overflow` at `acc = acc + v` because `valid_cols_num` bounded the DECIMAL(38,4)
cell by its type (1e38), so two valid rows already exceed i128 (same root cause as r4 T3; the prover argued a counterexample, not
hand arithmetic; I accepted it as confirmed because Verus rejected the add and the transpiler agent reproduced it). After the
transpiler agent's fix (cells bounded by min(type digits, catalog cap), refusal when rows x cap can exceed i128) the same shape proved
on the first try with the existing recipes (backward pass, branch-free accumulate, min witness/bound invariants, no helper).
Clears the 5.0x SEC target against the all-core engine (synthetic 1M-row data, so not GenDB-scale). Blame for the first failure: step 2
(transpile), host spec.

| r5 TPC-H T2 HELD-OUT `SELECT l_returnflag, min(l_extendedprice), count(*) FROM lineitem WHERE l_shipmode = 'AIR' GROUP BY l_returnflag` (TPC-H SF1, 6.0M rows) | T2 | **held-out** | manual, 11 of 12 checks | **proof YES (35 verified, 0 errors); speed bar MISSED** | 59,671 | 7,548 | 26,331 | **0.13x / 0.44x** |

r5 T2 held-out trace: checks 1 to 5 `RLIMIT: Z3 ran out of resources ... --rlimit 3` on `run_query` (18 to 33 verified), found by bisecting
whole checks (no `--profile`): the culprit was a lemma `ensures` quantified over `row_hit` (fix: pointwise lemmas called from `assert forall
... by`), and `valid_cols_lineitem` kept in every loop invariant put its quantifier in every loop context (fix: plain length and ROW_CAP facts);
check 10 proved (66,490 us), check 11 tried a 3-byte `as_bytes` compare for `l_shipmode = 'AIR'` (59,671 us). Classification: the proof
failures are step 3/5 with blame **setup didn't give the ability** (the inlined recipe is COUNT-only with different names; no per-group MIN
invariant example; the rlimit hint does not say "prefer pointwise lemmas"); the speed miss is step 7 with blame **setup didn't give the ability**:
the loader materializes string columns as `Vec<String>` (one heap pointer per row), so the filter on `l_shipmode` costs ~10 ns/row while the
reference engine scans a dictionary-coded column. No provable cheap alternative exists today (the only trick is the 1-char `as_bytes` code of
the TPC-H Q1 example). Candidate for a PROPOSAL to Emil (not built, would be new trusted code via the adversary-gated protocol): a
dictionary-encoded string column in the loader (codes `u8/u16` plus a code-to-string table) with the loader relation as the trusted statement.

| **r5 SEC T3 HELD-OUT `SELECT MIN(n.ddate) FROM num n JOIN sub s ON n.adsh = s.adsh WHERE n.uom = 'USD'`** (DECIMAL schema, synthetic, num 1M x sub 40k) | T3 | **held-out** | manual, 2 checks | **YES, 11 verified, 0 errors** | **8,633** | 15,024 | 32,647 | **1.74x / 3.78x** |

r5 T3 held-out: check 1 proved first try but 22,613 us (0.66x); check 2 added "skip the probe for rows that cannot improve the MIN
(`!(any && d >= lo)`)" with the cheap string filter first: 8,633 us. Design: `StringHashMap<usize>` built from `sub.adsh` (value = row
index = the join witness), probed while scanning `num` once. Now fixture `join_min_stringhashmap_probe.rs` (verified by test) with recipe
`join_min_probe` and the skip tip in the speed section of the prompt.

**Rlimit regression (found while re-verifying fixtures after merging the float idealization):** the long hard fixture
`hard/group_decimal_sums_string_keys_sorted.rs` verified at `--rlimit 3` before the merge (63 verified) and now fails with
`error: function body check: Resource limit (rlimit) exceeded` in `lemma_codes_insert`; with `LEMMA_VERUS_RLIMIT=6` it verifies (59 verified, 0 errors
in the harness run). The f64 idealization lemmas now sit in every spec's context, so long proofs cost more. The fixture test sets rlimit 6 for
that one fixture (documented in the test); a real agent faces the host default 3 -> for the coordinator: either raise the default for declarative
runs or move the f64 lemmas out of the context of specs that do not use floats.

Prove rate by tier so far (manual prover, all rounds, tuned+held-out; only counted when a prover really tried): T1: 3/3 proved (min/max
string filter, Q6 variant, held-out MIN+SUM), 2/3 faster than the all-core engine (3.83x, 5.35x; Q6 0.53x). T2: 2/2 proved (TPC-H Q1 1.15x,
held-out TPC-H min/count 0.13x). T3: 1/2 proved (held-out join MIN 1.74x; the other was a host spec bug now fixed). T4: 1/4 proved (Q11 0.64x;
Q20/Q24/Q19 early failures with the pre-fix setup). Frontier: T1 to T3 prove reliably; T4 proves with long hand-built helpers (Q11).
Held-out only: T1 1/1 (5.35x), T2 1/1 proved (0.13x), T3 1/1 (1.74x).

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

## REAL-SIZE RESULTS (data stated per line; synthetic numbers are retired for claims)

Real EDGAR 2022-2024 loaded by the coordinator: num 39,401,761 rows (value exact DECIMAL(38,4)), pre 9,600,799, sub 86,135, tag 1,070,662
(`holdout/gendb_sec_edgar/duckdb/sec_edgar_dec.duckdb`, package `sec_margin_dec`, passes on the real data). TPC-H SF1 (lineitem 6,001,215). One heavy job at a time, memory caps via systemd-run.

| query | data | tier | body | proved | us | duck 8t | duck 1t | speedup (8t / 1t) |
|---|---|---|---|---|---|---|---|---|
| `SELECT MIN(value), SUM(value) FROM num WHERE value > 5000` | real SEC, full 39.4M num rows (reads value only: i128, 630 MB) | T1 | single-threaded (the r5 held-out body, transplanted and RE-VERIFIED against the real-data spec: 5 verified, 0 errors) | yes | 107,684 | 230,712 | 931,027 | **2.14x / 8.65x** |
| `SELECT SUM(value) AS total FROM num WHERE value > 5000` | real SEC, full 39.4M num rows | T1 | PARALLEL, 8 vstd threads (`parallel_ungrouped_sum.rs` templated to i128/value, 18 verified, 0 errors) | yes | **17,128** | 219,016 | 872,864 | **12.79x / 50.96x** |
| TPC-H Q6 variant | TPC-H SF1 (6.0M lineitem) | T1 | PARALLEL, 8 vstd threads (`parallel_ungrouped_product_sum.rs`, 21 verified, 0 errors) | yes | **5,827** | 11,874 | 22,786 | **2.04x / 3.91x** (the single-threaded body was 0.53x / 1.22x) |

| TPC-H Q6 variant, same parallel body | TPC-H SF3 (18.0M lineitem; 4 columns, 0.5 GB) | T1 | PARALLEL 8 vstd threads (21 verified, 0 errors) | yes | 16,925 | 19,181 | 67,619 | **1.13x / 4.00x** |
| TPC-H Q6 variant, same parallel body | TPC-H SF10 (60.0M lineitem; 1.7 GB binary memory) | T1 | PARALLEL 8 vstd threads (21 verified, 0 errors) | yes | 55,668 | 69,506 | 262,942 | **1.25x / 4.72x** |

| `SELECT COUNT(*), SUM(value) FROM num WHERE uom = 'USD'` | real SEC, full 39.4M num rows, dict mode (uom as codes) | T1 | single-threaded (dict_filter_count_sum.rs, 8 verified, first check) | yes | 65,068 | 278,767 | 1,015,002 | **4.28x / 15.6x** |

| `SELECT uom, COUNT(*), SUM(value) FROM num GROUP BY uom` | real SEC, full 39.4M num rows, dict mode (dense arrays over codes) | T2 | single-threaded (dict_group_count_sum_dense.rs, 10 verified, first check) | yes | 52,550 | 255,004 | 999,800 | **4.85x / 19.0x** |
| `SELECT COUNT(*), MIN(line) FROM pre WHERE stmt = 'BS' AND line > 3` | real SEC, full 9.6M pre rows, dict mode, NULLABLE `stmt` (validity bit) | T1 | single-threaded (7 verified, 7 checks of speed tuning) | yes, **speed bar missed** | 13,419 best / 17,620 last | 12,618 | 35,913 | **0.94x best, 0.72x last (timing noise 13.4 to 18.4 ms) / 2.0x to 2.7x** |

The last one is a bandwidth-bound scan (about 96 MB) that loses to the all-core engine single-threaded, exactly the class the parallel path is for;
a parallel body for the dict + validity shape is not written yet. Observation from the prover: the check's timing noise (about 30 percent between identical runs on this shared box) makes a 6 percent gap undecidable: a repeat or median-of-more timing in the check would help.

| `SELECT uom, COUNT(*), SUM(value) FROM num GROUP BY uom` | real SEC, full 39.4M num rows, dict + PARALLEL 8 workers with dense per-worker arrays | T2 | parallel (dict_group_count_sum_parallel.rs, 26 verified, 2nd check) | yes | 22,475 median of 9 (best 21,068) | 293,965 | 1,208,574 | **13.08x (best 13.95x) / 53.8x** |

| TPC-H Q1 (2 dict string keys, 3 decimal sums incl. a product, count, ORDER BY keys) | TPC-H SF3 (18.0M lineitem), dict + PARALLEL 8 workers, flat m1*m2 slot array | T2 | parallel (`hard/dict_parallel_q1.rs`, 87 verified, 5 checks) | yes | 21,931 median of 9 (best 21,585) | 86,551 | 295,017 | **3.95x (best 4.01x) / 13.5x** |
| TPC-H Q1, same body (size-independent: row cap by `ROW_CAP_lineitem`) | TPC-H SF10 (60.0M lineitem), dict + PARALLEL | T2 | parallel, re-verified against the SF10 spec (87 verified) | yes | 59,412 median of 9 (best 54,872) | 226,544 | 977,544 | **3.81x (best 4.13x) / 16.5x** |

| `SELECT COUNT(*), MIN(line) FROM pre WHERE stmt = 'BS' AND line > 3` (nullable stmt) | real SEC, full 9.6M pre rows, dict + PARALLEL 8 workers | T1 | parallel (`parallel_dict_nullable_count_min.rs`, 23 verified, 2nd check) | yes | 6,614 median of 9 (best 6,322) | 12,162 | 35,203 | **1.84x (best 1.92x) / 5.3x** (single-threaded body: 0.72x to 0.94x) |

| `SELECT SUM(n.value) FROM num n JOIN sub s ON n.adsh = s.adsh WHERE s.form = '10-K'` | real SEC, num 39.4M JOIN sub 86,135, dict adsh codes | T3 | single-threaded (transpiler agent's `dict_join_probe_sum.rs`: per-sub-code count array, num dictionary translated to sub codes once, one probe pass; 24 verified; re-verified on the real spec) | yes | 117,412 median of 9 (best 113,662) | 293,080 | 1,221,707 | **2.50x (best 2.58x) / 10.4x** |

TPC-H 2.8x target: MET by Q1 at SF3 (3.95x) and SF10 (3.8x to 4.0x), a compute-bound shape (6 aggregates over 2 tiny-domain keys) where the parallel dense-array design beats the all-core engine; Q6-class scans are structurally bandwidth-bound (1.1x to 1.25x at SF3/SF10).

Measurement protocol from here: the timed measure is the MEDIAN of 9 runs and the check also reports the best run (`speedup`, `speedup_best`); gaps under 25 percent between a body and the reference engine are ties (the shared box shows ~30 percent run-to-run noise: DuckDB's own 8-thread median for the same query moved 255 to 294 ms between prepares).
Transplanting the single-threaded TPC-H Q1 body (r4, SF1 spec) to the SF3 spec failed: `54 verified, 1 errors` (the SF1 body does not carry over); a dict + parallel Q1 prover run on SF3 is in progress.

Real-data blocker found: real EDGAR has NULL cells in columns queries read (pre.stmt 1,073, sub.fy 4,662, sub.fp 4,665, tag.crdr 119,636 ...); the export refuses NULLs, so those queries cannot run yet (sent to the transpiler agent, who is building validity-bit NULL support). Dict caps (max_distinct) were declared by the transpiler agent and pass check.py on the real DB.

Scale ladder for Q6 (data stated): SF1 2.04x, SF3 1.13x, SF10 1.25x vs the all-core engine; ~4x vs one thread at every size. At SF3/SF10 the parallel scan reads ~30 GB/s (504 MB in 16.9 ms), i.e. it is at the machine's memory bandwidth, and DuckDB 8t is about as fast
(zone-map pruning of the shipdate range avoids part of the data). So the 2.8x TPC-H target is NOT reachable for this bandwidth-bound scan with the same bytes read; SF10 is the largest that ran (generated with `research_loop/scripts/gen_tpch.py`, dbgen under a 3 GB DuckDB memory limit: 81 s, 2.7 GB file; export 4:52).

Parallel path (declarative-only, `LEMMA_PARALLEL_VSTD=1`, `declarative_spec/parallel.py`): `run_query` also takes `<t>_arc: &std::sync::Arc<Cols_t>` with
`requires **<t>_arc == *<t>` (host main passes the same object twice), ensures unchanged. Workers own `Arc::clone`s and fold row ranges; the host's
suffix folds are additive so the partials telescope (no copy, no concatenation lemma). Trusted base: vstd `spawn`/`join`/`Arc` only; no
new trusted code of ours. A panicked worker (`join` Err, impossible for proved code) is recomputed inline with the same loop (a `loop {}` is not
admissible: no `decreases`). Examples verified by tests with negative mutations. The bandwidth-bound loser class (Q6) now beats the all-core engine; the
5.0x SEC target is met by the parallel SUM (12.8x) and the 2.8x TPC-H target is not yet (2.04x at SF1; larger SF not tried: 14 GB box, concurrent agents).
Not parallelized yet: grouped aggregates, joins, projections.

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
