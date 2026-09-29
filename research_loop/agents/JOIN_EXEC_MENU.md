These exec functions are in scope when this file's `spec.rs` contains them. Each line is the function and what it ensures. Do not invent a HashMap or HashSet index. Do not call `build_hashset_u32` or `probe_sum_u64` unless that function is in `spec.rs`. A derived-table Map is an extra step argument, not a second index.

- `equijoin_pairs_str(outer, inner) -> Vec<(usize, usize)>`
  — `pairs@ == nested_eq_pairs(...)`; one `String` equality
- `equijoin_pairs_str2(o0, o1, i0, i1) -> Vec<(usize, usize)>`
  — `pairs@ == nested_eq_pairs2(...)`; two `String` equalities
- `equijoin_pairs_str3(o0, o1, o2, i0, i1, i2) -> Vec<(usize, usize)>`
  — `pairs@ == nested_eq_pairs3(...)`; three `String` equalities
- `equijoin_pairs_u64(outer, inner) -> Vec<(usize, usize)>`
  — `pairs@ == nested_eq_pairs(...)`; one `u64` equality
- `equijoin_pairs_u32(outer, inner) -> Vec<(usize, usize)>`
  — `pairs@ == nested_eq_pairs(...)`; one `u32` equality
- `orjoin_pairs_str(oa, ob, ia, ib) -> Vec<(usize, usize)>`
  — `pairs@ == nested_or_eq_pairs(...)`; two-table `A.a=B.a OR A.b=B.b`
- `star_eq_triples_str(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v)`
  — `-> Vec<(usize, usize, usize)>`; `triples@ == nested_star(...)`; 3-table star
- `chain_eq_triples_str(a_k, b_k, b_m, c_m)`
  — `-> Vec<(usize, usize, usize)>`; `triples@ == nested_chain(...)`; 3-table chain
- `q6_eq_triples_str(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v)`
  — `-> Vec<(usize, usize, usize)>`; `triples@ == nested_q6(...)`; 3-table Q6 (1+3)
- `star_eq_quads_str(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v)`
  — `-> Vec<(usize, usize, usize, usize)>`; `quads@ == nested_quad(...)`; 4-table star
- `semi_hit_rows_str(outer, inner) -> Vec<usize>`
  — `hits@ == nested_semi_hits(...)`; SEMI (matched outer row ids)
- `semi_hit_rows_str2(o0, o1, i0, i1) -> Vec<usize>`
  — `hits@ == nested_semi_hits2(...)`; two-key SEMI hits
- `semi_hit_rows_str3(o0, o1, o2, i0, i1, i2) -> Vec<usize>`
  — `hits@ == nested_semi_hits3(...)`; three-key SEMI hits
- `anti_miss_rows_str(outer, inner) -> Vec<usize>`
  — `misses@ == nested_anti_misses(...)`; LEFT anti / ANTI miss ids
- `anti_miss_rows_str2(o0, o1, i0, i1) -> Vec<usize>`
  — `misses@ == nested_anti_misses2(...)`; two-key LEFT anti / ANTI misses
- `anti_miss_rows_str3(o0, o1, o2, i0, i1, i2) -> Vec<usize>`
  — `misses@ == nested_anti_misses3(...)`; three-key LEFT anti / ANTI misses
- `left_outer_pairs_str(outer, inner) -> Vec<(usize, Option<usize>)>`
  — `pairs@ == nested_loj_pairs(...)`; LEFT OUTER slots
- `left_outer_pairs_str2(o0, o1, i0, i1) -> Vec<(usize, Option<usize>)>`
  — `pairs@ == nested_loj_pairs2(...)`; two `String` LEFT OUTER equalities
- `left_outer_pairs_u64(outer, inner) -> Vec<(usize, Option<usize>)>`
  — `pairs@ == nested_loj_pairs(...)`; LEFT OUTER on `u64` keys
- `right_outer_pairs_str(outer, inner) -> Vec<(usize, Option<usize>)>`
  — `slots@ == nested_right_pairs(...)`; RIGHT OUTER slots
- `right_outer_pairs_str2(o0, o1, i0, i1) -> Vec<(usize, Option<usize>)>`
  — `slots@ == nested_right_pairs2(...)`; two `String` RIGHT OUTER equalities
- `full_outer_parts_str(left, right) -> (pairs, left_miss, right_miss)`
  — matched `nested_eq_pairs` + both `nested_anti_misses`; FULL OUTER parts
- `full_outer_parts_str2(l0, l1, r0, r1) -> (pairs, left_miss, right_miss)`
  — matched `nested_eq_pairs2` + both `nested_anti_misses2`; two `String` FULL OUTER
- self-join — same `equijoin_pairs_*` ensures; params are SQL aliases (`Cols_<alias>`),
  not a second physical table
