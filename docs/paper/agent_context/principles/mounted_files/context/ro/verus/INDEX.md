# Verus reference (read-only)

`vstd/` is the exact vstd source of the pinned Verus (0.2026.07.18.3a4d30b). Read it for lemma
statements, `requires`/`ensures`, and broadcast groups. Useful files: `seq.rs`,
`seq_lib.rs`, `map.rs`, `map_lib.rs`, `set.rs`, `set_lib.rs`, `hash_map.rs`,
`arithmetic/`, `std_specs/`, `relations.rs`, `calc_macro.rs`.
Start with `LEMMAS.md` (one entry per vstd lemma / broadcast group / spec fn / exec method, path,
signature, requires/ensures, doc line; methods are `## Owner::name`, the std exec specs such as
`Vec::push` and `String::eq` are in it too), `EXAMPLES_INDEX.md` (one line per small verified program
with the features it uses) and `GUIDE_INDEX.md` (one line per guide page with its headings).
Grep those, then Read the page or one small program from `examples/` or `tests/`.
`guide/` is the Verus guide (markdown). You cannot run Verus yourself: call `run_runquery`.
Search the source with `grep -rn "proof fn lemma_" vstd/`.
Every vstd module is already imported by glob in the spec; write no `use` lines.
You may write `broadcast use vstd::<module>::group_<name>;` for exactly the groups listed below.
A `broadcast use` turns a bundle of vstd lemmas on for automatic use by Z3 in the current scope
(for example `broadcast use vstd::seq::group_seq_axioms;`). More groups means more solver noise,
so use them when stuck. Helper `proof fn` / `spec fn` / exec `fn` items (an exec helper is verified against its own requires/ensures) go between `// AGENT_HELPERS_START`
and `// AGENT_HELPERS_END`.

## Lookup recipes (run from `context/ro/verus/`; each is one grep)

- Seq::subrange length lemma: `grep -n -A4 "lemma_seq_subrange_len" LEMMAS.md`
- `decreases` of a while loop: guide page: `grep -n "decreases" guide/recursion_loops.md`
- `decreases` of a while loop: example programs: `grep -n "decreases.*while loop" EXAMPLES_INDEX.md`
- HashMapWithView insert/get/contains_key specs: `grep -n -A5 "^## HashMapWithView::" LEMMAS.md`
- StringHashMap API: `grep -n -A5 "^## StringHashMap::" LEMMAS.md`
- String equality in exec code: `grep -n -A5 "^## String::eq" LEMMAS.md`
- Vec::push and its view: `grep -n -A5 "^## Vec::push" LEMMAS.md`
- `assert forall ... by`: guide pages: `grep -n "assert forall" GUIDE_INDEX.md`
- `assert forall ... by`: example programs: `grep -n "assert forall" EXAMPLES_INDEX.md`
- `by (nonlinear_arith)`: guide pages: `grep -n "nonlinear" GUIDE_INDEX.md`
- `by (nonlinear_arith)`: example programs: `grep -n "nonlinear_arith" EXAMPLES_INDEX.md`
- `broadcast use` groups and their members: `grep -n -A2 "^## group_" LEMMAS.md`
- `reveal` and `opaque`: guide pages: `grep -n -i "reveal\|opaque" GUIDE_INDEX.md`
- `reveal` and `opaque`: example programs: `grep -n "reveal.*opaque\|opaque.*reveal" EXAMPLES_INDEX.md`
- `choose`: guide pages: `grep -n "choose" GUIDE_INDEX.md`
- `choose`: example programs: `grep -n "choose" EXAMPLES_INDEX.md`
- loop invariant with a quantifier over a Seq: `grep -n "loop invariant forall" EXAMPLES_INDEX.md`

## Broadcast groups you may use (generated from the vstd source)

