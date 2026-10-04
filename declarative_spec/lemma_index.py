"""Markdown index of host lemmas and vstd items for declarative agents."""


def lemma_index_markdown() -> str:
    lines = [
        "# Declarative spec lemma index",
        "",
        "Write the `run_query` edit before you read the rest of this index.",
        "Every vstd module is already imported by glob. Write no `use` lines.",
        "The one allowed line is `broadcast use vstd::<module>::group_<name>;` (exact name, see",
        "`context/ro/verus/INDEX.md` for the list).",
        "Still forbidden: `assume(`, `admit(`, `#[verifier::external_body]`, and a name containing",
        "`axiom`, `arbitrary`, or `proof_from_false`.",
        "A new `spec fn` or `proof fn` goes between `// AGENT_HELPERS_START` and `// AGENT_HELPERS_END`.",
        "`proof { lemma_...(); }` is allowed.",
        "",
        "Host lemmas (call these; the integer adds need none, Verus checks overflow itself):",
        "",
        ("- `lemma_dense_count_map(keys, counts, map, key_cap)`, when this spec defines it. "
        "Once every slot of `counts` equals `group_count(keys, 0, k)` and `map` holds exactly "
        "the nonzero slots, the map meets the `ensures`. Call it after the copy loop. "
        "Pass `KEY_CAP_... as int`."),
        "",
        ("- `lemma_f64_sum_within_eps(acc: f64, n_terms: int, mag_cap: int, eps: f64, terms: Seq<f64>)`. "
        "A plain left-to-right f64 fold is within eps of the real sum of the loaded floats when "
        "eps is at least host_f64_sum_error(n_terms, mag_cap). Pass the ghost sequence you tracked; "
        "do not unfold an f64 add step by step."),
        "",
        ("- `lemma_f64_add_defined(x: f64, y: f64)`. "
        "IEEE f64 addition is defined for every pair of values. Call it before `acc + x`."),
        "",
        ("- `lemma_f64_left_fold_empty()` and `lemma_f64_left_fold_push(prefix, x, acc, next)`. "
        "The host opaque f64 accumulator: empty is 0.0. "
        "`next` is one f64 add, and it is the fold of `prefix.push(x)`."),
        "",
        ("- `host_f64_sum_error(n_terms: int, mag_cap: int) -> real`. "
        "Host error bound depending only on term count and magnitude cap."),
        "",
        "- `abs_real(x: real) -> real`. Absolute value on reals.",
        "",
        "vstd items the declarative spec uses:",
        "",
        ("- `HashMapWithView::<K, V>::new`, `insert`, `contains_key`, `get` (vstd::hash_map). "
        "`insert` ensures the view is `old(self)@.insert(k@, v)`."),
        "",
        ("- `StringHashMap::<V>::new`, `insert`, `contains_key`, `get` for string keys; "
        "view key is `Seq<char>`."),
        "",
        "- `Map::contains_key`, `Map::insert`, `Map::empty` (vstd::map) as the spec view.",
        "",
        ("- The host already broadcasts "
        "`vstd::std_specs::hash::axiom_u64_obeys_hash_table_key_model` "
        "(and the i64 and i128 variants) for the group key. "
        "Do not use it by name. A name containing `axiom` is an assume and is rejected."),
        "",
        "- `Seq::len`, `Seq::index`, `Seq::skip`, `Seq::push`.",
        "",
        ("You may call these and other vstd lemmas by bare name; look them up in `context/ro/verus/` "
        "when unsure. Do not use a name containing `axiom`, `arbitrary`, or `proof_from_false`. "
        "Do not `assume(` or `admit(` a fact. "
        "Write helper `spec fn` / `proof fn` items only in the helper region."),
    ]
    return "\n".join(lines) + "\n"
