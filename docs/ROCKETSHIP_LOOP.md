# Rocketship Trusted loop (append-only)

Goal: every product-path Trusted is expert-blind (or derived from such), and
prove_loop r13 stays **≥98%** `VERIFY True`. No empty fold axioms; no greenwash
reinject. Append dated entries; do not rewrite history.

## Bar (reminder)

1. One idea, local, `ensures ≡ body` under named `requires`.
2. Expert would accept for high-assurance code — or claim is **proved** from such.
3. Loader `valid_cols` = Layer A data boundary (named), not “arith won’t wrap.”
4. Empty `external_body` proof lemmas must leave or become real proofs.

## Open gaps (start)

| Gap | Issue | Target |
|-----|--------|--------|
| `lemma_u64_add_*_prev_le` / `*_fit` | empty `external_body` | prove with nonlinear / delete if unused |
| `lemma_rem_cap_*_pow4` | empty; u64 product wraps in requires | int-cap requires + prove |
| HAVING peel | `unsafe` transmute + `ensures true` | real `@` contract or fold into HAVING Trusted only |
| `load_cols_*` | I/O → `valid_cols` | keep as Layer A; document as boundary |
| Map insert lemmas | container axioms | keep (expert-blind); note in inventory |

## Baseline

- Date: 2026-08-11
- HEAD: `b86d2d0` (fold-slot `lemma_*` only; r13 lemma-only 50/50)
- r13 batch: 50/50 under inductive default (artifact `r13_lemma_only_batch.json`)

---

## Log

### 2026-08-11 — kickoff

Started loop. First commit: this file + plan. Next: prove empty fit/`prev_le`
lemmas; fix pow4; harden HAVING peel; re-batch r13 after each host milestone.

### 2026-08-11 — prove fit/prev_le + HAVING peel (landed)

- Commits `63623e5`, `fb53004`: empty `*_prev_le` / `*_fit` / money wrappers
  became real proofs; HAVING unwrap/`ensures true` removed (peel private inside
  `apply_having_filter_exec_*`); loader documented as Layer A.

### 2026-08-11 — sound ROWS_4 for legacy `*_pow4`

**Finding:** `lemma_rem_cap_*_pow4` under full `LEMMA_MAX_ROWS` (65536) is
**unsound** — ROWS⁴·NATIVE ≫ u64::MAX. Agents had been calling empty/pow4
Trusteds that hid that.

**Fix:**
- `*_pow4` / `fold_suffix_rem_leq_rows_pow4` now use **`LEMMA_MAX_ROWS_4`** and
  forward to proved `*_4` / `lemma_join_nested_rem_leq_rows_4`.
- Added proved `lemma_rem_cap_native_add_fits_4`.
- r13 agents: depth-3 → cube rem_join + `rem_cap_*_cube`; depth-4 → rem_join_4 +
  `rem_cap_*_4` (no expand-equality fight).
- Checkpoint before rewrite: `prove_loop_r13_pre_pow4_to_rows4.tar.gz`.

Spot: q1/q2/q5/q50 VERIFY True. Full batch next.

