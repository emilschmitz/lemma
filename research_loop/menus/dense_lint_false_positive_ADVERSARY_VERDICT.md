# Adversary verdict: dense-budget lint, expression-level product detector

Verdict: PASS WITH FINDINGS

Setup: new lint = working tree `declarative_spec/dense_budget.py`; old lint = `git show HEAD:declarative_spec/dense_budget.py` loaded as a temp module. Spec/sizes: THREE + REAL from the test file, and the real run specs and `decl_data/expect.json` dict_sizes. `uv run pytest tests/test_declarative_dense_budget.py -q`: 29 passed.

## (b) False positives

- Real attempts, run q32708 (6 files): new lint passes 6/6. The old lint rejected 001-005.
- Real attempts, run q490000 (5 files): new lint passes 5/5. The old lint rejected 001 and 004.
- The only allocations in those files are `vec![0i128; cap]` in q490000 004/005 (a hash table, not a product).
- Hard fixtures: none of the `declarative_proofs` fixtures I could extract and size at 1e6 per dictionary is flagged by either lint. The dict_join3 fixture at real SEC sizes passes, and its dense mutation is rejected (the repo test covers this).
- Remaining false positives: none found on real data. By design, any real product of two dictionary-derived names is rejected even when it is not a slot count (a hash mix such as `(m1 as u64) * (m2 as u64)`). That is accepted conservatism.
- New improvement over old: a `//` comment containing `;` no longer hides a product (`let t = m1 // c; hi` then `* m2`, new True, old False). `m1 * 4 + m2` (a pack with a constant) is no longer flagged.

## (a) False negatives (new misses, old caught)

Repros use the harness `HEAD = let m1 = s.name__dict.len(); let m2 = n.tag__dict.len();` then the snippet, followed by `let g = vec![0u64; t];`.

1. MEDIUM, compound assignment. `let mut t = m1; t *= m2;`. The tokenizer emits `*=` as one token and the detector only looks at `*`, so it is never seen. The old lint caught it. A plausible LLM idiom: `total *= m`.
   Fix: treat `*=` as a product (left operand is the assigned name, right is the operand).
   Also missed by both lints: `let mut t = 1usize; t *= m1; t *= m2;` (taint is only set by `let`).

2. MEDIUM, closure or fn wrapper. `fn f(a: usize, b: usize) -> usize { a * b } let t = f(m1, m2);` (the old lint caught it) and `.iter().fold(1usize, |a, b| a * b)` over `[m1, m2]`. The parameters `a` and `b` carry no taint, so the `*` has no dictionary operands, and the call-site statement has no `*`. Closure form `let f = |a, b| a * b; f(m1, m2)` is missed by both. `.iter().product::<usize>()` over `[m1, m2]` is missed by both, since only the `pow` and `_mul` method names are handled. The file docstring already admits helper-fn products are a gap, but this one is a regression relative to the old lint.

3. LOW, block comment. `let t = m1 /* c */ * m2;`. `_strip_comments` strips only `//`, and `/ *` tokens break the operand parse. The old lint caught it. Fix: strip `/* ... */` as well.

4. LOW, brace operands. `let t = { m1 } * { m2 };`. The `prev` check accepts `)` and `]` but not `}`, so the `*` is read as a dereference. The old lint caught it. Unlikely in practice.

5. LOW, `mul_assign` in one statement, `let mut t = m1; t *= m2;` is item 1.

Missed by BOTH lints (not regressions, listed for completeness): `let (a, b) = (m1, m2); a * b` (tuple destructuring does not taint); `m1 * m1` (fewer than two distinct dictionaries); `m1 << k`; `Mul::mul(m1, m2)` / `m1.mul(m2)`; `(0..m1).map(|_| m2).sum()` and an additive loop; `vec![vec![0; m2]; m1]` and a push loop that pushes a `vec![0; m2]` per `m1` iteration (a real dense table over a product); `s.name__dict@.len() * n.tag__dict@.len()` (the `@` view form); `let mut t = 1; t = m1; t = t * m2` after a non-let assignment.

## Severity summary

No blocking issue. The reported host bug (false rejection of valid hash bodies) is fixed on all 11 real attempts. The lint remains best effort, as its docstring says. Recommended before merge: handle `*=` and `/* */` (cheap, both are regressions); optionally add tests for them.

## Author response
- `*=` and `/* */` regressions: fixed, test `test_compound_assignment_and_block_comments_do_not_hide_a_product`.
- Helper fn / closure products (`fn f(a,b){a*b}`, `fold(|a,b| a*b)`): accepted as a documented regression (parameters carry no taint); the docstring already lists helper-fn products as unseen. Brace operands `{m1} * {m2}`: accepted (LOW).
- Trade-off stated: 7 of 11 real Sonnet attempts were rejected with no product in the flagged statement; the old lint was blocking the recommended packed-key technique.
