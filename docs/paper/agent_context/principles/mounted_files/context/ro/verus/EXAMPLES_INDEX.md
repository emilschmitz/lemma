# Verus example index (generated)

Each line: `path (lines): features`. Grep a feature to find a small program that uses it:
`grep -n 'assert forall' EXAMPLES_INDEX.md | sort -t'(' -k2 -n`, then Read the file.
Paths are relative to this directory. Files under `tests/` hold Verus code inside
`verus_code! { ... }`; `examples/` files are plain Verus programs.

examples/adts.rs (86): 
examples/adts_eq.rs (29): 
examples/assert_by_compute.rs (454): decreases, assert-by, compute, Seq, Vec, spec fn, proof fn, Vec push, subrange, int overflow/as
examples/assertions.rs (32): 
examples/assorted_demo.rs (69): exists, while loop, spec fn, external_body
examples/atomic_increment.rs (171): invariant, spec fn, ghost/tracked
examples/atomics.rs (140): invariant, spec fn, proof fn, opaque, ghost/tracked, assume
examples/basic_failure.rs (25): Seq, proof fn
examples/basic_lock1.rs (101): invariant, spec fn, ghost/tracked
examples/basic_lock2.rs (77): invariant, spec fn, ghost/tracked
examples/bitmap.rs (176): invariant, forall, bit_vector, Seq, Vec, while loop, spec fn, proof fn, loop invariant forall, Vec push, view (@), int overflow/as
examples/bitvector_basic.rs (127): forall, trigger, assert-by, bit_vector, proof fn, choose, external_body, int overflow/as
examples/bitvector_equivalence.rs (174): decreases, forall, assert-by, bit_vector, Seq, spec fn, proof fn, int overflow/as
examples/bitvector_garbage_collection.rs (178): forall, bit_vector, Seq, spec fn, proof fn, int overflow/as
examples/broadcast_proof.rs (190): trigger, assert-by, nonlinear_arith, broadcast use, broadcast group, spec fn, proof fn, opaque, int overflow/as
examples/calc.rs (51): calc!, Seq, proof fn, int overflow/as
examples/cargo-verus/library/src/lib.rs (13): 
examples/cargo-verus/test/src/main.rs (17): external_body, int overflow/as
examples/cells.rs (25): ghost/tracked
examples/cuckoo_hash_table/cuckoo.rs (1457): invariant, decreases, assert forall, forall, exists, trigger, Seq, Vec, while loop, spec fn, proof fn, opaque, ghost/tracked, choose, loop invariant forall, Vec push, external_body, int overflow/as
examples/cuckoo_hash_table/main.rs (71): ghost/tracked, external_body
examples/cuckoo_hash_table/rwlock.rs (684): invariant, forall, trigger, assert-by, broadcast use, Multiset, while loop, spec fn, proof fn, opaque, ghost/tracked, loop invariant forall, view (@), int overflow/as
examples/datatypes.rs (103): invariant, decreases, spec fn, reveal
examples/debug.rs (81): invariant, while loop, spec fn, int overflow/as
examples/debug_expand.rs (324): decreases, spec fn, proof fn, reveal, opaque, int overflow/as
examples/doubly_linked.rs (592): invariant, assert forall, forall, trigger, Seq, Map, Set, while loop, spec fn, opaque, ghost/tracked, Vec push, subrange, view (@), int overflow/as
examples/doubly_linked_xor.rs (494): assert forall, forall, trigger, assert-by, bit_vector, Seq, Map, Set, spec fn, proof fn, ghost/tracked, Vec push, subrange, external_body, int overflow/as
examples/entry_api.rs (53): HashMap, int overflow/as
examples/even_cell.rs (55): invariant, spec fn, ghost/tracked, subrange
examples/exec_termination_example.rs (115): invariant, decreases, while loop, for loop
examples/extensionality.rs (121): forall, bit_vector, Seq, Map, Set, spec fn, proof fn, Vec push, subrange, int overflow/as
examples/external.rs (19): ghost/tracked, external_body
examples/float.rs (92): trigger, broadcast use, broadcast group
examples/fun_ext.rs (36): forall, trigger, proof fn
examples/generics.rs (76): spec fn, proof fn, reveal, opaque, int overflow/as
examples/guide/assert_by_compute.rs (90): decreases, assert-by, compute, Seq, spec fn, proof fn
examples/guide/bst_map.rs (427): decreases, forall, Map, spec fn, opaque, subrange
examples/guide/bst_map_generic.rs (764): decreases, assert forall, forall, trigger, Map, spec fn, proof fn, opaque
examples/guide/bst_map_type_invariant.rs (421): decreases, forall, Map, spec fn, opaque
examples/guide/calc.rs (39): calc!, proof fn
examples/guide/const.rs (92): spec fn
examples/guide/datatypes.rs (131): assert-by, nonlinear_arith, spec fn, proof fn
examples/guide/equality.rs (40): 
examples/guide/exec_attr.rs (124): invariant, Seq, Vec, for loop, ghost/tracked, Vec push, int overflow/as
examples/guide/exec_spec_unverified.rs (32): forall, Seq, spec fn, int overflow/as
examples/guide/exec_spec_verified.rs (37): forall, Seq, spec fn, int overflow/as
examples/guide/ext_equal.rs (87): Seq, Set, proof fn, Vec push
examples/guide/external_trait_specs.rs (89): assert-by, bit_vector, spec fn
examples/guide/getting_started.rs (22): assert forall, forall, spec fn
examples/guide/higher_order_fns.rs (195): invariant, assert forall, forall, trigger, Vec, while loop, loop invariant forall, Vec push
examples/guide/integers.rs (113): int overflow/as
examples/guide/interior_mutability.rs (66): spec fn, opaque
examples/guide/invariants.rs (258): invariant, decreases, forall, trigger, Seq, while loop, for loop, spec fn, proof fn, loop invariant forall, subrange, assume, int overflow/as
examples/guide/iterators.rs (221): invariant, forall, trigger, Seq, Vec, for loop, spec fn, proof fn, opaque, loop invariant forall, Vec push, subrange, int overflow/as
examples/guide/lib_examples.rs (294): decreases, assert-by, Seq, Map, Set, Vec, spec fn, proof fn, choose, Vec push, subrange
examples/guide/logatom.rs (213): invariant, spec fn, ghost/tracked
examples/guide/modes.rs (373): assert-by, spec fn, proof fn, opaque, int overflow/as
examples/guide/nonlinear_bitvec.rs (87): forall, trigger, assert-by, nonlinear_arith, bit_vector, spec fn, proof fn
examples/guide/opaque.rs (35): spec fn, reveal, opaque
examples/guide/overflow.rs (50): 
examples/guide/pervasive_example.rs (19): Seq
examples/guide/quants.rs (498): invariant, decreases, assert forall, forall, exists, trigger, assert-by, Seq, Vec, while loop, spec fn, proof fn, reveal, choose, loop invariant forall, Vec push, external_body, int overflow/as
examples/guide/recursion.rs (532): invariant, decreases, assert-by, bit_vector, Seq, while loop, for loop, spec fn, proof fn, reveal, subrange, int overflow/as
examples/guide/references.rs (112): invariant, decreases, while loop
examples/guide/requires_ensures.rs (31): external_body
examples/guide/requires_ensures_edit.rs (85): 
examples/guide/strings.rs (60): Seq, String, subrange
examples/guide/traits.rs (187): forall, Seq, Vec, spec fn, proof fn, opaque, Vec push
examples/helping.rs (450): invariant, spec fn, proof fn, ghost/tracked
examples/imo_1988_6.rs (128): decreases, assert-by, nonlinear_arith, proof fn
examples/impl_basic.rs (69): 
examples/integer_ring/circular_by_d.rs (166): nonlinear_arith, proof fn, view (@)
examples/integer_ring/integer_ring.rs (312): nonlinear_arith, proof fn, int overflow/as
examples/integer_ring/integer_ring_bound_check.rs (131): nonlinear_arith, proof fn, external_body, int overflow/as
examples/integers.rs (66): spec fn, proof fn, opaque, int overflow/as
examples/invariants.rs (41): invariant, spec fn, opaque, ghost/tracked, int overflow/as
examples/logatom_lib.rs (497): invariant, spec fn, proof fn, ghost/tracked, view (@)
examples/mergesort.rs (189): invariant, decreases, forall, trigger, broadcast use, Seq, Multiset, Vec, while loop, for loop, spec fn, proof fn, loop invariant forall, Vec push, subrange, int overflow/as
examples/modules.rs (37): spec fn, proof fn, opaque
examples/multiset.rs (47): broadcast use, Seq, proof fn, Vec push
examples/nevd_script.rs (214): invariant, decreases, assert-by, bit_vector, Vec, while loop, spec fn, proof fn, ghost/tracked, Vec push
examples/overflow.rs (70): view (@)
examples/playground.rs (43): forall, trigger, spec fn, proof fn
examples/power_of_2.rs (213): decreases, assert-by, nonlinear_arith, bit_vector, spec fn, proof fn, reveal, assume, int overflow/as
examples/prelude.rs (18): Seq, proof fn
examples/proposal-rw2022.rs (76): invariant, decreases, while loop, spec fn, proof fn
examples/quantifiers.rs (101): assert forall, forall, exists, trigger, spec fn, int overflow/as
examples/recommends.rs (64): decreases, Seq, spec fn, proof fn, reveal
examples/recursion.rs (117): invariant, decreases, for loop, spec fn, proof fn, reveal, opaque, int overflow/as
examples/recursive_types.rs (134): decreases, Set, spec fn, proof fn
examples/resource/agreement.rs (102): spec fn, proof fn, opaque, ghost/tracked
examples/resource/count_to_two.rs (329): invariant, spec fn, ghost/tracked
examples/resource/log.rs (302): invariant, assert forall, forall, Seq, spec fn, proof fn, opaque, ghost/tracked
examples/resource/monotonic_counter.rs (363): invariant, spec fn, proof fn, opaque, ghost/tracked
examples/resource/oneshot.rs (482): invariant, spec fn, proof fn, opaque, ghost/tracked
examples/rfmig_script.rs (256): invariant, decreases, assert-by, nonlinear_arith, bit_vector, Vec, while loop, spec fn, proof fn, ghost/tracked, Vec push, external_body, int overflow/as
examples/rw2022_script.rs (190): invariant, decreases, forall, assert-by, bit_vector, Vec, while loop, spec fn, proof fn
examples/rwlock_vstd.rs (66): invariant, spec fn, ghost/tracked
examples/scache/rwlock.rs (1181): invariant, assert forall, forall, trigger, Map, Multiset, spec fn, proof fn, loop invariant forall, assume
examples/set_from_vec.rs (59): invariant, forall, broadcast use, Set, Vec, for loop, spec fn, opaque, loop invariant forall, Vec push, int overflow/as
examples/state_machines/adder.rs (48): invariant
examples/state_machines/adder_generic.rs (44): invariant
examples/state_machines/adder_with_max.rs (69): invariant
examples/state_machines/arc.rs (332): invariant, forall, Multiset, spec fn, ghost/tracked, subrange, assume
examples/state_machines/conditional.rs (115): 
examples/state_machines/counting.rs (268): invariant, forall, Multiset, spec fn, proof fn, opaque, ghost/tracked
examples/state_machines/disk_example.rs (295): invariant, decreases, Map, spec fn, ghost/tracked, assume
examples/state_machines/dist_rwlock.rs (408): invariant, assert forall, forall, trigger, assert-by, Multiset, Vec, while loop, spec fn, opaque, ghost/tracked, loop invariant forall, Vec push, int overflow/as
examples/state_machines/flat_combine.rs (462): invariant, assert forall, forall, trigger, assert-by, Seq, Set, spec fn, loop invariant forall, Vec push, int overflow/as
examples/state_machines/interner.rs (294): invariant, forall, trigger, Seq, Vec, while loop, spec fn, ghost/tracked, loop invariant forall, Vec push, external_body, int overflow/as
examples/state_machines/leader_election_complete.rs (183): invariant, assert forall, forall, Seq, spec fn
examples/state_machines/maps.rs (137): invariant, forall
examples/state_machines/petersons_algorithm.rs (177): invariant, spec fn
examples/state_machines/reference-examples/strategy_option.rs (93): invariant, proof fn, ghost/tracked
examples/state_machines/refinement.rs (122): invariant, spec fn, proof fn, reveal, choose, assume
examples/state_machines/refinement_labels.rs (136): invariant, spec fn, proof fn, reveal, choose, assume
examples/state_machines/rwlock.rs (198): invariant, forall, assert-by, Multiset, int overflow/as
examples/state_machines/top_sort_dfs.rs (548): invariant, assert forall, forall, trigger, assert-by, Seq, Vec, while loop, spec fn, ghost/tracked, choose, loop invariant forall, Vec push, assume, int overflow/as
examples/state_machines/tutorial/counting_to_2.rs (210): invariant, spec fn, ghost/tracked, int overflow/as
examples/state_machines/tutorial/counting_to_n.rs (225): invariant, forall, trigger, Vec, while loop, spec fn, ghost/tracked, Vec push, int overflow/as
examples/state_machines/tutorial/counting_to_n_atomic.rs (63): invariant
examples/state_machines/tutorial/fifo.rs (767): invariant, assert forall, forall, trigger, assert-by, Seq, Map, Vec, while loop, spec fn, opaque, ghost/tracked, Vec push, subrange, int overflow/as
examples/state_machines/tutorial/pcell_example.rs (55): ghost/tracked, subrange
examples/state_machines/tutorial/rc.rs (336): invariant, forall, Multiset, spec fn, ghost/tracked, subrange, assume
examples/state_machines/tutorial/ref_cell.rs (436): invariant, forall, trigger, Multiset, spec fn, opaque, ghost/tracked, loop invariant forall, int overflow/as
examples/state_machines/tutorial/unverified_counting_to_2.rs (59): 
examples/state_machines/tutorial/unverified_counting_to_n.rs (54): Vec, for loop, Vec push
examples/state_machines/tutorial/unverified_fifo.rs (133): Vec, while loop, Vec push, int overflow/as
examples/state_machines/tutorial/unverified_rc.rs (97): 
examples/statements.rs (61): invariant, decreases, while loop
examples/statics.rs (174): invariant, spec fn, ghost/tracked
examples/std_test/chars_iterator.rs (32): for loop
examples/std_test/num.rs (246): 
examples/std_test/option_test.rs (64): 
examples/std_test/rc_test.rs (45): 
examples/std_test/result.rs (66): 
examples/std_test/template.rs (13): 
examples/std_test/vec_test.rs (29): Vec
examples/std_test/vecdeque_test.rs (64): invariant, for loop
examples/structural.rs (31): 
examples/summer_school/chapter-1-22.rs (241): decreases, forall, Seq, spec fn, proof fn, reveal, choose, int overflow/as
examples/summer_school/chapter-2-1.rs (50): assert forall, forall, spec fn
examples/summer_school/chapter-2-2.rs (50): invariant, forall, while loop, spec fn
examples/summer_school/chapter-2-3.rs (111): decreases, assert forall, forall, trigger, Seq, Set, Multiset, Vec, spec fn, proof fn, view (@), assume, int overflow/as
examples/summer_school/chapter-6-1.rs (308): invariant, assert forall, forall, exists, Seq, Map, Set, spec fn, proof fn, choose, external_body
examples/syntax.rs (693): decreases, assert forall, forall, exists, trigger, assert-by, nonlinear_arith, bit_vector, broadcast use, Seq, Set, Multiset, Vec, while loop, spec fn, proof fn, reveal, opaque, ghost/tracked, choose, Vec push, view (@), assume, int overflow/as
examples/syntax_attr.rs (340): decreases, assert-by, nonlinear_arith, bit_vector, spec fn, proof fn, reveal, opaque, ghost/tracked, int overflow/as
examples/test.rs (21): 
examples/test_expand_errors.rs (239): decreases, forall, trigger, spec fn, proof fn, reveal, opaque, external_body
examples/thread.rs (35): ghost/tracked
examples/trait_for_fn.rs (24): spec fn, proof fn
examples/traits.rs (80): spec fn, external_body
examples/trigger_loops.rs (114): invariant, decreases, assert forall, forall, exists, trigger, while loop, spec fn, proof fn, choose, assume
examples/vectors.rs (159): invariant, decreases, assert forall, forall, exists, trigger, Seq, Vec, while loop, for loop, spec fn, loop invariant forall, Vec push, int overflow/as
examples/verified_vec.rs (172): forall, trigger, assert-by, nonlinear_arith, Seq, Map, spec fn, opaque, ghost/tracked, Vec push, assume, int overflow/as
tests/adts.rs (1991): assert forall, forall, trigger, Seq, Vec, String, spec fn, proof fn, opaque, ghost/tracked, assume, int overflow/as
tests/adts_generics.rs (255): forall, spec fn, proof fn
tests/adts_opaque.rs (195): spec fn, reveal, opaque
tests/arrays.rs (509): invariant, Seq, for loop, spec fn, proof fn, ghost/tracked, view (@), assume, int overflow/as
tests/assert_bitvector_by.rs (77): assert-by, bit_vector, proof fn, int overflow/as
tests/assert_by_compute.rs (849): decreases, assert-by, bit_vector, compute, Seq, spec fn, proof fn, opaque, Vec push, subrange, external_body, int overflow/as
tests/assert_forall_by.rs (309): assert forall, forall, trigger, assert-by, spec fn, proof fn, reveal, ghost/tracked, int overflow/as
tests/assoc_type_impls.rs (1044): trigger, broadcast use, Vec, String, spec fn, proof fn, opaque, Vec push, view (@), external_body, int overflow/as
tests/async_functions.rs (181): 
tests/atomic_lib.rs (1048): assert-by, bit_vector, String, ghost/tracked, view (@), assume, int overflow/as
tests/atomics.rs (384): invariant, while loop, proof fn, ghost/tracked, external_body
tests/basic.rs (832): forall, spec fn, proof fn, reveal, assume
tests/bitvector.rs (1574): decreases, assert forall, forall, trigger, assert-by, bit_vector, spec fn, proof fn, view (@), assume, int overflow/as
tests/boundary_suggestions.rs (426): String, external_body
tests/broadcast_forall.rs (661): invariant, decreases, trigger, broadcast use, broadcast group, spec fn, proof fn, reveal, opaque, external_body, assume, int overflow/as
tests/btree.rs (483): invariant, decreases, assert forall, forall, exists, assert-by, broadcast use, Seq, Map, Set, Vec, for loop, spec fn, choose, Vec push, subrange, assume, int overflow/as
tests/calc.rs (116): calc!, Seq, proof fn, assume, int overflow/as
tests/cargo.rs (165): String, Vec push
tests/cell_lib.rs (406): String, ghost/tracked, subrange, view (@), assume
tests/choose.rs (267): spec fn, proof fn, choose, int overflow/as
tests/closures.rs (169): spec fn, proof fn, int overflow/as
tests/common/mod.rs (982): invariant, Vec, String, for loop, Vec push, subrange
tests/compile.rs (33): String
tests/consts.rs (667): decreases, spec fn, proof fn, reveal, opaque, ghost/tracked, external_body, int overflow/as
tests/contrib.rs (85): proof fn, int overflow/as
tests/control_flow.rs (1250): invariant, decreases, Seq, while loop, spec fn, proof fn, assume
tests/core_special_setup.rs (88): broadcast use, Seq, Set, Multiset, proof fn
tests/cow.rs (50): spec fn, int overflow/as
tests/dafny_axioms.rs (49): decreases, Set, proof fn
tests/default_trait.rs (266): Vec, HashMap, String
tests/eq_cmp.rs (124): trigger, spec fn, proof fn, reveal, opaque
tests/erase.rs (31): spec fn, proof fn, ghost/tracked, view (@)
tests/examples.rs (163): Vec, String, for loop, Vec push
tests/exec_closures.rs (1884): invariant, decreases, forall, trigger, while loop, spec fn, proof fn, ghost/tracked, external_body, assume, int overflow/as
tests/exec_spec_unverified.rs (323): forall, exists, trigger, Seq, spec fn, int overflow/as
tests/exec_spec_verified.rs (2044): decreases, forall, exists, trigger, Seq, Map, Set, Multiset, Vec, HashMap, spec fn, reveal, opaque, Vec push, subrange, int overflow/as
tests/exec_termination.rs (412): invariant, decreases, while loop, for loop, external_body
tests/expand_errors.rs (459): forall, trigger, Seq, Set, spec fn, proof fn, reveal, Vec push, assume, int overflow/as
tests/expr_stmts.rs (91): 
tests/ext_equal.rs (593): invariant, decreases, forall, trigger, assert-by, calc!, Seq, Map, Set, for loop, spec fn, proof fn, opaque, ghost/tracked, Vec push, assume
tests/external_fn_specification.rs (1645): String, spec fn, proof fn, opaque, external_body, assume
tests/external_traits.rs (900): decreases, trigger, broadcast use, Seq, Vec, spec fn, proof fn, opaque, ghost/tracked, external_body
tests/external_type_specification.rs (491): ghost/tracked, external_body
tests/float.rs (228): forall, assert-by, bit_vector, assume, int overflow/as
tests/fndef_types.rs (2065): assert forall, forall, trigger, assert-by, compute, Seq, Vec, spec fn, proof fn, ghost/tracked, Vec push, assume, int overflow/as
tests/functions.rs (134): spec fn, proof fn
tests/generics.rs (178): trigger, Seq, spec fn, proof fn, external_body, int overflow/as
tests/harness.rs (84): 
tests/hash.rs (973): invariant, decreases, assert-by, broadcast use, Seq, Map, Set, Vec, HashMapWithView, StringHashMap, HashMap, String, for loop, spec fn, Vec push, subrange, external_body, assume, int overflow/as
tests/impl.rs (337): spec fn, proof fn, opaque, ghost/tracked, subrange
tests/inline.rs (247): decreases, forall, Seq, Set, spec fn, proof fn, reveal, opaque, assume
tests/integer_ring.rs (314): spec fn, proof fn
tests/integers.rs (617): spec fn, proof fn, ghost/tracked, int overflow/as
tests/iterators.rs (492): invariant, decreases, assert forall, forall, exists, trigger, broadcast use, Seq, Map, Vec, for loop, spec fn, proof fn, opaque, ghost/tracked, choose, Vec push, subrange, assume
tests/layout.rs (501): assert-by, compute, proof fn
tests/let_else.rs (177): spec fn, proof fn, external_body
tests/lifetime.rs (2063): invariant, forall, trigger, Seq, Vec, while loop, spec fn, proof fn, ghost/tracked, loop invariant forall, Vec push, subrange, external_body, int overflow/as
tests/literals.rs (69): Seq, Set, proof fn
tests/logatom.rs (694): invariant, String, spec fn, proof fn, opaque, ghost/tracked, assume, int overflow/as
tests/loops.rs (1882): invariant, decreases, assert forall, forall, trigger, assert-by, nonlinear_arith, compute, broadcast use, Seq, Vec, while loop, for loop, spec fn, proof fn, opaque, loop invariant forall, Vec push, subrange, view (@), int overflow/as
tests/loops_havoc.rs (572): while loop
tests/loops_no_spinoff.rs (1441): invariant, decreases, forall, Vec, while loop, for loop, spec fn, proof fn, opaque, loop invariant forall, Vec push, view (@), int overflow/as
tests/maps.rs (187): assert-by, broadcast use, Map, Set, proof fn, choose
tests/marker_traits.rs (376): invariant, spec fn, proof fn, ghost/tracked
tests/match.rs (1394): invariant, decreases, while loop, spec fn, proof fn, reveal, ghost/tracked, external_body, assume, int overflow/as
tests/modes.rs (1783): decreases, assert forall, forall, Set, while loop, spec fn, proof fn, ghost/tracked, view (@), external_body, assume
tests/modules.rs (409): spec fn, proof fn, reveal, opaque, external_body
tests/multiset.rs (129): forall, Multiset, proof fn, choose
tests/mut_refs.rs (5280): invariant, Vec, while loop, spec fn, proof fn, opaque, ghost/tracked, external_body, assume, int overflow/as
tests/mut_refs_closures.rs (851): assert forall, forall, proof fn, ghost/tracked
tests/mut_refs_libs.rs (479): 
tests/mut_refs_loops.rs (2211): invariant, while loop, for loop, assume
tests/mut_refs_modes.rs (1987): trigger, assert-by, broadcast use, spec fn, proof fn, ghost/tracked, view (@), external_body
tests/mut_refs_old.rs (625): invariant, decreases, assert forall, forall, trigger, assert-by, nonlinear_arith, spec fn, proof fn, opaque, ghost/tracked, int overflow/as
tests/mut_refs_patterns.rs (4254): proof fn, ghost/tracked, assume, int overflow/as
tests/mut_refs_slices_arrays.rs (1970): Vec, spec fn
tests/mut_refs_temporaries.rs (3939): trigger, broadcast use, spec fn, proof fn, ghost/tracked
tests/mut_refs_time_travel.rs (1802): invariant, decreases, assert forall, forall, Vec, while loop, for loop, spec fn, proof fn, ghost/tracked, assume
tests/mut_refs_unions.rs (990): proof fn, external_body
tests/mutable_params.rs (590): invariant, decreases, spec fn, proof fn, ghost/tracked
tests/nested_items.rs (244): decreases, trigger, assert-by, broadcast use, spec fn, proof fn, ghost/tracked, external_body
tests/never_type.rs (105): spec fn, proof fn, ghost/tracked, external_body
tests/no_cheating.rs (108): decreases, spec fn, proof fn, external_body, assume
tests/nonlinear.rs (290): assert-by, nonlinear_arith, proof fn, assume, int overflow/as
tests/opaque_reveal.rs (488): decreases, assert-by, nonlinear_arith, broadcast use, Seq, while loop, spec fn, proof fn, reveal, opaque, assume, int overflow/as
tests/opaque_types.rs (587): spec fn, external_body
tests/open_invariant.rs (1034): invariant, while loop, spec fn, proof fn, opaque, ghost/tracked, external_body
tests/operators.rs (355): spec fn, opaque
tests/option.rs (127): proof fn
tests/output_json.rs (273): String, assume
tests/overflow.rs (342): assert-by, bit_vector, proof fn, int overflow/as
tests/partial_eq.rs (22): 
tests/proof_closures.rs (1868): forall, trigger, while loop, spec fn, proof fn, ghost/tracked, external_body, assume, int overflow/as
tests/proof_in_spec.rs (490): decreases, assert-by, bit_vector, spec fn, proof fn, ghost/tracked, choose, external_body, assume
tests/proph.rs (69): ghost/tracked, view (@)
tests/prophecy.rs (860): decreases, while loop, spec fn, proof fn, opaque, ghost/tracked, external_body, assume
tests/quantifiers.rs (325): assert forall, forall, exists, trigger, assert-by, broadcast use, Seq, Map, spec fn, proof fn, choose, external_body, assume, int overflow/as
tests/raw_ptrs.rs (394): Set, proof fn, ghost/tracked, assume, int overflow/as
tests/real.rs (75): exists, trigger, assert-by, nonlinear_arith, spec fn, proof fn
tests/recommends.rs (100): forall, exists, trigger, Seq, spec fn, proof fn, opaque, ghost/tracked
tests/recursion.rs (2358): invariant, decreases, forall, trigger, assert-by, broadcast use, Seq, Map, Set, Vec, while loop, spec fn, proof fn, reveal, opaque, ghost/tracked, choose, Vec push, external_body, assume
tests/recursive_types.rs (413): decreases, Map, Set, spec fn, proof fn, external_body
tests/refs.rs (659): forall, Vec, spec fn, proof fn, opaque, ghost/tracked, external_body, assume
tests/regression.rs (1535): invariant, decreases, assert forall, forall, exists, trigger, assert-by, Seq, Map, Set, Vec, spec fn, proof fn, reveal, opaque, ghost/tracked, choose, external_body, assume, int overflow/as
tests/results.rs (85): proof fn
tests/return.rs (236): invariant, while loop, spec fn, proof fn
tests/returns_postcondition.rs (485): spec fn, proof fn, assume, int overflow/as
tests/safe_api.rs (444): invariant, spec fn, proof fn, ghost/tracked
tests/scope.rs (169): 
tests/seqs.rs (131): assert forall, forall, Seq, proof fn, Vec push, subrange, int overflow/as
tests/sets.rs (188): assert forall, forall, exists, trigger, assert-by, broadcast use, Set, spec fn, proof fn, opaque, choose, assume, int overflow/as
tests/shr_ref_struct_wrap.rs (382): invariant, spec fn, proof fn, ghost/tracked
tests/size_of.rs (241): broadcast use, spec fn, proof fn, external_body, assume, int overflow/as
tests/slices.rs (572): invariant, Vec, for loop, subrange, assume
tests/spec_derive.rs (553): Seq, Vec, HashMap, String, spec fn, proof fn
tests/state_machines.rs (9224): invariant, decreases, forall, assert-by, Map, Set, Multiset, spec fn, proof fn, ghost/tracked, assume
tests/std.rs (1649): forall, trigger, assert-by, bit_vector, compute, Map, Vec, HashMap, spec fn, proof fn, Vec push, view (@), int overflow/as
tests/strings.rs (849): invariant, Seq, Vec, String, for loop, spec fn, proof fn, reveal, subrange, int overflow/as
tests/struct_with_invariants.rs (51): invariant, spec fn, opaque
tests/structural.rs (112): Vec, while loop
tests/summer_school.rs (1035): invariant, decreases, assert forall, forall, exists, trigger, assert-by, Seq, Map, Set, Vec, while loop, spec fn, proof fn, reveal, loop invariant forall, subrange, view (@), assume, int overflow/as
tests/syntax_attr.rs (1681): invariant, forall, Seq, Vec, while loop, for loop, proof fn, ghost/tracked, loop invariant forall, Vec push, external_body, int overflow/as
tests/traits.rs (4818): decreases, forall, exists, trigger, assert-by, nonlinear_arith, broadcast use, while loop, spec fn, proof fn, reveal, opaque, ghost/tracked, view (@), external_body, assume, int overflow/as
tests/traits_dyn.rs (434): decreases, trigger, broadcast use, spec fn, proof fn, ghost/tracked
tests/traits_extend_ensures.rs (859): assert forall, forall, spec fn, proof fn
tests/traits_modules.rs (1047): decreases, spec fn, proof fn, opaque
tests/traits_modules_pub_crate.rs (1049): decreases, spec fn, proof fn, opaque
tests/triggers.rs (651): assert forall, forall, trigger, assert-by, nonlinear_arith, broadcast use, Seq, Map, Set, spec fn, proof fn, external_body, assume, int overflow/as
tests/ui.rs (34): 
tests/unions.rs (380): spec fn, proof fn, ghost/tracked
tests/unsafe.rs (27): proof fn, external_body
tests/unwind.rs (608): invariant, spec fn, proof fn, ghost/tracked, external_body, assume
tests/user_defined_type_invariants.rs (2717): invariant, decreases, Set, Vec, spec fn, proof fn, opaque, ghost/tracked, external_body, assume
tests/vec.rs (69): invariant, decreases, Vec, for loop, Vec push
tests/verifier_assume_allow.rs (82): assume
tests/when_used_as_spec.rs (288): decreases, Vec, spec fn, proof fn, Vec push, assume
tests/z3_restart.rs (173): forall, trigger, assert-by, nonlinear_arith, bit_vector, Multiset, proof fn, int overflow/as
