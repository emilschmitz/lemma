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
| emitter refuses float ordering, equality, MIN, MAX (`declarative_spec/float_order.py`) | no proved bridge from f64 `<` to real `<` (see Q24); coverage item, not an agent failure | `tests/test_declarative_float_order.py` (7 refused forms, 4 allowed forms) |
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

## Round 2 (seed 7102) - in progress

Refused during the draw (coverage items): SEC Q18 and Q17 (`ORDER BY n.value DESC` over a float, correlated float MAX),
Q14 (HAVING SUM(float) > scalar subquery), Q9 (ORDER BY SUM(float)). All reason: `float comparison has no proved bridge to reals`.

Drawn: SEC Q2 (`pre` GROUP BY `(stmt, rfile)` with COUNT(DISTINCT adsh), AVG(line), ORDER BY cnt; string tuple key, known-hard),
SEC Q19 (`num` NOT EXISTS `pre`, float SUM, HAVING COUNT > 10, ORDER BY cnt LIMIT 1000; known-hard),
TPC-H Q6-variant (ungrouped decimal sum with date and discount filters; worked-example shape).
