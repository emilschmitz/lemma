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
