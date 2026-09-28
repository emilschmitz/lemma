# Join proof paths (open for the shape you have)

Menu of proved exec statements is in the agent prompt and in `COMPILATION_GUIDE.md`.
This file is the **how**: which `lemma_<helper>_is_*` / `lemma_<helper>_method_is_fold` to
call, in what order, the backward walk, and derived-map notes. Open only the section that
matches your SQL. Do not invent a second index or call `build_hashset_u32` / `probe_sum_u64`.

## Shared rules

- `spec.rs` shows `proof fn` bodies as `{ }`. That is the reading copy. Verus checks the
  proved bodies. Call the lemmas named under `## This spec`. Do not re-prove them, and
  do not add a `proof fn` because a body looks empty.
- `exec_sort_by`, when this file has it, ensures `spec_seq_sort_by` of the same
  predicate. It sorts. It does not prove the join or the aggregate.
- `group_keys_helper`, when this file has it, is the key order. Build that sequence in
  the same backward walk (`pair_acc` / `triple_acc`). There is no second exec for it.
  `HashMapWithView` is the map `agg_step_*` already updates.
- Write `run_query` and call `run_runquery` once the call order below is chosen. A
  wall-clock kill with no edit saves nothing.
- Match lists (`pairs@`, `triples@`, `quads@`, misses, hits, LOJ/right slots) are outer-major,
  inner ids increasing. `method_spec` folds from the high index downward — walk from the end.
- Filters and aggregates stay in that loop. The match list is the join geometry, not the whole
  query result.
- After the backward walk, call `lemma_<helper>_method_is_fold` (when this file emits it) so
  `ensures res == method_spec` follows without re-deriving wrappers.
- `method_spec` may still apply `map_values`, `spec_map_at_keys`, `spec_seq_sort_by`,
  `spec_seq_take`, or `apply_having_filter` to the helper's result. The walk proves the
  helper. Those wrappers stay in `method_spec`.
- <!-- shape: derived --> When a derived-table Map is an extra helper parameter, the same
  `lemma_<helper>_is_pairs` (or `_is_pairs2` / `_is_star_pairs` / matching `_is_*`) threads that
  Map into the step closure — do **not** build a second index of the subquery.

## Call order by shape

### One equality — `equijoin_pairs_str` / `equijoin_pairs_u64` / `equijoin_pairs_u32`

1. Call the matching `equijoin_pairs_*`.
2. Walk pairs from the end with
   `invariant acc == pair_acc(pairs@, step, base, k as int)`.
3. Call `lemma_<helper>_is_pairs` (via `_is_loop`). Prefer `_is_pairs` over chaining
   `_is_loop`, `lemma_acc`, and `lemma_pair_pos_origin`.
4. Call `lemma_<helper>_method_is_fold`.

The file also contains `lemma_<helper>_is_loop` (for example
`lemma_join_method_spec_helper_is_loop` or `lemma_multi_agg_helper_is_loop`). `_is_loop` proves
the helper equals `loop_acc` on the join keys; `_is_pairs` proves the helper at `(0, 0)` equals
`pair_acc` of `nested_eq_pairs` at index 0 (same step closure), which is what `equijoin_pairs_*`
returns.

### Two string equalities — `equijoin_pairs_str2`

1. Call `equijoin_pairs_str2`.
2. Same `pair_acc` walk from the end.
3. Call `lemma_<helper>_is_pairs2` (built on `_is_loop2` / `lemma_loop2_at_origin`) against
   `nested_eq_pairs2`.
4. Call `lemma_<helper>_method_is_fold`.

### Three string equalities — `equijoin_pairs_str3`

1. Call `equijoin_pairs_str3`.
2. Same `pair_acc` walk.
3. Call `lemma_<helper>_is_pairs3` against `nested_eq_pairs3`.
4. Call `lemma_<helper>_method_is_fold`.

### OR equalities — `orjoin_pairs_str`

1. Call `orjoin_pairs_str`.
2. Same `pair_acc` walk.
3. Call `lemma_<helper>_is_or` against `nested_or_eq_pairs`.
4. Call `lemma_<helper>_method_is_fold`.

### 3-table star — `star_eq_triples_str`

1. Call `star_eq_triples_str`.
2. Walk triples from the end with
   `invariant acc == triple_acc(triples@, step, base, k as int)`.
3. Call `lemma_<helper>_is_star_pairs` (built on `_is_star` / `lemma_star_at_origin`) against
   `nested_star`.
4. Call `lemma_<helper>_method_is_fold`.

### 3-table chain — `chain_eq_triples_str`

1. Call `chain_eq_triples_str`.
2. Same `triple_acc` walk.
3. Call `lemma_<helper>_is_chain_pairs` (built on `_is_chain` / `lemma_chain_at_origin`) against
   `nested_chain`.
4. Call `lemma_<helper>_method_is_fold`.

### 3-table Q6 (1+3) — `q6_eq_triples_str`

1. Call `q6_eq_triples_str`.
2. Same `triple_acc` walk.
3. Call `lemma_<helper>_is_q6_pairs` against `nested_q6`.
4. Call `lemma_<helper>_method_is_fold`.

### 4-table star — `star_eq_quads_str`

1. Call `star_eq_quads_str`.
2. Walk quads from the end with
   `invariant acc == quad_acc(quads@, step, base, k as int)`.