- `broadcast use vstd::arithmetic::div_mod::group_div_basics;`
- `broadcast use vstd::arithmetic::div_mod::group_mod_basics;`
- `broadcast use vstd::arithmetic::div_mod::group_mod_properties;`
- `broadcast use vstd::arithmetic::div_mod::group_fundamental_div_mod_converse;`
- `broadcast use vstd::arithmetic::mul::group_mul_basics;`
- `broadcast use vstd::arithmetic::mul::group_mul_is_distributive;`
- `broadcast use vstd::arithmetic::mul::group_mul_is_commutative_and_distributive;`
- `broadcast use vstd::arithmetic::mul::group_mul_properties;`
- `broadcast use vstd::arithmetic::power::group_pow_properties;`
- `broadcast use vstd::array::group_array_axioms;`
- `broadcast use vstd::endian::group_endian_nat_axioms;`
- `broadcast use vstd::function::group_function_axioms;`
- `broadcast use vstd::hash_map::group_hash_map_axioms;`
- `broadcast use vstd::hash_set::group_hash_set_axioms;`
- `broadcast use vstd::laws_cmp::group_laws_cmp;`
- `broadcast use vstd::laws_eq::group_laws_eq;`
- `broadcast use vstd::layout::group_align_properties;`
- `broadcast use vstd::layout::group_layout_axioms;`
- `broadcast use vstd::map::group_map_lemmas;`
- `broadcast use vstd::map_lib::group_map_union;`
- `broadcast use vstd::map_lib::group_map_properties;`
- `broadcast use vstd::map_lib::group_map_extra;`
- `broadcast use vstd::multiset::group_multiset_axioms;`
- `broadcast use vstd::multiset::group_multiset_properties;`
- `broadcast use vstd::raw_ptr::group_raw_ptr_axioms;`
- `broadcast use vstd::seq::group_seq_axioms;`
- `broadcast use vstd::seq::group_seq_lemmas;`
- `broadcast use vstd::seq::group_seq_lemmas_expensive;`
- `broadcast use vstd::seq_lib::group_filter_ensures;`
- `broadcast use vstd::seq_lib::group_seq_lib_default;`
- `broadcast use vstd::seq_lib::group_to_multiset_ensures;`
- `broadcast use vstd::seq_lib::group_seq_properties;`
- `broadcast use vstd::set::group_set_lemmas;`
- `broadcast use vstd::set_lib::group_set_properties;`
- `broadcast use vstd::set_lib::group_set_lib_default;`
- `broadcast use vstd::slice::group_slice_axioms;`
- `broadcast use vstd::string::group_string_axioms;`
- `broadcast use vstd::utf8::group_utf8_lib;`
- `broadcast use vstd::std_specs::bits::group_bits_axioms;`
- `broadcast use vstd::std_specs::control_flow::group_control_flow_axioms;`
- `broadcast use vstd::std_specs::iter::group_iter_axioms;`
- `broadcast use vstd::std_specs::manually_drop::group_manually_drop_axioms;`
- `broadcast use vstd::std_specs::btree::group_btree_axioms;`
- `broadcast use vstd::std_specs::hash::group_hash_axioms;`
- `broadcast use vstd::std_specs::range::group_range_axioms;`
- `broadcast use vstd::std_specs::slice::group_slice_axioms;`
- `broadcast use vstd::std_specs::vec::group_vec_axioms;`
- `broadcast use vstd::std_specs::vecdeque::group_vec_dequeue_axioms;`
- `broadcast use vstd::std_specs::nonzero::group_nonzero_axioms;`
- `broadcast use vstd::imap::group_imap_lemmas;`
- `broadcast use vstd::imap_lib::group_imap_union;`
- `broadcast use vstd::imap_lib::group_imap_properties;`
- `broadcast use vstd::imap_lib::group_imap_extra;`
- `broadcast use vstd::iset::group_iset_lemmas;`
- `broadcast use vstd::iset_lib::group_iset_properties;`
- `broadcast use vstd::iset_lib::group_iset_lib_default;`
