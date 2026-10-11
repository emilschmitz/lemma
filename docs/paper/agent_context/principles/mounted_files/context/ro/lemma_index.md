# Declarative spec lemma index

Write the `run_query` edit before you read the rest of this index.
Every vstd module is already imported by glob. Write no `use` lines.
The one allowed line is `broadcast use vstd::<module>::group_<name>;` (exact name, see
`context/ro/verus/INDEX.md` for the list).
Still forbidden: `assume(`, `admit(`, `#[verifier::external_body]`, and a name containing
`axiom`, `arbitrary`, or `proof_from_false`.
A new `spec fn` or `proof fn` goes between `// AGENT_HELPERS_START` and `// AGENT_HELPERS_END`.
`proof { lemma_...(); }` is allowed.

Host lemmas (call these; the integer adds need none, Verus checks overflow itself):

- `lemma_dense_count_map(keys, counts, map, key_cap)`, when this spec defines it. Once every slot of `counts` equals `group_count(keys, 0, k)` and `map` holds exactly the nonzero slots, the map meets the `ensures`. Call it after the copy loop. Pass `KEY_CAP_... as int`.

vstd items the declarative spec uses:

- `HashMapWithView::<K, V>::new`, `insert`, `contains_key`, `get` (vstd::hash_map). `insert` ensures the view is `old(self)@.insert(k@, v)`.

- `StringHashMap::<V>::new`, `insert`, `contains_key`, `get` for string keys; view key is `Seq<char>`.

- `Map::contains_key`, `Map::insert`, `Map::empty` (vstd::map) as the spec view.

- The host already broadcasts `vstd::std_specs::hash::axiom_u64_obeys_hash_table_key_model` (and the i64 and i128 variants) for the group key. Do not use it by name. A name containing `axiom` is rejected except inside `broadcast use vstd::<module>::group_<name>;`, which is allowed for every vstd group.

- `Seq::len`, `Seq::index`, `Seq::skip`, `Seq::push`.

You may call these and other vstd lemmas by bare name; look them up in `context/ro/verus/` when unsure. Do not use a name containing `axiom`, `arbitrary`, or `proof_from_false`. Do not `assume(` or `admit(` a fact. Write helper `spec fn` / `proof fn` items only in the helper region.

Dictionary-encoded string columns (this spec has `<col>__dict` fields):

- A string column `c` is two vectors: `t.c` (one small integer CODE per row) and `t.c__dict` (the distinct strings).
  The spec reads a cell as `t.c__dict@[t.c@[i] as int]@`; `valid_cols` gives you that every code is below
  `t.c__dict@.len()` and that dictionary entries are pairwise distinct. Nothing about `t.c[i]` itself is a string.
- `c = 'lit'` becomes a code comparison. Look the literal's code up ONCE before the row loop (scan `t.c__dict` with
  `String == String`, keep `found` and `code`); distinctness makes it the only entry equal to the literal, so the
  cell equals the literal exactly when `found && (t.c[i] as usize) == code`. The row loop then reads one small
  integer per row. A worked body: `context/ro/examples/scan_filter_sum_count.rs` (the filter) and `group_by_dict_key.rs` (a literal's code).
- GROUP BY a string key: use a dense array indexed by the code (`counts: Vec<u64>` of length `t.c__dict.len()`),
  then build the result from the nonzero slots; the dictionary entry is the key string. The result is a `Vec<OutRow>`
  whose key field is a `String`. A worked, verified body (counts backwards to match the suffix fold, a ghost slot
  sequence for the output rows, `lemma_count_pos` for 'count > 0 means a witness row'):
  `context/ro/examples/group_by_dict_key.rs`.