3. Call `lemma_<helper>_is_quad_pairs`.
4. Call `lemma_<helper>_method_is_fold`.

### LEFT / ANTI miss — `anti_miss_rows_str` / `anti_miss_rows_str2` / `anti_miss_rows_str3`

1. Call `anti_miss_rows_str` (1-key), `anti_miss_rows_str2` (2-key), or `anti_miss_rows_str3`
   (3-key). Keyword ANTI reuses the same lists as LEFT anti.
2. Walk misses from the end with `miss_acc`.
3. Call `lemma_<helper>_is_left` (LEFT anti / left-side projection) or `lemma_<helper>_is_anti`
   (keyword ANTI JOIN). Two-key uses `nested_anti_misses2`; three-key uses `nested_anti_misses3`.
4. Call `lemma_<helper>_method_is_fold`.

### SEMI hits — `semi_hit_rows_str` / `semi_hit_rows_str2` / `semi_hit_rows_str3`

1. Call `semi_hit_rows_str` (1-key), `semi_hit_rows_str2` (2-key), or `semi_hit_rows_str3`
   (3-key).
2. Walk hits from the end with `hit_acc`.
3. Call `lemma_<helper>_is_semi` against `nested_semi_hits` / `nested_semi_hits2` /
   `nested_semi_hits3`.
4. Call `lemma_<helper>_method_is_fold`.

### LEFT OUTER — `left_outer_pairs_str` / `left_outer_pairs_u64`

1. Call `left_outer_pairs_str` or `left_outer_pairs_u64`.
2. Walk slots from the end with `loj_acc`.
3. Call `lemma_<helper>_is_loj` against `nested_loj_pairs`.
4. Call `lemma_<helper>_method_is_fold`.

### LEFT OUTER two-key — `left_outer_pairs_str2`

1. Call `left_outer_pairs_str2(outer0, outer1, inner0, inner1)`.
2. Walk slots from the end with `loj_acc` (same generic fold as one-key LOJ).
3. Call `lemma_<helper>_is_loj2` against `nested_loj_pairs2` (via
   `lemma_<helper>_is_loj2_loop` + `lemma_loj_at_origin2`). Multi-agg GROUP BY
   uses `join_loj_multi_agg_helper` /
   `lemma_join_loj_multi_agg_helper_method_is_fold`. Two-key LEFT projection
   uses `join_loj_projection_helper` with the same pair list; right columns are
   `Option` (`Some` / `None` pad), left columns copied on match and miss.
4. Call `lemma_<helper>_method_is_fold`.

### RIGHT OUTER — `right_outer_pairs_str`

1. Call `right_outer_pairs_str`.
2. Walk slots from the end with `right_acc` (hit and miss steps).
3. Call `lemma_<helper>_is_right` against `nested_right_pairs`. Projection uses
   `join_right_projection_helper`; scalar `COUNT(*)` uses `join_right_count_helper`;
   GROUP BY with one or more aggregates uses `join_roj_multi_agg_helper` /
   `lemma_join_roj_multi_agg_helper_method_is_fold` (same `right_outer_pairs_str` list).
4. Call `lemma_<helper>_method_is_fold`.

### RIGHT OUTER two-key — `right_outer_pairs_str2`

1. Call `right_outer_pairs_str2(outer0, outer1, inner0, inner1)`.
2. Walk slots from the end with `right_acc` (same generic fold as one-key RIGHT).
3. Call `lemma_<helper>_is_right2` against `nested_right_pairs2` (via
   `lemma_<helper>_is_right2_loop` + `lemma_right_at_origin2`). Multi-agg GROUP BY
   uses `join_roj_multi_agg_helper` /
   `lemma_join_roj_multi_agg_helper_method_is_fold`. Two-key RIGHT projection
   uses `join_right_projection_helper` with the same pair list; nullable-side
   columns are `Option` (`Some` / `None` pad), preserved-side columns copied on
   match and miss. Scalar `COUNT(*)` uses `join_right_count_helper` with the same
   list; match and miss steps both contribute +1 (count = slot-list length).
4. Call `lemma_<helper>_method_is_fold`.

### FULL OUTER — `full_outer_parts_str`

1. Call `full_outer_parts_str`.
2. Fold matched / left-miss / right-miss with `full_acc`.
3. Call `lemma_<helper>_is_full`.
4. Call `lemma_<helper>_method_is_fold`.
   Multi-agg GROUP BY on the join key uses `full_join_groupby_helper` /
   `lemma_full_join_matched_helper_method_is_fold` (same three-phase list;
   right-miss keys remap via the equality; other-side measures are 0).

### FULL OUTER two equalities — `full_outer_parts_str2`

1. Call `full_outer_parts_str2(l0, l1, r0, r1)`.
2. Fold matched / left-miss / right-miss with `full_acc` of `nested_eq_pairs2` /
   `nested_anti_misses2` (via `lemma_loop2_at_origin` + `lemma_anti2_at_origin`).
3. Call `lemma_<helper>_is_full` (calls `lemma_full_at_origin` on the two-key lists).
4. Call `lemma_<helper>_method_is_fold`.
   Multi-agg GROUP BY on one join-key column uses the same chain; right-miss keys
   remap via that equality. Two-equality projection needs NULL padding — not wired.

### Self-join

Same helpers and the same call order as the matching equality shape. Params are SQL aliases
(`Cols_<alias>`), not a second physical table.
