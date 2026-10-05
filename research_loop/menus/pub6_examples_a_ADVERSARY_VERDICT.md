# Adversary verdict: pub6 examples A (dict_anti_join_group_topk.rs, dict_join3_group_topk.rs)

Reviewer: manual adversary (Sonnet). No Verus was run. No code was modified.

## Verdict: SOUND AFTER FIXES

Neither fixture teaches an unsound proof pattern and neither contains a banned construct. There are two real defects in
the prompt wiring (finding 1: plain-mode mounting bug; finding 2: contradictory "no worked example" warning), one
policy hole (finding 3: per-function `#[verifier::rlimit]` taught and not rejected), one mis-route (finding 4), and several
header/test weaknesses.

## What I verified (all by reading code and running non-Verus commands)

- Admission: ran `admit_declarative_body` on the extracted AGENT_EDIT body and `admit_helpers` on the AGENT_HELPERS region of both
  fixtures: `ok=True, violations=[]` for all four calls. (Helper name collision against host names is checked only at assemble
  time; I passed an empty spec.)
- Grep for `assume`, `admit`, `external`, `arbitrary`, `axiom`, `unimplemented`, `assume_specification`, `requires false`,
  `unsafe`, `use`: nothing in code. The only `#[verifier::...]` attributes are `opaque` (both files) and one `rlimit(30)` (join3 only).
  `by (nonlinear_arith)` appears only in the `pk` range/injectivity lemmas, with explicit `requires`.
- Every `proof fn` has real `requires` that are discharged at call sites; the `ensures` on `lemma_final*` mirror the host
  `ensures` (top-k, completeness when `res.len() < LIMIT`, sorted, distinct, omitted-row bound). Packing is guarded:
  `gok` includes the `< 2^32` checks and `lemma_pk_inj` is used for membership (header item 3 is accurate). The sentinel
  (dictionary length) for untranslatable pre strings is proved in `tr_ok`. So no vacuous invariant or too-weak quantifier lets a
  wrong result verify.
- Spec equivalence: emitted specs (SEC catalog, dict mode) for the fixture's LEFT JOIN ... IS NULL form and for the same query as
  NOT EXISTS are identical except for the order of conjuncts in `row_hit`; both produce `!exists_1(n, p, i0)` and both
  `query_features` contain `not_exists`. So registering the LEFT JOIN fixture as the `not_exists` witness is right.
- Routing (ran `emit_declarative_spec` + `spec_shape`): LEFT JOIN anti, NOT EXISTS and positive EXISTS (2 tables) -> `dict_anti_join`;
  IN / NOT IN -> `dict_join` (no `exists_` in spec); 3-table grouped join -> `dict_join3`; self-correlated NOT EXISTS (1 table) -> `dict_group`.
- `uv run pytest -q -p no:cacheprovider tests/test_declarative_prompt.py tests/test_declarative_shapes.py`: 47 passed.

## Findings

1. **Plain-string mode mounts the two dict-only examples (real bug).** `declarative_spec/prompt.py:282-283`
   (`mount_examples`): the skip `if name.startswith("dict_")` tests the full relative name, and the new `_EXAMPLES` entries
   (prompt.py:181-190) are `hard/dict_anti_join_group_topk.rs` / `hard/dict_join3_group_topk.rs`, which start with `hard/`. I ran
   `mount_examples` with `LEMMA_STRING_ENCODING=plain`: it wrote `examples/hard/dict_anti_join_group_topk.rs` and
   `examples/hard/dict_join3_group_topk.rs`. This contradicts the intent of `test_both_new_examples_are_mounted_in_dict_mode_only`
   (tests/test_declarative_prompt.py:347-354), which only checks `dict_having_scalar_subquery.rs` (not in `_EXAMPLES`) and so does not catch it.
   Plain-mode agents get 4.5k lines of examples whose spec idiom (`__dict`, `Cols_*__dict`) does not exist in their spec.
   Fix: `if Path(name).name.startswith("dict_"): continue` and extend the test to assert both new files are absent in plain mode.

2. **Contradictory warning in the NOT EXISTS prompt.** `_HARD_FEATURES` (prompt.py:215) still lists `exists_` as "EXISTS / IN / NOT EXISTS
   against another table", and `build_declarative_prompt` (prompt.py:708-717) then prints "## Warning: this spec has features with no worked
   example" right after the recipe section that points to the anti-join example. The agent is told both. Fix: in dict mode drop the `exists_`
   hard feature when `recipe == "dict_anti_join"` (or reword the warning: "worked example above is the NOT EXISTS shape; positive EXISTS is the flipped test").

3. **`#[verifier::rlimit(30)]` is taught and not rejected (policy hole, not a soundness hole).** `dict_join3_group_topk.rs:16` (header item 5:
   "give the aggregator lemma `#[verifier::rlimit(N)]`") and `:2376` (`rlimit(30)` on `lemma_final_all`). The host budget is `--rlimit 3`
   (verus_limits.py: "never a weakening"; prompt.py:588 says the budget is the host's `--rlimit`). A per-function attribute is a 10x
   override that `admit_helpers` does not reject (it only rejects `#[verifier::external...]`), and an agent following the header can write
   `rlimit(1000)` to dodge the host limit and burn the 300 s wall instead. This also contradicts the prompt line "rlimit budget is the host's".
   Fix: either restructure `lemma_final_all` so it verifies at 3 (preferred, matches every other fixture), or state in the header the
   exact maximum used (30), say it was needed on one lemma only after splitting, and add `verifier::rlimit` handling to admission (reject, or cap N).
   Also note the fixture test (`tests/test_declarative_hard_fixtures.py:_verify`) runs with `timeout_sec=600` while the host default wall is 300 s
   (`DEFAULT_TIMEOUT_SEC`): a 3218-line proof may not fit the agent's wall; record the measured verify time in the header.

4. **`dict_join3` mis-routes ungrouped or non-top-k three-table joins.** `prompt.py:232`: `elif recipe == "dict_join" and tables >= 3`. I ran
   `SELECT MIN(n.ddate) FROM num n JOIN sub s ... JOIN pre p ...` (ungrouped) and a plain grouped join with no ORDER BY/LIMIT: both get
   `dict_join3` ("four-key GROUP BY, SUM and COUNT, ORDER BY the sum and LIMIT"), a 3218-line example that has no scalar-MIN or no-top-k
   structure, instead of the small `dict_join_probe_sum.rs`. Fix: require `out_row_ok(` and a limit marker (as the group top-k fixtures have;
   cf. line 271) before choosing `dict_join3`, else keep `dict_join`. Also add a routing test for positive EXISTS (now `dict_anti_join`; the
   description says "flip the membership test", which is acceptable, but nothing tests it) and for the ungrouped 3-table case.
   Minor: a self-correlated NOT EXISTS (one `Cols_` struct) gets `dict_group`, no anti-join example; acceptable but not mentioned.

5. **Dataset-specific constants in the bodies are not flagged in the headers.** `dict_anti_join_group_topk.rs:379-394` and the body assert on
   `46116860184273879039999` (the SEC `value` cell bound), and `dict_join3_group_topk.rs:473,484,783-792`: `assert(JOIN_CAP_num_pre as int == 68719476736int)`
   and the same i128 literal. These numbers come from the SEC catalog; an agent with another catalog that copies them gets assert failures
   (not unsoundness) and the header never says "read these bounds from your spec's `valid_cols_*` / `JOIN_CAP_*`". Item 4 of the join3 header
   ("Bound sums with the host join cap") also hides that the uniqueness of `sub.adsh` used by technique 2 (`lemma_ae_unique`, line 197) comes from
   the host's `valid_cols_sub` (catalog unique key); if the join key is not declared unique, the per-code array is wrong and a chain on both
   sides is needed. Fix: add one header line each: "numeric caps and the unique-key fact come from your spec's `valid_cols_*`/`JOIN_CAP_*`; do not copy the literals".

6. **Header item 8 overstates (anti-join).** `dict_anti_join_group_topk.rs:19` says `valid_cols_<t>(cols)` stays in the invariant of "every loop".
   By my loop scan, 2 of 12 loops lack it: the `used` init loop (`while z < glen`, body line ~444) and the inner selection scan (`while g < glen`, ~480);
   neither indexes a column, which is fine and consistent with the prompt's slimming rule, but the claim is false as written and
   `test_the_new_examples_keep_valid_cols...` (test_declarative_prompt.py:384-395) only checks that `valid_cols_` occurs once anywhere in the body.
   Fix header: "in every loop that indexes a column". Strengthen the test to check per loop, or drop the claim from the test name.
   Item 3 says "tuple and String keys are not hashable here" while the same body uses `StringHashMap<usize>`: say "tuple keys and multi-column keys".

7. **Test weaknesses.**
   - Mutation tests (tests/test_declarative_hard_fixtures.py:126-144) assert `not ok and "error" in out`. `"error" in out` is vacuous (it matches
     "0 errors", "timeout", a guard kill message), and `not ok` is also true for a rustc error, a wall/RAM-guard kill, or an rlimit hit.
     By inspection the four mutants are type-correct (bool flip, constant change) and replace the first and only occurrence, so they should fail
     in proof; the date and fiscal-year ones fail at semantic asserts (`hit == row_hit`, `sf`). The `"EUR"` mutant, however, fails at the fixture's own
     `usd@ == "USD"@` invariant before any semantic check, so it proves only literal consistency, not that the spec's literal is checked; prefer
     mutating the `uok`/`ufound` comparison. Fix: assert `re.search(r"verification results:: \d+ verified, [1-9]\d* errors", out)` (and no `error[E` rustc code).
   - `assert "keep" in p  # the header is inlined` (test_declarative_prompt.py, new routing test) is nearly vacuous: lowercase "keep" appears in
     the hygiene text of every prompt. Assert a distinctive header string ("Techniques (each fixed a failure").
   - The banned-construct test searches raw text including comments (`text.replace("// ","//")` does nothing useful) and does not call admission;
     call `admit_declarative_body`/`admit_helpers` on the extracted regions instead (both pass as of this review).

8. **Stale size claim.** `prompt.py:459` still says "about 550 lines" for every `hard/` example; these are 1286 and 3218 lines (Read defaults to 2000 lines).
   Fix: compute the line count or say "read it in chunks".

## Not found

No (a) unsound pattern, no (c) banned construct, and the registration in `shapes.py:49` is correct. `rlimit` is the only item in category (a)/(d) and
it is a resource-policy issue (finding 3). Query literals (`'USD'`, `2023`, `20230101`) are acceptable, and both headers state "names differ in your spec; keep the structure".

## Resolution (author, after the review)

1. Fixed: `mount_examples` tests `Path(name).name`; test added (plain mode mounts neither dictionary hard example).
2. Fixed: the `exists_` "no worked example" warning is dropped when the recipe is `dict_anti_join`; test added.
3. Not restructured: `#[verifier::rlimit(30)]` stays on the one join3 lemma that exceeded the default budget of 3 (it is a resource attribute, not a trust surface); the header now says so and says to keep N small. Measured: the whole join3 fixture verifies in about 6 s here, far below the wall. Capping the attribute in admission is left as a follow-up (host change, not an example change).
4. Fixed: `dict_join3` routing requires a LIMIT marker (`res@.len() <= N`); ungrouped 3-table test added.
5. Fixed: both headers say the cell bounds and `JOIN_CAP_...` come from the agent's own spec; join3 notes the unique `sub.adsh` assumption.
6. Fixed: header item 3 (String keys) and item 8 (valid_cols in loops that read columns).
7. Fixed: mutation tests assert `verification results:: N verified, [1-9]\d* errors`; banned-construct check now also runs `admit_declarative_body` / `admit_helpers`.
8. Fixed: "about 550 lines" replaced.
